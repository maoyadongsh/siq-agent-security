# macOS Luke：P01 修复候选重测（配对链路 + LaunchAgent 生命周期）

接续 [P00/P01](../p00-p01-20260915-222504/report.md) 与 [P02](../p02-20260916-000754/report.md)。本批把 P02 期间发现并修复的四类 OS/宿主适配缺陷固化为正式实现候选，在干净候选上重建 darwin/arm64 二进制，重测受影响的配对/会话链路，并对新实现的 `launchctl print` 归属核对完成真实 LaunchAgent 全生命周期实测。**macOS 总体、N09、A01–A12 全旅程不关闭。** Intel/amd64、Safari、系统通知、N01 迁移仍未测。

配对码、管理员 token、会话 token、状态私钥仅本机保留，未写入本目录。

| 身份 | 实际值 |
| --- | --- |
| 实现 SHA | `170c13ecfc950105cc805411e38e948e6fc69629`（`codex/macos-luke-p01-20260915-222504`，基线 `b303c6f` + 45 文件修复） |
| 源码状态 | 提交后干净；`npm run build` / `build:local` 未改 tracked 文件 |
| darwin/arm64 二进制 SHA256 | `3ca7d504ba0845ff25011ad3d15f3053202e20d49f27328ec6b2276f26378232` |
| `file` | `Mach-O 64-bit executable arm64`，`CGO_ENABLED=0`，`-trimpath`，go1.27.1 darwin/arm64 原生（`sysctl.proc_translated=0`） |
| 工具链 | go1.27.1 装于 `~/.local/siq-macos-luke-tools/`，未改全局 PATH、未 sudo |
| 发行身份 | 本机自建 `0.0.0-dev`，无正式签名 |

## 开发检查（任务书 8.1）

| 检查 | 结果 |
| --- | --- |
| `gofmt -l .` | 输出为空 |
| `go vet ./...` | 通过 |
| `go test ./...` | 39 包全部 ok |
| `go test -race`（internal/state、stateformat、server） | 通过 |
| `npm test`（apps/web） | 23 文件 / 84 测试通过 |
| `npm run build` + `build:local` | 成功，embed 无 tracked 变化 |
| control-api `test_schema_contracts.py` | 206 passed（本机无 uv，用临时 venv 安装依赖复现，测试后清理） |

## 修复内容概要（实现候选 `170c13e`）

1. **Darwin 卷别名祖先检查**：`/var`、`/tmp` 为指向 `/private/...` 的卷别名。`stateformat.AcceptDirectory`/`LeafDirectory` 只接受卷根下、Stat 为目录的符号链接作为路径分量；状态根、叶路径与用户中间符号链接仍拒绝。应用于 state/inventory/adapterinstall/hermeshome/effectevidence/runtimeidentity/skillimport/skillinstall 十处。规格 §3 与 N01 文档同步。
2. **`launchctl list -x` 在 Darwin 25 不是 XML 开关**：新 `launch_agent_print.go` 改用 `launchctl print gui/<uid>/<label>`，封闭顶层键名单，逐字段与签名源核对（type/规范源路径/program/arguments//dev/null 输出/八进制 umask/exit timeout/精确状态目录环境变量/gui 域/running 状态/exit code），未知键 fail-closed。规格 §3.11.26–3.11.28 同步。
3. **OpenClaw 2026.9.4 会话仓 sqlite**：smoke 夹具读 `session_nodes.session_key`，不再假定 2026.5.12 JSON 路径。
4. **client_install/rollback/restore 产物身份**：staged 程序 Lstat 普通文件校验 + 双侧 EvalSymlinks 规范比较；卸载清理空插件目录与空 `plugins` 键。

## 配对/会话链路重测（隔离状态目录，端口 47614）

| 检查 | 结果 |
| --- | --- |
| `status` / `state-status` | ready / compatible=true（JSON 字段读回，非仅退出码） |
| 错误配对码 | HTTP 401 |
| 有效配对（`remember:true` + `X-SIQ-Session:1`） | HTTP 200，`local-admin-session/v1`，64 位会话 + `siq_session_<port>` cookie（HttpOnly/SameSite=Strict/Path=/v1/session） |
| 配对码复用 | HTTP 401 `pairing code already used` |
| 会话恢复（cookie + 头） | HTTP 200，固定剩余时长（43191s，不延长授权） |
| 坏 cookie / 缺 `X-SIQ-Session` 头 | 401 `pairing required` / 403 `session header required` |
| 受保护端点（/v1/audit）无凭据 / 有效凭据 | 401 / 200 |
| 登出 | 会话与刷新链同时失效（audit 401、restore 401） |
| `stop --confirm-stop` | `local-service-stop-result/v1`，`status=drained`，端口释放 |
| 重启后旧 bearer / 旧 cookie | 均 401，必须重新配对 |

`stop`/`start` 子命令从状态目录 config 读取端口，拒绝未知 `--port` 参数（`flag provided but not defined`）——符合「未知参数拒绝」设计。此前一次测试误用 `stop --port` 未实际停服，属测试脚本错误，非产品缺陷；已用正确调用重测。

## LaunchAgent 生命周期实测（Darwin 25 真实 launchd）

隔离状态目录 `~/.local/siq-macos-luke-p01-c170-20260916`（0700），候选二进制路径绑定。`serve` 持有主 Writer 时 `launch-agent-prepare` 正确拒绝（`write lock held by another process (pid …)`），停服 drained 后执行：

| 阶段 | 结果 |
| --- | --- |
| `launch-agent-prepare` | `local-launch-agent-record/v1`；label=`dev.siq.agent-security.<instance_id>`；plist SHA256 `99422277…` + 签名 |
| `launch-agent-register` | 发布 `~/Library/LaunchAgents/<label>.plist` 精确链接；明示「尚未确认加载或启动，保护未因此启用」 |
| `launch-agent-load --confirm-load` | bootstrap 成功；「已加载并通过配置归属核对」——`launchctl print` 新归属核对实机通过 |
| 独立核对 | `/bin/launchctl list` 含 label；`launchctl print gui/<uid>/<label>`：`state = running`，program=候选二进制，pid=46814 |
| `launch-agent-start --confirm-start`（运行中重复） | 幂等：报告已运行 + 本地 API 健康，不重复启动 |
| `launch-agent-status` | 「已加载并报告运行进程，本地 API 目录健康检查通过」 |
| `launch-agent-stop --confirm-stop` | 进程退出、台账写锁释放、配置保留；status 转为「未报告运行 PID」 |
| `launch-agent-unregister --confirm-unregister` | 注册链接删除；launchctl list 无 label；重复调用幂等 |
| 日常 LaunchAgents | 5 个既有第三方 plist 全程未动，测试后逐名核对无变化 |

## 未测 / 缺口（保持开放）

- Intel/amd64 原生与 Rosetta：未测（本机 Apple M4 arm64）
- Safari：本批仅 CLI/HTTP 层；浏览器 UI 旅程沿用上一批 Chrome 内置浏览器证据
- 系统通知（A09）、N01 迁移/升级恢复（P03 §6.3）、WorkBuddy 桌面接入：未关闭
- `launchctl print` 输出键名单基于 Darwin 25 实测；其他 macOS 版本未验证

## 清理

测试状态目录与临时 cookie/token 文件已删除；LaunchAgent 已注销，链接已移除；隔离 Go 工具链保留于 `~/.local/siq-macos-luke-tools/`。旧构建目录保留于 repo `.tmp/`（git 忽略）。
