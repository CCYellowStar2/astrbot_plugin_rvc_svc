"""B 站视频搜索、BV 号解析，以及把结果拼成两栏长图。"""

import asyncio
import html
import json
import os
import re
import tempfile
from io import BytesIO

import aiohttp
from astrbot.api import logger
from PIL import Image, ImageDraw, ImageFont

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_FONT_CANDIDATES = (
    os.path.join(_PLUGIN_DIR, "assets", "NotoSansCJKsc-Regular.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_BILI_HEADERS = {"User-Agent": _UA, "Referer": "https://www.bilibili.com/"}
_TAG_RE = re.compile(r"<[^>]+>")
_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}", re.IGNORECASE)

# 版式：两栏 × 每栏若干行
BOARD_WIDTH = 900
COLUMNS = 2
COL_GAP = 10
ROW_HEIGHT = 118
COVER_W, COVER_H = 168, 94
PADDING = 12


def _clean_title(raw) -> str:
    return html.unescape(_TAG_RE.sub("", str(raw or ""))).strip()


def _cover_url(pic) -> str:
    pic = str(pic or "").strip()
    return "https:" + pic if pic.startswith("//") else pic


def _format_play(value) -> str:
    try:
        count = int(value)
    except (TypeError, ValueError):
        return ""
    return f"{count / 10000:.1f}万播放" if count >= 10000 else f"{count}播放"


def parse_bv(text: str):
    """从输入里抠出 BV 号（支持裸 BV 号、完整链接、短链文案）。"""
    match = _BV_RE.search(str(text or ""))
    if not match:
        return None
    return "BV" + match.group(0)[2:]


def _to_video(data: dict) -> dict:
    duration = data.get("duration") or 0
    try:
        minutes, seconds = divmod(int(duration), 60)
        duration_text = f"{minutes}:{seconds:02d}"
    except (TypeError, ValueError):
        duration_text = ""
    return {
        "id": str(data.get("bvid") or ""),
        "name": _clean_title(data.get("title")),
        "artists": str((data.get("owner") or {}).get("name") or ""),
        "duration": duration_text,
        "play": _format_play((data.get("stat") or {}).get("view")),
        "pic": _cover_url(data.get("pic")),
    }


async def fetch_video_meta(bvid: str) -> dict:
    """按 BV 号取视频信息（不需要签名）。"""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers=_BILI_HEADERS,
        ) as response:
            text = await response.text()
    try:
        payload = json.loads(text)
    except ValueError as error:
        raise RuntimeError(f"B站返回非 JSON（多半是风控页面）: {text[:60]}") from error
    if payload.get("code") != 0:
        raise RuntimeError(f"B站返回 code={payload.get('code')} {str(payload.get('message'))[:40]}")
    return _to_video(payload.get("data") or {})


_TRANSPORT_READY = False


def _prepare_transport() -> None:
    """给 bilibili_api 设一些更抗抖的传输参数（只需一次）。"""
    global _TRANSPORT_READY
    if _TRANSPORT_READY:
        return
    try:
        from bilibili_api import request_settings

        request_settings.set_timeout(20)
        try:
            # 不吃系统代理环境变量，避免被本地代理/分流打断 TLS
            request_settings.set_trust_env(False)
        except Exception:
            pass
    except Exception as error:
        logger.warning(f"设置 bilibili_api 传输参数失败: {error}")
    _TRANSPORT_READY = True


async def search_videos(keyword: str, limit: int = 16, attempts: int = 3) -> list:
    """用 bilibili_api 搜索视频（自带 wbi 签名）。

    B 站偶尔会在 TLS 握手阶段直接掐断连接（curl: (35) BoringSSL SSL_connect:
    Connection closed abruptly），属于风控/网络抖动，重试通常就好了，所以这里带退避重试。
    """
    from bilibili_api import search

    _prepare_transport()

    result = None
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            result = await search.search_by_type(
                keyword,
                search_type=search.SearchObjectType.VIDEO,
                page=1,
            )
            break
        except Exception as error:
            last_error = error
            logger.warning(f"B站搜索第 {attempt}/{attempts} 次失败: {type(error).__name__} {error}")
            if attempt < attempts:
                await asyncio.sleep(attempt)

    if result is None:
        raise RuntimeError(
            f"B站搜索连续 {attempts} 次失败（多为网络或风控）：{type(last_error).__name__}: {last_error}"
        )

    videos = []
    for item in (result.get("result") or [])[:limit]:
        bvid = str(item.get("bvid") or "").strip()
        if not bvid:
            continue
        videos.append(
            {
                "id": bvid,
                "name": _clean_title(item.get("title")),
                "artists": str(item.get("author") or "").strip(),
                "duration": str(item.get("duration") or "").strip(),
                "play": _format_play(item.get("play")),
                "pic": _cover_url(item.get("pic")),
            }
        )
    return videos


