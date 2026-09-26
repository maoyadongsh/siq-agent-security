# 企业运行时绑定身份一致性 v1

绑定登记是人工声明，不是运行时/沙箱归属证明。既有 active 状态不得解释为执行效果已核验，用户提交的 attestation 也不是服务端认证事实。

登记时按验证租户依次定位实例、实例资产、请求环境（404），之后检查 policy:manage（403）。实例 environment_id 必须明确且与请求环境一致，否则 409 binding_instance_environment_unverified / binding_instance_environment_mismatch。不得通过绑定把未知环境实例补成某环境事实，也不得静默搬迁实例。

部署准备在权限与绑定 active/环境校验后，重新查询同租户实例/资产；实例 asset_id 与绑定资产一致、environment_id 与绑定环境一致且非空。不存在、跨租户或漂移统一 409 binding_source_identity_changed；发生在适配器/编译/外部写入之前。历史绑定不自动修复或重定向。来源与外部写入之间的数据库并发变化仍需后续事务/租约联动，不宣称该检查消除全部竞态。

本层不新增权限、不放宽 selector/隔离/审批/读回门禁，不证明发现设备、网关、Skill 摘要、沙箱 revision 或共享沙箱的归属。ENT-013 的这些绑定与撤销联动仍须继续实现。

执行前复验（2026-09-26 追加，wire 不变）：execute_deployment 在其执行期 probe/authority 检查之后、创建新的 Deployment 行或调用 apply_dynamic / 创建 publish_policy 任务之前，以验证租户为谓词对绑定行做列级重读（绕过 ORM identity map），并与准备阶段的独立标量副本逐字段比对（status、environment_id、asset_id、agent_instance_id、backend、backend_target_id），同时按当前持久值重跑实例/资产来源核对。该副本是普通 dict，不随 ORM 属性刷新而变化，并非语言层面不可修改对象。当前状态非 active 统一 409 binding_revoked；行缺失、跨租户或任一字段漂移统一 409 binding_source_identity_changed。持久预约路径在进入此执行阶段前可能已保存 pending Deployment、预约及 reserve 审计；复验拒绝不释放这些记录，既有调用方保守返回 unconfirmed，同键重放只读。拒绝旧准备结果时不采用新目标、不重编译、不回写绑定、不恢复吊销、不重试外部写入。此位置不声称覆盖适配器内部所有后续读取；复验与外部写入之间的残余竞态窗口未消除（无跨服务锁/租约），不证明设备、Skill、沙箱独占或共享归属。
