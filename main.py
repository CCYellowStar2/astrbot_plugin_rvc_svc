from pathlib import Path
import os
import asyncio
import shutil
from datetime import datetime
import traceback
from pydub import AudioSegment
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.message.components import Record
from astrbot.api.message_components import Node, Plain, Image as CompImage
from astrbot.core.utils.session_waiter import session_waiter, SessionController
from astrbot import logger
from functools import partial
from gradio_client import Client

# 定义分隔符常量，方便修改
MODEL_ALIAS_SEPARATOR = "|||"

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
        
        # === 支持两个独立的后端配置 ===
        self.rvc_base_url = config.get("rvc_base_url", "http://127.0.0.1:7860/")
        self.svc_base_url = config.get("svc_base_url", "http://127.0.0.1:7866/")
        
        # 向后兼容旧配置
        if "base_url" in config and "rvc_base_url" not in config:
            self.rvc_base_url = config.get("base_url")
        
        self.default_api = config.get("default_api", "netease_nodejs")
        self.nodejs_base_url = config.get("nodejs_base_url", "http://127.0.0.1:3000")
        self.timeout = config.get("timeout", 60)
        
        # === 为 RVC 和 SVC 分别存储模型列表 ===
        self.rvc_models_keywords = config.get("rvc_models_keywords", [])
        self.svc_models_keywords = config.get("svc_models_keywords", [])
        
        # 向后兼容旧配置
        if "models_keywords" in config and not self.rvc_models_keywords:
            self.rvc_models_keywords = config.get("models_keywords", [])
        
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

    async def _update_models_from_api(self, api_type="rvc"):
        """从指定的 API 更新模型列表"""
        base_url = self.svc_base_url if api_type == "svc" else self.rvc_base_url
        client = Client(base_url)
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

    @filter.command("设置rvc后端链接")
    async def set_rvc_url(self, event: AstrMessageEvent):
        args = event.message_str.replace("设置rvc后端链接", "").strip().split()
        if not args:
            yield event.plain_result(f"当前 RVC 后端: {self.rvc_base_url}\n用法: /设置rvc后端链接 <URL>")
            return
        _url = args[0]
        if not _url.endswith("/"): _url += "/"
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

    @filter.command("设置svc后端链接")
    async def set_svc_url(self, event: AstrMessageEvent):
        args = event.message_str.replace("设置svc后端链接", "").strip().split()
        if not args:
            yield event.plain_result(f"当前 SVC 后端: {self.svc_base_url}\n用法: /设置svc后端链接 <URL>")
            return
        _url = args[0]
        if not _url.endswith("/"): _url += "/"
        self.svc_base_url = _url
        self.config["svc_base_url"] = _url
        self.config.save_config()
        yield event.plain_result(f"SVC 后端链接已设置为: {_url}")

    @filter.command("svc")
    async def svc(self, event: AstrMessageEvent):
        """SVC 翻唱命令"""
        async for result in self._handle_cover(event, api_type="svc"):
            yield result

    # ==================== 通用处理逻辑 ====================

    async def _handle_cover(self, event: AstrMessageEvent, api_type="rvc"):
        """统一的翻唱处理逻辑"""
        cmd = api_type  # "rvc" 或 "svc"
        args = event.message_str.replace(cmd, "").strip().split()
        
        if not args:
            yield event.plain_result(f"用法: /{cmd} <歌名> [升降调]")
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
            yield event.plain_result("请输入歌名！")
            return

        songs = await self.api.fetch_data(keyword=song_name, limit=10)
        if not songs:
            yield event.plain_result("没能找到这首歌喵~")
            return
        
        # --- 步骤 1: 等待用户选择歌曲 ---
        await self._send_selection(event, songs)
        yield event.plain_result(f"请在{self.timeout}秒内输入歌曲序号进行选择：")
        
        selected_song_index = None
        id = event.get_sender_id()
        
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
        yield event.plain_result(f"好的！正在使用 {api_type.upper()} 模型【{selected_model}】为您生成《{selected_song['name']}》，请耐心等待...")
        await self._send_song(event=event, song=selected_song, model_name=selected_model, key_shift=key_shift, api_type=api_type)

    async def _send_selection(self, event: AstrMessageEvent, songs: list):
        formatted_songs = [f"{i + 1}. {s['name']} - {s['artists']}" for i, s in enumerate(songs[:10])]
        chain=[Plain("为您找到以下歌曲：\n" + "\n".join(formatted_songs))]
        node = Node(
            uin=3974507586,
            name="玖玖瑠",
            content=chain
        )
        await event.send(event.chain_result([node]))

    async def _send_song(self, event: AstrMessageEvent, song: dict, model_name: str, key_shift: int, api_type="rvc"):
        """根据 API 类型调用对应的后端"""
        result_path = None
        try:
            base_url = self.svc_base_url if api_type == "svc" else self.rvc_base_url
            client = Client(base_url)
            result_path = await self._async_predict(
                client,
                song_name_src=str(song["id"]),
                key_shift=key_shift,
                vocal_vol=0,
                inst_vol=0,
                model_dropdown=model_name,
                api_name="/convert",
                timeout=self.inference_timeout
            )
            if result_path and os.path.exists(result_path):
                await event.send(event.chain_result([Record(file=result_path)]))
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
