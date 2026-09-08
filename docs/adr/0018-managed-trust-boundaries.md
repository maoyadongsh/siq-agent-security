# ADR-018：企业签发者与 Managed Linux 信任边界预留

- 日期：2026-09-08
- 状态：接口边界决策；Managed Linux生产部署不在本轮实现范围
- 依据：Provenance-Bound Effect V1模板§83–84、§92–93、§120

## 决策

沿用现有单进程Reference Monitor。当前本地管理身份是受信根；生产能力来自经过校验的Store与签名文档，适配器不持有签名私钥，也不选择最终授权结果。不新增空壳TrustBundle服务或未使用的接口来冒充企业集成。

Intent V3的authority.issuer是标识字符串，合同可以表达local-admin与enterprise-control-plane；它不是自动可信的枚举开关。当前本地Store验签不因字符串改成企业名称就接受未知公钥。企业issuer将来必须由经过管理配置的trust bundle提供公钥、许可来源、scope、撤销/轮转信息，不能把调用者提交的公钥当信任根。

Provenance Issuer已提供public_key或local_key_ref二选一，以及allowed_source_types、max_trust_level、scope、expires_at、revoked_at。已实现外部Ed25519公钥校验；这只是接入点，不表示企业Control Plane下发、密钥轮转或远程撤销协议已部署。ContextAssertion V1目前限定local-admin与workspace_root；外部attestor需版本化扩展issuer验证规则，不能直接放宽现有校验。

## 未来进程边界

| 能力 | 当前接入点 | 未来隔离实现必须补齐 |
| --- | --- | --- |
| IssuerResolver | IntentLookup/Provenance registry，读取受信存储 | 受信根配置、租户/scope绑定、轮转、撤销、缓存时效和离线失败语义 |
| ContextAttestor | ContextLookup与请求摘要、subject/task绑定 | attestor身份认证、freshness、nonce/重放策略及最小claim白名单 |
| EffectObserver | 独立capEffectObserve、source/scope token、action/rid关联 | 不同UID或受控服务身份、最小文件/网络权限、不可伪造采样来源、传输完整性 |

将来可以采用Unix socket与SO_PEERCRED、不同UID服务、OpenShell或独立系统遥测。任何身份信息都必须由受信传输/内核验证，不能从JSON uid/process_id字段推导。Windows/macOS不得假设拥有相同的Linux身份机制。

迁移后继续保持Authority invalid hard deny、同一动作关联、来源不自动提权、效果unknown不当成功。采样中断、丢事件、observer重启、凭据撤销及权限不足须显式降为unknown/拒绝；不能为了通过演示而回退到工具自报。

## 当前限制与后续验收

当前desktop-same-uid签名主要提供协议/审计完整性与逻辑权限分离，不抵御恶意同UID进程读取状态、盗取凭据、删除记录或回滚整个目录。host_independent不等于OS-isolated，受控test oracle也不代表通用公网效果验证。

本轮可运行`go test -race ./internal/intent ./internal/provenance ./internal/effectevidence ./internal/server`验证现有逻辑边界；该命令不能证明跨UID隔离。真正Managed Linux验收须在具备不同UID/受控socket权限的测试主机上，验证伪造peer身份、直接读私钥、绕过observer、断连、轮转/撤销、重放和资源逃逸均被预期控制，并归档实际系统配置与执行证据。未完成前能力矩阵保留unverified，不修改平台supported状态。
