# ADR-036：固定 Skill 候选的权限准备

状态：权限准备与人工批准入口已实现并完成本批验证；UX-007/009 增量，继续既有 Grant 人工审批状态机。

## 内容绑定与兼容

导入原始 admission ID 由旧内容摘要前缀产生，同样内容可来自多个候选，而旧内容摘要不包含所有签名辅助文件。不能直接发布该原始 admission 后复用旧 Grant。新增 `local-skill-import-permission-source/v1`，包含 import_id、artifact_digest、analysis_sha256。严格规范化 JSON 作为派生 admission.source.ref；派生 admission ID 为 `adm-si-` 加该规范化对象 SHA256。`source.locator` 保留 `skill-import:<id>`，其余扫描结论、时钟、引擎和事实语义保持原值；证据 ID 按派生 admission ID 与原证据 ID 哈希生成独立命名空间，更新引用并重新签署派生记录和证据，避免共享旧证据 ID 时混入不同来源元数据。此记录表示既有结论的内容绑定，不冒充重新扫描。

原始导入记录与 analysis.json 不修改。派生 ID、签名、来源引用及三个摘要必须可从当前完整校验的导入副本重建并逐字节比对；quarantine 不能准备权限。派生记录存储使用严格 JSON 同值检查，不适用旧“同 ID/内容即可保留首次写入”的兼容规则；卡片可以复用原检查卡片，来源绑定事实由签名 admission 表达。

Grant 继续使用现有合同，其签名与批准挑战中的 admission_id 通过完整 SHA256 锁定上述来源引用，不新增第二套批准权威。新的导入权限 Grant ID 使用 `grt-si-` 加规范化 `{source, platform, subject, actor_id, request_id}` SHA256。明确请求 ID、平台、主体和操作者；不因旧 Grant 的 live 状态复用别的权限。初始仍 pending_approval/default-deny，使用原有权限/期限编辑和 challenge/approve。两个实例的草稿互相独立；变更权限必须走现有 revision CAS 和重新批准。

`adm-si-` 是保留来源命名空间，普通 HTTP/CLI 的“从 admission 创建 Grant”不得绕过导入准备入口创建这类 Grant。服务器的 challenge/approve/draft 必须完整重新校验来源；离线 CLI 使用同一来源验证后才签发挑战或批准。拒绝/撤销不依赖来源仍存在，确保损坏候选可撤权。读取、编辑展示不把历史来源绑定当作当前运行证明。

## 接入顺序与运行边界

先接通已拥有稳定实例解析和 hri 身份映射的 Hermes 实例选择；OpenClaw、WorkBuddy 目标解析仍按任务书继续实现，不以平台名字符串或任意目录冒充真实目标。UI 从导入结果选目标实例、准备权限，再进入已有 Grant 编辑与批准页。

安装与可信 Skill 调用归属尚未完成，因此本增量只提供准备/批准，不将其转为实例运行权限。核心 MarkDeployed/MarkEffective 对保留导入 admission 明确返回 `grant_import_installation_required`；后续安装事务验证目标、批准摘要、写入内容与读回后再实现受证据约束的转换。不能使用既有通用 deploy 按钮或离线 CLI 提前激活，也不能将实例级权限包声明为已验证的 Skill 隔离。

尚未给旧二进制提供完整状态降级保护；个人发布/升级验收前必须按 UX-010/014 解决旧写入方兼容，不声称当前开发状态可无条件回滚。

## 管理请求

管理 POST `/v1/skill-imports/{id}/permissions`：`local-skill-import-permission-create/v1` 包含 schema_version、request_id（ip-32hex）、artifact_digest、analysis_sha256、instance_id（hi-32hex）、actor_id。服务解析实际 Hermes 实例并派生 hri 主体；客户端不能指定任意平台、主体或目录。完整 Load 后验证请求摘要，发布派生 admission、默认拒绝草稿、策略和审计，返回 `local-skill-import-permission-created/v1`：import_id、source、grant、state_revision、reused、installed=false。失败的派生 admission 不产生权限；最终 Grant 仍由既有 commit journal 控制可见性与恢复。重试按相同请求确定 ID，保留已编辑/已批准的当前版本，不重置或复活终态记录。

## 验证要求

同一原始内容的不同导入、签名辅助文件变化、来源替换、错误摘要、quarantine、损坏签名与严格持久化冲突；同一请求重试和不同实例/操作者/请求的独立性；旧 v1 样例与签名保持不变；编辑使旧挑战失效；批准仍不允许 deploy/effective；拒绝/撤销可处理已损坏来源。HTTP 管理身份、严格字段/空值/重复字段、取消和并发负向、浏览器路由恢复与真实本地 daemon 验证随后补齐。


## M20 验证结果（2026-09-11）

导入结果中的目标选择、真实权限准备 API、既有权限编辑/人工批准页和完整来源摘要展示已接通。首次 201，同请求重试 200；重复请求只返回当前 Grant，不重置批准。离开组件取消准备请求，响应丢失可按原参数重试。候选变更在 challenge/approve/draft 前阻断，损坏来源仍可拒绝或撤销。通用 HTTP/CLI 创建入口及 deploy/effective 核心均有负向测试。

Go 全量/vet、skillimport/server/grant/state/CLI race、120 项 Python 合同（含规范化来源与 Grant ID 的独立 SHA256 重算）、33 项 Web 测试、个人/企业构建、四目标交叉编译通过。真实隔离 daemon/Chromium 的导入权限流程 8 项、既有本地导入 16 项、HTTPS 前端 7 项、CLI/HTTP 导入 12 项在同一个候选通过；HTTPS 成功展示仍是 M19 明确的 DTO 响应夹具。权限目标为隔离 Hermes 配置目录，不运行宿主或安装 Skill。

[验证清单](../evidence/personal-experience/skill-import-permissions-20260911/verification.json)保存本批范围和身份。旧本地浏览器截图检查改为直接滚动到结果标题，避免新增权限区使长卡片居中后标题在视口外；保留标题在视口与水平溢出断言。此为测试定位修正，不放宽 UI 验收。

下一步是绑定目标目录/实例、批准权限摘要和完整 Skill 制品的安装预览、人工确认、原子写入、恢复及目标读回；再决定何时可进入平台接入与运行验证。旧二进制降级保护、其他平台与真实三系统仍是完整任务书的待办。
