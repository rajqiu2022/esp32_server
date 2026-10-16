# MAAI28ST 板子固件

这里保存当前 Makerfabs **MAAI28ST** 的板级改造源码，与本仓库的自建后台配套。
基于官方 [78/xiaozhi-esp32](https://github.com/78/xiaozhi-esp32) 固定版本
`d7a1c05308fb6e116ffb44b9e2c6e67b3366302a`（2.5.3）。
上游固件代码使用 MIT 许可证；板级改造也按本仓库 MIT 许可证提供。

- `maai28st/board/`：完整板级源码、引脚配置、构建配置及硬件说明。
- `maai28st/integration.patch`：在固定上游版本中注册板型的 CMake/Kconfig 补丁。
- `maai28st/source.json`：上游版本与当前硬件验证情况。

目前包括 ST7789V 屏幕、GT911 触摸、音量/亮度/Wi-Fi 设置、双 I2S 音频、
GPIO0 共用 BOOT 的 WS2812 灯控，以及与触摸共享 I2C0 的 OV3660 摄像头。
屏幕使用微信式左右对话气泡，上下滑动查看最近 20 条记录；底部按钮控制语音对话，
左上角“设置”展开 Android 风格的快捷面板，点击面板外区域收起。

## 在新目录准备源码

以下 PowerShell 命令从本仓库根目录执行；目标目录应不存在。

```powershell
git clone https://github.com/78/xiaozhi-esp32.git ../xiaozhi-maai28st
git -C ../xiaozhi-maai28st checkout d7a1c05308fb6e116ffb44b9e2c6e67b3366302a
$integrationPatch = Join-Path $PWD 'firmware/maai28st/integration.patch'
git -C ../xiaozhi-maai28st apply --check $integrationPatch
git -C ../xiaozhi-maai28st apply $integrationPatch
Copy-Item -LiteralPath ./firmware/maai28st/board -Destination ../xiaozhi-maai28st/main/boards/makerfabs-maai28st -Recurse
```

在已激活的 ESP-IDF **6.0.1 或更新版本**环境中构建：

```powershell
cd ../xiaozhi-maai28st
python scripts/build.py makerfabs-maai28st --name makerfabs-maai28st --language zh-CN
```

构建会自行生成 sdkconfig、依赖、资源及 build 目录，不将这些生成结果存入此仓库。

## 更新现有板子的应用

当前实物通过 CH340K 串口连接电脑；实测端口为 COM9，新电脑请按实际端口替换。
已有可用分区表、唤醒资源和设备配置时，仅更新应用：

```powershell
python -m esptool --chip esp32s3 -p COM9 -b 460800 write-flash --flash-mode dio --flash-freq 80m --flash-size 16MB 0x20000 build/xiaozhi.bin
```

这条命令保留 NVS、资源分区、分区表与 OTA 选择。
它不是空白芯片的首次烧录流程；不要用整片擦除或完整 flash_args 替代现有设备的应用更新。
Wi-Fi、设备接入地址与账号凭据需要单独配置，不随源码提交。

## 已验证范围

- 该板型在 ESP-IDF 6.0.1 下构建成功，应用分区刷写校验通过。
- 触屏驱动、麦克风/扬声器及唤醒模型成功初始化；此前实物语音回复已获用户确认。
- 开机蓝灯自检、语音开灯已获用户确认，共用 GPIO0 的误触发已修复。
- 摄像头实测 OV3660 PID 0x3660，读取 640×480 RGB565 帧 614400 字节，注册拍照工具。
- 后台本机及云端各通过 16 项自动化测试；公网 HTTPS、实际 MCP 令牌及模型识别红色测试图通过。
- 实物摄像头的“语音提问→拍照→识物→语音回复”最终体验仍待用户确认。

更多硬件细节参见 [板级说明](maai28st/board/README.md)。
