# 本批环境与执行身份

Windows 11 Pro for Workstations 25H2、build 26200.8875、amd64、NTFS，PowerShell 7.6.5。Go 组件测试使用 Go 1.27.1 windows/amd64；工具链 SHA256 为 `d3ccdb604eafa6031133aefe1a3db24f0bb7362b857bc2125ac4e4c178b4b490`。Go 临时测试程序与 SIQ CLI 发行二进制分别记录。

Hermes 为 Windows 原生已安装公共 CLI，库存版本 0.21.2，实际 venv Python 3.11.16；版本来自既有源码盘点，本组未取得独立运行时 --version 输出。独立 NUL 设备检查使用工作区 Python 3.13.7，不能当作 Hermes guard 的同参数重放。

OpenClaw 在已有 WSL2/Linux 环境运行：Ubuntu 24.04.4、x86_64、kernel 6.6.87.2-microsoft-standard-WSL2，OpenClaw 2026.9.4 (3a9d69d)，Node.js 24.19.0。宿主 CLI 版本在预检实际取得；Node 版本来自此前盘点且每次核对二进制摘要。Node SHA256 为 `bc17c508ffeed0ec622934f9b7fa72f8e78da65350e63c3eceb56fa688aa5e12`。这不是 Windows 原生 OpenClaw。

全部运行使用明确命名的自有临时 profile、合成文件与受控本地 provider。未传入真实模型密钥或日常账号；WorkBuddy 5.5.6 的盘点沿用此前材料，本批未运行其桌面流程。原始材料仅留本机私有目录。

固定源码及各次退出、耗时、资源回收和摘要见子报告。证据分支从 main `b303c6f92392f3a44c306d81ad7323c6291ef4f2` 新建，不将此前固定 `9cc1863…` 测试重标为该主线实测。本批只追加证据与方案，没有修改生产代码、依赖、Schema 或发布状态。
