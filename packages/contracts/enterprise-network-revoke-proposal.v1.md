# 网络允许项撤除申请 v1

GET `/api/v1/policies/{policy_id}/network-revoke-baseline` 读取基线标识、版本及摘要，
不返回原始策略。POST `/api/v1/policies/{policy_id}/network-revoke-proposals` 创建
新策略版本及 proposed 变更，绝不批准、发布或执行。两端点均先验证租户对象 404，
再要求 policy:read、policy:manage、change:propose，否则 403。响应 no-store。

基线响应 schema_version=enterprise-network-revoke-baseline/v1，含 policy_id、
policy_version、baseline_digest。摘要绑定完整策略内容、名称及验证租户/操作者/类型。
请求 schema_version=enterprise-network-revoke-proposal/v1、baseline_digest、UUID
request_key、selections（1–256 个只含 endpoint/binary_path 的严格对象）。不接受
租户、提出者、档位、审批状态或替代策略正文。基线变化 409，非法撤除 422。

按 network-revoke-plan/v1 规划；新版本沿用同租户原策略名称，版本为当前最大值+1，
原策略不修改。新策略 static validated、变更 proposed/standard；原独立审批和
部署前置校验仍必需。impact 记录来源策略/版本及请求摘要，不写配置原文。
两条 policy.create/change.request.create 审计与 change.requested outbox 同事务，
失败全部回滚，公共错误不回显内部异常。

同租户 request_key 派生内部唯一键；相同操作者/类型、原策略、摘要及规范排序选择
重试返回原变更，无新写。同键不同输入/操作者 409。不同租户键互不碰撞。
对基线行请求行锁，策略版本和变更幂等键仍受数据库唯一约束；唯一冲突回滚后只在
找到内容匹配的原变更时返回，否则 409 重试冲突。SQLite 测试不证明生产锁语义。

响应 schema_version=enterprise-network-revoke-proposal-result/v1，含 source_policy_id、
policy_id（新版本）、change_request_id、requires_independent_approval=true、executed=false。
即使历史申请后来获批，幂等重读也不会重新批准或执行；实际状态通过原变更读接口核对。
本接口不证明期望策略与当前沙箱一致、共享影响完整或撤权生效。后续部署仍需目标、
共享影响、revision/CAS、有效期和独立后端读回；前端不得以申请成功显示“已撤权”。
## 同快照可选项

GET `/api/v1/policies/{policy_id}/network-revoke-options` 使用相同定位与权限检查。
响应 schema_version=enterprise-network-revoke-options/v1，含 policy_id、policy_version、
baseline_digest、selections（去重排序的 endpoint/binary_path）、coverage=complete_policy_network。
complete 只表示该期望策略中的受支持网络允许对，不表示设备、运行时或组织全部权限。
与摘要从同一源策略读取，不允许客户端从另一份历史文本拼接摘要。
未知网络语义 422 network_revoke_baseline_unsupported；超过 256 个选项、字段不能
完整安全展示或脱敏/截断时 422 network_revoke_options_unavailable，不返回部分成功。
空列表只表示该期望策略显式没有网络允许项。接口不修改策略或自动申请。

## 只读请求恢复

GET `/api/v1/policies/{policy_id}/network-revoke-proposals/{request_key}`，request_key
必须为 UUID。请求键不是凭据；按验证租户派生内部键，并核对原提出者 ID、身份类型
及来源策略。源策略或申请不存在、越租户、非原操作者、身份类型不匹配统一 404；
定位后再核对 policy:read/manage 和 change:propose，失权 403。

响应 schema_version=enterprise-network-revoke-recovery/v1，含 source_policy_id、
policy_id、change_request_id、change_status、lookup_executed=false。change_status
是记录的当前状态，不保证策略实际效果；lookup_executed=false 只表示此次查询不
发起执行，不表示历史申请从未执行。不返回原请求选择、策略正文或操作者信息。
no-store；任意次数查询无申请、审批、部署、审计或 outbox 写入。

新申请 impact 额外记录服务端派生的 proposal_actor_type 供恢复匹配。缺少该字段的
历史申请不猜测身份类型，恢复接口返回 404；原同内容幂等 POST 逻辑不变。404 不代表
原提交绝对未到达，可能仍在处理中或身份不匹配，客户端不得据此自动另建申请。
