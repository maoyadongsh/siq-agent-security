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

V2：有 tool_call_id 时保存服务端 action_id/receipt_id（最多 2048 项、TTL 300 秒）并在 post 回传；重复 ID 冲突不覆盖旧关联，产生无关联的拒绝路径。无 ID 时由服务端用相同参数唯一匹配，歧义拒绝。除 hook 单测外，已有 [Hermes 原生分发器与真实 HTTP 集成证据](../../../docs/trusted-intent-v2-native-validation-20260907-191006.md)，覆盖合成工具调用的允许/拒绝、关联、失联及重启。新增 [原生 Agent 完整会话证据](../../../docs/trusted-intent-v2-conversation-validation-20260907-200400.md)，通过本地合成模型的 SSE 响应驱动实际会话循环，覆盖生成会话 ID、跨轮固定授权和动作链。hold/审批及真实平台 V2 综合验收仍为 unverified。

## 显式MCP来源采集（组件集成）

可在插件config.json中指定精确工具名与服务器身份映射：

```json
{"mcp_sources": {"mcp__reports__lookup": "https://reports.example.invalid/mcp"}}
```

示例域名仅作配置说明。映射应由部署者根据实际注册工具填写，不能从工具结果取得；不按名称前缀拆分服务器名。匹配的post_tool_call会将实际result提交本地daemon的受限报告API，来源始终MCP/untrusted，服务器身份+工具名仅提交摘要。需已有有效Intent绑定、稳定tool_call_id、decision凭据和daemon服务；报告失败不生成可用引用。

宿主可通过`provenance_reference(session_id, tool_name, tool_call_id)`取回引用，并在后续pre_tool_call传入`parameter_provenance`或`context_assertion_id`。这只是显式桥接，不能直接把原结果引用绑定到变换后的参数；选择/派生必须经过daemon的对应API生成内容摘要匹配的引用。插件不推断模型隐式lineage，不签发可信声明，也不把自称USER的工具结果提升权威。

内存引用缓存最多2048条、5分钟到期，满时不驱逐既有引用来假装干净；不持久化原结果或token。结果预算预留JSON编码空间，超限不截断后当完整来源。默认映射为空，原版Hermes自动配置/传播和真实原生MCP链路仍需单独验证；现有测试只证明钩子映射、受限上报及缓存边界。


真实daemon组件桥接复现：

```bash
python3 scripts/validate-mcp-provenance.py --hermes-bridge --out /tmp/hermes-mcp-bridge.json
```

脚本执行真实loopback MCP initialize/tools-call，将实际结果交给本适配器post hook自动上报，经daemon确定性select后通过pre hook提交参数来源；MCP路径阻断，admin签发USER的相同路径允许。最后复验daemon回执链。此模式直接调用钩子，不包含原生Hermes MCP注册/调度器，不等同原生端到端支持；不会操作真实用户配置。
