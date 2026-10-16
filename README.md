# 声伴 · ESP32 Server

个人使用的中文 ESP32 语音伙伴控制台。管理设备、角色、音色、模型连接和文字对话记录。
Python + SQLite + 原生网页，无需 Java、MySQL、Redis 或前端构建步骤。

语音引擎使用 [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)，
作为 Git submodule 固定在 `eb9dc8ca0fc8a30bc8afb0f302dcfc1578f76a7b`。
通过上游支持的 manager-api 接口提供配置和接收对话记录，不修改其核心语音代码。
上游及本项目采用 MIT 许可证，参见 [上游许可证](vendor/xiaozhi/LICENSE) 和 [本项目许可证](LICENSE)。

## 首版功能

- 单管理员账号：首次设置密码、登录、退出、HttpOnly 会话 Cookie、登录限流。
- 设备管理：MAC、设备名称、角色分配、独立接入地址、Client ID 固定绑定、实时连接状态。
- 角色配置：中文提示词、四种中文音色、语速。新语音连接读取最新配置。
- 模型配置：Ollama 本地模型，或兼容 Chat Completions 的服务；密钥不回显，切换地址需重新填写。
- 文字对话测试：多轮上下文、真实模型回复、会话历史。
- 语音服务：SenseVoiceSmall 中文识别 → 模型 → Edge TTS → Opus 音频回复。
- 对话记录：设备与网页来源标记、上报去重，首版只保存文字。

设备使用 WebSocket 协议，设备音量继续保存在板子上。长期记忆、知识库、多人账号、
手机控制、家电工具、MQTT 网关和云端固件升级留待后续扩展。
本服务不会给板子推送固件或资源包，因此不覆盖已适配的屏幕、触摸和唤醒模型。

## 当前电脑启动

```powershell
cd F:\Code\ESP32\esp32_server
.\scripts\start.ps1
```

打开 <http://127.0.0.1:8002/>。当前已创建的账号保存在本机 `data/first-login.txt`，
该文件、数据库、模型、日志、设备凭据均被 Git 忽略。
管理服务默认只监听本机 `8002`，语音服务监听本机 `8000`。
停止本项目启动的进程：`.\scripts\stop.ps1`。

启动脚本优先使用本项目 `.venv`，也支持 `ESP_PYTHON` 或 `-Python` 指定解释器。
本次部署复用了同级 `xiaozhi-server/.venv` 的 Python 3.10 环境和已有模型缓存；
本机 Ollama 必须处于运行状态，并已安装 `qwen2.5:3b`，或在网页中配置其他模型。

## 新机器安装

```bash
git clone --recurse-submodules https://github.com/rajqiu2022/esp32_server.git
cd esp32_server
python3.10 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

只体验管理界面与文字对话：`python -m server`，首次访问创建账号。
文字对话使用你在界面中配置的模型服务。

启用完整语音链路，还需系统 `ffmpeg`、`libopus`、语音引擎依赖和 ASR 模型：

```bash
pip install -r vendor/xiaozhi/main/xiaozhi-server/requirements.txt
python scripts/prepare_models.py
python scripts/run_all.py
```

`prepare_models.py` 下载 SenseVoiceSmall，并复制上游固定版本的 Silero VAD 文件到
`data/models`。已有缓存可用 `ESP_MODELS_DIR` 指定包含 `SenseVoiceSmall` 和
`snakers4_silero-vad` 两个目录的路径。模型体积较大，需要预留下载时间和磁盘空间。
Windows 原生安装还需让当前 Python 找到 `opus.dll` 与完整的 FFmpeg；本机复用环境已配置。

## 网络和板子接入

1. 管理后台“我的设备”添加板子的 MAC 和角色。
2. 设置板子能访问的地址，再启动服务。例如局域网：

   ```powershell
   $env:ESP_BIND_HOST='0.0.0.0'
   $env:ESP_PUBLIC_URL='http://电脑局域网IP:8002'
   $env:ESP_WS_URL='ws://电脑局域网IP:8000/xiaozhi/v1/'
   .\scripts\start.ps1
   ```

3. 点击设备的“接入地址”，将专属 OTA URL 配置到板子配网页面。
4. 板子重启后使用独立接入凭据领取语音连接 Token，首次连接固定其 Client ID。

专属 OTA URL 含设备接入凭据，只交给自己的板子。普通设备列表不返回该凭据。
更换板子身份或恢复出厂导致 Client ID 改变时，需要重新处理绑定，服务不会静默接受身份变化。

当前实物板子连接手机热点，电脑使用另一网络的有线连接；两者尚未互通。
在网络打通前可以使用网页测试，实物板子继续使用已配置的官方服务。
`127.0.0.1` 接入地址只供本机模拟设备测试，不能直接填到实物板子上。

## Docker / 云服务器

腾讯云的单域名 HTTPS/WSS 配置与账号迁移说明见 [腾讯云部署](deploy/tencent/README.md)。

提供 `Dockerfile`、`compose.yml` 和前台进程监督器，尚未在当前无 Docker 的 Windows 环境验证镜像构建。

```bash
cp .env.example .env
docker compose build
docker compose run --rm studio python scripts/prepare_models.py
docker compose up -d
```

默认端口仅映射到服务器回环地址。公网部署请用反向代理分别提供管理站点 HTTPS 和
语音站点 WSS，在 `.env` 中填写对应 `ESP_PUBLIC_URL`、`ESP_WS_URL`。
反向代理需要支持 WebSocket 升级，持久化保存 `data/`，不要将内部接口单独暴露。
容器内的 `127.0.0.1:11434` 指容器自身；网页配置中填写容器能访问的模型地址。
Edge TTS 需要联网，默认组合不属于完全离线方案。

## 验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q server scripts
node --check web/app.js
```

真实语音联调（需要已启动两项服务、可用模型及本机 `data/first-login.txt`）：

```bash
python scripts/smoke_voice.py
# 也可复用已有的合成语音文件
python scripts/smoke_voice.py --audio /path/to/test.mp3
```

脚本创建临时模拟设备，验证无效 Token 被拒绝，再运行完整 ASR → LLM → TTS 链路，
确认语音双向文字记录进入管理后台，并将回复解码为 `data/smoke-reply.wav`。
结束后清理本次创建的临时设备和测试记录。

本机已通过 8 项控制台与迁移集成测试、浏览器登录/添加设备/模型连接/网页对话验证，
完整语音测试收到 103 个 Opus 包并成功解码，双向文字记录上报通过。
模拟设备验证不等同于实物麦克风和扬声器验证。

## 数据与配置

`data/control.db` 包含账户、API Key、设备凭据和对话，`data/secrets.json` 包含内部服务密钥。
两者都属于私有部署数据，备份时一起保存；不会上传 GitHub。
数据库中的模型密钥没有额外应用层加密，访问权由部署主机和管理账号控制。
不要将 `data/` 或 `.runtime/` 作为静态网站目录。

`ESP_DATA_DIR` 可指定私有数据目录，`ESP_MODELS_DIR` 可指定模型缓存，
`ESP_BIND_HOST` 默认为 `127.0.0.1`，`ESP_PORT` 默认为 `8002`。
上游源码只读，运行时复制到忽略的 `.runtime/voice`，本项目配置与旧部署互不覆盖。
