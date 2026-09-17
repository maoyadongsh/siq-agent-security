# macOS Luke：Mac-P04 通知、审批与 Skill 闭环

接续 [P03](../p01-retest-20260916-101021/report.md)（LaunchAgent 负向与 N01）。本批完成 macOS 桌面通知默认路径实现与真实投递、OpenClaw/Hermes 真实链路审批（允许/越权/撤销失联）、审批收件箱浏览器旅程、Skill 安装/更新/移除/更新检查浏览器旅程，并如实记录 OpenClaw approval-gate 夹具在 2026.9.4 上的剩余不兼容。**macOS 总体、N09、A01–A12 全旅程不关闭。** Intel/amd64、Safari、WorkBuddy 桌面仍未测。

配对码、管理员 token、状态私钥未写入本目录；材料仅含 schema 结果、SHA256 摘要与布尔检查项。

| 身份 | 实际值 |
| --- | --- |
| 实现候选 | `2ce0eb1` + `60c2016`（通知默认）+ `848d8c7`（gate 夹具适配），分支 `codex/macos-luke-p04-20260916-133816` |
| 本批 darwin/arm64 候选 SHA256 | `afe47938ee0df834d885f8635fcfb6d636f670d27ecb9dae82fec2480b2af010` |
| 宿主 | OpenClaw 2026.9.4（Homebrew）、Hermes（`~/.local/bin/hermes`）、Chromium 153（Playwright headless，隔离真实 daemon） |

## 1. macOS 桌面通知默认路径（A09 增量，实现 `60c2016`）

`notify.DefaultCommand` 新增 darwin 分支：`/usr/bin/osascript` 固定两参 `on run` handler（`display notification (item 2 of argv) with title (item 1 of argv)`），argv 直执行、无 shell、无用户内容拼接。真实 GUI 投递在本机通知中心可见（Aqua 会话，`launchctl managername=Aqua`）。

- `desktop_notify: true` 配置后 serve 日志确认 dispatcher 启动；pending=0 时不投递（合并不误报）
- osascript 语法错误退出 1 → `ErrDeliveryFailed`；超时/缺二进制路径为既有单测覆盖
- **如实缺口（规格 §3.12.34 已记录）**：`display notification` 无点击导航回调，点击不打开待办页；免打扰/权限拒绝下 osascript 仍可退出 0，投递证明以通知中心可见为准，不以退出码伪称

## 2. 真实链路审批（OpenClaw + Hermes）

| 链路 | 结果 | 材料 |
| --- | --- | --- |
| OpenClaw 2026.9.4 托管 v3 安装 + 真实 `agent --local` hook 生命周期 | 18 项检查全过：预览不改宿主、托管身份签发、写拒绝于执行前、允许读、显式任务授权后原参数/原文采集、回执链验证、撤销身份阻断新调用 | [openclaw-managed-native.json](openclaw-managed-native.json) |
| Hermes 真实 `chat --oneshot` + 插件生命周期 | 6 项检查全过：native 启动、会话自动绑定、允许读、写拒绝于执行前、拒绝后允许、回执链验证 | [hermes-cli-runtime.json](hermes-cli-runtime.json) |

审批单次性/重放/撤销语义由引擎与收件箱层覆盖（见 §3、Go 契约测试）；gate 级夹具剩余缺口见 §5。

## 3. 审批收件箱浏览器旅程（Chromium + 隔离真实 daemon）

[confirmation-inbox-browser.json](confirmation-inbox-browser.json)：13 项全过——打开不批准、显式审阅一次有效、重放冲突、拒绝可见且无批准控件、并发处理冲突刷新、断连禁用动作+恢复、移动端视口、长期权限精确定位、回执历史关联、无页面运行错误、仅 3 张预期签名回执、通知权限拒绝不阻塞、客户端截止使陈旧批准失效。

[confirmation-notifications-browser.json](confirmation-notifications-browser.json)：23 项全过——通知 opt-in、仅泛化计数、点击只定位不修改状态、同源去重、合并限流、元数据无凭据/原操作标识、禁用全窗口传播、构造失败不丢请求、登出取消在途准备。浏览器通知层与 §1 的 OS 通知层互补，两者都不携带批准能力。

## 4. Skill 安装/更新/移除/更新检查浏览器旅程

| 旅程 | 结果 | 材料 |
| --- | --- | --- |
| 安装管理 | `passed`，9 检查 0 失败（桌面/移动端安装、确认、恢复） | [skill-install-management-browser.json](skill-install-management-browser.json) |
| 更新 | `passed`，7 检查 0 失败 | [skill-update-browser.json](skill-update-browser.json) |
| 移除 | `passed`，10 检查 | [skill-removal-browser.json](skill-removal-browser.json) |
| 更新检查 | `passed`：changed/same/unavailable/unsupported/wrong_install_id/取消丢弃迟到响应/移动端 7 项 fixture 响应全过 | [update-check-browser.json](update-check-browser.json) |

`update-check` 材料中 `native_upstream_acceptance: false` 为脚本硬编码标记（真实上游接受属另一验收项），非本项失败。

## 5. OpenClaw approval-gate 夹具：部分适配 + 如实阻塞（实现 `848d8c7`）

在 2026.9.4 上实测发现并修复三个夹具缺陷：

1. gate 从未向 worker 传 `OPENCLAW_CONFIG_PATH`（所有 openclaw-*-worker.mjs 启动必需）→ 已补；worker 失败时将 worker.log dump 到 stderr（从磁盘重开——子进程直写 fd）
2. `nativeFunction` 只匹配 `.js` 而 2026.9.x 为 `.mjs`；且 chunk 名漂移（`server.impl-`→`server-`、`pi-tools-`→`agent-tools-`、`native-hook-relay-`→`hook-helpers-`）→ 改为按符号+有序候选前缀解析，双扩展名
3. 合成配置写 `canvasHost`（2026.9 已移除该键，启动即拒）→ 改为省略（新旧 schema 均合法）

**剩余阻塞（不伪称完成）**：修复后 worker 侧 gateway 仍报 `0 plugins`——2026.9.4 的插件审批运行时挂接方式改变，worker 完成用例但无 hold、干净退出，gate 以明确指因的失败消息终止（不再误报 "exited before result"）。真实 CLI 审批旅程由 §2 的 managed-native smoke 覆盖；worker gateway 插件运行时重新挂接留作独立工作项。

## 6. 未测 / 缺口（保持开放）

- Intel/amd64 与 Rosetta、Safari、WorkBuddy 桌面接入：未测
- OS 通知的免打扰/权限拒绝场景无法脚本化切换，未做 GUI 级负向；点击导航缺口见 §1
- approval-gate worker 的 2026.9+ 插件运行时挂接（§5）
- Hermes 宿主回调等待时长/批准后重试的宿主语义级测试（真实回调重试窗口）

## 清理

测试状态目录、临时 venv（playwright 建于 /tmp，复用后删除）、smoke 沙箱均已删除；隔离 Go 工具链保留；Playwright chromium 缓存保留于用户缓存目录。
