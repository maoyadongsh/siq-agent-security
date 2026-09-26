# 企业多目标部署预览 v1

POST /api/v1/deployment-previews/batch 为只读预检，不执行部署、审批或权限变更。
请求 schema_version=enterprise-deployment-batch-preview-request/v1，items 为 1–20 个
既有 deployment-preview-request/v1。禁止额外字段，重复 binding_id 或重复 change_request_id
拒绝 422，避免同一变更并发消费和重复目标。逐项复用单项预览的租户定位、权限、已批准
变更、运行时绑定、隔离、来源归属及后端预检。任一失败整批失败，不返回部分结果。

整批先按验证身份定位全部变更、其策略、环境和绑定；任一不存在或越租户统一
404 not_found，并且不开始任何单项目标准备或后端预检。全部对象定位完成后才
核对 policy:manage、policy:read、env:read，权限不足 403。这项批次前置检查不替代
单项准备时的重新定位、审批/绑定复验和后端身份校验，也不是数据库快照隔离保证。

不同绑定若解析到相同 backend/target，409 batch_preview_target_overlap；此版本保守
拒绝同名目标，即使它们可能属于不同网关，不把环境 ID 当成后端隔离证据。
请求按 binding_id 排序处理，结果同序，避免客户端顺序影响摘要和锁获取顺序。

响应 schema_version=enterprise-deployment-batch-preview/v1，items 为原单项预览结果，
preview_digest 为绑定租户、操作者及类型、全部结果的规范 JSON SHA-256。
batch_submission_supported=false：摘要只是当前预检快照，不是授权或可提交批次。
本版本无批量 submit，不持久化批次、不构造已生效记录；可用既有单项流程重新核验
和确认，不能把批量预览成功当作批量已部署。no-store。

此为 ENT-015 的预览基础，不提供权限收窄/撤权转换、完整共享影响枚举、有效期限、
持久批次、CAS/幂等提交及部分失败恢复。上述能力仍是整体目标的待完成要求。

## 预览返回前的登记身份复验

单项 `/api/v1/deployment-preview` 在准备完成后、生成预览前，复用既有绑定身份
校验，核对准备时的标量副本与当前事务可见的绑定、实例/资产来源。
批量接口在全部目标准备完成后、生成成功批次响应前，再对本批逐项执行该复验，
覆盖后续目标探测期间前序目标发生的可观察漂移。

吊销使用既有 `409 binding_revoked`，身份/来源变化使用既有
`409 binding_source_identity_changed`；任一复验失败整批拒绝、不返回部分 items。
原排序、目标重叠判定、摘要算法及只读性不变，不新增后端探测或重新准备。

这不是原子批次快照，不超越事务隔离级别，也不消除最终逐项复验之间及复验之后的
并发窗口。字段范围限于既有登记身份校验，不能推导策略、审批或 attestation 等
其他字段在整个请求期间不变。所有提交/执行入口仍需保留独立复验。
