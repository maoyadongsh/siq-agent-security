# Windows WorkBuddy Skill 安装、更新与归属接入 v1

日期：2026-09-18。状态：实施中，尚未完成集成检查或原生验收。初始只读核对基线为 `edbf5d1e5a52a92f126f58302a59fd4dc27f60d2`；后续合同、安装库、服务端和界面按本文接线，开发检查与真实宿主结果分别记录。资源编辑、安装引导和通知改动另有专项规格。

本文细化 Windows 任务书中 WorkBuddy 的完整 Skill 旅程，继承 ADR-033–047、N05 SEC、Windows 资源事实与 N01 私密状态约束。必须先落版本化合同，再改实现及样例。用户级和项目级均为本轮实现范围；使用同一套现有 `internal/skillinstall` 暂存、排他发布、更新、移除和恢复事务，不另建安装引擎。当前仓库没有独立 `internal/skillupdate` 包，更新实现在 `skillinstall/update_*.go`。

## 1. 原生依据与可声明的能力

### 1.1 官方资料与安装分发物

[WorkBuddy 官方项目说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Project)列出项目 `.codebuddy/skills`，并说明项目级同名 Skill 的优先级。[设置说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Setting)描述 `.codebuddy` 配置兼容；这不等于 WorkBuddy 自身的用户配置根恒为 `.codebuddy`。[Skill 市场说明](https://www.codebuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)区分安装、启用和卸载，不授权 SIQ 自动改原生启用设置。

本机只读来源为 `C:/Program Files/WorkBuddy/resources/app.asar` 与 `app.asar.unpacked/cli/dist/codebuddy.js`。读取 ASAR 条目时比对其 integrity SHA256，没有导入、执行或修改程序。来源记录已有 `.tmp/windows-delivery-draft/workbuddy-source-identity.json`；产品元数据为 WorkBuddy、genieVersion `5.5.6`、commit `5f9692923c93033111c51ad7b003eb80204a9b75`，不把版本元数据当作运行验证。

| 来源位置（解包内容的 LF 行号） | 已核实事实 |
| --- | --- |
| `main/workbuddy-product-config.js:443` | 产品配置根优先显式 WorkBuddy 环境变量，兼容 CodeBuddy 环境变量，最后用产品数据目录 |
| `main/app-instance.js:81–82` | WorkBuddy 启动器把两个配置目录环境变量都设为已解析的 WorkBuddy 根 |
| `main/workbuddy-paths.js:99` | 用户 Skill 根为 WorkBuddy 配置根下 `skills` |
| `main/server.js:86963`、`:87351` | 桌面 Skill 服务从配置根派生用户目录；其显式配置、环境、实例编号处理不能被 SIQ 静默猜测 |
| bundled `codebuddy.js:2851` | 用户根来自上述传入配置；项目根来自 workspace/workdir 下 `.codebuddy/skills`，独立于配置根 |
| bundled `codebuddy.js:905` | `SkillProductProvider` 先项目、后用户，再连接器/会话包等；同名先到者优先；有加载缓存，扫描深度上限为 5 |
| bundled `codebuddy.js:893` | 启动和内部 `reload-command` 等路径可清 Skill 缓存；未核实 SIQ 可调用的公开重载 API |
| `main/server.js:86762` | 此安装版本桌面列表的项目扫描使用产品数据目录名（默认 `.workbuddy`），与 bundled CLI 的 `.codebuddy` 不同；用户目录一致 |

内容身份：`workbuddy-paths.js` SHA256 为 `6ace7c90a1f783b7430bf09e94668394bfa96177c2911486844022cff5ed3f52`；`server.js` 为 `f396eb18957eacbe584282d8b5a7177a7ea3f4daa3070e4c7fa5eba3b034ae8b`；bundled CLI 为 `eb018e35d80673db02ebdaa7547b72f43d130d660c9c907c338d35e2f7b42ff7`。这些是 WorkBuddy 自身分发物，不能用独立 CodeBuddy 宿主测试替代 WorkBuddy 证据。

### 1.2 能力边界

两种正式目标分别为 `<WorkBuddyConfigDir>/skills/<name>` 与 `<registeredProject>/.codebuddy/skills/<name>`。不为迁就桌面列表另写 `.workbuddy/skills` 副本，不修改闭源程序。项目 Skill 的实际加载应由 WorkBuddy 原生项目任务核验，桌面列表缺席和执行端加载分别记录。

安装成功只表示文件已按签名清单发布。自动重载、原生启用、模型选用及逐调用因果归属均不能由目录存在推导。新任务/原生重载后须分别读取实际宿主证据；本规格不增加私有 RPC、后台轮询宿主数据库或账号读取。

## 2. 服务端目标模型

### 2.1 宿主实例与安装目标分开

保留 `instance_id=hi-…` 和 `agent_id=hri-…` 的既有运行身份语义。新增安装目标 `target_id=sit-<64 lowercase hex>`，不能把项目目录派生成一个冒充 WorkBuddy 配置实例的 hi-ID。

管理只读 `GET /v1/skill-installation-targets?instance_id=<hi-id>` 返回新 `local-skill-install-targets/v1`。结果由服务端根据唯一 WorkBuddy 实例、显式已登记项目和原生路径检查产生；最多 1 个用户目标加既有最多 16 个登记范围中的项目目标。请求不能提供 platform、目标绝对路径或权限摘要。条目给出 target_id、instance_id、platform、scope（`user`/`project`）、脱敏 root/目标显示、filesystem_profile，以及可用性/固定错误类别；列表不创建目录、不授予写入权限。

用户根复用 `server.workBuddyRoot()`：只认服务自身 `WORKBUDDY_CONFIG_DIR` 或 Home 下 `.workbuddy`，不新增 CODEBUDDY 环境回落，不从浏览器 OS、hook cwd、登录数据库、模型参数或进程搜索推测实例。自定义根须与实际 WorkBuddy 启动配置一致。跨产品同根或同 ID 歧义仍拒绝。

项目候选复用现有管理流程保存的 `state.DiscoveryRoots.ProjectDirs`；`SkillDirs`、一次扫描请求的 cwd、当前网页展示路径不是项目安装授权。首次进入项目安装时，UI 引导用户通过已有目录登记流程选择项目，再刷新目标列表；安装确认仍单独明确同意写入。不得扫描全部磁盘或读取项目普通文件以发现目标。

`target_id` 对域标记 `workbuddy-skill-target/v1`、instance_id、scope、规范根定位摘要的 canonical 对象做 SHA256。目录替换不应悄悄成为同一旧计划的新目标：定位 ID 可稳定，物理身份必须由签名计划另行固定。不同 WorkBuddy 实例下相同项目路径得到不同目标 ID；发布时仍以实际目的地锁和排他创建阻止相互覆盖。

### 2.2 Plan/v2 的目标绑定

保留 v1 的公共字段，新增闭合 `target_ref`，包含：

- `target_id`、`scope`；平台恒为 WorkBuddy，instance_id 仍来自外层计划。
- `filesystem_profile` 恒 `windows-local-drive/v1`。
- `root_locator_digest`：用户配置根或登记项目根的规范定位摘要。
- `root_identity_digest`、`config_root_identity_digest`：现场查询到的根及宿主配置根身份，复用 runtimepath 的 Windows 身份域。
- `existing_parent_relative_path`、`existing_parent_identity_digest`：预览时最深已存在的固定目标父目录。用户级只能为 `""`/`"skills"`；项目级只能为 `""`/`".codebuddy"`/`".codebuddy/skills"`。

现有 `target_locator_digest` 继续表示最终 Skill 目录的定位摘要；v2 定位字节规范和域在合同样例中固定，不改 v1 历史算法。目标显示只供审阅，不能用于解析、授权或验签替代。不得对已签名路径补盘符、改斜杠或做 Unicode 归一化。

stage-create/v2 新增 `target_id`；保留 instance_id、请求身份和明确的目录名，其余目标信息全部服务端派生。v2 身份输入必须包含新请求版本和完整 target_ref，防止同一 request_id 在 user/project、项目 A/B 或根替换后重用。相同请求复用不续期，变化拒绝。v1 不接收 target_id，不为 WorkBuddy 隐式生成默认用户计划。

### 2.3 路径与创建约束

限定实际本地 Windows 盘符，使用现有 Windows 路径/profile 检查；拒绝 UNC、设备、ADS、相对、尾点/尾空格、保留名、重解析、大小写别名、无效 Unicode 和父链身份改变。沿用现有目录名、文件数、总量、暂存数量与时间预算。

目的地由 scope 的固定布局构造，不靠调用方相对路径拼接。对配置根、项目根和已存在父目录在预览、提交、恢复、检查及运行验证时按签名身份复验；只看字符串前缀不够。`.codebuddy`/`skills` 缺失时在已确认事务内按固定深度创建，用现有归属记录/排他发布机制记录本次创建对象；已有父目录不改 ACL、不写所有者标记、不清理其中未知配置。

同 profile 私有操作材料继续使用现有 `.siq-agent-security-installs/<sin-id>` 布局。项目操作材料置于项目根的同名私有目录，位于原生 Skill 扫描根之外；拒绝未知或不安全的同名元数据目录。不能把备份放进 `.codebuddy/skills` 使旧版本继续被自动发现。清理仅限事务拥有且身份/内容未变的对象；创建与归属发布间崩溃留下的未知空目录保留并报告。

Plan 的预览锚点永远按保存的 `existing_parent_relative_path` 现场复验，不能在安装器创建新父目录后改签计划，也不能机械地要求当前最深父目录仍等于旧锚点。v2 安装器每次创建缺失的固定中间父目录后，在现有本安装私密操作目录排他追加 `local-skill-install-parent-fact/v1`；最多两份，分别签入 `install_id`、`claim_signature`、`relative_parent`（仅 `skills`、`.codebuddy`、`.codebuddy/skills`）、`identity_digest`、`recorded_at` 与 `signature`。后续发布、检查、更新、移除、恢复和运行验证都复验原锚点及这些新父链事实。事实缺失、签名/身份不符或归属冲突拒绝，不把当前目录反推为本安装所建；创建后尚未发布事实即崩溃的目录保持未知并保留。v1 不新增或读取此事实，也不改变旧事务语义。

## 3. 版本化合同与旧签名

### 3.1 必须新增的合同闭包

下列现有 v1 全部保留原文件、常量、签名字节和样例；对应新增 `.v2.schema.json`：

| 安装合同 | 更新合同 |
| --- | --- |
| `local-skill-install-stage-create`、`local-skill-install-plan`、`local-skill-install-plan-created` | `local-skill-update-comparison` |
| `local-skill-install-claim`、`local-skill-install-record`、`local-skill-install-view` | `local-skill-update-plan`、`local-skill-update-plan-created` |
| `local-skill-install-catalog`、`local-skill-install-inspection`、`local-skill-install-removal-view` | `local-skill-update-claim`、`local-skill-update-view` |

这 14 个构成 Plan 引用闭包，不能只换最外层 schema_version。另新增上述 `local-skill-install-targets/v1` 及复用的闭合 target_ref 定义/样例。catalog/v2 可明确接纳 record/v1、record/v2 混合，旧 catalog/v1 不扩引用；其他包装按内部实际版本选择，拒绝 v1 外壳夹带 v2 对象和任意混搭。

Windows Grant/v2 还要求新增 `local-skill-install-runtime-readiness/v2` 和 `local-skill-import-permission-created/v2`，因为现有这两份响应只引用 `grant.schema.json`（v1）。首次 import draft 可仍是 Grant/v1；原权限准备请求在 resources/v2 之后重试读回 Grant/v2 时，也必须返回正确新版包装。update-comparison/v2 与 removal-view/v2 的 Grant 引用同步支持实际 Windows 版本。

以下字段/语义不变即可保留 v1：install 的 apply、recover、operation、owner、remove、removal-claim、removal-result、activate、activated、runtime-binding；update 的 stage-create、compare、commit、recover、result、check、check-result、source-save、source-disable、schedule、schedule-view、schedule-run、schedule-run-result；import permission create/source；SEC、SEC revoke 和管理 issue/revoke。它们通过计划/claim 签名间接绑定新目标，不得绕过新记录回读。此次不把实例权限激活改成项目执行隔离，因此不新增 runtime-binding 字段。

### 3.2 字节兼容和持久化

当前 `record.go` 以 typed JSON → canonical JSON 生成签名，并要求持久原文与 typed round-trip 逐字节相等。实现须按 schema 分支解码/签名；可采用独立 wire 类型或明确受版本约束且 `omitempty` 的字段，但不能让 v1 多出零值 key、null、空对象或新的身份域。所有 nested claim、update plan/claim 的旧字节也要保留。

v1 的 Plan.identity/request 算法原样保留；v2 明确签入 target_ref。更新 `replacementPlan` 必须继承旧计划的 target_id、scope、profile、根定位/身份和配置根身份，不能重新解析成当前默认用户根。先完整复验旧计划锚点与其父链事实后，新计划的 `existing_parent_relative_path` 和 `existing_parent_identity_digest` 可推进到旧计划或已验签 parent-fact 覆盖的更深现存父目录；不退回、更换同级目录或采信未经旧事实链验证的目录。该推进先签入新计划再产生新 claim，不改旧 Plan 或复用旧 claim 写入新事实。最终 Skill 定位、目录名与宿主实例保持不变。旧 v1 安装仍按旧语义更新，不自动迁成 WorkBuddy 或项目目标。

新记录只新建/追加，走现有 statefs/privatefs 和 N01 状态门禁。旧二进制遇 v2 不得误读、清理、恢复或激活；未知记录必须明确不可用。以既有消费者拒绝证明兼容边界，不假设升级 schema 名即可防止旧写入。若发现旧消费者可接受或操作新记录，必须在发布前补现有 N01 兼容屏障，不能重签历史记录绕过。不得重构状态协议或另建后台服务。

## 4. 完整业务链

### 4.1 导入、批准、安装

复用固定导入 → PermissionAdmission/BuildImported → 人工资源编辑/批准 → 安装预览 → 明确 apply。`skill_import_permissions.go` 当前也经过拒绝 WorkBuddy 的 `resolveSkillTarget`，需分开“宿主身份解析”和“安装 scope 解析”；导入 Grant 仍绑定唯一宿主 agent_instance，不把项目 target_id 写进旧 subject。

WorkBuddy Windows 的导入 Grant 在 resources/v2 中显式确认 Windows profile；保留 Skill/source、审阅版本和原批准语义，不用普通 instance-draft 替换导入来源，也不删除 Skill 字段绕过安装校验。批准前发现、资源事实和安装目标各自校验；安装授权只允许确认的内容发布，不扩大运行资源权限。

既有 `grant/v2` 合同已定义可选 SkillRef，本增量无需改变其 wire 版本。Windows profile 实现只额外接纳精确 `adm-si-<64 lowercase hex>`、受管 `hri-<32 lowercase hex>` 主体且 SkillRef 完整的导入授权；不接纳普通 Skill Grant、不把保留导入来源的缺失 SkillRef 当实例基线。该形状本身不是来源证明：管理资源编辑和批准均须按原导入锁复验持久化准入、固定副本，以及 Grant 与准入的 Skill ID/版本/内容摘要完全对应。只有当前 pending、签名有效、明确资源确认和状态门禁通过才能产生新 pending 修订；保留原 Skill 与来源，普通 deploy/effective 仍拒绝导入授权，安装激活及 SEC 约束不变。撤销和历史验签不依赖源文件仍存在。

stage、Load、apply 均重新读取批准版本/签名、权限摘要、完整导入副本和目标身份。排他 claim 先于目标写入；写后完整读回仍产 `installed_unverified`、`runtime_verified=false`。超时或响应丢失先 GET 原操作，不自动重复写入。

### 4.2 更新、移除和恢复

更新沿用 compare → approved candidate → stage → confirm → revoke/remove previous → install candidate → result；不能在更新请求改 scope、instance、target 或根身份。迁移到另一目标是另一次安装及明确移除，不伪装原地更新。保留原期限、并发/CAS、审计、内容读回和恢复语义。

开始移除后旧运行绑定立即不可用；失败或中断不复活旧授权，新版文件安装也不自动恢复 identity/SEC。用户改动、未知对象和归属不明目录保留，分别报告 revocation_pending/cleanup_pending/recovery_required。已完成事务重试只能读历史，不删除后来出现的新目录。

源检查与定时检查继续仅形成候选，不自动批准/更新。计划签名已改变会使既有 schedule 摘要相应变化，既有字段足够，不为 WorkBuddy 新造另一轮询器。

### 4.3 原生发现、优先级和缓存

inventory 新增显式 WorkBuddy 配置根输入，和 server 使用同一已核验根；不能继续只扫描静态 Home/.workbuddy。对已登记项目加入 `.codebuddy/skills` 的 WorkBuddy 能力关联，同目录也属于 CodeBuddy 时记录共享物理来源，不能因扫描先后把宿主混为同一产品或两次读回当两份证据。

同名 Skill 优先级按原生项目优先规则展示。安装目标内既有目录/大小写冲突继续拒绝；发现已知项目与用户 Skill 同名时提示实际选用可能被覆盖，不能悄悄删除另一版本。扫描登记之外的未知项目不得为了证明无冲突而遍历。缓存没有经过实际加载确认时保持未验证，不自动写启停设置或调用内部 reload-command。

## 5. 运行权限与可信归属

复用现有安装内容绑定 activate → identity/create-v2 → 原生 session enroll → 管理 SEC issue → decide/observe。安装导入 Grant 保持 approved 的专用提交语义；普通 deploy/effective 入口继续拒绝导入授权。每次运行仍复验当前 Grant、profile、安装完整内容及目标根身份；任何 Authority 缺口在 block/warn/audit_only 全部 hard deny，不缓存成功、不扩大 WorkBuddy 4 秒总 HTTP 预算或安装内容校验 5 秒预算。

SEC/v1 可以继续使用：`install_id + claim_signature` 串联 claim/v2 → Plan/v2 → target_ref。`skillcontext/store.go` 当前硬编码 record/v1 的 Issue/liveInstall 要按版本完整验证；不能只放宽 schema 字符串而跳过签名、当前成功安装状态、平台/实例、Grant 和目标内容。身份/登记会话继续来自 WorkBuddy 自身原生 session_id 派生，模型提供 Skill 名、cwd、generation_id、安装摘要或 SEC ID 均不替代它。

用户级、项目级均采用已有 `controlled_session` 语义：管理员明确选择一个安装记录，将整个已登记会话绑定给它。UI 必须写明“会话全部调用归并到该 Skill，不含逐调用因果”。项目 scope 描述安装位置，不是自动限制执行所在项目的沙箱；执行目录边界由另外批准的 Windows Grant/Intent 资源决定。相同会话已有 SEC 时拒绝另一个 Skill 的并行替换，更新后需重新明确准备/签发。

没有 SEC 的 import Skill Grant 继续 unknown + deny。有效 SEC 可以证明受控会话归属，不能证明 WorkBuddy 当前项目的自动加载选择。项目切换即时隔离和逐调用 Skill 因果不属于现有可信字段能力：不得把 hook cwd 升为 Authority，也不为基础项目安装额外要求一个不存在的原生 Skill 字段。若将来实现更强项目执行约束，应另立可信项目上下文合同；本次不偷改 SEC/v1 的含义。

## 6. UI 与接口接线

在原个人安装旅程内扩展，不新增平行工作台：

1. ImportPermissionPanel 加入服务端支持的 WorkBuddy 实例；使用可信平台能力，不用浏览器 OS 猜测。保留 Hermes/OpenClaw 和 macOS legacy 行为；本规格不宣称 macOS 新受管安装。
2. SkillInstallPreview 在批准后读取目标列表，显式选择“用户级”或已登记项目；预览显示 scope、目标、来源摘要和权限。选择变化废弃原确认，不能默认把失效项目退回用户目录。
3. API/类型/形状验证器以 schema 判别 union；各计划、记录、更新与安装结果严格核对 instance_id、target_id、scope、来源、签名关系。API 出错或跨目标响应撤下旧成功状态。
4. InstalledSkillsPage、安装结果、更新差异、移除确认与恢复页沿用同一 target_ref 显示；更新不提供改目标选择。保留旧记录查看与深链恢复。
5. InstalledSkillProtection/实例接入显示 Windows Grant/v2 和正确 readiness/v2；实例权限已准备、受控会话归属、宿主实际加载分别说明。安装页不得把 prepared/controlled_session 改写为逐调用 Skill 识别。
6. 项目重载说明采用用户可操作的 WorkBuddy 新任务/原生项目操作，保留本机桌面列表差异提示；不自动触发模型、闭源命令或付费调用。

## 7. 可并行实现的文件所有权

先冻结合同字段和样例，再分工；同一文件单一写入负责人。以下是待实施清单，本次不改这些文件。

| 负责人边界 | 文件/职责 |
| --- | --- |
| 合同与规格 | `packages/contracts/` 第 3 节闭包、targets/target_ref、fixtures；`testdata/contracts` 对应静态样例及 Python schema 登记；公共 dev-spec、N05/WorkBuddy 规格只加准确引用与过时状态修订 |
| 安装库 | `internal/skillinstall/{stage,record,target,operation,publication,inspection,removal,runtime,update_compare,update_stage,update_operation}.go` 与新版本/目标辅助文件；维护读签名、target resolve 接口、scope 布局、父链事实、单一事务复用；update_source/scheduler 只在必要版本调度处改，不改远端检查语义 |
| Server 与发现 | `internal/server/{skill_target,skill_import_permissions,skill_install,skill_update_operation}.go`、新 targets handler/注册；`server.go` 仅接线；`internal/inventory` 的配置根/项目关联；现有 DiscoveryRoots 不改变登记即观察的语义 |
| 运行归属（与安装库协调） | `internal/skillcontext/store.go` 的 v2 记录读取；现有 runtime identity/state Grant 验证入口只补真实必要兼容；复用 SEC/v1，不修改 WorkBuddy hook 字段或会话算法 |
| Web | `local/{types,api,importPermissions,skillInstall,skillInspection,skillRemoval,skillRuntime,skillUpdate}.ts`；`components/{ImportPermissionPanel,SkillInstallPreview,SkillInstallationResult,InstalledSkillProtection}.tsx`；`pages/{InstalledSkillsPage,SkillUpdatesPage,GrantsPage}.tsx` 的必要接线与现有验证器测试；实际 embed 在实现收敛后统一生成 |

库与 server 接口必须先约定：v1 仍可按 instance_id 调旧 resolver；v2 用 `(instance_id,target_id)` 查询完整 Target，后续已签计划解析不能丢 scope。目标枚举是管理只读接口；安装库不读取 UI/请求原始目录，server 不复制签名或安装状态机。若共享 `Target` 增字段须先检索位置式字面量，避免跨包隐式字段错位。

## 8. 实现后的必需验证与有界结束条件

本轮规格阶段不运行下列测试；功能完成、单次审阅收敛后再执行，固定候选与失败证据分别保留。

| 必需正向 | 必需负向/兼容 |
| --- | --- |
| WorkBuddy 默认及自定义配置根用户级安装；登记项目级安装（父目录已存在/缺失） | CodeBuddy 冒充、同根多宿主歧义、未知 target、未登记项目、请求直接路径/cwd、用户级与项目级互换 |
| 新 Plan/claim/record/update 的 schema 样例和实际 Go 输出一致 | v1 原签名/ID 固定向量不变；v1 外壳夹 v2、错误 target_ref、重复/null/尾随 JSON；旧程序不消费 v2 |
| 正式 HTTP 导入→Windows resources→批准→两种 scope 的 stage/apply/inspection | 明确确认缺失、未批准/撤销/过期/修订 Grant、源变化、目标根/祖先替换、大小写别名、junction/UNC/ADS、任一模式 Authority hard deny |
| 更新、移除、故障恢复与响应丢失后的 GET 查回 | 跨项目更新、跨实例/安装借用绑定、目标重定向、并发相同物理目的地、未知用户改动不删、失败不复活旧授权 |
| prepared→WorkBuddy 专属身份→原生会话→管理 SEC→允许与越权拒绝 | 无 SEC、伪造 claim/摘要/cwd、跨会话、换 Skill/版本、撤销与失联；不宣称项目切换隔离；4 秒/5 秒预算保持 |
| UI 用户/项目选择、旧新记录混合、明确确认与刷新恢复 | stale 响应、selection 变化、服务端 capability 缺失、默认回落用户目录、普通 token 执行管理写入 |
| 最终 WorkBuddy 自身真实用户级与项目级加载、更新、撤权/移除结果 | 不使用 CodeBuddy 独立 CLI或组件夹具代替桌面证据；同名覆盖和缓存未更新不得报已加载 |

完成标准：上述两类目标沿同一正式产品路径可安装、检查、更新、移除和恢复；旧记录/签名可读且安全边界不变；运行权限与 controlled_session 归属接通；必要定向组件/HTTP/UI验证及固定候选原生证据完成，脱敏材料可审阅。原生验证涉及付费模型时遵守已有授权范围，额度未授权或宿主能力差异须记明确未完成项，不能用用户级通过、仅文件安装或文档调查充当项目级/整体完成。源码实现、组件结果、原生事实三个层次分别登记。