def _font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


async def _fetch_cover(url: str):
    """取封面图（异步）。B 站图床有防盗链，必须带 Referer，否则可能拿到占位图。"""
    if not url:
        return None
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(url, headers=_BILI_HEADERS) as response:
                if response.status != 200:
                    return None
                data = await response.read()
        if not data:
            return None
        return Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return None


def _wrap(draw, text: str, font, max_width: int, max_lines: int = 2) -> list:
    """按像素宽度换行，最多 max_lines 行，超出用省略号。"""
    lines, current = [], ""
    for char in text:
        candidate = current + char
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = char
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return []
    # 判断是否还有剩余没画出来
    joined = "".join(lines)
    if len(joined) < len(text):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines


async def build_board(videos: list) -> str:
    """把搜索结果拼成一张两栏长图，返回临时文件路径。

    封面并发下载（16 张串行会明显拖慢），拼图本身是纯 CPU/内存操作，
    丢到线程里做，避免阻塞事件循环。
    """
    if not videos:
        raise ValueError("没有可绘制的结果")
    covers = await asyncio.gather(*(_fetch_cover(video.get("pic", "")) for video in videos))
    return await asyncio.to_thread(_render_board, videos, covers)


def _render_board(videos: list, covers: list) -> str:
    title_font = _font(17)
    meta_font = _font(13)
    col_width = (BOARD_WIDTH - PADDING * 2 - COL_GAP * (COLUMNS - 1)) // COLUMNS
    rows = (len(videos) + COLUMNS - 1) // COLUMNS
    board = Image.new(
        "RGB",
        (BOARD_WIDTH, ROW_HEIGHT * rows + PADDING * 2),
        (22, 22, 26),
    )
    draw = ImageDraw.Draw(board)

    text_x_offset = COVER_W + 10
    text_width = col_width - text_x_offset
    cover_y_offset = (ROW_HEIGHT - COVER_H) // 2

    for index, video in enumerate(videos, start=1):
        column = (index - 1) % COLUMNS
        row = (index - 1) // COLUMNS
        left = PADDING + column * (col_width + COL_GAP)
        top = PADDING + row * ROW_HEIGHT

        cover = covers[index - 1] if index - 1 < len(covers) else None
        if cover is not None:
            ratio = max(COVER_W / cover.width, COVER_H / cover.height)
            resized = cover.resize(
                (max(COVER_W, int(cover.width * ratio)), max(COVER_H, int(cover.height * ratio)))
            )
            crop_left = (resized.width - COVER_W) // 2
            crop_top = (resized.height - COVER_H) // 2
            board.paste(
                resized.crop((crop_left, crop_top, crop_left + COVER_W, crop_top + COVER_H)),
                (left, top + cover_y_offset),
            )
        else:
            board.paste(Image.new("RGB", (COVER_W, COVER_H), (48, 48, 56)), (left, top + cover_y_offset))

        text_x = left + text_x_offset
        title_lines = _wrap(draw, f"{index}. {video.get('name', '')}", title_font, text_width, max_lines=2)
        for line_index, line in enumerate(title_lines):
            draw.text((text_x, top + 12 + line_index * 22), line, font=title_font, fill=(238, 238, 242))

        meta_parts = [video.get(key, "") for key in ("artists", "duration", "play")]
        meta_text = " · ".join(part for part in meta_parts if part)
        meta_line = _wrap(draw, meta_text, meta_font, text_width, max_lines=1)
        if meta_line:
            draw.text((text_x, top + 74), meta_line[0], font=meta_font, fill=(148, 148, 158))

    handle, path = tempfile.mkstemp(prefix="bili_board_", suffix=".png")
    os.close(handle)
    board.save(path, "PNG")
    return path
