# WorkBuddy Windows 受管 command 接入增量 v1

本规格继承 ADR-028/029、Windows Authority 与 N01 消费者屏障。范围为 Windows WorkBuddy 自身的 command hook，不用 CodeBuddy CLI 或源码阅读代替桌面实测。实现、组件验证、真实桌面验证分别记录；本文件不宣布 WorkBuddy 完成。

## 实例与版本

服务从自身配置的 `WORKBUDDY_CONFIG_DIR`，或其 Home 下 `.workbuddy` 恢复根目录与既有 `hi-` ID；不读取 CODEBUDDY_CONFIG_DIR、数据库、登录态、cwd 或请求提供的路径。绝对本地目录、祖先、重解析及真实 Windows 路径事实必须通过既有检查。跨产品同根导致实例 ID 歧义时拒绝。Skill 安装目标的既有平台范围不随本增量扩展。

首版仅显式 Windows 权限：pending Grant 经 resources/v2 确认、独立批准和部署后，才可 create/v2 再次确认并签发 identity/v2，进而生成 Intent v4/binding v2。旧 v1 身份不扩展 WorkBuddy；不提供 WorkBuddy POSIX identity fallback。macOS 旧 command 接入及历史读取不变。

2026-09-18 新鲜核对 main 为 bb364015；Grant/identity/issued v2 是本轮 b335421 新增未发布合同，list v2 是 a9c8c72 新增未发布合同。仅这些未发布 v2 的 Windows 分支添加 WorkBuddy；旧签名序列化与已发布 v1 合同不改。issued/v2、list/v2 既有字段足够，platform 为 workbuddy，filesystem_profile 固定 windows-local-drive/v1。

WorkBuddy 实例列表新增 local-adapter-instances/v2；保留原列表字段，增加服务端 `managed_runtime_available` 布尔值。仅 Windows 且受管目录可核验时为 true；其他系统 false。此值只表示可配置受管实例，不表示钩子加载、桌面调用或 Skill 归属已验证。Hermes/OpenClaw 继续原 instances/v1。

WorkBuddy 受管安装计划使用新 `local-adapter-plan/v4`，字段延续 v3 且 platform 固定 workbuddy；不原地扩写已发布 v3。真实入口为已签名准入 → 独立 `grant-instance-draft-create/v1` 实例草稿 → resources/v2 → 批准部署，不删除或重签旧 Skill Grant 的归属字段。

## 原生会话和调用身份

真实 command 外层 session_id 和 tool_use_id/call_id 是宿主命名空间输入，均须有效 UTF-8、1–256 字节、无控制字符及首尾空白；不能从 tool_input 取值，不补默认值或随机后缀。

- `session_id = "workbuddy-session/v1:" + lowercase_hex(sha256("workbuddy-native-session/v1" + NUL + host_session_id))`。
- `tool_call_id = "workbuddy-call/v1:" + lowercase_hex(sha256("workbuddy-native-call/v1" + NUL + host_session_id + NUL + host_call_id))`。

仅受管 WorkBuddy 使用上述格式；旧全局凭据的 WorkBuddy POSIX 行为保持。此摘要仅隔离宿主命名空间，不是授权、UUID epoch、重生证明或同 UID 隔离。宿主可能折叠 parentSessionId；不能可信区分的子任务/恢复保持 unknown 和未验证，不宣称独立隔离。更换 host session 改变 SIQ 会话；同一 host session 的重复登记不能延长期限、换身份或复活撤销。

POST /v1/runtime-sessions 仍接受 enroll/v1 的两个严格字段及实例 bearer。WorkBuddy 成功响应为新 enrolled/v2，字段恰好为 schema_version、identity_id、platform、agent_id、session_id、binding_id、intent_id、expires_at；platform 固定 workbuddy，返回原派生 session。其他两宿主保持 enrolled/v1。受管 decide/observe 必须提供上述有界 tool_call_id；会话、实例、Grant 与 profile 每次在线复验，错误不可变成 advisory。

## 配置和命令

配置仅为 `<WorkBuddyConfigDir>/siq-agent-security.json`，schema `workbuddy-managed-hook/v1`，固定字段 schema_version/runtime_identity_id/instance_id/agent_id/credential_path/endpoint/enforcement_mode/state_dir。state_dir 是明确安装状态目录，credential_path 必须等于该目录的 runtime-identity-secrets/<identity>.token；命令显式 `hook workbuddy --state-dir <abs> --managed-config <abs>`。不写明文 token、管理员权限或签名私钥。

