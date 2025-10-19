# astrbot_plugin_rvc_svc

## ✨ 简介
一个 [AstrBot](https://github.com/Soulter/AstrBot) 插件，可以使用 RVC 和 SVC 模型对网易云音乐的歌曲进行 AI 翻唱。支持自动下载歌曲、人声伴奏分离、AI 变声、音频后处理和混音等全流程操作。

## 📦 安装

### 方法一：通过插件商店安装（推荐）
通过 AstrBot 自带插件商店搜索 `astrbot_plugin_rvc_svc` 一键安装

### 方法二：手动安装
1. 下载本插件到 AstrBot 的 `data/plugins` 目录
2. 重启 AstrBot

## 🔧 前置要求

⚠️ **重要提示**：本插件需要配合后端 API 和原版RVC或SVC使用，请按以下步骤操作：

### 1. 下载 RVCSVC-API 后端整合包
**下载链接：** [你的整合包下载链接](https://cdn-lfs-cn-1.modelscope.cn/prod/lfs-objects/3b/c8/85158a094aae0eaa570626922757b85268c6a3dba7911913e4be9a4e1870?filename=RVCSVC-API.7z&namespace=CCYellowStar&repository=RVCSVC-API&revision=master&tag=model&auth_key=1760883358-05cb700c23334501a487fb5479f6a414-0-649c7193180e95e0b2025668eab34a8c
)

### 2. 启动后端服务
解压整合包后，根据需要启动对应的服务：
- 使用 RVC 模型：运行 `启动 rvcapi.bat`
- 使用 SVC 模型：运行 `启动 svcapi.bat`
- 两个都需要：同时运行两个 bat 文件
- **同时也要启动原版的RVC或者SVC（SVC需要替换一个文件，整合包里有说明）**

### 3. 查看使用说明
⚠️ **请务必阅读整合包内的 `使用说明.txt`**，里面包含：
- 模型放置位置
- 端口配置说明

## ⚙️ 配置

请在 AstrBot 的控制面板进行配置：

**插件管理 -> astrbot_plugin_rvc_svc -> 操作 -> 插件配置**

### 配置项说明

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `rvc_base_url` | RVCAPI 后端地址 | `http://127.0.0.1:7860/` |
| `svc_base_url` | SVCAPI 后端地址 | `http://127.0.0.1:7866/` |
| `default_api` | 音乐 API 类型 | `netease_nodejs` |
| `nodejs_base_url` | 网易云 API 地址 | `https://163api.qijieya.cn` |
| `timeout` | 用户选择超时时间（秒） | `60` |
| `inference_timeout` | AI 推理超时时间（秒） | `300` |
| `rvc_models_keywords` | RVC 模型别名列表 格式为 '模型文件名\|\|\|别名' | `[]` |
| `svc_models_keywords` | SVC 模型别名列表 格式为 '模型文件名\|\|\|别名' | `[]` |

## ⌨️ 使用方法

### RVC 模式命令
- `/rvc <歌名> [升降调]` - 使用 RVC 模型翻唱歌曲
- `/刷新rvc模型` - 从 RVC 后端刷新模型列表
- `/设置rvc后端链接 <URL>` - 设置 RVC 后端地址

### SVC 模式命令
- `/svc <歌名> [升降调]` - 使用 SVC 模型翻唱歌曲
- `/刷新svc模型` - 从 SVC 后端刷新模型列表
- `/设置svc后端链接 <URL>` - 设置 SVC 后端地址

### 参数说明
- `<歌名>`：要翻唱的歌曲名称
- `[升降调]`：可选参数，范围 -12 到 12，例如 `2` 表示升高 2 个半音

## 📌 使用示例

### 示例 1：使用 RVC 翻唱
```
用户: /rvc 孤勇者 2
Bot: 为您找到以下歌曲：
1. 孤勇者 - 陈奕迅
2. 孤勇者（伴奏） - 陈奕迅
...
请在60秒内输入歌曲序号进行选择：

用户: 1
Bot: 已选歌曲: 孤勇者
使用: RVC

可用模型：
1. 模型A
2. 模型B
...
请在60秒内输入模型序号：

用户: 1
Bot: 好的！正在使用 RVC 模型【模型A】为您生成《孤勇者》，请耐心等待...
[音频文件]
```

### 示例 2：刷新 SVC 模型列表
```
用户: /刷新svc模型
Bot: 正在刷新 SVC 模型列表，请稍候...
刷新成功！
当前 SVC 可用模型：
1. 声音模型_v1
2. 声音模型_v2
...
```

### 示例 3：设置后端地址
```
用户: /设置rvc后端链接 http://192.168.1.100:7860/
Bot: RVC 后端链接已设置为: http://192.168.1.100:7860/
```

## 🔄 工作流程

1. **歌曲搜索**：从网易云音乐搜索歌曲
2. **用户选择**：选择要翻唱的歌曲和 AI 模型
3. **自动下载**：从网易云下载原始音频
4. **人声分离**：使用 UVR5 分离人声和伴奏
5. **AI 变声**：使用 RVC/SVC 模型进行音色转换
6. **音频处理**：自动进行 EQ、压缩、混响等处理
7. **混音导出**：合并人声和伴奏，导出最终音频

## ❓ 常见问题

### Q1: 提示 "获取模型列表失败"
**A:** 请检查：
1. 对应的后端服务是否已启动（rvcapi.bat 或 svcapi.bat）
2. 配置的后端地址是否正确
3. 防火墙是否拦截了端口

### Q2: 生成超时怎么办？
**A:** 在插件配置中增加 `inference_timeout` 的值（默认 300 秒）

### Q3: 模型列表为空
**A:**
1. 确保已将模型文件放入整合包的正确目录（见 `使用说明.txt`）
2. 使用 `/刷新rvc模型` 或 `/刷新svc模型` 命令重新加载

### Q4: 音质不好或有杂音
**A:**
1. 检查原始歌曲音质
2. 尝试调整升降调参数
3. 确保使用的模型训练质量良好

### Q5: 同时使用 RVC 和 SVC 会冲突吗？
**A:** 不会！本插件已经做了文件隔离处理，两个模式可以同时使用互不干扰。

## 📊 系统要求

- **推荐配置**：
- GPU: NVIDIA 显卡（支持 CUDA）
- 显存: 4GB 及以上
- 内存: 16GB 及以上

## 更新日志

### V1.0.0
- ✨ 支持 RVC 和 SVC 双模式
- ✨ 独立的命令系统（/rvc 和 /svc）
- ✨ 分别管理两套模型列表
- ✨ 自动人声伴奏分离
- ✨ 音频后处理和混音

## 📝 许可证

本项目仅供学习和研究使用，请勿用于商业用途或侵犯他人权益。

## 🙏 致谢

- [AstrBot](https://github.com/Soulter/AstrBot) - 强大的跨平台聊天机器人框架
- [RVC](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) - RVC 语音转换项目
- [so-vits-svc](https://github.com/svc-develop-team/so-vits-svc) - SVC 语音转换项目
- [UVR5](https://github.com/Anjok07/ultimatevocalremovergui) - 人声分离工具
- [NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi) - 网易云音乐 API

## 📞 支持

- [AstrBot 帮助文档](https://astrbot.app)
- [问题反馈](https://github.com/你的用户名/astrbot_plugin_rvc_svc/issues)
