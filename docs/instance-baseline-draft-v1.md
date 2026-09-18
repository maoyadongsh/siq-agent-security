# 明确创建实例权限草稿 v1

真实 `admit → /v1/grants` 保留 Skill 归属，不能直接充当实例基线。Windows profile v2 只接受明确的实例基线；既有组件测试使用缺 SkillID 的合成准入，未覆盖真实创建入口。本增量增加独立管理接口，不改变旧接口或删除既有授权的 Skill。

`POST /v1/grants/instance-drafts` 使用严格合同 `grant-instance-draft-create/v1`，仅接受 `schema_version`、`actor_id`、`instance_id`、`admission_id`、`request_id`、`confirm_instance_scope: true`。`actor_id` 必须为原样非空、无首尾空白/控制字符且不超过 128 字符；`request_id` 为 `gid-` 加 32 个小写十六进制字符。服务端从当前 inventory 唯一解析目标平台与实例根，由 instance_id 派生主体；不接受客户端 platform、subject、路径或权限事实。沿用管理会话鉴权、状态屏障和宿主支持边界。

仅使用真实保存、验签通过、非 quarantine、非保留 Skill import 准入。准入仍保留原 SkillID、内容摘要和 evidence；新 Grant 在首次签名前明确构造成无 Skill 的实例基线，其 `admission_id` 保留原来源。只沿用现有声明/推断事实与 deny 默认值，不能由模型生成 effective、批准、身份或会话。新对象状态固定 `pending_approval`；编辑 Windows 资源、批准、部署、身份签发均为后续独立步骤。旧准入与 Skill Grant 逐字节不变，旧 `/v1/grants` 继续生成原有 Skill 授权。

新 Grant ID 为 `grt-id-` 加规范化 `{actor_id, request_id}` 的 SHA256；使用独立命名空间。相同 actor/request 重放必须匹配初次保存的 admission_id、inventory 平台与实例主体，且原对象和策略验签/读取完整；否则 409，不覆盖。返回已有对象的当前 revision/status，不重置已编辑、批准或撤销状态。不同 request 或 actor 可明确另起独立草稿。并发创建通过现有 Grant 事务锁和 expected revision=-1 排他发布；只有胜者追加一次 `grant_instance_draft` 审计，审计与状态同事务，审计失败不能发布可读权限。进行中提交允许等待原事务后读回；损坏/崩溃残留必须拒绝，不能被当作可重建缺失对象。

新建返回 201，幂等读回返回 200，均为 `grant-instance-draft-created/v1`：`instance_id`、`grant`、`state_revision`、`reused`。首次返回只能 pending；后续原样返回当前 v1/v2 Grant。响应不含凭据、路径根或新的 Skill 归属声明。客户端必须再次核对主体、平台、准入、无 Skill 与 revision；需要单独明确确认实例范围，不能把已有 Skill 准入自动升级为实例授权。

错误：非法字段/版本/确认/标识为 400 `grant_instance_draft_invalid`；缺准入为 404 `grant_instance_draft_admission_not_found`；不可信准入为 409 `grant_instance_draft_admission_unavailable`；目标不存在/有歧义/不支持为 409 `grant_instance_draft_target_unavailable`；幂等键绑定不同请求为 409 `grant_instance_draft_request_conflict`；既有对象/策略不完整为 409 `grant_instance_draft_unavailable`；事务错误沿用现有错误映射。不自动修目录、改 ACL、启用 profile 或重签旧授权。

验证必须从真实 HTTP admit 创建并保留一个旧 Skill Grant，再从新接口创建、验签、资源编辑/独立批准；断言旧对象不变、并发幂等、重放保留新 revision、不同绑定冲突、缺确认/未知字段/非管理员/不可用目标/不可信准入拒绝，以及审计故障不可发布。合同样例由真实 Go 输出投影并经 Python JSON Schema 校验。
