"""把翻唱成品发成 QQ 音乐卡片：临时托管 -> 签名 -> OneBot json 段。

为什么不用 AstrBot 自带的 Music 组件：它的 `_type` 字段被 pydantic 当私有字段，
`toDict()` 出来的 `data` 里没有 `type`，OneBot 那边认不出是音乐卡片。
这里照 astrbot_plugin_music 的做法：自己拼 segment，并用签名服务换取可渲染的卡片。

签名服务要求 `cover` 非空（空值会回「缺少必要参数: …」，极具误导性），
所以缺封面时这里会兜底上传一张内置默认封面。
"""

import asyncio
import io
import json
import os
import re
import tempfile
import time

import requests
from astrbot.api import logger
from PIL import Image

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
# B 站图片有防盗链，下载时必须带 Referer，否则可能拿到占位图
_COVER_HEADERS = {**_UA, "Referer": "https://www.bilibili.com/"}
DEFAULT_ARK_API = "https://apii.xianyuw.cn/api/v1/qq-musicArk"
_REQUIRED_CARD_FIELDS = {"app", "meta", "prompt", "view"}

# QQ 卡片对标题不宽容：过长、带 emoji、带控制符都可能让卡片渲染失败或被丢弃
MAX_TITLE_LEN = 40
MAX_SINGER_LEN = 20
_STRIP_RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0xFE00, 0xFE0F))

# 实测这些字符会让 QQ 音乐卡片发不出去（retcode=100 无回执），统一换成安全等价物
_UNSAFE_MAP = {
    "〜": "~",  # U+301C WAVE DASH
    "～": "~",  # U+FF5E FULLWIDTH TILDE
    "·": "-",  # U+00B7 MIDDLE DOT（我们自己模板里原来就用的这个，已踩坑）
    "・": "-",  # U+30FB KATAKANA MIDDLE DOT
    "•": "-",  # U+2022 BULLET
    "｜": "|",
    "丨": "|",
    "(": "（",  # 半角括号一律换全角（基线用全角可发）
    ")": "）",
}


