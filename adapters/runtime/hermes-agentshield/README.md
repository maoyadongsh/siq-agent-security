# hermes-agentshield（Hermes 运行时适配器）

把 Hermes 的 `pre_tool_call` / `post_tool_call` 钩子接到本机 `siq-agent-security serve` 的决策 API。只做 HTTP 映射，不含规则、判定或密钥（`apps/agentshield/AGENTS.md` 硬性规则）。

## 安装

```bash
siq-agent-security adapter install hermes
# copies plugin.yaml + __init__.py into ~/.hermes/plugins/siq-agent-security/
# and writes ~/.local/bin/hermes-skills-install (admit-then-install wrapper)
```

Hermes 在下次会话启动时发现插件（`hermes_cli/plugins.py` 从 `~/.hermes/plugins/` 扫描）。工具边界仍由 grant 写入的 `platform_toolset_modes: allowlist` 承担；本插件负责运行时回执与阻断（L2）。

## 行为映射

| 决策 API `action` | 插件返回 | 说明 |
| --- | --- | --- |
| `allow` | `None` | 放行 |
| `deny` | `{"action":"block","message":...}` | Hermes 把 message 作为工具错误返回给模型 |
| `hold` | block + 控制台 URL | Hermes 无审批通道，退化为阻断（规格 §4.2）|
| `redact` | block + 提示移除密钥 | `pre_tool_call` 不能改参 |

`post_tool_call` 把结果（截断 64 KiB）发到 `/v1/observe`，服务端脱敏并更新会话污点。

## fail-closed

| 场景 | `block` | `audit_only` / `warn` |
| --- | --- | --- |
| 服务不可达 / 超时 / 401 / 非法 JSON / 无 token | **block** | allow + stderr 警告 |

## 卸载

```bash
rm -rf ~/.hermes/plugins/siq-agent-security
# or: siq-agent-security adapter uninstall hermes   (restores any pre-existing files from <state>/backups/adapters/)
```

## 已知限制

- L1 安装门禁：Hermes 无装前钩子；用 `siq-agent-security admit <src>` 后再 `hermes skills install`，或让 `siq-agent-security serve` 周期盘点 `~/.hermes/skills` 标出未准入 Skill。
- `agent_id` 默认取 `HERMES_PROFILE` 或 `default`，需与 grant 的 `subject.id` 一致。
