# 跨策略网络撤除申请 v1

POST `/api/v1/network-revoke-batches` 仅批量创建期望策略新版本与待审批变更，不执行。
请求严格字段：schema_version=`enterprise-network-revoke-batch/v1`、UUID request_key、
items（1–20 项）。每项只含 policy_id（1–64 字符）、baseline_digest（64 位小写 hex）、
selections（沿用单策略撤除的严格 endpoint/binary_path 对，1–256 项）。全批选择不超过
512 对，不允许重复 policy_id，也不允许选择同名策略的多个源版本。

先按验证租户定位全部源策略（任何不可见对象统一 404），再核对 policy:read/manage、
change:propose。按源 ID 排序加行锁，权限、基线摘要、只收窄规划、静态校验沿用单策略
规则。任意项失败整批回滚：无部分策略、变更、审计或 outbox 留存。每项独立保留标准
审批；批量申请不是批量审批，更不是部署或撤权生效。

幂等摘要绑定验证租户、操作者及类型、整批规范排序输入；条目和选择重排不改变含义。
子申请使用 batch 专属内部键空间，不与单策略请求键混用。同键不同内容或操作者 409；
同内容完整重试返回全部原记录，不再写入；发现不完整原记录时拒绝，不尝试补写。
数据库唯一冲突回滚后仅允许返回完整匹配记录；否则 409。其他持久化失败全部回滚并
返回固定 503，不回显策略正文或异常。SQLite 测试不证明 PostgreSQL 并发锁语义。

201 响应 no-store，schema_version=`enterprise-network-revoke-batch-result/v1`、
items（按 source_policy_id 排序的既有 enterprise-network-revoke-proposal-result/v1
对象）、requires_independent_approval=true、executed=false。executed=false 仅表示本次
申请不执行，不推断原记录的历史状态；每项当前审批/部署通过已有变更接口核对。

## 无正文只读恢复

GET `/api/v1/network-revoke-batches/{request_key}`，UUID 不是凭据。新申请在全部子变更
impact 同事务存入服务端生成的 batch_manifest：版本标识、规范排序的源策略 ID 列表、
整批摘要。不保存原选择正文；无新增独立状态表。历史缺少 manifest 的批次不猜测补全。

恢复先按验证租户、原操作者 ID/类型定位首项，再核对 manifest、全部子变更的内部键、
身份及摘要、全部源策略/新策略的同租户关系。缺失或不一致、越租户、非原身份均 404，
无部分成功；完整定位后检查 policy:read/manage、change:propose，失权 403。

响应 no-store，schema_version=`enterprise-network-revoke-batch-recovery/v1`、
lookup_executed=false、items（按源 ID 排序；每项 source_policy_id、policy_id、
change_request_id、change_status）。状态为当前记录值，不证明运行时撤权效果。
lookup_executed=false 只表示此次查询未执行，不表示历史申请从未部署。
任意次数查询无策略/变更/审计/outbox/部署/任务写入。404 也可能表示尚未持久化或
当前身份不匹配，客户端不能据此另建申请或重放 POST。

前端入口仍待交付。保留完整请求才能以原 request_key 同内容重试，查询不替代提交。
无自动审批、部署、真实运行效果或全共享影响的完成声明。