def clean_card_text(text, limit: int) -> str:
    """清掉控制符 / emoji / 多余空白，替换会让卡片失效的符号，并限制长度。"""
    value = re.sub(r"[\x00-\x1f\x7f]", " ", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    value = "".join(
        ch for ch in value if not any(low <= ord(ch) <= high for low, high in _STRIP_RANGES)
    ).strip()
    value = "".join(_UNSAFE_MAP.get(ch, ch) for ch in value).strip()
    if len(value) > limit:
        value = value[: max(1, limit - 1)] + "…"
    return value


_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_COVER_PATH = os.path.join(_PLUGIN_DIR, "assets", "default_cover.jpg")

# 进程内缓存：封面处理结果（源 URL -> 上传后的直链），防止同一张图反复上传
_COVER_CACHE: dict = {}
_COVER_CACHE_LIMIT = 24
_DEFAULT_COVER_URL = ""


class CardError(Exception):
    """卡片链路任意一步失败，调用方据此回退为语音消息。"""


# ---------------- 上传 + 校验 ----------------

def _verify_media(url: str, kind: str = "audio") -> tuple:
    """探一下直链返回的是不是原始媒体字节，返回 (是否通过, 说明)。

    只取前 2KB（Range），避免为了校验把整个文件拖下来；
    校验结果只当参考——真正的判据是签名服务能不能吃下这个地址，
    所以调用方不会因为它失败就放弃（见 _upload_with_retry）。
    """
    headers = {**_UA, "Accept-Encoding": "identity", "Range": "bytes=0-2047"}
    try:
        response = requests.get(url, headers=headers, timeout=8, stream=True)
        content_type = response.headers.get("Content-Type", "")
        head = next(response.iter_content(16), b"")
        response.close()
        detail = f"HTTP {response.status_code} {content_type or '(无类型)'} 首字节={head[:12]!r}"
        if response.status_code not in (200, 206):
            return False, detail
        if kind == "audio":
            ok = "audio" in content_type or head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3")
        else:
            ok = "image" in content_type or head.startswith(b"\xff\xd8") or head.startswith(b"\x89PNG")
        return ok, detail
    except Exception as error:
        return False, f"{type(error).__name__}: {error}"


def _upload_uguu(path: str, mime: str = "audio/mpeg") -> str:
    with open(path, "rb") as handle:
        response = requests.post(
            "https://uguu.se/upload?output=text",
            files={"files[]": (os.path.basename(path), handle, mime)},
            headers=_UA,
            timeout=20,
        )
    if response.status_code != 200:
        raise CardError(f"uguu 上传失败: HTTP {response.status_code}")
    url = response.text.strip().splitlines()[-1].strip()
    if not url.startswith("http"):
        raise CardError(f"uguu 没有返回链接: {response.text[:120]}")
    return url


def _upload_pomf2(path: str, mime: str = "audio/mpeg") -> str:
    with open(path, "rb") as handle:
        response = requests.post(
            "https://pomf2.lain.la/upload.php",
            files={"files[]": (os.path.basename(path), handle, mime)},
            headers=_UA,
            timeout=20,
        )
    if response.status_code != 200:
        raise CardError(f"pomf2 上传失败: HTTP {response.status_code}")
    files = (response.json() or {}).get("files") or []
    url = str((files[0] or {}).get("url", "")) if files else ""
    if not url.startswith("http"):
        raise CardError(f"pomf2 没有返回链接: {response.text[:120]}")
    return url


_ALL_UPLOADERS = {"pomf2": _upload_pomf2, "uguu": _upload_uguu}
_UPLOADERS = (("pomf2", _upload_pomf2), ("uguu", _upload_uguu))

# 某个源刚失败过就冷却一段时间，别让每首歌都在它身上白试两轮。
# 实测 uguu 会整段时间连着 502：4 次尝试全 502，每次白白多等 1 秒 + 两次请求。
_SOURCE_COOLDOWN_SECONDS = 300
_source_down_until: dict = {}


def set_upload_sources(spec) -> None:
    """按配置调整上传源顺序，例如 "pomf2,uguu"；未知名字忽略，空值恢复默认。"""
    global _UPLOADERS
    names = [n.strip().lower() for n in str(spec or "").replace("，", ",").split(",") if n.strip()]
    picked = [(n, _ALL_UPLOADERS[n]) for n in names if n in _ALL_UPLOADERS]
    if not picked:
        picked = [("pomf2", _upload_pomf2), ("uguu", _upload_uguu)]
    # 去重保序
    seen = set()
    ordered = []
    for name, uploader in picked:
        if name not in seen:
            seen.add(name)
            ordered.append((name, uploader))
    _UPLOADERS = tuple(ordered)
    logger.info(f"临时上传源顺序: {' → '.join(n for n, _ in _UPLOADERS)}")


def _pick_uploaders():
    """可用源优先，冷却中的源排到最后（全都冷却时照旧按原顺序试）。"""
    now = time.time()
    alive, down = [], []
    for name, uploader in _UPLOADERS:
        (down if _source_down_until.get(name, 0) > now else alive).append((name, uploader))
    return alive + down


def _looks_like_server_error(error: Exception) -> bool:
    """5xx / 连接类错误当作「这个源当前不可用」，立刻换源而不是原地重试。"""
    if isinstance(error, (requests.exceptions.Timeout, requests.exceptions.ConnectionError)):
        return True
    return re.search(r"HTTP (5\d\d|403)", str(error)) is not None


def _upload_with_retry(path: str, mime: str, kind: str) -> str:
    """两个源 × 各试两次；上传成功即返回，直链预检只作提示（真正的判据是签名服务）。

    kind 必须是 "audio" 或 "image"（校验逻辑按它分支），日志里用中文标签显示。
    """
    label = {"audio": "音频", "image": "封面"}.get(kind, kind)
    size_mb = os.path.getsize(path) / 1024 / 1024
    began = time.perf_counter()
    errors = []
    for name, uploader in _pick_uploaders():
        for attempt in (1, 2):
            started = time.perf_counter()
            try:
                url = uploader(path, mime)
            except Exception as error:
                elapsed = time.perf_counter() - started
                errors.append(f"{name}(第{attempt}次, {elapsed:.1f}s): {type(error).__name__} {error}")
                # 每次失败都记一笔：以前非超时的失败（如 HTTP 502）完全不留痕迹，
                # 用户只觉得“慢”，却看不出时间花在哪一跳
                logger.warning(
                    f"{label} 上传到 {name} 第{attempt}次失败（{elapsed:.1f}s）："
                    f"{type(error).__name__} {error}"
                )
                # 超时 / 5xx / 连不上：这个源当前不可用，记冷却时间并立即换源
                if _looks_like_server_error(error) or elapsed > 30:
                    _source_down_until[name] = time.time() + _SOURCE_COOLDOWN_SECONDS
                    logger.warning(
                        f"{name} 标记为暂时不可用（{_SOURCE_COOLDOWN_SECONDS // 60} 分钟内不再优先尝试），"
                        f"本次换下一个源"
                    )
                    break
                if attempt == 1:
                    time.sleep(1)
                continue
            elapsed = time.perf_counter() - started
            speed = size_mb * 8 / elapsed if elapsed > 0 else 0.0
            total = time.perf_counter() - began
            _source_down_until.pop(name, None)
            logger.info(
                f"{label} 已上传到 {name}: {url} | 本次 {elapsed:.1f}s"
                f"（{size_mb:.1f} MB，约 {speed:.1f} Mbps），含前面失败尝试共 {total:.1f}s"
            )
            ok, detail = _verify_media(url, kind)
            if not ok:
                logger.warning(f"{label} 直链预检没过（{detail}），仍交给签名服务判定: {url}")
            return url
    raise CardError(f"{label} 临时上传全部失败 -> " + " | ".join(errors))


def upload_audio(path: str) -> str:
    """上传音频，返回可被 QQ 解析的直链。"""
    if not os.path.isfile(path):
        raise CardError(f"文件不存在: {path}")
    return _upload_with_retry(path, "audio/mpeg", "audio")


_COVER_TTL = 2 * 3600  # uguu 3 小时删文件，这里提前 1 小时失效重传
_DEFAULT_COVER_AT = 0.0


def _normalize_cover_bytes(raw: bytes) -> bytes:
    """把任意图片规范成 300×300 JPEG（居中裁正方形）。

    目的是绕开「封面内容」类问题：网易云原图动辄 7 MB、B 站防盗链会返回占位图、
    还有 WebP / 带透明通道的 PNG —— 签名服务与 QQ 客户端只吃标准 JPEG。
    """
    with Image.open(io.BytesIO(raw)) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        rgb = rgb.crop((left, top, left + side, top + side)).resize((300, 300), Image.LANCZOS)
        buffer = io.BytesIO()
        rgb.save(buffer, "JPEG", quality=88, optimize=True)
        return buffer.getvalue()


def _download_cover(url: str, attempts: int = 2) -> bytes:
    last = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, headers=_COVER_HEADERS, timeout=20)
            if response.status_code == 200 and response.content:
                return response.content
            last = f"HTTP {response.status_code}（{len(response.content)} 字节）"
        except Exception as error:
            last = f"{type(error).__name__} {error}"
        if attempt < attempts:
            time.sleep(1)
    raise CardError(f"封面下载失败: {last}")


