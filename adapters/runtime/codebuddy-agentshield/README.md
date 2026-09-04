# codebuddy-agentshield（CodeBuddy / WorkBuddy 适配器：L2）

CodeBuddy 没有装前钩子；运行时用全局 `PreToolUse` / `PostToolUse` 命令钩子调用 `agentshield hook codebuddy`（Go，在 `apps/agentshield`）。Skill frontmatter hooks 仅对 `context: fork` 生效且默认被 `allowUntrustedFrontmatterHooks=false` 关闭，因此不采用。

## 安装（需用户确认；写入前备份）

`~/.codebuddy/settings.json` 追加：

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": ".*", "hooks": [ { "type": "command", "command": "/usr/local/bin/agentshield hook codebuddy", "timeout": 5 } ] }
    ],
    "PostToolUse": [
      { "matcher": ".*", "hooks": [ { "type": "command", "command": "/usr/local/bin/agentshield hook codebuddy", "timeout": 5 } ] }
    ]
  }
}
```

`agentshield serve` 必须在运行；`hook` 子命令从状态目录读 `config.json`（端口、enforcement_mode）与 `token`。`AGENTSHIELD_AGENT_ID` 指定 grant 的 `subject.id`（默认 `default`）。

## I/O 合同

stdin（CodeBuddy）：`{session_id, cwd, permission_mode, hook_event_name, tool_name, tool_input | tool_response}`

stdout：

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow|deny|ask","permissionDecisionReason":"AgentShield: ... (receipt rcp-...)"}}
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

移除上述两条钩子（`agentshield adapter uninstall codebuddy` 会还原备份，W5 提供）。

## 验证状态

Go 单测覆盖映射与 fail-closed 表；未在真实 CodeBuddy 客户端上运行（国内客户端，需本机验证）。
