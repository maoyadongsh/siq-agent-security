# ADR-016：参数级来源约束

- 状态：采纳；Provenance-Bound Effect V1，2026-09-08。

来源类型、可信度和签发权限分开建模。RuntimeActionDescriptor 标识高影响参数，Intent V3 对值与来源施加联合约束；V2 保留双读。只支持显式、可验证的 lineage，不追踪模型内部 token。

可信 store 是 Assertion 的验签入口，验签还必须验证 issuer registry、完整 scope、时效、撤销与内容摘要。签名只证明某个 issuer 作出了声明，不证明声明内容客观真实。派生不得升级父节点信任；unknown lineage 保留 unknown。所有引用逐一验证，不能用一个高可信父节点掩盖另一个不可信父节点。

Decision token 不得注册 issuer、签发可信 USER/IAM/数据库来源或设置完成状态。MCP 上报默认 untrusted。持久化只保存摘要和引用，限制节点、边、父节点数与深度；容量耗尽拒绝，不把被丢弃的来源标为干净。

落地按合同基础、不可变 issuer/assertion store、Intent V3/runtime matcher、MCP 接入依次验证；只有所有端到端负例和恢复测试通过后才宣称该能力完成。
