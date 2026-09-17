# workbuddy-agentshield（WorkBuddy 桌面适配器：L2）

WorkBuddy 桌面应用把用户钩子写在 `settings.json` 的 `PreToolUse` / `PostToolUse`。安装器在该文件追加 `siq-agent-security hook workbuddy`，JSON 合同与 CodeBuddy 相同，但回执 `platform` 必须为 `workbuddy`。CodeBuddy CLI、`~/.codebuddy` 与 `hook codebuddy` 不能代替本适配器。插件市场 / `enabledPlugins@source` 尚未接管，装前拦截保持缺失。

本适配器不读取 `config.yaml`、`workbuddy.db` 或 `claw` 凭据。

## 安装（需用户确认；写入前备份）

```bash
siq-agent-security adapter install workbuddy
# merges command hooks into ${WORKBUDDY_CONFIG_DIR:-$HOME/.workbuddy}/settings.json (backup first)
```

安装、自动发现、状态和卸载均支持 `WORKBUDDY_CONFIG_DIR`；覆盖值须为绝对路径且现存目录及祖先无符号链接。安装器拒绝非法覆盖，不回退默认目录；卸载拒绝与最新安装记录不符的配置目录。安装保留 `enabledPlugins` 及其他未知键。写入的命令为 `hook workbuddy --state-dir <绝对状态目录>`，因为 Electron 子进程通常不继承 SIQ 环境变量。

`siq-agent-security serve` 必须在运行；`hook workbuddy` 从 `--state-dir` 或状态目录环境读 `config.json`（端口、enforcement_mode）与 `token`。`SIQ_AGENT_SECURITY_AGENT_ID` 指定 grant 的 `subject.id`（默认 `default`）。

## I/O 合同

stdin：`{session_id, cwd, permission_mode, hook_event_name, tool_name, tool_input | tool_response}`

stdout：

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow|deny|ask","permissionDecisionReason":"siq-agent-security: ... (receipt rcp-...)"}}
```

| 决策 API `action` | `permissionDecision` |
| --- | --- |
| `allow` | `allow` |
| `deny` | `deny`（reason 回传给模型）|
| `hold` | `ask` |
| `redact` | `ask`（当前适配器尚未接入原生改参）|

`PostToolUse` 只观测（`/v1/observe`），从不阻断。宿主把退出码 1 视为非阻断错误，不能用 exit 1 代替拒绝。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 服务不可达 / 401 / 非法响应 / stdin 畸形 | `deny` | `allow` + reason 注明 |

## 卸载

`siq-agent-security adapter uninstall workbuddy` 只剥离本产品钩子，保留 `enabledPlugins` 及其他设置。首次原文备份用于恢复参考，不整文件覆盖后来配置。

## 验证状态

Go 单测覆盖安装幂等、`enabledPlugins` 保留、`WORKBUDDY_CONFIG_DIR` 隔离、回执 platform 与 fail-closed 表。桌面 `native_desktop` 允许/拒绝/不可达必须在真实登录会话中验证，不能用 CodeBuddy CLI 或 source review 代替。矩阵在桌面证据完成前不标 `supported`。
