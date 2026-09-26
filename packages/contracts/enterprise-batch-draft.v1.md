# 企业批次预览草稿 v1

POST /api/v1/deployment-batch-drafts 保存一次经原批量预检的快照，不部署、不批准。
请求 schema_version=enterprise-batch-draft-create/v1，items 同批量预览（1–20，
重复变更/绑定拒绝），request_key 为 UUID。未知字段拒绝。

先定位整批租户对象、检查 policy:manage/policy:read/env:read，再查询幂等键。
同租户同键、同操作者及类型和同一规范请求返回原草稿（200）；冲突 409。
首次成功 201，草稿及 deployment.batch_preview.create 审计同事务。
只保存原预览的脱敏投影，不保存原策略、凭据或审批秘密。

GET /api/v1/deployment-batch-drafts/{id} 按租户定位（404），要求 policy:read、
env:read 且操作者/类型匹配（403）。读取历史快照不重跑后端、不更新有效期限。
响应 schema_version=enterprise-batch-draft/v1，字段 id、preview（原批量响应）、
created_at、expires_at、state（previewed/expired）、submission_supported=false。
时间为 UTC；期限自开始预检起五分钟，状态在每次读取时计算。过期重试仍返回原
expired 草稿，不能自动续期；重新预览必须使用新键。

草稿可刷新恢复，但不代表快照仍与后端一致；未过期也必须在未来提交时重验。
本版本没有执行、审批、取消、删除、自动重放或恢复未知部署结果的接口。

POST /api/v1/deployment-batch-drafts/{id}/revalidate 是只读复验：请求为
schema_version=enterprise-batch-draft-revalidate/v1 和 preview_digest（64 位小写
十六进制）。先按租户定位、检查原操作者及读取权限，再检查 policy:manage。
客户端摘要必须匹配存储摘要；期限在后端预检前后都检查。由存储快照恢复全部目标，
复用整批预检并比较摘要，过期 409 batch_draft_expired，摘要或后端快照改变
409 batch_draft_changed。审批、绑定、隔离和归属失败沿用原拒绝码。
成功返回原 DraftOut，不改记录或有效期限，不产生审计/任务/部署写入。
复验响应不是执行令牌；未来执行必须在同一受控流程内再次复验，不能信任客户端
此前收到成功。该接口不宣称并发快照隔离，也不消除复验之后的竞态。

幂等由数据库 tenant_id/request_key 唯一约束保证；碰撞败方回滚后只读已存草稿，
绝不提交第二条审计。迁移降级遇到已有草稿拒绝，避免删除历史。
