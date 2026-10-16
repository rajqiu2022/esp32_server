# 腾讯云部署配置

本配置供已有 Linux 服务器使用。实际服务器、域名和 SSH 访问方式确定后再执行部署。
本机已运行的服务和实物板子的官方服务连接不会因准备这些文件而改变。

## 访问结构

- 一个域名承载管理网页、HTTPS 设备配网接口及 WSS 语音。
- Caddy 自动管理 HTTPS；`/xiaozhi/v1/` 转发语音服务，其余普通请求转发管理服务。
- `/xiaozhi/` 下其他 manager-api 路由在公网入口返回 404。
- 容器的 8000、8002 端口不直接映射到主机公网，仅 Caddy 发布 TCP 80、443。
- 语音引擎、ASR 模型和数据库位于服务器；大模型可以通过网页配置为外部 API。

Caddy 的 WebSocket 转发与证书行为见官方文档：
[reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)、
[Automatic HTTPS](https://caddyserver.com/docs/automatic-https)。
腾讯云服务器入口规则需要根据实际使用的轻量应用服务器防火墙或 CVM 安全组配置，
参见[轻量应用服务器防火墙](https://cloud.tencent.cn/document/product/1207/44577)。
SSH 端口保留供部署维护，80/443 供证书和用户访问；不要开放容器内部端口。

## 迁移现有账号和角色

在本机项目目录执行：

```powershell
python scripts/export_state.py
```

它使用 SQLite 在线备份 API，输出私有 `data/exports/esp32-state-*.tar.gz` 和 SHA256 文件。
归档仅含一致的 `control.db` 和 `secrets.json`，不包含模型、日志、录音或初始明文密码文件。
数据库保留账号密码哈希、角色、设备、模型设置及文字记录；移除旧浏览器会话和在线状态。
数据库中的 API Key 和设备凭据仍属于敏感内容，归档只通过 SSH/SCP 发送到自己的服务器。

在服务器首次启动前，将这两个文件恢复到项目 `data/` 目录。已有数据目录应先备份，
不要直接覆盖正在使用的数据库。恢复后继续使用原账号密码登录，并重新配置云端可访问的模型地址。

## 启动步骤

先确认服务器的系统、内存、磁盘、Docker/Compose、域名解析和网络端口满足实际部署条件。
以下命令假定 Docker 与 Compose 已安装，并且当前目录为项目根目录：

```bash
git submodule update --init --recursive
cp deploy/tencent/env.example .env.tencent
# 编辑 .env.tencent，将 ESP_DOMAIN 填为已解析到服务器的真实域名。
docker compose --env-file .env.tencent -f deploy/tencent/compose.yml config
docker compose --env-file .env.tencent -f deploy/tencent/compose.yml build
docker compose --env-file .env.tencent -f deploy/tencent/compose.yml run --rm studio python scripts/prepare_models.py
docker compose --env-file .env.tencent -f deploy/tencent/compose.yml up -d
docker compose --env-file .env.tencent -f deploy/tencent/compose.yml ps
```

验证管理端健康状态、登录、模型调用、角色读写及模拟设备语音链路后，
在“我的设备”复制新域名下的专属接入地址，再切换实物板子。
切换前保留板子当前设置备份。服务器首次镜像构建及 ASR 模型下载可能需要较长时间。

## 当前验证范围

部署配置和状态导出工具可在本机检查；实际容器构建、证书签发和腾讯云公网连通性
需要登录目标服务器后验证。当前电脑没有 Docker，不能把配置准备完成当作云端已部署成功。
