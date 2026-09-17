# macOS Luke：P07 WorkBuddy 桌面适配器与隔离钩子

接续 [P06](../p06-20260916-160800/report.md) 与 [P02 WorkBuddy 只读盘点](../p02-20260916-000754/workbuddy-inventory.json)。本批把 WorkBuddy 从「桌面接入待实测」接到独立的 `adapter install workbuddy` / `hook workbuddy --state-dir`，并在已登录的 Aqua WorkBuddy 5.5.6 会话里用 `conversation/open?autoSend=true` 派生真实 PreToolUse：无 Grant 的 Read 被拒，服务停止后 Read fail-closed。**未改日常 `~/.workbuddy` 的 claw/db/settings。** 未提交、未推送。

| 身份 | 实际值 |
| --- | --- |
| 分支 | `codex/macos-luke-p06-20260916-153008`（工作区脏） |
| git HEAD | `e03c9f5bb9f5208d673b23e96ad0d5b8f2d8385b` |
| 受测二进制 | darwin/arm64，SHA256 `82b8f45c6a3698fe872c4058de87f43871561035688423e712634fc311d39597`（`CGO_ENABLED=0`、`-trimpath`、go1.27.1；adhoc/linker-signed，非正式签名） |
| 隔离服务 | `127.0.0.1:47614`（结束后已关闭） |
| 既有服务 | `47612` / `47613` 仍在听，未被本批终止 |
| WorkBuddy | `com.tencent.workbuddy.mac` 5.5.6 Electron，主进程 69850，Aqua 已登录 |

配对码、管理员 token、状态私钥、日常 claw 正文未写入本目录。

## 1. 规格与适配器

`docs/agentshield-dev-spec-v1.md` §4.3 将 WorkBuddy 桌面与 CodeBuddy CLI 分列：配置根只认 `WORKBUDDY_CONFIG_DIR`（否则 `~/.workbuddy`），不静默使用 `CODEBUDDY_CONFIG_DIR`；inventory 读 `settings.json`，不读 claw/db；安装写入 `hook workbuddy --state-dir <abs>`，因为 Electron 子进程通常不继承 SIQ 环境变量。UI 对 WorkBuddy 提供独立安装按钮，不再显示「桌面接入待实测」。Trae 仍 unsupported。

本机包测试（隔离 Go 1.27.1）：`gofmt -l` 空；`go vet` 与 `go test` 覆盖 `internal/adapterinstall`、`internal/adapters`、`internal/inventory`、`internal/server`、`cmd/agentshield` 通过。合同样例已同步 WorkBuddy 发现根与 diagnostics `not_installed`。

## 2. 隔离安装 / 钩子（native 组件 + 登录桌面在场）

材料：[isolated-native.json](isolated-native.json)、[workbuddy-live-app.json](workbuddy-live-app.json)、[preview-redacted.json](preview-redacted.json)、[pending-unavailable-redacted.json](pending-unavailable-redacted.json)。

| 检查 | 结果 |
| --- | --- |
| 预览不改隔离 `settings.json` | pass |
| 安装保留 `enabledPlugins`，命令为 `hook workbuddy --state-dir`，不含 `hook codebuddy` | pass |
| 卸载去掉 hooks，保留 `enabledPlugins` | pass |
| 有服务、无 Grant 的 Bash PreToolUse | `permissionDecision=deny`，exit 0（宿主非阻断 exit 1 未使用） |
| 隔离 serve 停止后 Read PreToolUse | `permissionDecision=deny`，pending `platform=workbuddy`、`signed=false`、原因类别 `decision service unavailable` |
| 日常 `~/.workbuddy/settings.json` | SHA-256 与本批开始时相同 `89e179cf…`，仍无 `hooks` 键 |
| 用 `open -a WorkBuddy` 打开隔离工作区 | 主进程 69850 仍在；task 深链当时只预填未发送 |

`normal_execution`（有 Grant 的允许路径）本批仍未做。`install_interception` 仍为 host_capability_missing。stdin 钩子不能代替桌面旅程；桌面 PreToolUse 见第 3 节。

## 3. 已登录桌面派生 PreToolUse

