# codebuddy-agentshield（CodeBuddy / WorkBuddy 适配器：L2）

CodeBuddy 没有装前钩子；运行时用全局 `PreToolUse` / `PostToolUse` 命令钩子调用 `siq-agent-security hook codebuddy`（Go，在 `apps/agentshield`）。Skill frontmatter hooks 仅对 `context: fork` 生效且默认被 `allowUntrustedFrontmatterHooks=false` 关闭，因此不采用。

## 安装（需用户确认；写入前备份）

```bash
siq-agent-security adapter install codebuddy
# merges PreToolUse / PostToolUse command hooks into ~/.codebuddy/settings.json (backup first)
```

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
| `redact` | `ask`（CodeBuddy 不支持改参）|

`PostToolUse` 只观测（`/v1/observe`），从不阻断。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 服务不可达 / 401 / 非法响应 / stdin 畸形 | `deny` | `allow` + reason 注明 |

## 卸载

`siq-agent-security adapter uninstall codebuddy` 还原安装前的 `settings.json`。

## 验证状态

Go 单测覆盖映射与 fail-closed 表。linux 隔离 HOME 上已用真实 `siq-agent-security hook codebuddy` 跑通授前/授后 deny（[`docs/evidence/agentshield/codebuddy-linux-2026-09-05/`](../../../docs/evidence/agentshield/codebuddy-linux-2026-09-05/)）。**未**驱动 CodeBuddy GUI 客户端。矩阵不标 `supported`。
