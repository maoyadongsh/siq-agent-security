# codebuddy-agentshield（CodeBuddy / WorkBuddy 适配器：L2）

CodeBuddy 没有装前钩子；运行时用全局 `PreToolUse` / `PostToolUse` 命令钩子调用 `siq-agent-security hook codebuddy`（Go，在 `apps/agentshield`）。Skill frontmatter hooks 仅对 `context: fork` 生效且默认被 `allowUntrustedFrontmatterHooks=false` 关闭，因此不采用。

## 安装（需用户确认；写入前备份）

```bash
siq-agent-security adapter install codebuddy
# merges command hooks into ${CODEBUDDY_CONFIG_DIR:-$HOME/.codebuddy}/settings.json (backup first)
```

安装、自动发现、状态和卸载均支持 `CODEBUDDY_CONFIG_DIR`；覆盖值须为绝对路径且现存目录及祖先无符号链接。安装器拒绝非法覆盖，不回退默认目录；卸载拒绝与最新安装记录不符的配置目录。为多个实例设置独立的 SIQ 状态目录，并向 CLI、CodeBuddy 与 daemon 传递相同环境。

`siq-agent-security serve` 必须在运行；`hook` 子命令从状态目录读 `config.json`（端口、enforcement_mode）与 `token`。`SIQ_AGENT_SECURITY_AGENT_ID` 指定 grant 的 `subject.id`（默认 `default`）。

## I/O 合同

stdin（CodeBuddy）：`{session_id, cwd, permission_mode, hook_event_name, tool_name, tool_input | tool_response}`

stdout：

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow|deny|ask","permissionDecisionReason":"siq-agent-security: ... (receipt rcp-...)"}}
```

| 决策 API `action` | `permissionDecision` |
| --- | --- |
| `allow` | `allow` |
| `deny` | `deny`（reason 回传给模型）|
| `hold` | `ask`（用户在 CodeBuddy UI 确认）|
| `redact` | `ask`（当前适配器尚未接入原生改参）|

`PostToolUse` 只观测（`/v1/observe`），从不阻断。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 服务不可达 / 401 / 非法响应 / stdin 畸形 | `deny` | `allow` + reason 注明 |

## 卸载

`siq-agent-security adapter uninstall codebuddy` 只剥离本产品钩子，保留其他设置。首次原文备份用于恢复参考，不整文件覆盖后来配置。

## 验证状态

Go 单测覆盖映射与 fail-closed 表。linux 隔离 HOME 上已用真实 `siq-agent-security hook codebuddy` 跑通授前/授后 deny（[`docs/evidence/agentshield/codebuddy-linux-2026-09-05/`](../../../docs/evidence/agentshield/codebuddy-linux-2026-09-05/)）。**未**驱动 CodeBuddy GUI 客户端。矩阵不标 `supported`。

V2：透传 tool_use_id 为 tool_call_id；不同 hook 进程无需共享签名密钥或授权缓存，由本地 daemon 唯一匹配已授权动作。没有稳定 ID 时，需相同工具参数且只有一个候选；歧义 Observe 被拒绝，不能作为正常成功执行证据。Linux 上固定版本 CodeBuddy CLI 2.146.0 已通过原生 pre/post 关联验收，见下文；其他版本、GUI 和审批流程仍未验收。

2026-09-07 新增 [原生 CLI 验收](../../../docs/trusted-intent-v2-codebuddy-validation-20260907-231146.md)：固定版本 `@tencent-ai/codebuddy-code@2.146.0`，真实 CLI 安装/重装/卸载，8 次进程调用、19 次本地 SSE、13 条签名回执通过。覆盖正常读取、越权/写入拒绝、新会话、跨进程续聊、强杀恢复及 optional 边界。GUI 与 hold/redact 尚未验收，整体不标 `supported`。

初始化失败也会输出结构化 pre/post 结果：配置无法完整验证时 block；有效 warn/audit_only 配置但 token 不可用时 allow + pending。钩子只读取已有凭据，不生成 token；状态不可用时仍拒绝但无法持久化。已通过 [10 个原生故障/恢复场景](../../../docs/trusted-intent-v2-codebuddy-bootstrap-fix-20260907-232551.md)。此保证不覆盖二进制缺失、强杀、宿主超时或无法输出 JSON。