材料：[native-desktop.json](native-desktop.json)、[native-desktop-send.json](native-desktop-send.json)、[native-desktop-autosend.json](native-desktop-autosend.json)、[native-desktop-write.json](native-desktop-write.json)、[native-desktop-write-fresh.json](native-desktop-write-fresh.json)、[native-desktop-bash-write.json](native-desktop-bash-write.json)、[native-desktop-unavailable.json](native-desktop-unavailable.json)、[desktop-read-deny-redacted.json](desktop-read-deny-redacted.json)、[desktop-bash-deny-redacted.json](desktop-bash-deny-redacted.json)、[desktop-write-deny-redacted.json](desktop-write-deny-redacted.json)、[desktop-unavailable-redacted.json](desktop-unavailable-redacted.json)。

`workbuddy://task?action=start` 只走 `executeTaskDeeplink` / `prepareInput`，把 prompt 填进输入框，**不自动发送**（`currentConversationId` 仍为 null）。`osascript` 对 System Events 发 Return 被拒：error 1002，未授权发送按键，未改辅助功能设置。

随后对已登录 Aqua 会话打开 `workbuddy://conversation/open?autoSend=true`（带 `sidebarUrl` 与 `promptContentBlocks`）。主进程把 URL dispatch 到渲染进程，渲染进程记 `conversation/open deeplink detected` 并 `sendPrompt`。隔离工作区的项目级 `hook-wrap.sh` 于 `2026-09-16T09:08:24Z` 被桌面派生（pid 88033）。收据：`platform=workbuddy`、`tool=Read`、`action=deny`、`reason_code=grant_missing`、`enforcement_mode=block`，目标为隔离哨兵 `workspace/safe/README.txt`。哨兵仍在，未写出 `MUST_NOT_WRITE.txt`。日常 `~/.workbuddy/settings.json` 仍无 `hooks`，SHA-256 `89e179cf…`。47612/47613 仍在听；本批 47614 结束后已关闭。

无 Grant 的 Read 之后，停止隔离 serve（47614），再对桌面 `autoSend` 一次 Read：包装钩子于 `2026-09-16T09:25:08Z` 派生 `PreToolUse tool=Read`，pending `platform=workbuddy`、`outcome=deny`、`signed=false`、`reason=decision service unavailable`。这是桌面失联 fail-closed，不是 stdin 代跑。日常 settings 仍无 `hooks`。

Write：`conversation/open` 会清掉 task-starter cwd。更早一批 Write prompt 未派生 Write 工具。18:02 新会话 `9c715b70-…`（MiniMax-M3）在隔离 cwd 上真实派生了工具：`10:02:18Z` Bash `ls` 为有服务、无 Grant 的 signed deny（`grant_missing`，收据 `rcp-b1ba73fecf81-100218.750179`）；随后本批测试脚本关掉 47614，同会话 `10:02:21Z` Bash、`10:02:24Z` Read、`10:02:35Z` Write 均为桌面 PreToolUse fail-closed（unsigned pending，`decision service unavailable`）。`MUST_NOT_WRITE.txt` 未创建，哨兵 `README.txt` 未改。模型把 Write 失败说成同一张 `rcp-b1ba73fecf81-…` 收据，与日志不符；拦截以钩子/收据为准，不以模型口述为准。有 Grant 的允许路径未做（审批必须由人执行 `grant approve`，模型不得代批）。

## 3.1 管理台安装按钮（嵌入 UI 重建后）

材料：[ui-console-install.json](ui-console-install.json)、[workbuddy-settings-install.png](workbuddy-settings-install.png)。

旧嵌入 UI 仍显示「桌面接入待实测」。`npm run build:local` 后用隔离 Go 1.27.1 重编二进制（SHA256 `37c511bf…`），在 `WORKBUDDY_CONFIG_DIR` 指向隔离目录的 47614 上打开设置页：WorkBuddy 行有 **安装**，说明为「须在 WorkBuddy 桌面会话验证，不能沿用 CodeBuddy」。确认预览只改隔离 `ui-wb-config/settings.json`，保留 `enabledPlugins`，命令含 `hook workbuddy --state-dir`。应用后行变为「接入待验证 / 发现安装文件」，可重新安装/卸载。日常 `~/.workbuddy/settings.json` 仍无 `hooks`，SHA-256 `89e179cf…`。47612/47613 未停；本段 47614 结束后已关。

## 3.2 隔离配置卸载还原

材料：[isolated-uninstall-restore.json](isolated-uninstall-restore.json)。

