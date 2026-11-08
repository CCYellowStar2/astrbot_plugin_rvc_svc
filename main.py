from pathlib import Path
import os
import asyncio
import shutil
import time
from datetime import datetime
import traceback
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Record
from astrbot.api.message_components import Node, Plain, Image as CompImage
from astrbot.core.utils.session_waiter import session_waiter, SessionController
from astrbot.api import logger
from functools import partial
from gradio_client import Client
from .api_url import prepare_api_url
from .card_sender import (
    DEFAULT_ARK_API,
    CardError,
    ensure_cover,
    fetch_netease_cover,
    send_json_card,
    sign_ark,
    upload_audio,
)
from .bili_search import (
    build_board as build_bili_board,
    fetch_video_meta,
    parse_bv,
    search_videos as search_bili_videos,
)
from .separator_models import (
    extract_separator_models,
    format_separator_models,
    resolve_separator_model,
)

# 定义分隔符常量，方便修改
MODEL_ALIAS_SEPARATOR = "|||"

# 人声分离模型的快捷标记：/svc <歌名> [升降调] [msst|hp]
SEPARATOR_FLAGS = {
    "hp": "hp",
    "hp5": "hp",
    "vr": "hp",
    "msst": "msst",
    "roformer": "msst",
}
SEPARATOR_LABELS = {"hp": "VR-HP5 (默认)", "msst": "MSST BS-Roformer"}

# 混响快捷标记：/svc <歌名> 大混响
REVERB_FLAGS = {"大混响", "rv", "reverb", "bigreverb"}
BIG_REVERB_INTENSITY = 8
BIG_REVERB_DELAY = 5


def split_flags(args: list) -> tuple[list, str, bool]:
    """挑出 msst/hp（分离模型）与 大混响（混响+回声）标记，剩下的照旧当歌名。"""
    remaining, separator, big_reverb = [], None, False
    for token in args:
        key = token.strip().lower().lstrip("-")
        if key in SEPARATOR_FLAGS:
            separator = SEPARATOR_FLAGS[key]
        elif key in REVERB_FLAGS:
            big_reverb = True
        else:
            remaining.append(token)
    return remaining, separator, big_reverb


