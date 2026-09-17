# macOS 实机环境记录（Luke / Mac-P00）

日期：2026-09-15，Asia/Shanghai。范围：Mac-P00 环境盘点，以及本批 darwin/arm64 原生命令行构建、隔离启动、管理配对与会话恢复。本文只记录普通系统与软件身份、测试方法和隔离边界；不包含账号、个人用户名、机器序列号、私有绝对路径、凭据、配对码或启动日志原文。

本批为部分平台交付。OpenClaw、Hermes、WorkBuddy 的完整原生用户旅程尚未验收，N09 不关闭。Intel/amd64 原生与 Rosetta 翻译执行均未在本机拥有，不能填成 pass。

## 1. 受测代码与制品身份

| 字段 | 实际值 |
| --- | --- |
| 仓库 | `maoyadongsh/siq-agent-security` |
| 分支 | `codex/macos-luke-p01-20260915-222504`（从 `origin/main` 新建） |
| 上游 / 实现候选 | `b303c6f92392f3a44c306d81ad7323c6291ef4f2`（`source_dirty=false`；`npm run build:local` 未改 tracked embed） |
| darwin/arm64 原生二进制 SHA256 | `967d9c922a6a304823fd58461ffb115db9d20b59a2d633a7055e731e3738beb9` |
| 构建命令 | 在 `apps/agentshield` 执行 `env -u GOOS -u GOARCH CGO_ENABLED=0 go build -trimpath -o <build-dir>/siq-agent-security ./cmd/agentshield` |
| `file` 读回 | `Mach-O 64-bit executable arm64` |
| 发行身份 | 本机自建 `0.0.0-dev`。`codesign -dv` 读回 `Signature=adhoc`、`TeamIdentifier=not set`（Go darwin 链接默认，不是手工 `codesign` 冒充正式发行）。`spctl --assess --type execute` 退出 3 / rejected。二进制带 `com.apple.provenance`。未关闭 Gatekeeper/SIP。终端仍能启动该开发构建。正式签名/notarization 未测 |

开发工具链与制品分开记录：隔离 Go 进程的 `CGO_ENABLED` 探测值为 1；受测制品显式 `CGO_ENABLED=0`。

## 2. macOS、架构与工具链

| 项目 | 实际值与来源 |
| --- | --- |
| macOS | ProductVersion `26.6.2`，Build `25G83`（`sw_vers`） |
| 硬件 CPU | Apple M4；`hw.optional.arm64=1` |
| 内核 / 当前进程架构 | `uname -m=arm64`，`arch=arm64`，`sysctl.proc_translated=0`（非 Rosetta） |
| Go 工具链 | 官方 `go1.27.1.darwin-arm64` 归档，SHA256 `ee215d57e0ec269c60cc9ceca68e6bda321ba9ee5afe24f4b0988703c2d87d12`；解压到用户隔离目录，未写入全局 PATH、未用 sudo、未装 Homebrew formula `go` |
| Go 探测环境 | `GOHOSTOS=darwin`、`GOHOSTARCH=arm64`、`GOOS=darwin`、`GOARCH=arm64` |
| Node.js / npm | v26.8.2 / 11.19.1；`file` 读回 Node 为 `Mach-O 64-bit executable arm64`；来自 `/opt/homebrew/bin` |
| Homebrew | 7.0.1，仅作为本机已有包管理器记录；本批 Go 不依赖它 |
| Git | 2.55.0 |
| Python | 3.14.7（Homebrew `python3`，`file` 为 arm64）。`uv` 本机未找到；Control API 锁定回归未在本机运行 |
| C 编译器 / race | Command Line Tools 路径存在；`Apple clang version 21.0.0`。隔离 GOROOT 含 `src/runtime/race/race_darwin_arm64.syso`。本批未跑 `go test -race` |
| 管理会话浏览器 | Cursor 内置浏览器打开 `http://127.0.0.1:47612/overview`。系统 Safari `26.6.2` 与 Google Chrome `153.0.8010.37` 仅盘点；HTTPS 默认处理程序最近记录为 `com.google.chrome`。只测一个浏览器，不宣称全部兼容 |

Apple Silicon 本机没有第二套 Intel 硬件。本批不把交叉编译或翻译执行记为 darwin/amd64 native pass。

## 3. 文件系统、会话与隔离

