"""把翻唱成品发成 QQ 音乐卡片：临时托管 -> 签名 -> OneBot json 段。

为什么不用 AstrBot 自带的 Music 组件：它的 `_type` 字段被 pydantic 当私有字段，
`toDict()` 出来的 `data` 里没有 `type`，OneBot 那边认不出是音乐卡片。
这里照 astrbot_plugin_music 的做法：自己拼 segment，并用签名服务换取可渲染的卡片。
"""

import json
import os

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
    """上传到临时存储并回验直链，返回可被 QQ 解析的音频地址。"""
    if not os.path.isfile(path):
        raise CardError(f"文件不存在: {path}")

    errors = []
    for name, uploader in (("uguu", _upload_uguu), ("pomf2", _upload_pomf2)):
        try:
            url = uploader(path)
            if _verify_audio(url):
                logger.info(f"音频已上传到 {name}: {url}")
                return url
            errors.append(f"{name}: 直链不是音频")
        except Exception as error:
            errors.append(f"{name}: {type(error).__name__} {error}")
    raise CardError("临时上传全部失败 -> " + " | ".join(errors))


def sign_ark(ark_api: str, ark_key: str, audio_url: str, title: str, singer: str,
             cover: str = "", jump: str = "", card_format: str = "qq") -> dict:
    """调签名服务换取可渲染的卡片结构化数据。"""
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
    response = requests.get(ark_api or DEFAULT_ARK_API, params=params, headers=_UA, timeout=40)
    if response.status_code != 200:
        raise CardError(f"签名服务 HTTP {response.status_code}")
    payload = response.json()
    if payload.get("code") != 200:
        raise CardError(f"签名失败: {payload.get('code')} {payload.get('msg')}")
    data = payload.get("data") or {}
    if not isinstance(data, dict) or not _REQUIRED_CARD_FIELDS.issubset(data):
        raise CardError("签名返回的卡片结构不完整")
    return data


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