def clamp_db(value) -> float:
    """音量统一按 dB 处理：与后端滑条一致，限制在 -3 ~ 3，非法值当 0。"""
    try:
        return max(-3.0, min(3.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def format_elapsed_seconds(seconds: float) -> str:
    total_seconds = max(0, round(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes} 分 {remaining_seconds:02d} 秒"
    return f"{remaining_seconds} 秒"


@register(
    "astrbot_plugin_rvc_svc",
    "CCYellowStar2",
    "RVC/SVC翻唱网易云歌曲",
    "1.0.0",
    "https://github.com/CCYellowStar2/astrbot_plugin_rvc_svc",
)
class MusicPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._background_tasks = set()
        
        # === 支持两个独立的后端配置 ===
        self.rvc_base_url = prepare_api_url(config.get("rvc_base_url", "http://127.0.0.1:7860/"))
        self.svc_base_url = prepare_api_url(config.get("svc_base_url", "http://127.0.0.1:7866/"))
        self.separator_model = config.get("separator_model", "VR-HP5 (默认)")
        
        self.default_api = config.get("default_api", "netease_nodejs")
        self.nodejs_base_url = config.get("nodejs_base_url", "https://163api.qijieya.cn")
        self.timeout = config.get("timeout", 60)
        
        # === 为 RVC 和 SVC 分别存储模型列表 ===
        self.rvc_models_keywords = config.get("rvc_models_keywords", [])
        self.svc_models_keywords = config.get("svc_models_keywords", [])
        
        self.inference_timeout = config.get("inference_timeout", 300)
        
        if self.default_api == "netease":
            from .api import NetEaseMusicAPI
            self.api = NetEaseMusicAPI()
        elif self.default_api == "netease_nodejs":
            from .api import NetEaseMusicAPINodeJs
            self.api = NetEaseMusicAPINodeJs(base_url=self.nodejs_base_url)

    async def _async_predict(self, client, *args, timeout=300, **kwargs):
        """将同步的 predict 变为异步，并接受超时参数"""
        loop = asyncio.get_running_loop()
        job = client.submit(*args, **kwargs)
        fn = partial(job.result, timeout=timeout)
        return await loop.run_in_executor(None, fn)

    def _voice_display_name(self, model_name: str, api_type: str) -> str:
        """把模型文件名换成展示用的歌手名：优先用配置里的别名，否则用去扩展名的文件名。"""
        models_keywords = self.svc_models_keywords if api_type == "svc" else self.rvc_models_keywords
        for item in models_keywords or []:
            parts = str(item).split(MODEL_ALIAS_SEPARATOR, 1)
            if parts[0] == model_name:
                return (parts[1].strip() if len(parts) > 1 and parts[1].strip() else os.path.splitext(model_name)[0])
        return os.path.splitext(str(model_name or ""))[0] or "AI 歌手"

    @staticmethod
    def _supports_music_card(event: AstrMessageEvent) -> bool:
        """音乐卡片只有 OneBot(aiocqhttp) 能发，其他平台直接发文件，不做无谓尝试。"""
        try:
            return event.get_platform_name() == "aiocqhttp"
        except Exception:
            return False

    async def _send_result_audio(self, event: AstrMessageEvent, result_path: str, song: dict | None = None,
                                 voice_name: str = ""):
        sent_as_card = False
        if self.config.get("music_card", True) and self._supports_music_card(event):
            try:
                await self._send_music_card(event, result_path, song or {}, voice_name)
                sent_as_card = True
            except Exception as error:
                logger.warning(f"音乐卡片发送失败，回退为文件: {error}")
        try:
            if not sent_as_card:
                await event.send(event.chain_result([Record(file=result_path)]))
        except Exception:
            logger.error(traceback.format_exc())
        finally:
            if os.path.isfile(result_path):
                try:
                    os.remove(result_path)
                except OSError as error:
                    logger.error(f"删除临时文件失败: {error}")

    async def _send_music_card(self, event: AstrMessageEvent, result_path: str, song: dict, voice_name: str = ""):
        """上传 -> 签名 -> 发卡片；任何一步失败都抛异常，由调用方回退。"""
        if event.get_platform_name() != "aiocqhttp":
            raise CardError(f"当前平台 {event.get_platform_name()} 不支持音乐卡片")

        title = (song.get("name") or "AI 翻唱").strip()
        # 歌手位写「翻唱用的歌手」（模型名/别名），原唱放标题里，避免卡片上显示成原唱
        original_artist = (song.get("artists") or "").strip()
        singer = (voice_name or "").strip() or original_artist or "AI 歌手"
        cover = song.get("pic") or ""
        if not cover:
            # 签名服务要求 cover 非空；网易云那条路没有封面，补取一次
            cover = await asyncio.to_thread(fetch_netease_cover, song.get("id"))
        # 还没有就用内置默认封面兜底（首次上传后进程内缓存）
        cover = await asyncio.to_thread(ensure_cover, cover)

        audio_url = await asyncio.to_thread(upload_audio, result_path)
        card_title = f"{title}（AI 翻唱）"
        if original_artist and original_artist != singer:
            card_title = f"{title}（AI 翻唱 · 原唱 {original_artist}）"
        card = await asyncio.to_thread(
            sign_ark,
            self.config.get("ark_api") or DEFAULT_ARK_API,
            self.config.get("ark_key", ""),
            audio_url,
            card_title,
            singer,
            cover,
            audio_url,
            self.config.get("music_card_format", "qq"),
        )
        await send_json_card(event, card)
        logger.info(f"音乐卡片已发送: {card_title} / 歌手={singer}")

    def get_models_display_list(self, api_type="rvc"):
        """获取指定 API 类型的模型显示列表"""
        models_keywords = self.svc_models_keywords if api_type == "svc" else self.rvc_models_keywords
        display_names, key_list = [], []
        for index, item_str in enumerate(models_keywords, start=1):
            parts = item_str.split(MODEL_ALIAS_SEPARATOR, 1)
            model_name = parts[0]
            alias = parts[1] if len(parts) > 1 and parts[1] else ""
            display_name = alias or os.path.splitext(model_name)[0]
            display_names.append(f"{index}. {display_name}")
            key_list.append(model_name)
        return "\n".join(display_names), key_list

    def _fetch_separator_models(self, base_url: str | None = None) -> list[str]:
        # 分离模型列表按「当前使用的后端」去取，取不到再交叉兜底，
        # 避免只用 SVC 时因为连不上 RVC 而整条 /svc 流程失败。
        primary = base_url or self.rvc_base_url
        candidates = [primary, self.svc_base_url if primary == self.rvc_base_url else self.rvc_base_url]
        last_error = None
        for candidate in candidates:
            try:
                client = Client(prepare_api_url(candidate))
                return extract_separator_models(client.config)
            except Exception as error:
                last_error = error
                logger.warning(f"从 {candidate} 获取人声分离模型失败: {error}")
        raise last_error

    def _current_default_separator(self) -> str:
        """默认分离模型：每次现读配置，WebUI 里改完保存即生效。"""
        value = self.config.get("separator_model") or getattr(self, "separator_model", "")
        value = str(value or "").strip()
        return value or "VR-HP5 (默认)"

    def _resolve_separator_model(self, models: list[str]) -> str:
        selected_model, changed = resolve_separator_model(models, self._current_default_separator())
        if changed:
            self.separator_model = selected_model
            self.config["separator_model"] = selected_model
            self.config.save_config()
        return selected_model

    def _get_active_separator_model(self, base_url: str | None = None) -> str:
        return self._resolve_separator_model(self._fetch_separator_models(base_url))

    def _resolve_uvr_choice(self, base_url: str, preference: str | None = None) -> str:
        """本次用哪个分离模型：没指定就跟随配置里的默认值。"""
        if not preference:
            return self._get_active_separator_model(base_url)
        models = self._fetch_separator_models(base_url)
        keywords = ("msst", "roformer") if preference == "msst" else ("hp", "karaoke")
        for model in models:
            name = model.lower()
            if any(keyword in name for keyword in keywords):
                return model
        fallback, _ = resolve_separator_model(models, self._current_default_separator())
        logger.warning(f"后端没有与 {preference} 匹配的分离模型，回退到 {fallback}；可选: {models}")
        return fallback

    def _separator_models_message(self, models: list[str], selected_model: str) -> str:
        return f"可用人声分离模型：\n{format_separator_models(models, selected_model)}"

    async def _update_models_from_api(self, api_type="rvc"):
        """从指定的 API 更新模型列表"""
        base_url = self.svc_base_url if api_type == "svc" else self.rvc_base_url
        client = Client(prepare_api_url(base_url))
        try:
            model_list_from_api = await self._async_predict(client, api_name="/show_model")
        except Exception:
            model_list_from_api = await self._async_predict(client, api_name="/show_model")

        if not isinstance(model_list_from_api, list):
            raise ValueError(f"获取模型列表失败: {model_list_from_api}")

        # 获取当前配置的模型列表
        current_config_list = self.svc_models_keywords if api_type == "svc" else self.rvc_models_keywords
        old_aliases = {}
        for item_str in current_config_list:
            parts = item_str.split(MODEL_ALIAS_SEPARATOR, 1)
            if len(parts) > 1:
                old_aliases[parts[0]] = parts[1]

        new_models_list = [f"{m}{MODEL_ALIAS_SEPARATOR}{old_aliases.get(m, '')}" for m in model_list_from_api]
        
        # 保存模型列表
        if api_type == "svc":
            self.svc_models_keywords = new_models_list
            self.config["svc_models_keywords"] = new_models_list
        else:
            self.rvc_models_keywords = new_models_list
            self.config["rvc_models_keywords"] = new_models_list
        
        self.config.save_config()
        logger.info(f"{api_type.upper()} 模型列表已更新并成功保存，共 {len(new_models_list)} 个模型")

    @filter.command("分离模型列表")
    async def list_separator_models(self, event: AstrMessageEvent):
        try:
            models = self._fetch_separator_models()
            selected_model = self._resolve_separator_model(models)
            yield event.plain_result(self._separator_models_message(models, selected_model))
        except Exception as error:
            logger.error(traceback.format_exc())
            yield event.plain_result(f"获取分离模型列表失败: {error}")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("设置分离模型")
    async def set_separator_model(self, event: AstrMessageEvent):
        try:
            models = self._fetch_separator_models()
            selected_model = self._resolve_separator_model(models)
            args = event.message_str.replace("设置分离模型", "", 1).strip().split()
            if len(args) != 1 or not args[0].isdigit():
                yield event.plain_result(
                    f"用法: /设置分离模型 <序号>\n{self._separator_models_message(models, selected_model)}"
                )
                return

            model_index = int(args[0]) - 1
            if not 0 <= model_index < len(models):
                yield event.plain_result(
                    f"序号超出范围。\n{self._separator_models_message(models, selected_model)}"
                )
                return

            self.separator_model = models[model_index]
            self.config["separator_model"] = self.separator_model
            self.config.save_config()
            yield event.plain_result(f"已设置人声分离模型: {self.separator_model}")
        except Exception as error:
            logger.error(traceback.format_exc())
            yield event.plain_result(f"设置分离模型失败: {error}")

    # ==================== RVC 命令 ====================
    
    @filter.command("刷新rvc模型")
    async def refresh_rvc_models(self, event: AstrMessageEvent):
        yield event.plain_result("正在刷新 RVC 模型列表，请稍候...")
        try:
            await self._update_models_from_api(api_type="rvc")
            yield event.plain_result("刷新成功！")
            display_str, _ = self.get_models_display_list(api_type="rvc")
            display_str = display_str or "未发现任何模型。"
            chain=[Plain(f"当前 RVC 可用模型：\n{display_str}")]
            node = Node(
                uin=3974507586,
                name="玖玖瑠",
                content=chain
            )
            await event.send(event.chain_result([node]))
        except Exception as e:
            logger.error(traceback.format_exc())
            yield event.plain_result(f"刷新 RVC 模型出错了: {e}")
            
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("设置rvc后端链接")
    async def set_rvc_url(self, event: AstrMessageEvent):
        args = event.message_str.replace("设置rvc后端链接", "").strip().split()
        if not args:
            yield event.plain_result(f"当前 RVC 后端: {self.rvc_base_url}\n用法: /设置rvc后端链接 <URL>")
            return
        _url = prepare_api_url(args[0])
        self.rvc_base_url = _url
        self.config["rvc_base_url"] = _url
        self.config.save_config()
        yield event.plain_result(f"RVC 后端链接已设置为: {_url}")

    @filter.command("rvc")
    async def rvc(self, event: AstrMessageEvent):
        """RVC 翻唱命令"""
        async for result in self._handle_cover(event, api_type="rvc"):
            yield result

    # ==================== SVC 命令 ====================
    
    @filter.command("刷新svc模型")
    async def refresh_svc_models(self, event: AstrMessageEvent):
        yield event.plain_result("正在刷新 SVC 模型列表，请稍候...")
        try:
            await self._update_models_from_api(api_type="svc")
            yield event.plain_result("刷新成功！")
            display_str, _ = self.get_models_display_list(api_type="svc")
            display_str = display_str or "未发现任何模型。"
            chain=[Plain(f"当前 SVC 可用模型：\n{display_str}")]
            node = Node(
                uin=3974507586,
                name="玖玖瑠",
                content=chain
            )
            await event.send(event.chain_result([node]))
        except Exception as e:
            logger.error(traceback.format_exc())
            yield event.plain_result(f"刷新 SVC 模型出错了: {e}")
            
    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("设置svc后端链接")
    async def set_svc_url(self, event: AstrMessageEvent):
        args = event.message_str.replace("设置svc后端链接", "").strip().split()
        if not args:
            yield event.plain_result(f"当前 SVC 后端: {self.svc_base_url}\n用法: /设置svc后端链接 <URL>")
            return
        _url = prepare_api_url(args[0])
        self.svc_base_url = _url
        self.config["svc_base_url"] = _url
        self.config.save_config()
        yield event.plain_result(f"SVC 后端链接已设置为: {_url}")

    @filter.command("svc")
    async def svc(self, event: AstrMessageEvent):
        """SVC 翻唱命令"""
        async for result in self._handle_cover(event, api_type="svc"):
            yield result

    @filter.command("rvcb")
    async def rvcb(self, event: AstrMessageEvent):
        """RVC 翻唱（素材从 B 站搜索）"""
        async for result in self._handle_cover(event, api_type="rvc", cmd="rvcb", source="bili"):
            yield result

    @filter.command("svcb")
    async def svcb(self, event: AstrMessageEvent):
        """SVC 翻唱（素材从 B 站搜索）"""
        async for result in self._handle_cover(event, api_type="svc", cmd="svcb", source="bili"):
            yield result

    # ==================== 通用处理逻辑 ====================

    async def _handle_cover(self, event: AstrMessageEvent, api_type="rvc", cmd=None, source="netease"):
        """统一的翻唱处理逻辑；source="bili" 时改用 B 站搜索，song id 传 BV 号。"""
        cmd = cmd or api_type  # "rvc" / "svc" / "rvcb" / "svcb"
        args = event.message_str.replace(cmd, "", 1).strip().split()
        args, separator_pref, big_reverb = split_flags(args)
        
        if not args:
            subject = "关键词或 BV 号" if source == "bili" else "歌名"
            yield event.plain_result(
                f"用法: /{cmd} <{subject}> [升降调] [msst|hp] [大混响]\n"
                "msst 用 MSST BS-Roformer 分离、hp 用 VR-HP5（不加则跟随 /设置分离模型）；"
                "末尾加 大混响 会给这一首叠混响 8 + 回声 5"
            )
            return

        key_shift, song_name = 0, " ".join(args)
        if args and args[-1].lstrip('-').isdigit():
            try:
                val = int(args[-1])
                if -12 <= val <= 12:
                    key_shift = val
                    song_name = " ".join(args[:-1]) if len(args) > 1 else ""
            except ValueError: pass
        
        if not song_name:
            yield event.plain_result("请输入歌名！" if source == "netease" else "请输入要搜索的视频关键词！")
            return

        # --- 步骤 1: 确定素材（B 站可以直接贴 BV 号跳过搜索） ---
        id = event.get_sender_id()
        direct_bv = parse_bv(song_name) if source == "bili" else None

        if direct_bv:
            try:
                selected_song = await fetch_video_meta(direct_bv)
            except Exception as error:
                logger.error(traceback.format_exc())
                logger.warning(f"按 BV 号取视频信息失败: {error}")
                selected_song = {
                    "id": direct_bv,
                    "name": f"B站视频 {direct_bv}",
                    "artists": "",
                    "duration": "",
                    "play": "",
                }
            yield event.plain_result(f"已识别视频：{selected_song['name']}（{selected_song['id']}）")
        else:
            if source == "bili":
                try:
                    songs = await search_bili_videos(song_name, limit=16)
                except Exception as error:
                    logger.error(traceback.format_exc())
                    yield event.plain_result(f"B 站搜索失败了（已自动重试 3 次）: {error}\n稍后再试，或改用 /svc 从网易云搜。")
                    return
                if not songs:
                    yield event.plain_result("没能找到这个视频喵~")
                    return
                board = None
                try:
                    board = await asyncio.to_thread(build_bili_board, songs)
                except Exception as error:
                    logger.error(traceback.format_exc())
                if board:
                    await event.send(event.chain_result([CompImage.fromFileSystem(board)]))
                    try:
                        os.remove(board)
                    except OSError:
                        pass
                    yield event.plain_result(f"请回复序号（1-{len(songs)}），{self.timeout} 秒内：")
                else:
                    await self._send_selection(event, songs)
                    yield event.plain_result(f"封面图生成失败，请回复序号（1-{len(songs)}），{self.timeout} 秒内：")
            else:
                songs = await self.api.fetch_data(keyword=song_name, limit=10)
                if not songs:
                    yield event.plain_result("没能找到这首歌喵~")
                    return
                await self._send_selection(event, songs)
                yield event.plain_result(f"请在{self.timeout}秒内输入歌曲序号进行选择：")

            selected_song_index = None

            @session_waiter(timeout=self.timeout)
            async def song_waiter(controller: SessionController, event: AstrMessageEvent):
                if event.get_sender_id() != id:
                    return
                nonlocal selected_song_index
                user_input = event.message_str.strip()
                if user_input.isdigit() and 1 <= int(user_input) <= len(songs):
                    selected_song_index = int(user_input) - 1
                    controller.stop()

            try:
                await song_waiter(event)
            except TimeoutError:
                yield event.plain_result("选择超时，操作已取消。")
                return

            if selected_song_index is None:
                return

            selected_song = songs[selected_song_index]

        # --- 步骤 2: 等待用户选择模型 ---
        display_str, keys = self.get_models_display_list(api_type=api_type)
        if not keys:
            yield event.plain_result(f"当前没有可用的 {api_type.upper()} 模型，请先使用 /刷新{api_type}模型。")
            return
        
        chain=[Plain(f"已选歌曲: {selected_song['name']}\n使用: {api_type.upper()}\n\n可用模型：\n{display_str}")]
        node = Node(
            uin=3974507586,
            name="玖玖瑠",
            content=chain
        )
        await event.send(event.chain_result([node]))
        yield event.plain_result(f"请在{self.timeout}秒内输入模型序号：")
        
        selected_model_index = None

        @session_waiter(timeout=self.timeout)
        async def model_waiter(controller: SessionController, event: AstrMessageEvent):
            if event.get_sender_id() != id:
                return    
            nonlocal selected_model_index
            user_input = event.message_str.strip()
            if user_input.isdigit() and 1 <= int(user_input) <= len(keys):
                selected_model_index = int(user_input) - 1
                controller.stop()

        try:
            await model_waiter(event)
        except TimeoutError:
            yield event.plain_result("选择超时，操作已取消。")
            return

        if selected_model_index is None:
             return

        selected_model = keys[selected_model_index]

        # --- 步骤 3: 执行翻唱 ---
        separator_note = f"，分离模型用 {SEPARATOR_LABELS[separator_pref]}（本次）" if separator_pref else ""
        reverb_note = f"，本次启用大混响（混响 {BIG_REVERB_INTENSITY} / 回声 {BIG_REVERB_DELAY}）" if big_reverb else ""
        yield event.plain_result(f"好的！正在使用 {api_type.upper()} 模型【{selected_model}】{separator_note}{reverb_note} 为您生成《{selected_song['name']}》，请耐心等待...")
        await self._send_song(event=event, song=selected_song, model_name=selected_model, key_shift=key_shift, api_type=api_type, separator_pref=separator_pref, big_reverb=big_reverb)

    async def _send_selection(self, event: AstrMessageEvent, songs: list):
        formatted_songs = [f"{i + 1}. {s['name']} - {s['artists']}" for i, s in enumerate(songs[:10])]
        chain=[Plain("为您找到以下歌曲：\n" + "\n".join(formatted_songs))]
        node = Node(
            uin=3974507586,
            name="玖玖瑠",
            content=chain
        )
        await event.send(event.chain_result([node]))

    async def _send_song(self, event: AstrMessageEvent, song: dict, model_name: str, key_shift: int, api_type="rvc", separator_pref=None, big_reverb=False):
        """根据 API 类型调用对应的后端"""
        started_at = time.perf_counter()
        result_path = None
        try:
            base_url = self.svc_base_url if api_type == "svc" else self.rvc_base_url
            client = Client(prepare_api_url(base_url))
            # 不带 大混响 时不传这两个参数，保持后端滑条的默认（混响 4 / 回声 0）
            effect_params = (
                {"reverb_intensity": BIG_REVERB_INTENSITY, "delay_intensity": BIG_REVERB_DELAY}
                if big_reverb
                else {}
            )
            result_path = await self._async_predict(
                client,
                song_name_src=str(song["id"]),
                key_shift=key_shift,
                vocal_vol=clamp_db(self.config.get("vocal_vol", 0)),
                inst_vol=clamp_db(self.config.get("inst_vol", 0)),
                model_dropdown=model_name,
                uvr_choice=self._resolve_uvr_choice(base_url, separator_pref),
                **effect_params,
                api_name="/convert",
                timeout=self.inference_timeout
            )
            if result_path and os.path.exists(result_path):
                elapsed = format_elapsed_seconds(time.perf_counter() - started_at)
                await event.send(event.plain_result(f"✅ 翻唱完成，总用时：{elapsed}"))
                task = asyncio.create_task(
                    self._send_result_audio(
                        event, result_path, song, self._voice_display_name(model_name, api_type)
                    )
                )
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
                result_path = None
            else:
                await event.send(event.plain_result(f"生成失败，后端未返回有效文件路径。"))
        except Exception as e:
            logger.error(traceback.format_exc())
            if "Timeout" in str(e):
                await event.send(event.plain_result(f"生成超时了！后端在 {self.inference_timeout} 秒内没有完成任务。如果需要，请在配置文件中调高 'inference_timeout' 的值。"))
            else:
                await event.send(event.plain_result(f"生成时发生严重错误: {e}"))
        finally:
            if result_path and os.path.isfile(result_path):
                try: os.remove(result_path)
                except OSError as e: logger.error(f"删除临时文件失败: {e}")