对同一隔离 `WORKBUDDY_CONFIG_DIR`：`adapter preview workbuddy uninstall` 不改文件；随后 `adapter uninstall workbuddy` 外科移除本产品 hooks，保留 `enabledPlugins.sheetagent@builtin` 与 `sandbox.mode=workspace`。安装前 SHA `5bcfaeea…`，卸载后 SHA `5f068c83…` 与预览 `after_sha256` 一致；CLI status 为 `not installed`。重建后的管理台设置页把该行标为「配置待修复 / 未安装 / 安装」：`settings.json` 仍在（用户插件与 sandbox），诊断 `host_registration` 失败，不是「文件缺失」；说明含「须在 WorkBuddy 桌面会话验证，不能沿用 CodeBuddy」。截图 [workbuddy-settings-after-uninstall.png](workbuddy-settings-after-uninstall.png)。日常 `~/.workbuddy/settings.json` 仍无 `hooks`，SHA-256 `89e179cf…`。47612/47613 未停。

## 3.3 外科卸载后重装（orig 字节还原）

材料：[isolated-reinstall-after-uninstall.json](isolated-reinstall-after-uninstall.json)。

旧实现把外科卸载写成缩进 JSON，与紧凑 orig 字节不等，重装报 `existing original snapshot needs review`。规格 DEV07-A/B 改为按 JSON 语义比较；剩余文档与首备语义相同则写回 orig 原文。隔离 Go 1.27.1 包测 `TestWorkBuddyReinstallAfterSurgicalUninstall` / `TestCodeBuddyReinstallAfterSurgicalUninstall` 通过。

隔离夹具曾被泄漏的 `WORKBUDDY_CONFIG_DIR` 写成测试 `description`；从 orig 恢复后，修复二进制（SHA256 `64d09fdc…`）完成安装→卸载→重装：卸载后与 orig 字节相同，重装 status=`installed`，hooks 为 `hook workbuddy --state-dir`，保留 `enabledPlugins`。日常 settings 仍无 `hooks`，SHA `89e179cf…`。`testOpts` 现清空这两个配置环境变量，避免再写到实机隔离根。

## 3.4 有 Grant 的桌面 allow

材料：[native-desktop-grant-allow.json](native-desktop-grant-allow.json)、[desktop-read-allow-redacted.json](desktop-read-allow-redacted.json)、[matrix-verify-summary.json](matrix-verify-summary.json)。

首次 `POST /v1/grants` 被拒绝：`unknown platform "workbuddy"`。合同 `grant.schema.json` / `receipt.schema.json` 与 `grant.Build` 的平台名单补上 `workbuddy`；规格 §4.3 写明 ActiveGrant 必须按 `platform=workbuddy` 匹配钩子回执。隔离包测 `TestBuildAcceptsWorkBuddy` 通过。修复二进制 SHA256 `9cf41197…` 在 47614 替换旧 serve（47612/47613 未停）。

操作者明确授权后，管理会话走 admit → grant（`platform=workbuddy`、`subject=default`）→ patch-desired（工具 `Read`、只读 `workspace/safe`）→ challenge → `approve`（`actor_id=luke`，`channel=cli`）→ deploy。stdin 钩子 `permissionDecision=allow`。桌面 `conversation/open?autoSend=true` 跳到既有隔离会话 `9c715b70-…`：`2026-09-16T11:48:07Z` PreToolUse Read allow（`reason_code=allow`，matched grant），随后 PostToolUse `observation_accepted`。哨兵仍为 `p07-workbuddy-sentinel-ok`，`MUST_NOT_WRITE.txt` 未创建。日常 settings 仍无 hooks，SHA `89e179cf…`。

验收矩阵：P07 私有根写入 WorkBuddy `macos/arm64/native` 四项 `native_desktop` pass（discovery / normal_execution / pre_execution_denial / service_unavailable_denial）。工作区脏，`verify` 对 `source_dirty=true` 返回 `dirty_candidate`（退出 2）。把 dirty 标志去掉后的结构校验退出 0、`needs_native_evidence`；`--require-native` 退出 3。剩余缺口：approval_resume、final_parameter_recheck、skill_attribution、install_interception。这不是干净候选，不能关 N09。

## 4. 仍保持缺口

- Intel/amd64、Safari、正式签名/公证、登录/重启/休眠、真实断电
- 审批恢复、可信 Skill 归属、安装入口拦截、参数终检
- N09 总体验收（工作区脏，WorkBuddy 行仍有 4 项缺口）

隔离运行根 `~/.local/siq-macos-luke-p07-workbuddy-live-20260916-165200` 含完整日志与配对材料，不进本证据目录。