def _upload_cover_bytes(data: bytes) -> str:
    handle, path = tempfile.mkstemp(suffix=".jpg", prefix="cover_")
    os.close(handle)
    try:
        with open(path, "wb") as f:
            f.write(data)
        return _upload_with_retry(path, "image/jpeg", "image")
    finally:
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def prepare_cover(cover_url: str = "") -> str:
    """把封面规范成 300×300 JPEG 后重新上传，返回签名服务能直接用的直链。

    走这一步而不是把原 URL 直接丢给签名服务，是因为封面失败的根因多在「内容」：
    B 站防盗链占位图、网易云超大原图、WebP/透明 PNG 等。
    """
    global _DEFAULT_COVER_URL, _DEFAULT_COVER_AT
    now = time.time()

    if cover_url:
        entry = _COVER_CACHE.get(cover_url)
        if entry and now - entry[1] < _COVER_TTL:
            return entry[0]
        started = time.perf_counter()
        try:
            raw = _download_cover(cover_url)
            downloaded = time.perf_counter() - started
            url = _upload_cover_bytes(_normalize_cover_bytes(raw))
            if len(_COVER_CACHE) >= _COVER_CACHE_LIMIT:
                _COVER_CACHE.pop(next(iter(_COVER_CACHE)))
            _COVER_CACHE[cover_url] = (url, now)
            logger.info(
                f"封面处理完成｜源 {cover_url[:50]} ｜ 交给签名服务的直链 {url} ｜ "
                f"下载 {downloaded:.1f}s，总计 {time.perf_counter() - started:.1f}s"
            )
            return url
        except Exception as error:
            logger.warning(f"封面处理失败（{time.perf_counter() - started:.1f}s），改用默认封面: {error}")

    if _DEFAULT_COVER_URL and now - _DEFAULT_COVER_AT < _COVER_TTL:
        return _DEFAULT_COVER_URL
    if not os.path.isfile(_DEFAULT_COVER_PATH):
        raise CardError(f"内置默认封面不存在: {_DEFAULT_COVER_PATH}")
    with open(_DEFAULT_COVER_PATH, "rb") as handle:
        data = _normalize_cover_bytes(handle.read())
    _DEFAULT_COVER_URL = _upload_cover_bytes(data)
    _DEFAULT_COVER_AT = now
    logger.info(f"已启用内置默认封面: {_DEFAULT_COVER_URL}")
    return _DEFAULT_COVER_URL


