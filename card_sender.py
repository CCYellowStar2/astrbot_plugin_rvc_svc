"""把翻唱成品发成 QQ 音乐卡片：临时托管 -> 签名 -> OneBot json 段。

为什么不用 AstrBot 自带的 Music 组件：它的 `_type` 字段被 pydantic 当私有字段，
`toDict()` 出来的 `data` 里没有 `type`，OneBot 那边认不出是音乐卡片。
这里照 astrbot_plugin_music 的做法：自己拼 segment，并用签名服务换取可渲染的卡片。
"""

import json
import os
import time

import requests
from astrbot.api import logger

_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
DEFAULT_ARK_API = "https://apii.xianyuw.cn/api/v1/qq-musicArk"
_REQUIRED_CARD_FIELDS = {"app", "meta", "prompt", "view"}


class CardError(Exception):
    """卡片链路任意一步失败，调用方据此回退成文件发送。"""


def _verify_audio(url: str) -> bool:
    """确认直链返回的是原始音频字节，而不是 HTML 下载页。"""
    try:
        response = requests.get(url, headers=_UA, timeout=20, stream=True)
        content_type = response.headers.get("Content-Type", "")
        head = next(response.iter_content(9), b"")
        return response.status_code == 200 and ("audio" in content_type or head.startswith(b"ID3"))
    except Exception as error:
        logger.warning(f"音频直链校验失败 {url}: {error}")
        return False


def _upload_uguu(path: str) -> str:
    with open(path, "rb") as handle:
        response = requests.post(
            "https://uguu.se/upload?output=text",
            files={"files[]": (os.path.basename(path), handle, "audio/mpeg")},
            headers=_UA,
            timeout=90,
        )
    if response.status_code != 200:
        raise CardError(f"uguu 上传失败: HTTP {response.status_code}")
    url = response.text.strip().splitlines()[-1].strip()
    if not url.startswith("http"):
        raise CardError(f"uguu 没有返回链接: {response.text[:120]}")
    return url


def _upload_pomf2(path: str) -> str:
    with open(path, "rb") as handle:
        response = requests.post(
            "https://pomf2.lain.la/upload.php",
            files={"files[]": (os.path.basename(path), handle, "audio/mpeg")},
            headers=_UA,
            timeout=90,
        )
    if response.status_code != 200:
        raise CardError(f"pomf2 上传失败: HTTP {response.status_code}")
    files = (response.json() or {}).get("files") or []
    url = str((files[0] or {}).get("url", "")) if files else ""
    if not url.startswith("http"):
        raise CardError(f"pomf2 没有返回链接: {response.text[:120]}")
    return url


def upload_audio(path: str) -> str:
    """上传到临时存储并回验直链，返回可被 QQ 解析的音频地址。

    每个源尝试两次（临时存储偶尔 502，重试基本能过）。
    """
    if not os.path.isfile(path):
        raise CardError(f"文件不存在: {path}")

    errors = []
    for name, uploader in (("uguu", _upload_uguu), ("pomf2", _upload_pomf2)):
        for attempt in range(1, 3):
            try:
                url = uploader(path)
                if _verify_audio(url):
                    logger.info(f"音频已上传到 {name}: {url}")
                    return url
                errors.append(f"{name}(第{attempt}次): 直链不是音频")
            except Exception as error:
                errors.append(f"{name}(第{attempt}次): {type(error).__name__} {error}")
            if attempt == 1:
                time.sleep(1)
    raise CardError("临时上传全部失败 -> " + " | ".join(errors))


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

    参数错误（400，比如 format 不被支持）不重试，重试的是网络抖动、网关 5xx、
    以及服务端偶发的 code=500。每次重试间隔 1s、2s。
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
            # 明确的参数错误，重试没有意义
            if "HTTP 400" in message or "format参数无效" in message:
                raise CardError(f"{message}（format={params['format']}）") from error
            logger.warning(f"签名第 {attempt} 次失败: {message}")
            if attempt < attempts:
                time.sleep(attempt)
    raise CardError(f"签名重试 {attempts} 次仍失败: {last_error}")


def fetch_netease_cover(song_id) -> str:
    """网易云那条路没有封面，这里补一个（签名服务要求 cover 非空）。

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


async def send_json_card(event, card: dict) -> bool:
    """按 OneBot json 段发送卡片（仅 aiocqhttp 平台可用）。"""
    payload = {"message": [{"type": "json", "data": {"data": json.dumps(card, ensure_ascii=False)}}]}
    if event.is_private_chat():
        payload["user_id"] = event.get_sender_id()
        await event.bot.api.call_action("send_private_msg", **payload)
    else:
        payload["group_id"] = event.get_group_id()
        await event.bot.api.call_action("send_group_msg", **payload)
    return True
