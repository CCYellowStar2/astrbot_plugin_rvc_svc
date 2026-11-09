# astrbot_plugin_rvc_svc

## ✨ 简介

一个 [AstrBot](https://github.com/Soulter/AstrBot) 插件，用 RVC / SVC 模型把歌曲做成 AI 翻唱。
素材可以来自**网易云音乐**，也可以来自 **B 站视频**（搜索时直接发带封面的结果图，或者贴一个 BV 号）。
下载、人声分离、变声、混响、混音全在后端完成，插件只负责交互。

## 🆕 v1.1.0 新增

- **`/svcb`、`/rvcb`**：素材从 B 站来，搜索结果是**一张带封面的长图**（16 条，两栏），回序号即可
- **直接贴 BV 号**：`/svcb BV1NZ4y147dQ`（也认完整视频链接）跳过搜索，直奔选模型
- **人声分离模型可选**：配置项 `separator_model` 设默认值，命令里加 `msst` / `hp` 可临时覆盖
- **`大混响`** 参数：一首歌临时启用混响 8 + 回声 5
- **音乐卡片**：翻唱成品可以发成 QQ 音乐卡片（仅 OneBot 平台），失败自动退回语音文件
- 分离模型改为**按当前使用的后端**读取（以前固定读 RVC 那边，只用 SVC 时会被拖死）

## 📦 安装

### 方法一：通过插件商店安装（推荐）
在 AstrBot 插件商店搜索 `astrbot_plugin_rvc_svc` 一键安装。

### 方法二：手动安装
1. 下载本插件到 AstrBot 的 `data/plugins` 目录
2. 重启 AstrBot

依赖见 `requirements.txt`（`gradio_client`、`Pillow`、`bilibili-api-python`）。

## 🔧 前置要求

⚠️ 本插件只是交互层，**必须先有后端**（负责下载、分离、推理）：

1. 下载后端整合包：[ModelScope](https://www.modelscope.cn/models/CCYellowStar/RVCSVC-API/resolve/master/RVCSVC-API.7z)
   或使用源码：[RVCSVC-API](https://github.com/CCYellowStar2/RVCSVC-API)
2. 启动后端服务（按需选一个或都开）：
   - RVC 模型：`启动 rvcapi.bat`（默认 7860）
   - SVC 模型：`启动 svcapi.bat`（默认 7866）
   - **同时还要启动原版 RVC / so-vits-svc**（SVC 需要替换一个文件，整合包里有说明）
3. 模型文件放到整合包指定的目录，详见后端的 `使用说明.txt`

> 想用 `/svcb`、`/rvcb`，后端必须包含 `audio_source.py`（新版整合包），否则后端不认 BV 号。

## ⌨️ 命令一览

| 命令 | 说明 |
|------|------|
| `/svc <歌名> [升降调] [msst\|hp] [大混响]` | 网易云搜索 → 选歌 → 选模型 → SVC 翻唱 |
| `/rvc <歌名> [升降调] [msst\|hp] [大混响]` | 同上，走 RVC |
| `/svcb <关键词/BV号> [...]` | 素材从 B 站来（搜索发封面长图，或直接给 BV 号） |
| `/rvcb <关键词/BV号> [...]` | 同上，走 RVC |
| `/刷新svc模型` / `/刷新rvc模型` | 从后端重新拉取模型列表 |
| `/设置svc后端链接 <URL>` / `/设置rvc后端链接 <URL>` | 改后端地址（管理员） |
| `/分离模型列表` | 查看后端提供哪些人声分离模型 |
| `/设置分离模型 <序号>` | 改默认分离模型（管理员，等价于改配置项） |

### 参数说明

- `升降调`：`-12` ~ `12`，例如 `2` 表示升高 2 个半音；不带则不转调
- `msst` / `hp`：**只对本次生效**的分离模型选择
  - `msst` → MSST BS-Roformer（分离更干净，但更吃显存、更慢）
  - `hp` → VR-HP5（默认，5 分钟的歌十秒级）
- `大混响`：本次启用混响强度 8 + 回声 5（后端会自动测 BPM 定回声时值）
- 三个标记可以任意组合、顺序无关：`/svc 起风了 3 大混响 msst`

## ⚙️ 配置项

在 AstrBot 控制面板：**插件管理 → astrbot_plugin_rvc_svc → 插件配置**。

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `rvc_base_url` | RVCAPI 后端地址 | `http://127.0.0.1:7860/` |
| `svc_base_url` | SVCAPI 后端地址 | `http://127.0.0.1:7866/` |
| `separator_model` | **默认人声分离模型** | `VR-HP5 (默认)` |
| `default_api` | 网易云 API 实现 | `netease_nodejs` |
| `nodejs_base_url` | 网易云 Node.js API 地址 | `https://wyy.xhily.com` |
| `timeout` | 等待用户选择歌曲/模型的秒数 | `30` |
| `inference_timeout` | 等待后端推理完成的秒数 | `300` |
| `rvc_models_keywords` | RVC 模型别名，格式 `模型文件名\|\|\|别名` | `[]` |
| `svc_models_keywords` | SVC 模型别名，格式同上 | `[]` |
| `music_card` | 翻唱结果用 QQ 音乐卡片发送（仅 OneBot 生效） | `true` |
| `ark_key` | 音乐卡片签名服务的 key，留空则不发卡片 | 空 |
| `ark_api` | 音乐卡片签名服务地址 | 咸鱼 API 的 QQ 音乐卡片接口 |
| `music_card_format` | 卡片签名格式（`qq` / `bilibili`） | `qq` |
| `voice_also` | 卡片发成功时也补发一条语音 | `false` |
| `vocal_vol` | 人声音量（dB，-3 ~ 3，与后端滑条一致） | `0` |
| `inst_vol` | 伴奏音量（dB，-3 ~ 3，与后端滑条一致） | `0` |

> `separator_model` 改完**保存即生效**（插件每次使用时现读配置，不用重载）。
> 命令里的 `msst` / `hp` 优先级高于它；配置值在后端列表里找不到时会自动回退到第一项。

## 🎯 分离模型怎么选

| | VR-HP5 | MSST BS-Roformer |
|---|---|---|
| 速度 | 快（5 分钟的歌约 10~20 秒） | 慢（同长度约 1.5~2 分钟，取决于 `num_overlap`） |
| 显存 | 低 | 中（60 秒素材峰值约 2.8 GB） |
| 分离质量 | 一般，伴奏里常有人声残留 | 更干净，人声更实 |

## 🖼 B 站封面图

`/svcb` 会下载前 16 条结果的封面，用 Pillow 拼成一张 900px 宽的长图（两栏 × 8 行），
每条带序号、标题（超长自动折两行 + 省略号）、UP 主、时长、播放量。

字体使用 `assets/NotoSansCJKsc-Regular.ttf`（Noto Sans CJK SC 的**子集**，SIL OFL 1.1，见 `assets/NOTO-LICENSE.txt`）。
容器里默认没有中文字体，不附带这个文件就会渲染成方块。

该文件已用 fontTools 子集化：**GBK 全集（22097 字，含繁体）+ ASCII + 中文标点/全角符号**，
并去掉 OpenType 布局表（GSUB/GPOS/GDEF，只影响西文连字与字距微调），15.7 MB → **5.8 MB**。
实测常见标题、UP 主名、繁体人名（黄霄雲、臺灣）都不缺字；emoji 与极冷僻字仍会显示成方块
（字体本身没有 emoji 字形，改用完整字体也一样）。

## 🎵 音乐卡片（仅 OneBot 平台）

翻唱完成后，插件可以发一张**QQ 音乐卡片**，而不是一段语音文件。链路是：

1. 成品 mp3 先上传到临时存储（`uguu.se` 优先，失败换 `pomf2.lain.la`，每个源还会再试一次），拿到公网直链
2. 用签名服务（默认咸鱼 API 的 `qq-musicArk`）把直链签成可渲染的卡片数据；**失败会重试 2 次**（间隔 1s、2s），参数错误类（400）不重试
3. 通过 OneBot 的 `json` 消息段发出

**任何一步失败都会自动退回语音文件**，不会让成品发不出去。

卡片上的字段：标题「歌名（AI 翻唱 · 原唱 xxx）」，**歌手位写的是翻唱用的歌手名**（取模型的别名，没配别名就用去掉 `.pth` 的文件名）。

封面：B 站搜索结果的封面或网易云 `song/detail` 的 `album.picUrl` 会由插件**下载后规范成 300×300 JPEG 再上传**（而不是把原 URL 直接丢给签名服务）——这样能绕开 B 站防盗链占位图、网易云 7 MB 超大原图、WebP/透明 PNG 等内容类问题；取不到时用内置默认封面兜底。上传结果按源 URL 缓存，2 小时后失效重传（临时存储本身 3 小时删除文件）。

| 项 | 说明 |
|---|---|
| 平台 | 仅 `aiocqhttp`（NapCat / SnowLuma 等 OneBot 实现）；官方机器人平台不支持自定义音乐卡片 |
| 保留时间 | 临时存储通常只保留数小时，卡片过期后无法播放 |
| `ark_key` | 需要自行申请；留空 = 不发卡片，直接发文件 |
| `music_card_format` | `qq` 与 `bilibili` 实测能签；**`163` 当前服务端一律返回 500**（换网易云自家直链也一样，属服务端问题），选中后会走重试再回退文件 |

> 注：AstrBot 自带的 `Music` 组件不能直接用——它的 `_type` 字段被当作私有字段，`toDict()` 里没有 `type`，协议端认不出是卡片。本插件自己拼 `{"type":"json","data":{"data":…}}` 段发送。

## 📌 使用示例

### 网易云翻唱
```
用户: /svc 孤勇者 2
Bot: 为您找到以下歌曲：
1. 孤勇者 - 陈奕迅
2. 孤勇者（伴奏） - 陈奕迅
请在30秒内输入歌曲序号进行选择：

用户: 1
Bot: 已选歌曲: 孤勇者
使用: SVC

可用模型：
1. 模型A
2. 模型B
请在30秒内输入模型序号：

用户: 1
Bot: 好的！正在使用 SVC 模型【模型A】 为您生成《孤勇者》，请耐心等待...
[音频文件]
```

### B 站搜索 + MSST 分离 + 大混响
```
用户: /svcb 起风了 翻唱 3 大混响 msst
Bot: [一张 16 条结果的封面长图]
请回复序号（1-16），30 秒内：

用户: 3
Bot: 已选歌曲: 【翻唱】起风了 - 买辣椒也用券｜鲸鱼娘溯希Ver.
使用: SVC
...
Bot: 好的！正在使用 SVC 模型【模型A】，分离模型用 MSST BS-Roformer（本次），本次启用大混响（混响 8 / 回声 5） 为您生成《起风了》，请耐心等待...
```

### 直接贴 BV 号
```
用户: /svcb BV1NZ4y147dQ
Bot: 已识别视频：起风了 初级版 动态鼓谱（BV1NZ4y147dQ）
可用模型：...
```

## 🔄 工作流程

1. **搜素材**：网易云搜索 / B 站搜索（或直接给 BV 号）
2. **选模型**：从后端拉取可用的 RVC/SVC 音色
3. **后端处理**：下载音频 → 人声伴奏分离 → 变声推理 → 混响/混音
4. **回传**：插件把成品音频发给用户

## ❓ 常见问题

**Q1：提示「获取分离模型列表失败」或「生成时发生严重错误: [Errno 111] Connection refused」**
A：后端没起来或地址不对。只用 SVC 时确认 `启动 svcapi.bat` 在跑；这类报错是连不上端口，不是代码问题。

**Q2：B 站搜索报错**
A：搜索依赖 `bilibili-api-python`（自带 wbi 签名）。报错原文会直接回到聊天里；如果是 BV 号报错，注意 **BV 号区分大小写**。

**Q3：`/svcb` 不出封面图**
A：会退化成纯文字列表（功能不受影响）。若想恢复，检查 `assets/NotoSansCJKsc-Regular.ttf` 是否还在、`Pillow` 是否装好。

**Q4：生成超时**
A：调大 `inference_timeout`（默认 300 秒）。MSST 分离比 VR-HP5 慢得多，建议配合后端的 `num_overlap` 调优。

**Q5：某些歌下载失败**
A：VIP / 版权受限的歌拿不到音频直链，后端会返回具体是哪个源失败；换一首或改用 B 站视频。

**Q6：B 站视频只有一部分被翻唱**
A：目前只取视频第 1 P；超过 5 分钟的部分后端会自动截断。

**Q7：开了音乐卡片但收到的还是语音/文件**
A：说明卡片链路某一步失败了（默认会记 warning 日志）。常见原因：`ark_key` 没填或额度用尽、临时存储上传失败、当前平台不是 OneBot。看 AstrBot 日志里 `音乐卡片发送失败，回退为文件:` 后面的具体原因。

## 📊 系统要求

- GPU：NVIDIA 显卡（支持 CUDA），显存 4 GB 起
- 内存：16 GB 及以上
- 后端整合包自带 Python 运行时，无需单独安装 Python

## 更新日志

### V1.4.0
- 🐛 **修复卡片偶发发不出去**：实测标题里带 `·`（U+00B7）/ `〜`（U+301C）/ 半角括号时，QQ 音乐卡片会返回 `retcode=100 未确认送达` 而被丢弃。现在统一替换为安全等价物（`·`→`-`、`〜`→`~`、半角括号→全角）
- ✨ 新增管理员命令 `/卡片测试 [text|audio|cover|jp|long|sym|t:任意标题]`：单变量发测试卡片，用来定位「是文案、音频还是封面」的问题

### V1.3.7 / V1.3.8 / V1.3.9
- 🔧 逐步完善 `/卡片测试`：先做基线，再拆成 text / audio / cover 单变量模式，最后细化到 jp / long / sym / 自由标题

### V1.3.6
- 🐛 卡片标题/歌手做净化：去掉 emoji 与控制符、压缩空白、标题限 40 字、歌手限 20 字（超长用省略号）
- 🔧 发送前记录实际使用的标题与歌手，便于排查是文案还是其它原因

### V1.3.5
- ✨ 新增 `card_cover_mode`（`auto` / `default`）：可强制使用内置默认封面，用于区分封面与其它原因

### V1.3.4
- 🐛 封面改为**下载后规范成 300×300 JPEG 再上传**，修复「有些歌封面发不出来」（防盗链占位图 / 超大原图 / WebP 等）
- 🐛 默认封面缓存加 2 小时过期，避免临时存储过期后一直用死链接

### V1.3.3
- 🐛 卡片发送遇到「QQ 未回执」时自动重试一次（这类情况卡片往往已送达，只是没有回执）
- 🔧 卡片发送失败的错误信息带上原始异常类型，便于排查

### V1.3.2
- 🐛 修复 `bili_search.py` 缺少 `logger` 导入（异常/重试分支会 `NameError`）

### V1.3.1
- ✨ 新增 `voice_also` 配置：卡片发成功时也可以**同时补发一条语音**
- 🔧 文案统一：回退出去的是**语音消息**，不再是「文件」的说法

### V1.3.0
- ✨ 翻唱结果可选发 **QQ 音乐卡片**（仅 OneBot 平台）：上传临时存储 → 签名服务 → json 卡片；失败自动回退语音
- ✨ 封面四级兜底：B 站封面 → 网易云专辑图（https + 300×300）→ 内置默认封面
- ✨ 卡片歌手位显示**翻唱用的歌手名**（取模型别名），原唱挪到标题
- ✨ 新增 `vocal_vol` / `inst_vol` 配置（人声与伴奏各 ±3 dB，与后端滑条一致）
- 🐛 分离模型列表按当前后端读取，修复只用 SVC 时去连 RVC 端口的问题；改为异步取，不再阻塞事件循环
- 🐛 B 站搜索加 3 次退避重试 + 传输参数，缓解 TLS 握手中断
- 🐛 非 OneBot 平台直接跳过音乐卡片，不再做无谓尝试
- 🔧 按上架审查整改：logger 导入、`gradio_client.Client` 改 `asyncio.to_thread`、清理死代码、统一默认值

### V1.1.0
- ✨ 新增 `/svcb`、`/rvcb`：B 站搜索、封面长图、直接贴 BV 号
- ✨ 新增配置项 `separator_model`（默认人声分离模型）
- ✨ 新增命令参数 `msst` / `hp` / `大混响`
- 🐛 分离模型改为按当前后端读取，修复只用 SVC 时仍然去连 RVC 端口的问题
- 🐛 `separator_model` 改为每次现读配置，改完保存即生效

### V1.0.0
- ✨ 支持 RVC 和 SVC 双模式
- ✨ 独立的命令系统（/rvc 和 /svc）
- ✨ 分别管理两套模型列表
- ✨ 自动人声伴奏分离
- ✨ 音频后处理和混音

## 📝 许可证

本项目仅供学习和研究使用，请勿用于商业用途或侵犯他人权益。

`assets/NotoSansCJKsc-Regular.ttf` 采用 SIL Open Font License 1.1，许可证全文见 `assets/NOTO-LICENSE.txt`。

## 🙏 致谢

- [AstrBot](https://github.com/Soulter/AstrBot) - 跨平台聊天机器人框架
- [RVC](https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI) - RVC 语音转换项目
- [so-vits-svc](https://github.com/svc-develop-team/so-vits-svc) - SVC 语音转换项目
- [MSST](https://github.com/Anjok07/ultimatevocalremovergui) - 人声分离（BS-Roformer）
- [UVR5](https://github.com/Anjok07/ultimatevocalremovergui) - VR 架构人声分离
- [NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi) - 网易云音乐 API
- [bilibili-api-python](https://github.com/Nemo2011/bilibili-api) - B 站接口
- [Noto Sans CJK](https://github.com/notofonts/noto-cjk) - 中文字体

## 📞 支持

- [AstrBot 帮助文档](https://astrbot.app)
- [问题反馈](https://github.com/CCYellowStar2/astrbot_plugin_rvc_svc/issues)
