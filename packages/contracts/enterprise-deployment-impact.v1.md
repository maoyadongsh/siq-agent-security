# 企业部署影响核对 v1

POST `/api/v1/deployment-preview/impact` 是只读预检，无审批、部署、扫描或审计写入。
请求 schema_version=`enterprise-deployment-impact-request/v1`，字段为
change_request_id、environment_id、binding_id（1–64 字符）及 preview_digest
（64 位小写十六进制）；禁止额外字段。租户及操作者来自验证身份。

先复用部署预检：同租户对象定位 404，policy:manage / policy:read / env:read
权限不足 403，审批、隔离、绑定、后端身份及能力检查不绕过。读取实例身份还要求
agent:read；在后端预检前核对。请求摘要与当前预览不一致时 409
deployment_preview_changed，不返回过时影响报告。

响应 schema_version=`enterprise-deployment-impact/v1`，包含当前 preview、
registered_subject（binding_id、environment_id、asset_id、agent_instance_id），
coverage=`registered_binding_only`、shared_runtime_occupants=`unknown`、
skill_isolation=`not_established`、execution_confirmation_supported=false 及 impact_digest。
impact_digest 是规范 JSON（UTF-8、sort_keys、紧凑分隔符）SHA-256，涵盖上述投影以及
验证租户、操作者及身份类型。它不是授权令牌或执行接口接受的确认摘要。

RuntimeBinding 的租户/后端/目标唯一约束意味着查到一条绑定不能证明目标只有一个
角色或 Skill。登记身份不是运行时占用证明；本合同不声称列出了所有共享对象，
不从 selector 推导独立隔离。无 Skill 安装观测也不能解释为没有安装 Skill。
客户端不得将此响应解读为完整影响确认，不得据此自动部署。

Cache-Control: no-store。响应不包含 attestation、原始来源位置、秘密、其他租户对象。
读取不持久化影响快照，不改变旧版预览及执行接口。本合同是完整共享影响与执行
确认闭环的前置部分；后续需要独立运行时占用证据、完整覆盖证明与执行时复验合同。

## 报告生成前的登记身份复验

预检准备完成后、计算报告前，复用绑定身份复验，按验证租户列级重读绑定并核对
准备时的身份标量副本及实例/资产来源关联。可观察到的吊销返回既有
`409 binding_revoked`；绑定缺失或登记身份/来源变化返回
`409 binding_source_identity_changed`。拒绝不采用新目标、不重编译、不写业务状态。
响应结构及摘要算法不变。

此复验绕过 ORM 身份缓存，但不超越数据库事务可见性，也不提供原子快照或消除
复验之后的并发窗口。字段集限于既有绑定身份合同；不保证策略、审批、attestation
等所有字段在探测期间不变。报告仍不是执行授权，不替代执行时的独立复验。
