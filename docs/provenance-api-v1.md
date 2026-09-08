# Provenance V1 本地管理 API

状态：开发中。管理、受限 decision 上报与 V3 决策链路已接入；MCP 自动采集及效果证据尚未完成。下表管理接口使用本地服务的 admin session，决策 token 不具有这些权限。

| 方法与路由 | 请求 | 成功结果 |
| --- | --- | --- |
| POST `/v1/provenance-issuers` | [TrustedSourceIssuer](../packages/contracts/trusted-source-issuer.v1.schema.json) | 201，issuer 读回；同内容可重试 |
| GET `/v1/provenance-issuers/{id}` | 无正文 | 200，当前 issuer（含已验证撤销状态） |
| POST `/v1/provenance-issuers/{id}/revoke` | `{}` | 200，终态撤销；重复请求保留首次撤销时间 |
| POST `/v1/provenance-assertions` | [Assertion](../packages/contracts/provenance-assertion.v1.schema.json)，省略 signature，signing_schema 可省略 | 201，服务签名后的声明；仅 local-state issuer |
| POST `/v1/provenance-assertions/import` | 完整外部签名 Assertion | 201，通过 registry 公钥与父图验证的声明 |
| POST `/v1/provenance-resolve` | `{"provenance_id":"prov-1","scope":{"platform":"hermes","session_id":"s1","agent_id":"a1","task_id":"t1"}}` | 200，当前仍有效的声明 |

先通过既有 Intent 管理 API 创建 intent/v3 并绑定平台会话，再注册具有相同完整 scope 的 issuer。本地 issuer 使用 `local_key_ref: "local-state"`；外部 issuer 使用 base64 Ed25519 public_key，二者只能提供一个。注册时明确 allowed_source_types、max_trust_level 和 expires_at，禁止将来自工具结果的自报身份当成管理授权依据。

Assertion 的 content_digest 是参数值的 canonical JSON SHA256，例如 JSON 字符串包含引号后参与摘要；它不是任意文本文件的裸字节哈希。签发声明不会替代 Grant。调用 `/v1/decide` 时通过 `parameter_provenance` 提交 parameter_path 与 provenance_refs，不能在其中声明 trust 或 source_type。

所有引用逐一验签并检查完整父图；参数摘要改变、scope 重放、来源不允许、必需引用缺失、issuer 撤销等会导致强制拒绝。普通 V2 未携带新引用时保持原有行为。审批执行前会使用决策回执中的原始引用重新检查当前状态。

管理请求正文上限64 KiB，严格拒绝未知字段和尾随 JSON。错误使用 reason_code：输入/来源不合法通常400，decision token 调用管理接口403，同 ID 不同内容409，容量耗尽503；内部状态错误500且不泄露文件路径。

验证入口：`internal/server/provenance_http_test.go`。其中 warn 模式的允许仅说明有效 Authority 可进入原有 advisory policy，不证明存在独立 Grant 允许或真实文件效果。真实执行安全仍需后续平台与效果证据验证。

## 受限来源上报

`POST /v1/provenance-reports` 使用 decision token，正文见 [上报请求合同](../packages/contracts/provenance-report-request.v1.schema.json)。请求提供 report_id、platform/session_id/agent_id、source 和 content；服务从有效 Intent binding 获取 task_id，不接受调用方选择 issuer 或签名。

source 仅允许 MCP/WEB/TOOL/AGENT/UNKNOWN，trust 默认为 untrusted，不能升级为 trusted/authoritative。source_id 是自报标识，存储前转换为摘要；content 仅持久化 canonical 摘要。相同 scope+report_id+内容可重试，不同内容冲突；过期重试不会续期，新采集需要新 report_id。有效期最多15分钟且不晚于 Intent。

返回201及完整签名声明，可以将 provenance_id 用作后续参数来源引用。该签名证明服务记录了低可信自报输入，不证明实际连接过该 MCP endpoint，不提供独立效果证据。

## 从原始结果选择参数

`POST /v1/provenance-select` 使用 decision token，请求见 [选择合同](../packages/contracts/provenance-select-request.v1.schema.json)：parent_id、pointer、platform/session_id/agent_id、content。content 必须是与父节点摘要一致的完整原始 JSON；服务自行按 pointer 选取值，不接受 caller value、trust、issuer 或 task_id。

返回带父引用的签名子声明，保留低可信来源与原有效期。同一选择可重试；父节点过期或撤销会使选择失败。该入口只支持本地签发的低可信来源，不能派生可信 USER/IAM 授权。它证明确定性的字段选择，不证明模型内部语义传播。

## 隔离 MCP 集成验证

运行 `python3 scripts/validate-mcp-provenance.py --out /tmp/mcp-provenance.json`。需要本机 Go 与 Python 标准库；脚本创建临时状态与本地 MCP 服务，实际调用工具并将结果接入 Report/Select/V3 Decide，最后离线验证回执链。无需 Hermes 运行时或模型 API，不改用户配置。

参考 [MCP transport 2025-06-18](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) 与 [初始化流程](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)。脚本仅为固定 HTTP JSON 分支的协议组件验收，不作为通用 MCP 客户端发布；SSE、OAuth 和原生平台采集仍未覆盖。