# ---------------- 签名 ----------------

def _sign_once(ark_api: str, params: dict) -> dict:
    response = requests.get(ark_api or DEFAULT_ARK_API, params=params, headers=_UA, timeout=40)
    if response.status_code != 200:
        raise CardError(f"签名服务 HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError as error:
        raise CardError(f"签名服务返回非 JSON（多半是网关错误页）: {response.text[:80]}") from error
    if payload.get("code") != 200:
        raise CardError(f"签名失败: {payload.get('code')} {payload.get('msg')}")
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not _REQUIRED_CARD_FIELDS.issubset(data):
        raise CardError("签名返回的卡片结构不完整")
    return data


def sign_ark(ark_api: str, ark_key: str, audio_url: str, title: str, singer: str,
             cover: str = "", jump: str = "", card_format: str = "qq",
             attempts: int = 3) -> dict:
    """调签名服务换取可渲染的卡片结构化数据（默认最多试 3 次 = 首试 + 重试 2 次）。

    只重试网络抖动、网关 5xx、偶发 code=500；参数错误（400 / format 不支持）立即失败。
    每次重试间隔 1s、2s。
    """
    if not ark_key:
        raise CardError("未配置 ark_key")
    params = {
        "key": ark_key,
        "url": audio_url,
        "song": title,
        "singer": singer or "AI 翻唱",
        "cover": cover or "",
        "jump": jump or audio_url,
        "format": card_format or "qq",
    }

    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return _sign_once(ark_api, params)
        except Exception as error:
            last_error = error
            message = str(error)
            if "HTTP 400" in message or "format参数无效" in message:
                raise CardError(f"{message}（format={params['format']}）") from error
            logger.warning(f"签名第 {attempt} 次失败: {message}")
            if attempt < attempts:
                time.sleep(attempt)
    raise CardError(f"签名重试 {attempts} 次仍失败: {last_error}")


def fetch_netease_cover(song_id) -> str:
    """网易云那条路没有封面，这里补一个。

    网易云原始 picUrl 是 http，而且动辄好几 MB（实测 7.1 MB）；
    这里统一改 https 并追加 ?param=300y300，能压到 ~100 KB。
    """
    text = str(song_id or "").strip()
    if not text.isdigit():
        return ""
    try:
        response = requests.get(
            "http://music.163.com/api/song/detail",
            params={"ids": f"[{text}]"},
            headers={**_UA, "Referer": "http://music.163.com"},
            timeout=15,
        )
        songs = (response.json() or {}).get("songs") or []
        if not songs:
            return ""
        pic = str(((songs[0] or {}).get("album") or {}).get("picUrl") or "")
        if not pic:
            return ""
        pic = pic.replace("http://", "https://", 1)
        return pic if "?" in pic else f"{pic}?param=300y300"
    except Exception as error:
        logger.warning(f"取网易云封面失败: {error}")
    return ""


# ---------------- 发送 ----------------

_UNCONFIRMED_HINTS = ("not confirmed", "no message receipt", "未确认")


def _is_unconfirmed(error: Exception) -> bool:
    """QQ 有时收到了 ark 卡片却不给回执，协议端据此判失败——这属于「结果未知」，值得重试。"""
    text = str(error).lower()
    if any(hint in str(error) or hint in text for hint in _UNCONFIRMED_HINTS):
        return True
    return getattr(error, "retcode", None) == 100


async def send_json_card(event, card: dict, attempts: int = 2, delay: float = 2.0) -> bool:
    """按 OneBot json 段发送卡片（仅 aiocqhttp 平台可用）。

    对「未确认送达」单独重试一次：这种情况下卡片往往已经发出去了，只是没回执，
    重试的成功率明显高于直接判死。
    """
    payload = {"message": [{"type": "json", "data": {"data": json.dumps(card, ensure_ascii=False)}}]}
    if event.is_private_chat():
        payload["user_id"] = event.get_sender_id()
        action = "send_private_msg"
    else:
        payload["group_id"] = event.get_group_id()
        action = "send_group_msg"

    for attempt in range(1, attempts + 1):
        try:
            await event.bot.api.call_action(action, **payload)
            return True
        except Exception as error:
            if attempt < attempts and _is_unconfirmed(error):
                logger.warning(f"卡片发送未被确认（{type(error).__name__}），{delay:.0f} 秒后重试一次")
                await asyncio.sleep(delay)
                continue
            raise CardError(f"卡片发送失败: {type(error).__name__} {error}") from error
    return False
