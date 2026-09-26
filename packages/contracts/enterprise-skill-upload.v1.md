# 企业技能签名上传 v1

POST /edge/v1/skill-batches 为独立技能观察入口，不接受智能体候选/Evidence/权限授予。当前尚无公开任务签发入口，只有后续明确签发的 skill_scan 任务可调用；旧 scan 不接受，不能用旧任务扩大采集范围。

设备凭据每请求在线验证；Ed25519 签名采用现有 UTF-8 排序紧凑 JSON，签名输入移除 signature，包含 schema_version=enterprise-skill-upload/v1、task_id、scope_digest、observations。scope_digest 为任务 payload.scope 的同规范 SHA-256。任务必须属于设备真实环境，payload.connector=directory、inventory_kind=skills、scope.include=[SKILL.md]，target_device_identity 精确绑定设备，scope.roots 非空。首次必须有本设备持有的有效租约；有效期、任务类型、范围摘要均检查。

observations 0–200 项：locator_sha256、manifest_sha256、parser_version=enterprise-skill-manifest/v1、parse_status、name（可空）、allowed_tools_present、declared_tools（至多 64）、observed_at。安装位置摘要不得重复；完整清单摘要不得来自 too_large 状态。服务端拒绝非 parsed 状态携带名称/工具声明、非法标识及已知凭据形状；不接收正文、路径、任意元数据、effective 权限或角色关系。首次观察时间与服务端相差不超过五分钟。完整扫描零发现可提交空数组，仍保留签名输入与审计；采集失败或截断不得伪装成空结果。

上传按任务原子预留结果摘要；技能位置、观察、审计和 outbox 同事务提交。相同已上传任务/摘要重试返回 idempotent，不重复入库；不同结果拒绝。任何失败回滚，不把上传当成最终任务回执。数据库竞争回滚并返回冲突，可重试原批。过期任务或吊销设备即使相同内容也拒绝。

scope_digest 证明设备签名声明与任务范围一致，不证明实际读取行为；Edge 范围门禁与安全读取仍须实现验证。本轮 API 不签发 skill_scan，不部署，不声明完整自动技能盘点已完成。PostgreSQL 并发验证另行执行。

skill_upload_receipt 按任务只保存一份经 schema 校验的完整规范签名输入（不含 signature 字段）、签名、摘要与认证设备/租户引用，和观察同事务。该输入不含正文或路径，允许事后重新验签，而非只有不可重建的摘要；重复批不复制。迁移 0022 有数据时拒绝降级删除。

响应 schema_version=enterprise-skill-upload-result/v1、task_id、batch_digest、observations、idempotent。首次 observations 为本次写入条数，幂等重试为 0。Edge 必须校验任务、摘要、标志和数量，缺字段/不符即结果未确认。原生 prepareSkillUpload 拒绝带 issues 或 truncated 的采集结果，签名时冻结 JSON；UploadSkills 发送前重算摘要拒绝本机内容漂移，不隐式重试、不触发重扫。持久化日志与任务重试编排仍需由后续 runner 实现。

版本导航：本 v1 只描述 v1 线路。**`enterprise-skill-upload/v2` 与 `enterprise-skill-collection/v2` 的语义不另建文件**，完整定义见 [enterprise-skill-ancestry/v2](enterprise-skill-ancestry.v2.md)（该文说明 Linux Directory 新增 `collect_skills_v2` 返回 collection/v2、v2 对应 upload/v2、控制面同时接受 v1/v2、响应仍为 upload-result/v1）。控制面 `app/skill_upload.py:44` 同时接受两个版本且分支校验不同：v1 禁止 `ancestor_sha256`（含显式 null），v2 要求其为 1–33 个互异小写 SHA256 且首项等于 `locator_sha256`。跨文件名建档关系另由 `scripts/enterprise-experience/contract-version-aliases.json` 显式登记，供只读审计工具核对。
