# 技能任务最终回执 v1

沿用 /edge/v1/tasks/{task_id}/receipt 和在线设备凭据，不混用本地 RuntimeReceipt 合同。skill_scan 回执必须精确携带 task_id/device_identity，与环境及任务指定设备一致；成功增加 skill_batch_digest 和 skill_observation_count（含显式 0），candidate_count/evidence_count/evidence_ids 必须为空，truncated 必须 false。

成功只可从 uploaded 转 delivered：任务结果摘要、SkillUploadReceipt 摘要与回执摘要相同，保存的规范签名输入重新验签/校验摘要，输入中的观察数量和数据库该设备/租户/批次的观察数量一致。无上传记录不得成功，包含零发现。终态成功重放仍校验全部摘要和数量，不把同 status 当成充分证据。

任务控制面签名、有效期、精确设备与在线吊销每次核对；首次终结需当前设备有效租约，以状态条件 UPDATE 抵御重复终结，审计与 outbox 同事务。已 delivered 的一致回执重放不新增审计，但过期/吊销仍拒绝。

失败仅允许未上传 pending 任务，不携带技能成功字段；已 uploaded 不接受失败回执覆盖。上传结果未确认时 Edge 必须保留原批次并重试，不能自动上报失败来终结它。普通任务携带技能专用字段拒绝，原普通 scan 与 publish_policy 防御不改。

回执只确认技能盘点结果已入库，不创建权限或安全保护生效状态。执行器接入与真实全链路验收另行完成。
