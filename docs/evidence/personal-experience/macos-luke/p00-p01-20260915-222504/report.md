# macOS Luke 首批：P00 环境与 P01 原生构建/管理验证

本批完成 Mac-P00 环境盘点和 Mac-P01 的 darwin/arm64 原生命令行构建、隔离启动、管理配对、会话恢复与错误实例诊断。**macOS 平台总体验收仍未完成，Mac-P02–P05 与 N09 不关闭。** 本机未观察到需要改产品代码的配对/启动缺陷；完整失联时浏览器显示网络错误页，产品「暂时无法打开本地管理」卡片需要文档已加载后的 API 失败，两者分开记录。

| 身份 | 实际值 |
| --- | --- |
| 上游 / 实现候选 | `b303c6f92392f3a44c306d81ad7323c6291ef4f2` |
| 分支 | `codex/macos-luke-p01-20260915-222504` |
| 源码状态 | `source_dirty=false`；`npm ci` + `npm run build:local` 未改 tracked 文件 |
| darwin/arm64 二进制 SHA256 | `967d9c922a6a304823fd58461ffb115db9d20b59a2d633a7055e731e3738beb9` |
| 发行身份 | 本机自建 `0.0.0-dev`，没有发布签名、安装包或支持承诺 |

环境见 [environment.md](environment.md)，命令与退出码见 [verification.json](verification.json)。配对码、管理员 token、状态私钥仅本机保留。

## 本批实际步骤

1. 只读盘点 OS/架构/工具/三宿主；Go 装到用户隔离目录，不改全局 PATH、不 sudo、不关系统防护。
2. 从 `origin/main` 建独立分支；前端本地构建后确认 embed 无 tracked 变化，再 `CGO_ENABLED=0` 原生编译。
3. 使用独立 `0700` 状态目录和端口 47612 启动；`status` 与 `state-status` 读回 ready / compatible。
4. 真实管理 UI：错误配对码、一次有效配对、刷新恢复、第二标签恢复、退出跨标签撤销、`stop --confirm-stop` 后重启必须重新配对。
5. CLI 负向：错误端口、错误状态目录、非 SIQ HTTP 服务、配对码第二次使用。

启停只针对本批自建实例。`stop --confirm-stop` 返回 `local-service-stop-result/v1` 且 `status=drained` 后端口空闲，再由 `start-local.py` 新 PID 启动。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| 原生构建 | `file` 为 darwin arm64；`sysctl.proc_translated=0`；制品 SHA256 如上 |
| `status --port 47612` | 退出 0；`schema_version=local-service-instance-health/v1`，`product=siq-agent-security`，`status=ready`，`local_mode=true`，含 64 位 `state_directory_id` |
| `state-status` | 退出 0；`compatible=true`，`status=ok`，format/reader/writer 均为 2。不以退出 0 单独推定兼容，同时读 JSON 字段 |
| 错误配对码 | UI alert：`配对码无效、已使用或已过期。请运行 siq-agent-security pair 获取新码。` 仍停在配对页 |
| 有效配对 | 进入「智能体总览」，可见「退出管理」。`document.cookie` 为空，localStorage/sessionStorage 无 64 位 hex 凭据 |
| 刷新 / 新标签 | 两标签均恢复总览，无需重新输入配对码 |
| 退出管理 | 当前标签回到配对页；两标签刷新后均需重新配对 |
| 重启服务 | drained 后新进程 ready；两标签刷新后均需重新配对 |
| 错误端口 | 退出 1：`local service is unreachable; start siq-agent-security serve, then retry` |
| 错误状态目录 | 退出 1：`local service uses a different state directory; select the matching directory or a different port` |
| 非 SIQ HTTP 服务 | 退出 1：`local service returned an unexpected HTTP response; check the port and service version` |
| 配对码复用 | 第一次 `POST /v1/pair` HTTP 200，第二次 401 |
| 服务完全不可达 | Cursor 内置浏览器进入 `chrome-error://chromewebdata/`，无法加载产品重连卡片。恢复服务后再次导航回到配对页 |

截图：[配对页](evidence/pairing-page.png)、[错误配对码](evidence/p01-invalid-pair-error.png)、[已连接总览](evidence/overview-connected.png)、[第二标签恢复](evidence/p01-second-tab-restored.png)、[重启后再配对](evidence/p01-restart-repaired-overview.png)。总览计数来自默认宿主目录的只读发现，不是隔离 profile 接入证据。

## 发现但未当缺陷修复的行为

- 隔离 SIQ 状态仍会发现用户默认 OpenClaw/Hermes 目录中的资产。这是当前发现实现，不是 P01 配对失败。P02 必须设置独立宿主状态，不得改日常配置。
- 服务进程完全退出时，管理页依赖浏览器自身网络错误，而不是已加载文档上的「暂时无法打开本地管理」。Linux Playwright smoke 用 `ui-config.json` 路由中断覆盖后者；本批未在文档已加载时注入该失败。若产品要在完全失联时仍展示自有卡片，需要独立静态入口，不能从本机网络错误页伪称已验证。
- darwin 开发构建会被 `codesign` 读成 ad-hoc，且 `spctl --assess` 拒绝。这与正式 notarization 不是同一证据项；终端启动本批构建成功，不能据此宣称发行信任已通过。
- 一次有效配对码在提交前被另一次 `pair` CLI 刷新时，UI 会报无效/已过期。这是一次性码的既有语义，不是 macOS 适配缺陷。

## 验收映射与下一批

| 要求 | 本批状态 |
| --- | --- |
| P00 环境 | 完成。可测组合为 macOS 26.6.2 + Apple M4 arm64 native。amd64/Rosetta 保持未测 |
| A01 / P01 启动与身份 | 指定状态/端口启动、配对、会话恢复、退出、重启重新配对、错误端口/状态/服务已实测。Safari 未测 |
| A02–A08 / P02 | 三宿主已安装但未做隔离接入旅程 |
| A09 通知 | 未测；macOS 默认 Notifier 仍为实现缺口 |
| A10 / P03 | LaunchAgent 用户域、APFS 归属、N01 迁移未测 |
| A11 / A12 / P04 / P05 / N09 | 未关闭 |

下一批：用独立 OpenClaw/Hermes 状态做发现→权限预览，不写日常配置；WorkBuddy 安排真实桌面会话。需要提交时再把本目录作为证据提交，实现候选保持上述 SHA。

P02 已开始隔离 HOME 只读发现与 `adapter preview`（未确认安装）。见 [p02-isolated-discovery.md](p02-isolated-discovery.md)。