--managed-config 存在或检测到受管痕迹后，配置缺失、损坏、字段别名、重复、身份/路径不符均输出结构化 deny，禁止回退全局 token/default agent。无受管痕迹的旧接入仍是 legacy。凭据只发明确端口的 HTTP loopback，拒绝代理与重定向；单次完整 HTTP 链共用 20 秒预算，宿主同步 hook 等待 30 秒；不续时或自动重试。

受管接入的“安装或修复”必须将本实例已确认归属的 command 钩子恢复为独立 `matcher=.*` 分组和产品默认同步配置，不能只替换命令而沿用用户改窄的 matcher、异步属性或重复登记。仅移除与当前/记录二进制、状态目录和受管配置路径精确匹配的 SIQ command，随后每个事件写入一个规范分组；其他命令、非 command 项及其分组 matcher/元数据原样保留，不能通过扩大混合分组的 matcher 影响用户钩子。仍经原预览、确认、备份和归属校验流程写入。

## command 输入与能力边界

新 WorkBuddy 受管 hook 输入合同只允许 hook_event_name/session_id/tool_use_id/call_id/tool_name/tool_input/tool_response/cwd/transcript_path/permission_mode/agent_id/agent_type/generation_id/model/client/version。前六项必需，tool_use_id 与 call_id 精确相同；tool_input 必须 object；只接受 PreToolUse/PostToolUse，后者必须 tool_response。metadata 是可选 string，每项最多 4096 UTF-8 字节，无控制字符或首尾空白，存在时不得为 null 或其他类型；空 string 可接受。总量最多 1 MiB、深度最多 64，递归拒绝重复 JSON 字段、大小写别名、未知外层、非法 UTF-8 和多 JSON；用户工具参数 key 不作为 Authority 字段解释。transcript_path 不读取，外层 agent_id 不覆盖 SIQ 签名身份，cwd 不选择 profile 或授权根，相对路径仍按当前 Windows 资源合同拒绝。

generation_id/model/client/version 来自宿主 command 执行前的 GenerationContext/ClientInfo input processor；它们仅为描述性元数据，不参与 session/call 派生、Authority、重试证明或审批消费，不进入 decide/observe 的权限字段。此次补齐本轮未发布的输入合同 v1；外层 additionalProperties 仍为 false。源形状合成夹具与安装源 SHA/UTF-16 定位见 packages/contracts/fixtures/workbuddy_command_hook_input_v1_source_examples.json；所有值为合成脱敏值，该夹具不是桌面调用捕获，不能代替原生验收。

allow 输出仅表示 SIQ 无异议，不覆盖宿主原权限门禁；初次 deny/hold/redact 一律结构化 deny。审批恢复按 [WorkBuddy 审批恢复 v1](workbuddy-approval-resume-v1.md)：持久保存首次真实 pre 的原 hold 关联，用户在 SIQ 独立批准后，新的真实 pre 仅在身份/会话/tool/精确参数匹配、原 hold 在线核对和唯一 reserve 成功时允许；ask、新 call 或模型自报均不能独立消费批准。缺失/损坏关联、重复或不确定执行不回落新 allow。后置观察明确绑定对应允许的 pre/call/action/decision（恢复时为 reservation receipt），错误不得伪造成功。A06 仍须有原生桌面证据后才可验收。

## 验证要求

合同正负向、旧签名/旧 POSIX 兼容、真实目录发现、缺 session/call、跨实例/平台/session、profile 降级、撤销、重复登记不续期、服务不可达及 malformed 请求必须分别验证。核心 HTTP 夹具不能替代桌面允许/越界拒绝/失联恢复/撤销的原生证据；未经新增账号额度授权不发送 WorkBuddy 模型任务。

2026-09-19 按主开发规格的实机修复增量，替代此前固定 4 秒预算的约束：受管 Pre 的登记、裁决及审批恢复请求共用一次 20 秒 HTTP 截止时间，宿主同步 hook 等待 30 秒。原预算已在真实桌面正常调用中造成超时；预算调整后已取得正常写入及拒绝场景证据，见 [当前交付](windows-functional-delivery-20260918.md)。到期仍拒绝，不重置截止时间、不自动重试、不延迟撤销检查、不复用旧 Authority；这不构成审批恢复已实机通过的证据。
