# 原生运行身份管理接入 v1

OPT-08 D3a 在既有管理鉴权边界内开放已定义的 `local-runtime-identity-create/v3`，不改变其 JSON 字段或 v1/v2 身份语义。此增量替代 D2 阶段“所有新身份 HTTP 创建均关闭”的临时门禁；它不代表日常业务验收已完成。

## 管理签发

`POST /v1/runtime-identities` 仍只接受现有管理会话。v3 必须精确包含 schema_version、instance_id、grant_id、expected_grant_revision、actor_id、session_ttl_seconds、native_skill_policy；内层策略精确为 `mode=required` 和 runtime_artifact_sha256。拒绝未知/重复/错误大小写/null 字段，模型和普通运行凭据不能创建身份。

仅显式 `serve --native-host` 构造的服务可以处理 v3：Engine 已连接该 NativeRuntime、宿主桥接/身份存储/调用查询器已一次性绑定，且私有宿主连接配置与 socket 身份仍有效。缺少接线或连接配置变化返回 503 `native_skill_runtime_unavailable`，在签发任何凭据之前失败。语法错误仍返回 400。已有 v1/v2 创建不受此条件影响。

绑定的 Agent 基线 Grant 必须经过原有人工批准、当前 revision 和主体匹配检查；不能用 Skill Grant 代替基线。已有未撤销根身份仍冲突，不自动替换，不隐式迁移旧身份。v3 创建不批准权限、不安装 Skill、不登记实际运行进程，也不允许客户端自称“已验证”。

成功响应使用既有 `local-runtime-identity-issued/v3`，仅返回私有凭据文件路径与签名记录的非秘密摘要，runtime_state 必须为 `unverified`。随后会话登记使用现有运行凭据与 `local-runtime-session-enroll/v1`，返回 v3 会话读回，仍为 `unverified`。

## 启动与执行

管理签发选择固定制品策略，不需要让尚未启动的 runtime 伪造运行证据。发行阶段的连接检查仅证明本实例已配置并绑定正确的宿主通道，不宣称对应 Hermes 进程在线或已验证。

实际启动器在创建并核验受保护的 OpenShell/Hermes 进程之后，登记匹配实例、会话、制品和安装映射。原生 task_begin、Skill 加载、调用绑定与 `/v1/decide` 继续执行反向宿主核验；未登记、制品不符、撤权、进程失效或通道不可达时拒绝，不因身份已签发而回退旧插件或无 Skill 模式。

凭据留在宿主侧，通过既有 authenticated decision relay 转交裁决。管理 API 不接受核验 URL、PID、安装声明或自报健康作为授权事实。浏览器和模型不能通过本增量登记一个可信进程。

## 验收界限

应分别证明：管理身份正向签发；普通运行/发布凭据拒绝；未接线/失效配置无签发；严格字段及旧协议兼容；签发与会话登记后，未登记原生任务仍不能执行；实际 OpenShell 工具联验使用管理 HTTP 签发与会话登记，而非直接调用 Store.Create/Enroll。

真实业务仓库启动、模型对话、人工审批交互、安装升级和跨平台原生验收仍是独立门禁，不因管理入口开放而自动完成。
