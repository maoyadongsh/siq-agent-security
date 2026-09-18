# workbuddy-agentshield（WorkBuddy 桌面 command 接入）

WorkBuddy 使用 `settings.json` 的 `PreToolUse` / `PostToolUse` command hook。本适配器只做宿主协议与 SIQ HTTP 的映射，回执平台为 `workbuddy`。配置成功与真实桌面生效分别验收；CodeBuddy CLI 或阅读宿主源码不能代替桌面实测。

## Windows 受管接入

规格见 [WorkBuddy 受管增量 v1](../../../docs/workbuddy-managed-runtime-spec-v1.md)。通过本地管理界面选择服务端发现的 WorkBuddy 实例，明确确认 Windows 路径权限、批准并部署 Grant，再签发该实例的专属身份。安装预览使用 `local-adapter-plan/v4`，应用后写入：

- `${WORKBUDDY_CONFIG_DIR:-$HOME/.workbuddy}/siq-agent-security.json`：闭合的 `workbuddy-managed-hook/v1` 配置，仅保存 `runtime_identity_id`、`instance_id`、`agent_id`、`credential_path`、`endpoint`、`enforcement_mode`、`state_dir` 及版本。
- `settings.json` 的前置/后置命令：`siq-agent-security hook workbuddy --state-dir <绝对状态目录> --managed-config <绝对配置路径>`。

配置只引用 `state_dir/runtime-identity-secrets/<identity>.token`；不复制明文 token，不使用共享 token、默认 agent 或默认 session。安装先备份，保留 `enabledPlugins` 及其他设置，修复沿用已登记身份。受管配置缺失、损坏或残留时拒绝降级；诊断仅读取配置和公开身份引用，不读取凭据。

`WORKBUDDY_CONFIG_DIR` 须为可核验的绝对目录；不使用 `CODEBUDDY_CONFIG_DIR`、`cwd`、日常数据库或登录态定位实例。本接入不读取 `workbuddy.db`、`config.yaml`、`claw` 凭据或 `transcript_path`。

## 原生协议与 HTTP 链

stdin 外层必需 `hook_event_name`、`session_id`、`tool_use_id`、`call_id`、`tool_name`、`tool_input`。两种 call ID 必须非空且精确相等；`tool_input` 必须是对象。只接受 `PreToolUse` / `PostToolUse`，后者还必须包含 `tool_response`。可选的 `cwd`、`transcript_path`、`permission_mode`、`agent_id`、`agent_type`、`generation_id`、`model`、`client`、`version` 只作有界元数据，不能覆盖 SIQ 身份、证明重试或提供审批。

输入最多 1 MiB、嵌套深度最多 64；拒绝重复键、大小写字段别名、未知外层字段、尾随 JSON、无效 UTF-8、空或冲突 ID。session/call 使用规格中的域分离哈希，保留宿主命名空间。宿主可能折叠父任务 session，摘要不能证明独立子任务、恢复 epoch 或同用户隔离。

每次前置先用专属凭据 `/v1/runtime-sessions` 登记并核对 enrolled/v2 的身份、session、到期时间，再裁决新操作或核对并预留原批准的 hold。同次 HTTP 共用 4 秒截止时间，只访问明确端口的 `http://127.0.0.1`，不使用环境代理、不跟随重定向。后置只调用 `/v1/observe`，用持久记录中的同一 session/call/action/decision 明确关联已允许的前置；失败不伪造成功回执。

| SIQ 结果 | 受管 WorkBuddy 输出 |
| --- | --- |
| `allow` | 省略 `permissionDecision`，保留宿主原权限门禁 |
| `deny` | 结构化 `deny` |
| 初次 `hold` | 结构化 `deny`；在 SIQ 批准后，再在 WorkBuddy 重试同一操作 |
| `redact` | 结构化 `deny`，说明尚无原生改参支持 |
| 配置、凭据、会话、响应或连接无效 | 任意模式均结构化 `deny` |

审批恢复使用 [持久关联与唯一预留协议](../../../docs/workbuddy-approval-resume-v1.md)。只有原 hold 经 SIQ 批准、当前真实调用参数精确相同、完整权限在线复验且首次 reserve 成功，才继续经过宿主权限门禁。重复调用、关联损坏或丢失响应会阻止重放；“执行不确定”需要在 SIQ 检查记录，不能用再次发起相同任务消除。

普通 policy 在后端产生的 `warn` / `audit_only` 允许结果仍表示 SIQ 无异议。无效必需 Authority、连接/登记失败不因此放行。宿主把退出码 1 当作非阻断错误，拒绝必须通过结构化输出表达。

不把 `ask` 当成 SIQ 批准，也不宣称批准后任意新 call 都能执行。审批恢复组件验证与真实桌面 A06 验收分开记录；组件链通过不能代替宿主允许、拒绝和副作用证据。

## 卸载与旧接入

管理界面卸载先撤销身份，再按安装记录移除受管配置及本产品命令。配置冲突保留现场和恢复信息；撤销不会被文件回滚复活。直接 CLI 卸载活跃受管身份会拒绝，应先通过管理端撤销。首次备份保留，不覆盖卸载期间用户新增配置。

无任何受管标记的旧 command 接入仍走历史共享 token / POSIX 路线，包括 macOS 既有安装；它不获得 Windows 受管权限。`adapter install workbuddy` 的旧 CLI 路径不等于签发受管身份。旧接入按历史协议运行、可按记录卸载，不能作为本轮受管验收证据。

## 验证边界

组件测试验证严格输入、专属凭据和 HTTP 顺序、缺失/损坏配置不降级、安装备份、撤销卸载与宿主门禁保留。真实桌面允许、越权拒绝、服务失联/恢复、撤销和审批恢复须另有原生证据，完成前不标记 WorkBuddy 全部通过。插件市场和 `enabledPlugins@source` 的装前拦截尚未实现。