| 项目 | 已核对事实 |
| --- | --- |
| 文件系统 | 源码、`/tmp` 探测均为大小写不敏感；根卷 `diskutil` 公开字段为 APFS。未把同步盘、外置卷或网络目录当作受支持状态目录 |
| GUI 用户域 | 当前 `launchctl managername=Aqua`，非 SSH 会话。本批管理 UI 在 Cursor 内置浏览器完成；未安排注销登录或整机重启窗口 |
| 隔离资源 | 用户目录下独立 `0700` 的工具、P01 状态、证据三个目录；不是符号链接。状态目录不指向日常 SIQ 默认状态。恢复方法：`unset SIQ_AGENT_SECURITY_STATE_DIR AGENTSHIELD_STATE_DIR` |
| 端口 | loopback `127.0.0.1:47612`。占用时未终止未知进程；本批启停只针对该隔离实例。会话中曾出现多次 `start-local.py` 拉起的新 PID（父进程为 `launchd`，不是产品 LaunchAgent）。错误端口/错状态诊断必须在进程仍监听时采集，否则会误报 unreachable |
| LaunchAgents | 当前用户 `LaunchAgents` 中无 siq/agentshield 名称匹配项。本批未注册 LaunchAgent。PID 变化不能记成登录自启或 KeepAlive |
| 敏感材料 | 私钥、恢复凭据、配对码、状态备份只留本机私有目录；公开材料不含这些内容 |

日常 `~/.openclaw`、`~/.hermes`、`~/.workbuddy` 以及 `/Applications/WorkBuddy.app` 的 Application Support 已存在。P01 发现页会看见默认宿主目录中的资产计数；**未对日常配置做接入、备份或修改**。后续 P02 必须使用独立 `OPENCLAW_STATE_DIR` / `HERMES_HOME` / WorkBuddy 测试 profile。

## 4. 三宿主当前版本与实测边界

官方资料查阅日期：2026-09-15。安装来源以本机路径和版本命令为准，不把“命令存在”写成“已保护”。

| 宿主 | 本机身份 | 官方 macOS 来源 | 本批结论 |
| --- | --- | --- | --- |
| OpenClaw | Homebrew CLI `OpenClaw 2026.9.4 (3a9d69d)`，`/opt/homebrew/bin/openclaw` 为 Node 脚本。`/Applications` 无 OpenClaw.app | [macOS app](https://docs.openclaw.ai/platforms/macos)、[Gateway on macOS](https://docs.openclaw.ai/platforms/mac/bundled-gateway)、[Install](https://docs.openclaw.ai/install/) 声明 macOS CLI/Gateway 与可选菜单栏应用 | CLI 可测。菜单栏应用本机未安装。完整发现→接入→允许/越权/失联未测 |
| Hermes | `~/.local/bin/hermes`：`Hermes Agent v0.21.3 (2026.9.14) · upstream 345cd2b0`。无 Hermes.app | [Installation](https://hermes-agent.nousresearch.com/docs/getting-started/installation) 与 [Desktop](https://hermes-agent.nousresearch.com/desktop) 声明 Linux/macOS 安装脚本及 macOS 12+ Desktop | CLI 可测。Desktop 本机未安装。GUI/后台启动路径未测 |
| WorkBuddy | `/Applications/WorkBuddy.app` 版本 `5.5.6`，bundle `com.tencent.workbuddy.mac`；主程序 `Electron` 为 `Mach-O 64-bit executable arm64`。PATH 无 `workbuddy` CLI | [Mac 安装指南](https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Installation-Mac-Guide)、[腾讯云安装指南](https://cloud.tencent.com/document/product/1831/134387) 声明 macOS 12+，M 系列选 Mac ARM64 | 桌面应用存在且为 arm64 原生。未打开日常桌面会话，未验证钩子。不能用 CodeBuddy 代替 |

本机另确认 PATH 无 `codebuddy`，无 CodeBuddy.app。这只排除误用，不是 WorkBuddy 验收。

## 5. 可测原生组合与缺口

**可测原生组合：** macOS 26.6.2 + Apple M4 arm64（非翻译）+ 本机构建 SIQ `0.0.0-dev` + Cursor 内置浏览器管理会话。OpenClaw/Hermes 可走隔离 CLI；WorkBuddy 需真实桌面交互。

**保持未测 / blocked：**

- darwin/amd64 native 与 Rosetta 翻译执行：本机无对应硬件/翻译受测进程
- Safari 及其他浏览器管理会话
- `uv` / Control API 锁定 pytest
- 正式签名、notarization、登录自启、崩溃 KeepAlive（当前 plist `RunAtLoad=false`、`KeepAlive=false`）
- 三宿主完整 A02–A08、LaunchAgent 用户域、N01 旧制品迁移、系统通知
