# DGX Spark + Hermes + OpenShell 标杆优化执行台账

**E171 创建/监督结果未保存的保留与核对。** 两轮实际 API SIGKILL，分别保留 creating 或空 invocation；同库重启后自然租约到期，ready=false、原行和 owner 保留、无自动重放/提前 released。诊断使用故障时独立记录并再次核验的原实例结果补齐后，API 自动完成 startup 收尾。32 项测试、Ruff、两轮真机证明通过；临时资源回收、主服务及预览未变。生产恢复组件未修改，人工核对前提与剩余其他故障点保留。[报告](business-unknown-startup-e171-20260923.md)。

**E170 沙箱创建后的早期 API 崩溃。** 诊断在原 create 成功后、自身 SIGKILL 前持久记录实际实例，父进程确认真实沙箱存在且身份/监督/endpoint 均未创建；普通 API 同库重启后等待原租约自然到期，自动 startup finalizer released、原行 authority_lost，未恢复执行。48 项诊断测试通过，临时库/进程清理，主服务和预览身份未变。只关闭该已知实例窗口，未知创建、缺失 invocation 及其他原门禁保留。[报告](business-early-crash-e170-20260923.md)。

**E169 退出清理失败自动重试。** 修复只重复读取失败状态而不重试的缺口；仅清理句柄对原明确失败单元执行一次有界 recover，前后核对并新建私有证明。189 项组合、16 项诊断测试通过。实际模型输出后 API SIGKILL 与独立身份服务中断，使原退出清理及扫描失败；恢复依赖后 API 自动终结原执行、撤销子身份并释放资源，原失败记录保留。原主服务、模型/桥及预览未重启；临时库和进程清理。[报告](business-cleanup-retry-e169-20260923.md)。其他原目标门禁保留。

**E168 本机 API/Web 预览部署。** 新页面 15173 连接新 API 18084，真实库结果路由已加载，匿名读取 401/no-store；桌面/手机登录页通过。实际停止并重启预览，旧 API 18081 始终保持原进程。预览不接管恢复，保留必需恢复门禁；主服务切换、真实业务账号及其他原门禁仍待验收。[报告](business-preview-delivery-e168-20260923.md)。

**E167 实际业务库迁移。** 只读现场审计确认唯一缺失 022/023；完整私有备份成功恢复并先在恢复库迁移，通过后才对 API 实际使用的 siq_app 应用。官方审计 current，历史账本不变、重复 runner no-op，演练库清理。旧 running 记录租约过期但保留；API 身份未变且健康 200，新结果路由仍未加载，代码与 Web 部署继续。[报告](business-database-delivery-e167-20260923.md)。

**E166 在途业务撤权完成。** 修复初始 SSE 未逐事件复核授权的缺口，负向测试先复现后通过；真实模型输出后 HTTP 撤销业务 grant，原流失权、独立读取 403、无成功 done，约 18.7 秒后原运行 failed、finalizer released、旧子凭据 401、资源回收。相同源码正常 SSE 完整成功，262 项组合回归通过。两轮临时资源已清理，在线服务和冻结候选未变；其他故障窗口、生产集成、原生 CI 与签名发行仍未完成。[报告](business-grant-revoke-e166-20260923.md)。

**E165 原业务 API 崩溃门禁。** 真实模型输出后对自有候选 API 执行 SIGKILL，同库重启后等待原租约实际到期，原执行 `authority_lost`、正式 finalizer released、子凭据 401、运行资源回收通过。141 项相邻回归通过；临时 API/数据库/daemon 已清理，既有服务未重启。在途 grant 撤权、其他故障窗口、生产 IAM 与原生 CI 仍待验收；不改变客户端冻结范围。[验收报告](business-api-crash-e165-20260923.md)。

**E163 客户端开发收尾。** 固定本地候选提交 `fd02384d6de5f96a849f9d04bbfbfaff38cf6148`，独立源码 44 包、前端重建一致和四平台发行构建通过；主工作树保留，未推送/发布。待具体受控签发入口后执行签发与签名安装/升级验收；本轮不再加功能，原总目标后续项仍未完成。见 [收尾与交接](client-release-freeze-e163-20260923.md)。

**E162 既有发现故障验收。** E162 已修复不可读目录被预览接受的问题，真实后台发现故障/恢复 9 项、既有双框架接入 53 项、Go 44 包及四目标构建通过；提供更新体验包，正式签名安装/升级仍待完成。 见 [修复与交付记录](ux-discovery-recovery-e162-validation-20260923.md)。

**E161 本地体验候选收尾（2026-09-23）。** E161 已完成 DGX Spark 后台接入体验候选：修复首次 setup 身份初始化和 Hermes 原生卸载后重装；真实后台接入浏览器 53 项、Hermes/OpenClaw 原生各 12 项及各 8 项生命周期检查、Go 44 包与四目标构建通过。新体验包已解压验收。此轮候选完成，正式签名安装/升级、在线业务部署和原总目标缺口仍独立待办；不扩展本轮功能。 见 [交付说明与结束线](ux-background-setup-e161-validation-20260923.md)。

更新日期：2026-09-23
目标状态：`active`
权威方案：[DGX Spark + Hermes + OpenShell 标杆优化方案](../dgx-spark-hermes-openshell-flagship-optimization-20260921.md)

## E160 运行目录完成，转入交付收口

E160 已完成业务端固定运行目录、准确详情定位、返回分页与刷新后实时授权；API/迁移 125 项、合同 276 项、Web 544/135 项及真实浏览器 15 项通过。提供 Linux ARM64 独立状态体验包，已验证解压启动/配对/控制台/停止；它不是正式签名安装包，也不包含研究业务更新部署。用户要求尽快结束，本轮起停止扩展功能，后续集中现有候选交付及安装接入验收，增强项保持未完成清单。见 [E160 验收](ux-business-result-history-e160-validation-20260923.md)。 总目标仍 active。

## E159 业务端生成回复查看页

E159 已接通研究业务端聊天回复→运行结果页→实际授权 API，显式确认正文、关闭/刷新/撤权与登录返回可用；浏览器 12 项、Web 单测 544 项及行为 119 项通过。关联只取结构化运行与服务端审计/会话精确匹配；持久历史目录、安全控制台业务连接、正式报告与提交前恢复继续。见 [E159 验收](ux-business-result-page-e159-validation-20260923.md)。源码未部署，总体 active。

## E158 空库编号迁移链修复

E158 已修复空库/v008 升级在历史 015 缺前置表的失败：原迁移命令自动执行独立校验的基线，同事务记两本账，历史 SQL/checksum 不变；真实 PostgreSQL 并发、回滚、存量兼容及原命令/审计通过，组合回归 273 项全部通过，无排除。源码未部署；提交前恢复、正式产物与控制台业务连接继续。见 [E158 验收](ux-business-install-baseline-e158-validation-20260923.md)。总体 active。

## E157 业务结果持久归属

E157 已补齐终态生成回复的持久归属、实际清理路径保存和跨进程重新授权读取；研究回归 260 项、合同 275 项通过。完整空库迁移发现历史 015 缺少 user_artifacts 前置表（失败已保留，最终回归 1 项显式排除），安装基线修复待办，不放行部署；提交前崩溃恢复、正式产物、业务连接与报告导航继续。见 [E157 验收](ux-business-result-retention-e157-validation-20260923.md)。总目标 active，源码候选未部署。

## E156 业务结果独立读取边界

E156 已完成研究 API 独立业务结果读取边界及三份跨仓合同：准确运行、当前业务授权、显式确认、读前后复核和有界正文；研究 API 108 项、合同 275 项通过。仅表示生成回复，尚未连接控制台或核验正式发布；持久运行/产物归属、业务连接和报告导航继续。见 [E156 验收](ux-business-result-access-e156-validation-20260923.md)。整体 active；正式报告子项不关闭，已安装应用和在线业务服务未改。

## E155 OpenClaw 原生输出与双框架回归

E155 已完成 OpenClaw 2026.9.5 原生输出到页面 12 项，以及同候选 Hermes 12 项、输出页 11 项回归；同路由新宿主会话不复用采集授权。修复重复正文及过多字段展示，正文优先、原字段可核对，Web 290 项和双构建通过。正式业务报告、名称/生命周期与安装生产验收继续。见 [E155 验收](ux-runtime-output-openclaw-e155-validation-20260923.md)。总目标保持 active，未改已安装版本及后续安全清单顺序。

## E154 Hermes 原生输出与正文显示

E154 已完成真实 Hermes 0.21 工具分派/钩子→授权采集→重启→页面确认查看，12 项原生浏览器及 11 项输出回归通过；修复文件输出多层 JSON 转义，正文优先、原字段可展开，Web 287 项及双构建通过。OpenClaw 同类验收和正式业务报告继续。见 [E154 验收](ux-runtime-output-native-e154-validation-20260923.md)。本批不改变 SEC 后续顺序或已安装发行版，总目标保持 active。

## 当前结论

用户体验已按 2026-09-23 用户指示提升为当前优先交付。新增
[个人与企业易用性任务书](user-experience-onboarding-taskbook-20260923.md)，包含
UX-02–UX-11 与 ENT-UX-01–ENT-UX-04；原 17 项/约 75% 只反映此前技术范围，
不代表新增体验要求已完成。产品主线收敛为框架→角色→Skill→权限→运行记录与结果，
操作必须真实执行、持久读回和刷新一致，不能仅有可点击按钮。

2026-09-23 用户再次明确顺序：优先继续原开发任务；外部检查采纳项已经纳入
[任务书 SEC-F01–SEC-F10 后续清单](user-experience-onboarding-taskbook-20260923.md)，
不插队替代当前 UX 旅程。E151 真实页面到沙箱执行候选验收已通过，见下文；
Edge 重定向本轮仅检查，未修改实现，SEC-F03 仍待办。

E153 已接通运行详情的已采集输出目录与明确确认读取；按验签活动与历史身份/会话/绑定选取，旧 task-only 记录不混入。关闭/刷新清除、迟到响应、读取失败、快照变化和删除后拒读通过真实浏览器 11 项；原结果回归 32 项、Web 284 项、API 1067 项、Go 44 包及四目标构建通过。正式业务报告、生命周期与原生宿主钩子到页面验收继续。见 [E153 验收](ux-runtime-output-view-e153-validation-20260923.md)。

E152 补齐运行输出来源基础：原生采集将已验证身份/会话/绑定的哈希与密文一起认证保存，内部输出查询按完整运行元组匹配；旧任务级 v1 不猜测归属。Go 44 包、定向 race、跨语言合同 269 项与四目标构建通过。用户可见输出目录、显式读取和业务报告入口仍待接续，不将此基础改动计作完整结果体验。见 [E152 验收](ux-runtime-output-provenance-e152-validation-20260923.md)。

E151 已完成页面到真实沙箱的允许/撤销下发、独立读回、刷新及同键不重复部署，行为对照 HTTP 200 → 明确 403 → 回滚后 200；12 项现场验收通过。修复 Python/Go 撤销最后一条网络规则的空字段读回误报，保留已空 no-op 和完整摘要校验。API 1063 项、Go 44 包/vet/race/四目标构建通过；自有沙箱已清理，原网关登记未变。API 仍仅声明配置读回；业务结果、人工结案/安全重提、主动核验与安装生产验收继续。见 [E151 验收](ux-openshell-live-deployment-e151-validation-20260923.md)及[证据](../evidence/flagship-optimization-20260921/ux-openshell-live-deployment-e151.json)。

E150 已补部署请求持久恢复：执行前保存唯一请求/部署/审计，重复请求只读返回，刷新或丢响应后找回准确记录，预占后撤权复查拒绝。新增浏览器 17 项、审批回归 12 项、API 1060 项、Web 281 项通过；隔离 PostgreSQL 行锁/恢复/审计/迁移 11 项通过。0017 有记录时禁止删表降级；未知执行不会自动释放或重放。真实沙箱写入与行为验收、人工结案/安全重试继续。见 [E150 验收](ux-deployment-recovery-e150-validation-20260923.md)及[证据](../evidence/flagship-optimization-20260921/ux-deployment-recovery-e150.json)。

E149 已解除真实网关接入的目录上下文问题：完整 XDG 上下文下 HTTPS 握手成功，无需关闭 TLS 或修改证书。同步修复 Python/Go 网关版本解析和目录指纹，Python 读回保留真实方法/路径/IP 限制。真实预览 8 项、真实多网关浏览器 19 项、企业部署回归 16 项、个人结果 32 项，API 1050 项和 Go 44 包通过。原沙箱策略前后 revision/digest 一致，未执行策略写入；实际部署及持久恢复继续。见 [E149 验收](ux-openshell-live-preview-e149-validation-20260923.md)及[证据](../evidence/flagship-optimization-20260921/ux-openshell-live-preview-e149.json)。

E148 补齐部署预览、明确确认与提交重验：取消不下发，策略/目标/审批或执行端版本变化拒绝旧预览；修复后端错误码到中文提示的链路。新增浏览器 16 项、API 1026 项、Web 279 项通过，原流程回归通过。真实 OpenShell 只读握手遇到证书错误，未执行策略写入；持久恢复、生产并发及真实行为核验仍待办。见 [E148 验收](ux-enterprise-deployment-preview-e148-validation-20260923.md)及[证据](../evidence/flagship-optimization-20260921/ux-enterprise-deployment-preview-e148.json)。

E147 增加精确到单份变更的部署/审计读取，补齐部署审计对象 ID；失败、回滚、独立读回漂移/不可达不会被旧成功证据掩盖。修复 URL 查询参数变化卸载整页、丢失目标与待核对标记的问题；手机长记录窗口操作保持可见。新浏览器 **13 项**、原审批 **12 项**、工作台 **16 项**、两框架企业回归各 **28 项**、个人结果 **32 项**，API **1017 项**、Web **275 项**、Go **44 包**及四目标构建通过。dev/fake 下发任务不等同 OpenShell 执行；完整部署预览/持久重试与主动执行端核验继续。见 [E147 验收](ux-enterprise-change-execution-e147-validation-20260923.md)及[证据](../evidence/flagship-optimization-20260921/ux-enterprise-change-execution-e147.json)。

E146 增加完整有界策略审查、当前身份绑定快照、过时内容拒绝、明确批准/驳回与独立 GET 读回；响应丢失只核对，不直接重发。未填写项目折叠，移动端提供真实审查入口，按权限请求部署目录。审批浏览器 **12 项**、工作台 **16 项**、两框架企业回归各 **28 项**、个人结果 **32 项**，API **1009 项**、Web **273 项**、Go **44 包**及四目标构建通过。新 UI 门禁不替代旧接口兼容或部署执行证明；精确部署/审计读回、筛选/批量、生产 IAM 和安装仍继续。见 [E146 验收](ux-enterprise-change-review-e146-validation-20260923.md)及[证据](../evidence/flagship-optimization-20260921/ux-enterprise-change-review-e146.json)。

E145 增加只读验证身份上下文和企业默认工作台，按实际权限过滤导航/深链接，
角色职责中文说明、缺权联系路径与身份读取失败恢复落地；未扩展角色权限。
总览按新鲜心跳和本组织实际策略计数，前后端读权限一致。工作台 **16 项**、
两框架企业回归各 **28 项**、个人结果 **32 项**，API **994 项**、Web **271 项**、
Go **44 包**/vet/格式/四目标构建、Ruff 与空库迁移通过。
[验收](ux-enterprise-workspace-e145-validation-20260923.md)、
[E145 证据](../evidence/flagship-optimization-20260921/ux-enterprise-workspace-e145.json)。
签名 token 为隔离 HS256 夹具，非生产 IdP/JWKS/登录链验收；角色分配、所有企业
写按钮、完整审批与安装分发继续待办。ENT-UX-02 部分完成，总目标 active。

E144 将企业发现候选接续到中文用途与资产确认，权限投影控制候选操作及策略创建
入口；先读状态、写后读回、响应丢失保留输入并只读核对。修复过时页面可驳回已确认
资产的问题，证据失败不冒充为空；小屏改为完整卡片。最终 Hermes/OpenClaw 各
**28 项**真实 API/原生 Connector 浏览器、个人结果 **32 项**，API **985 项**、Web
**269 项**、Go **44 包**/vet/格式与四目标构建、迁移与 Ruff 通过。
[验收](ux-enterprise-candidate-review-e144-validation-20260923.md)、
[E144 证据](../evidence/flagship-optimization-20260921/ux-enterprise-candidate-review-e144.json)。
ENT-UX-02 仅部分完成：生产登录、角色工作台与负责人目录仍待办；候选确认不是权限
批准，没有宣称全局幂等或并发隔离。总目标继续 active，原设备/业务服务与安装版保持。

E143 扩展企业环境列表为首次接入流程：最少信息创建、一次性码与标准输入命令、
实际注册/心跳/扫描状态和候选读回。真实上传暴露 Edge typed slice 无法规范签名，
已按实际 wire JSON 修复并验证篡改拒绝。Hermes/OpenClaw 原生 Connector 各 **15 项**
浏览器通过（共享检查不重复计数），个人结果回归 **32 项**，API **976 项**、Web
**267 项**，API Ruff、干净库迁移、Edge 测试/race/vet、Go 本地 **44 包**及两模块
四目标构建通过。隔离开发身份/SQLite/合成配置不代替生产 IAM、安装分发与原生
多 OS 旅程。见[验收说明](ux-enterprise-onboarding-e143-validation-20260923.md)及
[E143 证据](../evidence/flagship-optimization-20260921/ux-enterprise-onboarding-e143.json)。
ENT-UX-01 部分完成，总目标 active；真实环境服务和已安装发行版未替换。

E142 将结果核验结论、原因与下一步放在前面，每项要求直接打开同任务证据，
内部标识折叠；历史 hold 不再称实时待审批。证据模态支持显式刷新/重试，失败撤下
旧成功，并修复 summary 键盘焦点。最终同候选结果浏览器 **32 项**、双平台 **53 项**、
权限编辑 **20 项**通过，Web **264 项**、Go **44 包**/vet/格式、双前端构建及四目标
构建通过。真实隔离宿主文件观测与服务重启读回覆盖缺证、失败、冲突、核验通过；
不冒充原生模型报告。见[验收说明](ux-result-evidence-e142-validation-20260923.md)与
[E142 证据](../evidence/flagship-optimization-20260921/ux-result-evidence-e142.json)。
业务生命周期/名称/报告产物、企业向导和安装发行体验继续待办，总目标保持 active。

E141 将工具权限改为中文勾选，提供只收窄已有选择的只读资料方案与撤回，未知工具
不推断能力；高级输入保留。方案不写后端，保存仍需批准，目录/拒绝/批准条件独立读回。
修复卸载预览依赖无关身份及旧请求未取消导致的 busy；仅明确忙碌拒绝的只读预览最多
重试两次，安装/卸载写入不自动重试。最终同候选权限编辑 **20 项**、双平台接入
**53 项**、权限替换/卸载 **17 项**浏览器通过（有重叠）；Web **261 项**，Go
全模块 **44 包**/vet/产品格式、两种前端构建及四目标构建通过。
[验收说明](ux-permission-tools-e141-validation-20260923.md)、
[E141 证据](../evidence/flagship-optimization-20260921/ux-permission-tools-e141.json)。
原生 OpenClaw 文件工具拒绝与 Hermes 安装钩子阻断分别记录；权限替换中的 Hermes
原生命令只证明注册/卸载，判定探针为 HTTP。未更新发行版；UX-05/总目标仍未整体完成，
继续业务结果产物、权限审批表达、企业接入和发行验收。外部安全清单保持后续顺序。

E140 打通已登记项目 Hermes 角色、Skill、模型、接入与原生自检：登记一次项目，
扫描固定 `.hermes` / `agents/hermes` 布局与一级 profiles，所有入口共用实例 ID；
旧实例 v1 保留，显式项目列表使用独立 v3。真实研究项目 `siq_analysis` 只读发现通过。
最终候选项目浏览器 **26 项**、模型列表回归 **13 项**、Web **257 项**、Go 全模块
**44 包**/vet/聚焦竞态、Python 新合同 **1 项**、app Ruff 和四目标构建通过。
[验收说明](ux-project-hermes-e140-validation-20260923.md)、
[E140 证据](../evidence/flagship-optimization-20260921/ux-project-hermes-e140.json)。
真实安装、自检 allow/deny、五条回执和结果链接只在自建合成项目执行；真实研究配置未写。
补齐 CLI 库存的登记范围，并修复自动扫描刷新清掉刚返回模型结果的竞态；失败证据保留。
仍需首次指定项目根目录；任意布局、项目私有 OpenShell 上下文、多 OpenClaw 根、
原生凭据继承、权限简化和业务结果继续实施。原生发行验收未完成，总目标 active。

E139 补齐已登记 OpenShell 多网关选择：用户选网关→真实沙箱→读取策略，
从 PATH 发现 CLI 时复用既有登记，无需再手填网关名称/地址。选择刷新恢复，切换
清除旧结果，登记消失不回退默认；原生默认网关及服务执行客户端不变。
最终同候选显式配置浏览器 **18 项**、PATH 浏览器 **19 项**、原入口回归 **15 项**
通过（场景有重叠）；Web **257 项**、Go 全模块 **44 包**/vet/聚焦竞态、
Python 新合同 **1 项覆盖 5 合同**、app Ruff 与四目标构建通过。
[验收说明](ux-openshell-gateways-e139-validation-20260923.md)、
[E139 证据](../evidence/flagship-optimization-20260921/ux-openshell-gateways-e139.json)。
PATH 证明沿用测试进程已有 XDG 上下文，不等于自动发现项目私有目录；主入口构建
仍有 500 kB 阈值提示。UX-03/总目标保持 active，继续项目配置、原生凭据接续、
权限简化和结果产物；未更新已安装发行版。

E138 完成模型回答测试按钮→异步后端→状态读回/刷新恢复：同请求去重、并发拒绝、
配置漂移失效、回包丢失恢复和失败不自动重试均已验证。真实 Step 5 固定公开文本
回答通过；最终同候选回答浏览器 **22 项**、原模型列表回归 **15 项**、Web **255 项**、
Python **970 项**、Go 全模块测试/vet/产品源码格式与四目标构建通过。
[验收说明](ux-model-inference-e138-validation-20260923.md)、
[E138 证据](../evidence/flagship-optimization-20260921/ux-model-inference-e138.json)。
记录仅属当前服务会话；不证明原生工具/企业业务链或发行完成。模型默认配置与已安装
客户端未变，UX-03/总目标继续 active，下一步接续项目/多网关、权限简化和结果产物。

E137 补齐已有模型配置发现与显式服务检查：Hermes 模型声明、OpenClaw 默认/备用
配置、环境变量与私密文件凭据引用可复用；真实 Step Plan 列表包含 step-5-preview。
最终同一候选模型浏览器 15 项、OpenShell 15 项、权限/记录 49 项与前端 253 项通过。
列表匹配不代表推理验证，未改默认模型/既有服务/发行版。
[验收说明](ux-model-connections-e137-validation-20260923.md)、
[E137 证据](../evidence/flagship-optimization-20260921/ux-model-connections-e137.json)。
UX-03 继续处理多网关/项目配置接续、原生凭据继承与完整推理，不记整体完成。

E136 完成已有配置下的 OpenShell 发现→选择真实沙箱→策略读回，新增命名网关
mTLS 上下文适配，修复目录扫描打断策略读取的交互问题。最终真实网关浏览器 15 项
通过，前端 38 文件/251 项通过；独立候选、只读原网关，未升级发行版。
[验收说明](ux-openshell-discovery-e136-validation-20260923.md)、
[E136 证据](../evidence/flagship-optimization-20260921/ux-openshell-discovery-e136.json)。
多网关/项目配置自动接续与模型发现仍待办，UX-03 只记部分完成。

E135 运行列表增加时间与调用裁决筛选、最近记录排序，技术标识折叠；
筛选在完整验签结果上先执行再分页，观察回执不重复计为调用。修复详情刷新返回丢失
来源页码及时间 from 与旧页码参数重名的问题。
[验收说明](ux-activity-filters-e135-validation-20260923.md)、
[E135 证据](../evidence/flagship-optimization-20260921/ux-activity-filters-e135.json)。

E134 补齐自检到精确运行详情的实际入口：新增管理接口用全部已验签回执关联同一活动，
不受原回执接口前 500 条限制，不猜任务 ID。真实浏览器进入详情、刷新与返回筛选列表、
回执暂时不可用后的原位恢复通过；历史失效结果保持失效。
[验收说明](ux-runtime-record-link-e134-validation-20260923.md)、
[E134 证据](../evidence/flagship-optimization-20260921/ux-runtime-record-link-e134.json)。

E133 接续 Hermes 页面接入→原生自检：接入成功后按后端诊断提供精确实例验证入口，
刷新恢复同一检查，配置漂移失效、取消撤权及卸载均纳入实际浏览器验收。
本批使用真实 Hermes 0.21 CLI 和合成模型响应，不等于真实业务模型验收。
[验收说明](ux-hermes-native-journey-e133-validation-20260923.md)、
[E133 证据](../evidence/flagship-optimization-20260921/ux-hermes-native-journey-e133.json)。

E132 阶段候选完成接入内 Skill 检查及结果页面收敛：无需退出弹窗检查，隔离结论不能
起草权限，目录暂时消失后保留选择并可恢复重试，检查不自动授权。**49 项真实后端浏览器
检查、243 项前端回归与本地/企业构建通过**；补齐 OpenClaw 页面权限编辑、批准、接入、
停用及原生 2026.9.5 插件加载器/文件工具的目录内允许、越界与撤权后拒绝。Hermes
继续通过安装后适配器钩子验证。运行详情先看结果，调用/审计按需展开，无独立结果证据
仍显示未知；两平台实例筛选、详情与返回通过。原生测试入口变更及合成 UUID 缺失的
失败均保留，未放宽产品校验。未升级发行版、未重启用户服务；原生 Hermes、完整模型
会话/业务产物、统一环境发现和企业向导仍待办。[验收记录](ux-permission-journey-e132-validation-20260923.md)、
[E132 证据](../evidence/flagship-optimization-20260921/ux-permission-journey-e132.json)。

E131 候选已通过真实后端浏览器 **36 项检查**、前端 **35 文件/243 项测试**及嵌入构建。
首页自动发现、框架/角色/Skill 分类、Hermes/OpenClaw 连接组件安装与卸载、配置冲突
后的重新预览，以及 Hermes 检查→权限编辑/批准→接入→停用均可读回；安装出的
Hermes 适配器允许合成目录内读取、拒绝目录外读取，页面停用后阻止读取。实例入口可
打开对应运行记录、详情和结果状态，刷新及返回保留筛选。修复弹窗焦点、检查反馈隐藏
及 Hermes 框架被分类遗漏的问题。全部为隔离 HOME/合成数据，无接口 mock；原生宿主、
业务产物、OpenClaw 权限完整复验、发行包、OpenShell/模型统一发现与企业向导继续待办。
既有安装与服务未改动。[验收记录](ux-onboarding-e131-validation-20260923.md)、
[E131 证据](../evidence/flagship-optimization-20260921/ux-onboarding-e131.json)。

E130 已修复独立活动快照和 SSE 重连的企业授权复核缺失，隔离数据库先复现撤权/
过期仍能读取，再增加原 scope 与当前 grant 检查、逐事件复核及状态换代拒绝。
当前专项 20 项与相邻组合 86 项通过（重叠）；常驻 API 未加载，历史消息授权待办。

E128 v4 已通过真实模型输出后的 HTTP 取消：原执行 cancelled，API 自身 finalizer released，沙箱/监督器/forward 消失，旧子凭据 401；检查时诊断父身份仍有效。SSE 无成功 done，有两条 cancelled 通知，尚未去重。桥首帧 200、结束 502 表示流被中断，不算完整回答成功。v1/v2/v3 原失败及独立恢复证据保留；v1 只完成显式操作恢复，不算自动恢复通过。[E128 证据](../evidence/flagship-optimization-20260921/ml-02-business-cancel-e128.json)。

E129 已修复模型桥完整缓冲上游 SSE，逐个验证 model/事件边界后转发；锁 drain 改为默认 10 秒有界等待，超时拒绝，不宣称同步即时撤权。受控部署 v3 及批准 Docker 网络内真实模型、正确凭据 200/错误凭据 401 均通过；桥已重启加载新源码，主 API 和模型未重启。部署 v1 的验证失败与自动回滚、v2 改动前失败均保留。两项共享的当前回归为 **111 passed / 265 warnings**，不得跨证据相加。[E129 证据](../evidence/flagship-optimization-20260921/ml-02-model-bridge-stream-e129.json)。

当前关键路径：真实 API 崩溃/重启与业务 grant 在途撤权、失败 ExecStopPost 自动重试、独立 active/history 授权、其他宿主检索边界、真实 IAM/业务审批/事件及原生 CI。总体工程估算保持约 75%，目标 active，整体候选与生产门禁 false。

截至 E127，正常**流式与非流式**真实业务 HTTP 均已通过指定隔离候选验收。流式 SSE 的 run/session、模型标记、桥 200 与原数据库执行行匹配；API 自身完成资源回收，诊断清理只做复核。整体候选 false，当前关键路径为 API 故障/在途撤权、独立 active/history 授权、其他宿主检索隔离、真实 IAM/业务审批/事件及原生 CI。

截至 E126，**真实非流式业务 HTTP 正常路径已贯通**：独立 API 登录 → HTTP 合成企业授权 → 分析师 `/api/analysis/chat` → 正式 selector/builder → Hermes/OpenShell/Qwen → 模型标记与桥 200 → 执行行 succeeded → API 自身 finalizer released。当前关键路径转为流式 HTTP、API 故障/在途撤权、宿主其他检索隔离、真实 IAM/业务审批/事件及原生 CI。以下早期记录保留各批次当时的限制；E126 不代表生产放行。

Hermes 0.21.0 沙箱迁移已经完成，并作为后续安全纵链的冻结运行基线。新增的 Hermes required gate、AgentShield Runtime Identity 与受限 relay 已完成真实启动、状态、授权/拒绝探针和干净停止。NW-01 已新增签名数据分类、公开/机密双模板和真实 broker 证明。DT-01 已把 Broker Request Identity 升级为 v3，绑定短时业务授权快照与企业数据 scope。ML-01 进一步在隔离候选网关上完成机密级 Hermes 0.21 原生推理与 8006 本地模型路由撤销演练。FX-01 已把真实三格式报告、质量/事实核验、批准对象、不可变发布、原子当前指针、独立读回和 AgentShield 效果核验连成非生产闭环；工具伪报成功会得到 `conflicting`。HM-03 已增加 operator 子工具上限、恢复后身份重验、批准重试精确绑定和取消联动，并以 Step Plan 合成公开数据完成真实 Hermes 父子委派。OS-01 已区分 OpenShell 命令与 Hermes 业务 run，完成停止后写静默、未知 writer 隔离和重启恢复门禁。EN-01 已把真实业务授权快照、数据 scope、模型 route 与 run 生命周期投影为无凭据版本化事件，并由新 SIQ Connector 通过 Edge 子进程协议采集。BU-01 已把报告发布封装为 Hermes 原生 MCP 固定语义工具，完成单任务工作区、双摘要复核、不可信写批准、AgentShield 精确绑定、不可变发布和读回闭环。OC-01 已按实际 OpenClaw 2026.9.5 建立库存/受控支持档位，完成 20 个原生审批场景和同一报告发布动作的精确摘要门禁；Step 5 Preview 已以 SecretRef 配置为首 fallback 并完成公开合成探针。SP-02 已统一 6 个 OpenShell 资源档位，完成两台遗留 canary 的身份验证后换代、OpenShell 0.0.83 scoped-mount gateway 事务升级及两台新 Hermes 0.21 canary 重建；活动资源审计为 `operational_ready=true`。多槽位决策桥已升级为 `openshell-decision-relay/v2`，两个槽位使用不同 bridge 端口，2/2 状态和 2/2 边界探针通过。CI-01 已实现 DGX Spark 原生自托管硬门禁；aiohttp 修复现由冻结 0001 补丁、锁定 SOURCE_BASELINE 和受限容器 import 三重绑定，候选包六层仍通过。ML-02 新增五补丁 Hermes 0.21 的 Qwen 专用镜像，并在真实 OpenShell 候选沙箱证明认证健康、合成 run 到模型桥 502 的逐请求关联、候选 generation 的模型桥令牌先行撤销、合成企业目录隔离和严格 broker 的签名 scope 拒绝边界。当前 dirty worktree 与 8006 模型离线继续如实阻断 native pass；Qwen 已完成隔离合成沙箱的正向推理，正式机密业务链仍未放行，隔离候选 broker 的合成在线撤销已在真实沙箱通过，但正式生命周期登记/撤销仍待接入。最终机密候选 runtime lock 使用不可变镜像状态快照；Qwen 模型已受控切换到 loopback/文件密钥安全 unit，既有 Nemotron binding 未切换。

所有 binding 仍是 `NOT_PRODUCTION_CANARY` / `readiness_effect=none`。本台账不把受控候选写成生产正式放行；`600418` 结果证明指定候选的业务沙箱已经接入 AgentShield，但不外推到其他公司、租户或生产流量。

按 17 个主任务的非生产候选交付衡量，14 项已有指定范围闭环，SP-01、ML-02 和 CI-01 仍有在线门禁或最终验收缺口；这不是 14/17 项生产就绪。若以方案要求的完整端到端标杆验收折算，当前**约 75%（工程估算，非自动化评分）**。Qwen 安全切换与真实合成沙箱正向推理已完成；剩余关键路径是正式业务生命周期/即时撤权与 SIQ IAM/业务授权联调、三仓可审查候选及 DGX Spark 原生 CI 通过。任何一项缺失都不能宣布完成。

E84 最新进展：真实 Qwen 模型经 Hermes HTTP 网关选择报告 MCP，AgentShield 按固定业务根和精确参数授权；第一次 HTTP 拒绝无发布副作用，第二次精确单次批准后发布和独立读回成功，三条 MCP 决策/observation 与 run、Grant、参数摘要及签名链匹配。此前未知效果拒绝和 HTTP 审批路由缺陷均已定位修复，原失败证据保留。该结果关闭了**合成业务模型驱动发布链**缺口；正式 IAM/业务批准、常驻监督和原生 CI 仍待完成，整体与生产门禁保持 false。详见 [E84 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-gateway-business-e84.json)。

E85 最新增量：实际业务 API 原先只在首次准入检查机密 grant，现已在池心跳和新 run 创建前复核原快照、主体/会话、沙箱绑定及当前业务权限。撤销、过期、异常和超时拒绝续租/创建，并进入既有停止与写静默门禁；原始授权只留内存，跨仓事件仍仅含摘要。隔离业务数据库与路由/恢复/导出组合 **181 项通过**。默认 18081 API 健康探针不可达，本轮没有宣称正式在线部署通过；周期检查也不是同步即时撤权。[E85 证据](../evidence/flagship-optimization-20260921/ml-02-api-pool-reauthorization-e85.json)。

E86 最新增量：独立宿主监督进程已接入真实 Qwen/Hermes/OpenShell 合成候选，读取私有原授权包，并通过新数据库会话复核隔离 PostgreSQL grant。首次 tick 通过后撤销 grant，子进程自行完成 broker 撤权、模型令牌切断、沙箱删除并退出；父进程确认终止、恢复 Provider、新代正向核验后释放网关。临时库、合成目录和私有运行状态清理通过，模型及桥未重启。**121 项回归通过**；SIGTERM/SIGKILL 回归的外部副作用使用测试替身，systemd 模板仅完成语法校验。正式业务首次模型调用前接线、systemd 真机崩溃恢复、实际时钟触发的自动续期、生产 IAM 与原生 CI 仍待验收。[E86 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-resident-supervisor-e86.json)。

E87 最新增量：固定 systemd 用户服务已在候选模型 run 前完成首次授权检查，按原 600 秒令牌和 300 秒续期窗口，在签发后 **308 秒**自动续期到 generation 2；旧令牌拒绝、新代查询成功。原 PostgreSQL grant 保持有效时，仅对绑定实例 main 发送 SIGKILL，ExecStopPost 自动完成 broker/模型/沙箱清理，进程归零；Provider 新代正向和最终回收通过。**134 项回归通过**，模板已安装但未启用开机自启；正式 API pool 业务启动/停止/恢复接线、生产 IAM/审批和原生 CI 仍待验收。[E87 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-systemd-supervisor-e87.json)。

E88 最新增量：正式 API 的重启恢复原先直接续 pool 租约，绕过 E85 的原授权快照复核，现已修复。恢复出的显式主体/非公开任务只获得清理 owner，发 stop 后独立核验精确 run 与写静默；不续执行授权，确认后以 `authority_lost` 终态释放，首次终态未知 child、错 run、超时或中断均保留 orphan。**193 项隔离组合回归通过**，无数据库迁移；18081 API 两个探针仍不可达，没有宣称在线部署通过。正式 Qwen pool 生命周期接线、真实 API 重启和生产 IAM 仍是未完成项。[E88 证据](../evidence/flagship-optimization-20260921/ml-02-api-recovery-authorization-e88.json)。

E89 最新增量：已修复新配置文件遮蔽旧认证/数据库设置造成的 API 启动缺口。显式迁移保留现有配置，补齐缺失项并创建私有备份；业务库归档及只读 schema 预检通过，启动前后规范化 schema 相同。实际 API 通过临时用户服务仅监听 `127.0.0.1:18081`，健康 200，恢复管理器 enabled/required/ready 均为 true；未认证业务状态和 grant 创建均返回 401。**12 项配置迁移测试通过**，Qwen 与桥没有重启。一级市场材料自动恢复暂未启用，旧 full-stack 服务历史失败仍保留；这仅关闭 API 不可达缺口，不代表正式 Qwen pool、在途任务重启、生产 IAM/批准或发布门禁通过。[E89 证据](../evidence/flagship-optimization-20260921/ml-02-api-local-candidate-bringup-e89.json)。

E90 最新增量：监督器新增显式真实只读 broker 模式，首次 tick 后启动固定 bridge/18794 服务；请求前和返回前均按原 scope 与实时业务 grant 复核，失权唤醒监督器。真实宿主 HTTP + PostgreSQL 验证专用只读角色/只读事务 200、跨市场 403；令牌仍有效登记时撤销隔离库 grant，下一请求直接 403，无需定时 tick。真实审计 allow/deny/deny 三条匹配。首次拒绝审计因字段触发脱敏词规则而返回 503，已修复且保留失败证据。**152 项回归通过**；临时库/状态/监听清理，API/模型/桥进程未重启。该真实 broker 尚未通过沙箱工具及正式 API 接线验收，已安装 systemd 模板保持原监督模式。[E90 证据](../evidence/flagship-optimization-20260921/ml-02-supervised-business-broker-e90.json)。

E91 最新增量：真实数据 broker 已接入 Qwen/OpenShell 隔离沙箱的独立监督流程，首次 tick 与 broker ready 均在模型 run 前通过；真实 Qwen 推理与桥接 200 关联。沙箱查询观察到专用只读角色和只读事务，镜像内已有 `pg_query.py` 成功，两条真实审计匹配原 run。撤销临时 PostgreSQL grant 后，常驻监督子进程切断并回收；端口/沙箱/私有状态/临时库清理，Provider 新代正向及 owner 释放通过。最终真机验收前冻结源码，**104 项回归通过**，API/模型/桥未重启。查询由 sandbox exec/业务辅助脚本发起，尚非模型自主选工具；正式 API 按请求运行时、该模式 systemd 故障恢复、生产 IAM 及原生 CI 仍待完成。下一步接线合同已明确旧公司 pool 与按请求 Qwen 运行时的边界。[E91 证据](../evidence/flagship-optimization-20260921/ml-02-real-business-broker-sandbox-e91.json)。

E92 最新增量：监督器 v2 新增不可变 API 执行 owner 绑定，包含原会话、运行、scope、租户、用户和代际；每次授权在业务查询前后复核自己的 durable 行。Qwen 租约固定 120 秒，过期 heartbeat/bind 不可复活，接管后原绑定失效；v2 必须启用真实 broker。隔离 PostgreSQL 三次验证均通过，最终源码验证证明两个并发恢复者仅一个接管成功、Hermes run ID 交接保持绑定有效、过期拒绝，临时库已删除。这是显式到期行测试，**没有运行 API 退出后真实等待 120 秒的沙箱演练**；正式 Qwen 请求接线仍待完成。[E92 证据](../evidence/flagship-optimization-20260921/ml-02-api-execution-lease-e92.json)。

E93 最新增量：实际 API 创建入口已补上资源排队和 Hermes create 阶段的原 claim 心跳，启动前、发送前和返回句柄前均检查；过期、接管、数据库异常或 pool 失权取消并等待启动任务退出。已发 create 但结果未知保留 orphan；取消后迟到返回 run ID 则停止精确 run 并独立检查写静默。独立 **13 项**启动测试通过，包含 E92、路由、授权、恢复和监督器的组合 **292 项通过**，ruff/diff 通过。首轮 5 个旧测试仅伪造 claim 没有对应续租，现已补明确替身及顺序断言，未放宽运行检查。实际 API/模型/桥仍 active、健康 200，**本轮未重启，在线 API 尚未加载 E92/E93**。下一步仍是正式 Qwen 按请求创建器与 API 后端分支、真实 IAM/审批及原生 CI；总体约 75% 估算和两个发布门禁保持不变。[E93 证据](../evidence/flagship-optimization-20260921/ml-02-api-startup-lease-guard-e93.json)。

E94 最新增量：正式按请求运行时发现旧挂载器与策略器只允许整家公司 analysis 根可写，现已新增显式请求模式。v4 mount 与 policy 共同绑定 `analysis/runs/qwen-request-<16hex>`，公司和公共元数据只读，运行快照必须 fresh 且同 run ID。Python 及相邻 **102 项通过**。真实网关创建探针揭示已部署 0002 Rust driver 仍拒绝叶目录；保留两次拒绝证据及初次证明器输出目录/清理接口修复记录，所有合成资源和 owner 已清理。新增独立 **0003 追加补丁**，验证同公司/市场、精确 run 快照及固定挂载模式；固定 ARM64 构建环境、无网络的完整 Docker driver **113 项原生测试通过**。旧 0002 补丁/二进制未改，API/模型/桥未重启。**尚未构建或部署新 gateway 可执行文件，真沙箱叶目录正向仍未通过**；下一步先完成独立制品身份、空候选网关可回滚切换及真实文件边界，再继续正式 API 创建器接线。[E94 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-workspace-e94.json)。

E95 最新增量：固定 commit、0002/0003 补丁、Cargo 文件、ARM64 构建镜像和 Z3 归档均经校验，离线构建独立请求目录网关；新增双版本制品校验和带私有 journal 的候选切换工具。空网关完成新候选切换、旧版本回滚与重新切入；人为制造 readiness 失败后自动回滚成功。另在旧进程停止后、新进程已启动但 PID 文件未落盘两个窗口让操作进程直接退出，显式恢复均找回正确进程并回滚，未依赖旧 PID 文件杀进程。最终候选运行新 0003，主 selector 不变。真实合成沙箱两次通过本 run 写入读回、公司读取、父目录/同级 run/公司根写入拒绝和跨公司读取拒绝七项检查；沙箱、owner 和合成资料已清理。**140 项组合回归通过**；本机 Python 缺少 pidfd_open 的适配缺口已用 glibc 同一 Linux 接口修复并通过真实子进程测试。API/模型/桥的 PID 与 invocation 均未改变。此轮没有运行模型或 Hermes 业务任务，正式 API 按请求生命周期、IAM/审批及原生 CI 仍待完成。[E95 证据](../evidence/flagship-optimization-20260921/ml-02-request-gateway-cutover-e95.json)。

E96 最新增量：正式 API v2 接线复审发现既有 systemd 模板没有真实 broker 模式，现新增独立 `siq-qwen38-api-supervisor@.service`，由已验证 manifest 自动选择，不覆盖旧模板、不允许降级。控制器核验实际加载命令、环境文件、无 drop-in、退出范围与禁自动重启；首次及后续就绪同时要求同 run、正整数 tick、90 秒内状态、当前 InvocationID 和严格 broker ready。读状态前后复核进程，过期/未来时间/换代/未知配置均拒绝。**153 项组合回归通过**；本机模板已安装且实际 systemd 查询核验通过，但未启动 v2 实例。首次查询发现 systemd 返回未展开变量表达式，已修正比较方式并单独绑定环境来源。旧模板与 E95 网关保持原身份，API/模型/桥未重启。此轮是正式请求创建器的服务托管前置，**尚非 v2 真实业务运行或 API 退出后 120 秒到期验收**；总体目标及发布门禁不变。[E96 证据](../evidence/flagship-optimization-20260921/ml-02-api-bound-supervisor-service-e96.json)。

E97 最新增量：新增 API 自有请求准备模块，从原授权、当前执行 owner 和精确 scope 生成只读计划，绑定公司 inode、主体/会话摘要、完整模型清单/route 摘要及验证过的镜像。取得精确 reserved owner 后才创建本 run 叶目录和私有状态，独立随机 API key 仅存 0600 文件，提交回执不含密钥；读取凭据再次校验实时 grant/执行 owner、回执和文件/目录身份。准备中失权或部分失败保留占位，既有输出不覆盖。共享镜像校验已从证明器提取；实际镜像身份通过。**115 项组合回归通过**，63 条 warning 为既有 datetime.utcnow 默认值弃用提示，无跳过项。两次隔离 PostgreSQL + 合成目录实测均通过，最终代码复验包含完整模型清单绑定；真实 grant 撤销后密钥读取拒绝，临时库、凭据、合成目录和 owner 已清理，API/模型/桥未重启。**本轮未发送正式 API 请求、未创建沙箱或启动 Hermes**，远端凭据传输、正式 start/heartbeat/stop/recover/status 接线和生产门禁继续待完成。[E97 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-preparation-e97.json)。


E98 最新增量：E97 私有 staging 已通过真实 OpenShell/Hermes 引导验证，独立随机 API key 由 0600 文件上传，create/exec 参数与输出无 key；上传副本在固定子进程启动前删除。实际 `/health/detailed` 返回同一子进程 PID，错 key 401，重复引导拒绝；grant 撤销后宿主再次读取 key 拒绝。首次鉴权通过后因 Hermes 的 Unix socket 被清理器拒绝，保留失败证据并精确修复固定 socket 清理，显式清理及 v2 全流程复验通过。**77 项组合回归通过**；沙箱、临时库、合成目录、私有凭据和 owner 均清理，API/模型/桥进程未变。本轮没有提交模型 run，也没有启动 v2 broker/supervisor，`business_ready=false`；正式 API 请求生命周期、IAM/审批及原生 CI 仍待完成。[E98 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-bootstrap-e98.json)。


E99 最新增量：API 自有请求配置组件已直接调用生产编译器，生成带业务 MCP 的 fresh profile、v4 请求挂载、机密 Qwen 策略和资源 lease，绑定原授权/owner、文件 inode/摘要及 bootstrap 源码。尝试标记与最后提交 manifest 分离，编译中失权拒绝、部分失败不可原地重试。创建前还以策略编译器 `--check` 只读重编译，拒绝源配置漂移；策略回执、挂载和快照摘要交叉复核。**17 项专项、94 项组合回归通过**；两次隔离 PostgreSQL 与真实 OpenShell/Hermes 启动鉴权通过，最终 v2 使用完整复核代码。所有合成资源、临时库和 owner 清理，API/模型/桥未重启。沙箱 create/exec 仍由诊断外壳执行，正式 API start/stop/recover、业务 endpoint 和 v2 监督首次就绪仍待接线，生产门禁不变。[E99 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-assets-e99.json)。


E100 最新增量：API 自有组件已实际承担沙箱 create 与预启动 stop。固定 CLI/候选网关/Provider、私有创建尝试记录及重复拒绝落地；创建后交叉核验 OpenShell ID/nonce、Docker 完整 ID、镜像与 CPU/内存/PID/非 privileged 限制，再激活 owner 并重新授权。未知结果保留占位，已识别实例后失权只回收精确实例。停止同时确认网关清单和 Docker（含停止容器）均无实例，重复停止重新核验。**17 项专项、111 项组合回归通过**；两次隔离 PostgreSQL + 真沙箱创建/回收通过，最终 v2 验证重复停止。沙箱写出的合成业务输出在组件 stop 后保留，原 owner 由诊断收尾才释放；临时资源清理，既有服务未重启。未知响应及创建中撤权使用隔离传输替身；本次未启动 Hermes/监督器或发布业务 endpoint，正式 HTTP 请求及完整运行生命周期仍待接线。[E100 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-creation-e100.json)。

E101 最新增量：API 自有监督组件已把创建后的精确沙箱、原业务授权、API 执行租约与独立 v2 systemd/真实数据 broker 接通。签名数据身份经私有文件原子安装，初次传输前创建可撤销空 registry；已有登记拒绝重置，冲突及传输/就绪失败进入精确清理并保留 owner。**172 项组合回归通过**。两次隔离 PostgreSQL + 真沙箱演练均通过专用只读角色/只读事务查询；不发心跳、不改执行行、不撤业务 grant，原 120 秒租约自然到期后独立监督器自动回收。最终 v2 独立确认数据 lease 撤销、模型客户端密钥轮换及 ExecStopPost 成功，broker/进程/沙箱停止，Provider 新代正向与临时资源清理通过；既有 API/模型/桥未重启。初次登记失败的清理缺口已修复并补负向测试；诊断清理未知时保留临时授权库供恢复。**没有启动 Hermes/AgentShield relay、发送正式 API 请求或杀死 API 进程**，不能替代正式 API 崩溃、模型业务链或生产 IAM/审批验收。总体目标与发布门禁不变。[E101 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-supervision-e101.json)。

E102 最新增量：发现请求监督器若用既有管理撤销接口，需要携带 admin 会话，故新增宿主专用的自身查询/自身撤销合同与研究侧 HTTP 客户端。查询在线复核原签名身份、当前实例和固定 Grant；清理仅凭自身原凭据撤销自身，即使 Grant 失效或实例消失仍可重试，并保留原签名撤销记录。拒绝目标/actor 覆盖、管理与全局凭据、重复字段和不确定成功；不扩充沙箱 relay 七条路由。Go 全模块、vet、身份/HTTP/relay race、四平台双二进制编译通过；研究侧 **56 项回归**、共享合同 **11 项校验**通过。独立 47811 daemon 的最终 v3 实测覆盖有效授权、Grant 撤销、合成 profile 删除三场景，自身撤销/重复清理成功，旧凭据登记均 401。首次构建 0775 权限被拒，收紧独立制品到 0700 后复验，原失败证据保留。临时 daemon 已退出，合成 profile/管理会话关闭，签名历史保留；主 47611/API/模型/桥未替换或重启。**新客户端尚未接入 v2 supervisor 的恢复清单，未启动 Hermes/沙箱**；请求身份与 relay 的完整托管、正式 API 崩溃、生产 IAM/审批和原生 CI 继续待完成。[E102 证据](../evidence/flagship-optimization-20260921/ml-02-agentshield-self-identity-e102.json)。




E103 最新增量：请求身份已纳入 v3 持久监督清单，固定原 scope/API 执行绑定、服务端身份/Grant 读回和私有凭据副本摘要。首次及周期检查增加身份在线复核，停止/恢复独立尝试数据、模型、沙箱断路和自身撤销；任何阶段不确定均保留失败状态与 owner。**264 项组合回归通过**，覆盖身份记录损坏、服务不可用、部分阶段复用拒绝和交接失败撤销。独立 AgentShield 候选 + 隔离 PostgreSQL + 真沙箱实测：原执行租约及业务 Grant 仍有效时 SIGKILL 监督 main，约 **2.355 秒**后 ExecStopPost 完成清理；AgentShield Grant/profile 未改变，管理诊断收尾前身份读回 revoked，旧凭据查询/会话登记均 401。数据 lease 撤销、模型凭据轮换、进程/broker/沙箱退出及 Provider 新代正向通过；私有副本、合成资料、临时库和 owner 清理，原主 daemon/API/模型/桥未重启。该时长为单次观测，不是 SLA。**尚未启动 relay/Hermes、发送正式 API 请求或杀死 API 进程**；身份仍由诊断签发给全新合成 profile，正式请求身份签发、完整运行时、生产 IAM/审批和原生 CI 未验收。目标保持 active，候选及生产门禁不放行。[E103 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-identity-supervision-e103.json)。

E104 最新增量：受限 relay 已进入 API 专用监督器 v4，由固定 unit/cgroup 派生；配置摘要绑定本次身份、scope/run、精确 OpenShell/Docker 实例与 bridge。就绪同时要求原身份、真实 broker、固定 relay 可执行文件/同 cgroup 和真实会话登记，v4 不接受缺失 relay ready。**299 项组合回归通过**。首次真机因就绪探针使用普通字符串会话后缀而违反既有 64 位摘要合同失败，安全回收及 Provider 恢复通过；修正探针、保留 Go 边界并补负向测试后，v2 真机验证正确会话登记、跨请求 400、宿主自身撤销路由 404。监督 main SIGKILL 后约 **2.105 秒**完成恢复，relay 子进程与监听消失，身份撤销、数据/模型/沙箱断路及 Provider 新代正向通过；原执行租约与两类授权仍有效，合成资源清理，原主 daemon/API/模型/桥未重启。该延迟不作为 SLA。**尚未向沙箱交付本次工具身份或启动 Hermes，未发送正式 API/模型请求**；下一步监督下 Hermes bootstrap/endpoint、正式请求身份发放、业务 API 全链、生产 IAM/审批及原生 CI 仍待验收。首次失败原证据保留，候选及生产门禁不变。[E104 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-relay-supervision-e104.json)。

E105 最新增量：API 请求组件已将本次独立工具身份通过私有包交付沙箱，在 v4 监督、原执行租约/业务授权及精确资产校验后启动 Hermes；鉴权健康绑定真实 child PID，错误 key 401，token 不进入 argv/环境/回执。沙箱内原生 dispatcher 实测读允许、越权写拒绝且无副作用，签名回执精确绑定本次身份与 Grant。最终 v6/v7 连续真机分别通过 SIGKILL 与正常停止，全断路、自身撤销、relay/沙箱回收、Provider 新代正向和临时资源清理均通过；两次恢复约 **2.137 / 2.379 秒**，仅为单次观测。修复 systemd 回收退出元数据后的严格恢复确认、Hermes watchdog socket 的精确清理和 relay TIME_WAIT 影响连续启动的问题；活跃监听冲突与错误恢复证据仍拒绝。最终相关组合 **329 项通过**，此前重叠 343 项亦通过，不累加。历史失败与三次私有恢复材料保留；其中 v4 最初底层启动原因未证明，v5 为诊断启动器误填 recovery 路径，均未冒充业务成功。原主 daemon/API/模型/桥未重启。**本轮原生工具由独立 dispatcher 进程执行，尚未发布宿主业务 endpoint、未发送正式 API 或模型业务请求**。下一步为受监督 endpoint、正式 API 生命周期与身份签发、真实 IAM/审批和原生 CI；总体约 75% 估算及生产门禁保持不变。[E105 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-gateway-e105.json)。

E106 最新增量：新增 supervisor v5，在同一 API 专用 cgroup 内托管本次 OpenShell forward，固定宿主回环端点与沙箱 Hermes 端口；manifest 绑定 CLI/启动脚本摘要，实际 exe/argv、子进程/cgroup 与监听 socket 共同就绪。API 端点组件通过原授权和引导 PID 完成正确 key 鉴权、错 key 401，凭据只留内存。复核补上缓存 ready 的缺口：每次端点准入重验实际子进程，发送健康请求鉴权头前确认已建立连接属于该进程；其他本地进程占端口的负向测试实际收到 **0 字节**。最终 **368 项组合回归通过**；v3/v4 两次真机在正常授权/执行租约仍有效时，分别通过 SIGKILL/正常停止及 forward/relay/身份/数据/模型/沙箱全回收，恢复约 **2.312 / 2.474 秒**（非 SLA），Provider 新代正向和临时资源清理通过。原 API/模型/桥/主 daemon 未重启，原 Hermes 镜像未变。初次 v1/v2 成功与加固后证据均保留。**业务 API 尚未消费该端点，未通过它发送模型 create/stream/stop 请求**；后续正式 HTTP transport 须沿用连接归属检查，继续接入路由与完整业务生命周期、正式身份签发、IAM/审批和原生 CI。总体约 75% 和生产门禁不变。[E106 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-endpoint-e106.json)。

E107 最新增量：`HermesRunRoute` 新增明确的请求后端与内存授权句柄，create/SSE/status/stop 均接入异步 HTTP 所有权校验；每次连接在发送凭据前确认实际 forward 接受 socket，并再次复核原授权和相同 PID。禁代理、重定向、连接复用与重试，补上 run ID 在 URL 规范化前的严格校验。**495 项组合回归及另 3 项证明器测试通过**，实际 TCP/SSE 负向覆盖冒用端口零字节、撤权、取消、超时和截断；旧 Host/canary 兼容通过。首次真机 v1 已创建真实 Hermes run，但未在 60 秒观察窗取得模型终态，记录 TimeoutError；没有执行预定 SIGKILL 或开始第二轮。原监督链最终正常停止，Provider 恢复、新代正向、临时身份/沙箱/数据库/owner 清理通过，原 API/模型/桥未重启。模型桥完整缓冲上游响应是待核查因素，**尚未证明超时根因，不把创建成功当作模型全链通过**。下一步接原 owner 续租与运行状态观测后复验，再完成正式 API 后端选择、生命周期、IAM/审批及原生 CI。目标仍 active、总体约 75%，两个发布门禁保持 false。[E107 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-client-e107.json)。

E108 最新增量：请求级心跳组件每 30 秒以原授权/端点复核原 owner，并在行锁内核对主体、代际和未过期执行租约，仍只续 120 秒；取消时等待同步线程退出，拒绝迟到复活。**536 项组合回归、追踪诊断专项 8 项通过（含重叠用例，不累加）**。v1 真实模型完成并 SIGKILL 回收，v2 在 240 秒超时后清理，根因尚未证明。新增按合成请求 trace 关联模型桥及清理前固定错误类别计数，v3 正常停止通过，最终同版 v4/v5 连续完成真实模型结果、HTTP stop/status 写静默、精确桥 200 和 SIGKILL/正常停止全资源回收；分别 5/2 次续租、约 2.562/3.002 秒回收（非 SLA）。身份在诊断管理收尾前已撤销，原 owner/generation 与业务 Grant 保持有效，时间字段通过正规续租改变。原 API/模型/桥未重启，全部临时资源清理。Provider 恢复探针只证明鉴权 `/models`；实际推理由独立客户端结果和桥回执证明。**正式 API 选择器与按请求编排尚未接入**，模型延迟稳定性、在途取消、真实 API 崩溃、正式身份签发/IAM/审批与原生 CI 仍未验收。历史超时保留，目标 active、约 75% 与发布门禁不变。[E108 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-heartbeat-e108.json)。

E109 最新增量：实际 `agent_chat_runtime_impl` 已明确区分请求后端与旧公司 pool，原 claim、主体/会话、路由摘要与输出目录逐项核验，空 `pool_binding` 不再跳过授权。创建阶段与运行/后处理续租使用原绑定及精确业务 run ID，行锁下完成 provisional→Hermes run ID 交接；取消等待同步写线程退出。失权后通过原 endpoint 清理监督执行域，未知 create/绑定提交/清理均保留 durable 行；旧池重启恢复器明确跳过请求行。**301 项组合回归、最终 36 项专项通过（有重叠，不累加）**，ruff、语法和 diff 检查通过。验证使用实际编排函数、隔离 SQLite 与本地合成 HTTP 服务；OpenShell/身份/监督为替身，本轮没有调用模型或重启现场服务。**资源停止后的 Provider/owner 持久终态交接仍待实现，所以 release 明确返回未释放，正式 selector 未开启**。下一步优先完成终态 finalizer，再接请求准备/排队/身份签发、请求财务回执与安全事件投影，随后真实 API 故障和 IAM/审批/原生 CI 验收；总体约 75%、目标 active、候选及生产门禁 false 不变。[E109 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-api-e109.json)。

E110 最新增量：请求终态清理已进入实际 API 的完成与失败创建分支。私有 prepared→provider_restored→released 记录绑定原计划/租约、端点、服务 invocation 和精确实例；固定监督停止、容器/监听消失确认后，以正式 Provider 配置组件恢复当前凭据，最后释放 gateway owner，业务输出和恢复材料保留。数据库终态须在资源交接后按原完整绑定写入，过期可清理、接管不可覆盖。真实子进程在删除 owner 后退出，旧任务重试对新占位零运行态操作；取消等待同步清理，连续目录 fsync 失败不提前记 released。**450 项组合回归通过；后续原计划绑定与持久化加固后，最终 68 项专项通过（重叠不累加）**，ruff/语法/diff 通过。Provider 专项首轮两项因测试锁文件缺失失败，已补齐前置条件，未放宽正式检查。本轮是隔离 SQLite/真实文件锁和进程退出验证，OpenShell/systemd/Provider CLI 为替身，未运行模型或重启现场服务。**尚需从磁盘加载仅供清理的句柄、接入 API 重启扫描并做真机终态交接**；正式 selector、请求签发/排队、回执/事件出口、IAM/审批和原生 CI 未完成，目标 active、约 75% 及候选/生产门禁 false 保持。[E110 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-finalization-e110.json)。

E111 最新增量：新增 0600 磁盘恢复描述与仅供清理的句柄，交叉校验原 stage、配置、实例、端点/网关及监督 manifest；不读取 API key、授权包或数据库连接串，不恢复业务执行权。实际 API lifespan 接入有界恢复扫描，有效原租约仅等待，过期/被替换/缺行后精确清理，资源交接后按原绑定和扫描 run ID 收尾。修复 OFFSET 漏扫、前页失败被后页成功掩盖及启动取消遗留已启动管理器的问题；健康输出仅开关、就绪和计数。**最终 20 文件组合回归 524 项通过**，ruff/语法/diff 通过。隔离 SQLite、真实文件锁/权限与 fork 退出后重新加载通过，OpenShell/systemd/Provider 为替身；未运行模型、重启在线 API 或变更现场服务。缺少端点恢复描述的启动中断仍保留占位且未就绪；**真机 finalizer、实际 API 重启、此前启动窗口恢复、正式 selector/身份签发/排队、回执/事件、IAM/审批与原生 CI 待完成**。目标 active、约 75% 与两个发布门禁 false 不变。[E111 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-recovery-e111.json)。

E112 最新增量：正式 finalizer 连续两轮真机交接通过。真实 v5 监督、Hermes/鉴权 endpoint 和 broker 就绪后，从磁盘加载仅清理句柄，由正式组件停止活动服务、核验 ExecStopPost/执行域消失、恢复 Provider 并释放 owner；再次从磁盘加载清理未再次轮换凭据。原业务 Grant/执行租约保持有效、数据库时间未改，身份先于诊断管理收尾撤销，relay/forward/数据/容器全部回收。两轮交接约 **2.676 / 2.802 秒**（非 SLA），独立 Provider 鉴权 `/models` 正向通过，未发模型推理请求。诊断收尾持 owner 锁拒绝后来占位，并校验最终 journal；合成资料、临时库/身份/私有文件及 owner 均清理，原 API/模型/桥 PID 与 invocation 未变。**161 项组合回归通过**，首次清单冲突测试因 fixture 使用固定空清单回调失败，已修正 fixture，安全断言未放宽。关闭 E110/E111 真机 finalizer 缺口；**实际 API 重启扫描/进程崩溃、端点前恢复、正式 selector/签发/排队、回执/事件、IAM/审批与原生 CI 仍待验收**。目标 active、总体约 75% 与发布门禁 false 保持。[E112 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-finalizer-live-e112.json)。

E113 最新增量：新增原 provisional claim→Qwen 请求准入组件，复核验证主体、原 owner/session/run、未过期租约与空 pool 字段，行锁加完整旧值 CAS 写入宿主随机 nonce 和固定 120 秒执行绑定。lease ID 绑定完整原 scope/授权快照，重试不换 nonce/不续租，同公司新快照亦不能替代；提交前复查实际业务账号/Grant，准备阶段续租拒绝过期、撤权及已切换业务 run。取消/截止时间/提交结果未知的隔离测试通过，恢复扫描改为等待合法未过期的准备阶段，过期缺材料仍未就绪。**最终 197 项组合回归通过**；隔离 PostgreSQL 两个独立 spawn 进程取得相同绑定，续租/撤权拒绝及临时库清理通过。诊断已从 generic claim 经正式 attach 进入真实 v5/Hermes/endpoint/finalizer，真机 v3 通过并回收全部临时资源，既有 API/模型/桥未重启。**尚未把准入组件接入默认 selector/资源队列，未实现正式工具身份签发或早期启动自动清理**；实际 API 重启/业务请求、回执/事件、IAM/审批与原生 CI 继续待办。目标 active、约 75% 和发布门禁 false 保持。[E113 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-admission-e113.json)。

E114 最新增量：正式资源队列持请求锁登记 pending，等待独占网关期间按原授权/租约续期，返回前发布 prepared；重复准备在续租前拒绝。取消等待同步工作退出；只有未曾尝试创建、目录内容属于准备阶段、原 reserved owner 且空清单才允许释放，最后按原绑定/CAS 收尾数据库。恢复扫描覆盖过期等待、部分 staging、准备完成及配置阶段；未知创建、active owner 或未知文件保留，其他 owner 不受运行面操作。**最终 185 项组合回归通过**，包含真实 fork 退出窗口；专项 36 项与组合重叠。真实隔离 PostgreSQL→正式队列→v5/Hermes 鉴权 endpoint→原生工具及签名回执→正式 finalizer 的 v1 链通过，本轮没有模型推理。临时库、合成目录/凭据、沙箱、owner 与监听清理；仅保留无凭据 released ticket 和锁，原 API/模型/桥未重启。**默认 selector、正式身份签发、创建后端点前恢复、真实 API 重启/业务入口、回执/事件、IAM/审批与原生 CI 仍待完成**。目标 active、总体约 75% 与发布门禁 false 不变。[E114 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-queue-e114.json)。

E115 最新增量：创建前发布无执行凭据的原计划/配置/租约/scope 清理描述，已确认实例可在 endpoint 之前从磁盘回收。监督记录 v2 在启动前固定 manifest，取得 InvocationID 即落盘，再等待就绪；仅清理控制器支持 v2–v5，旧记录 v1 只允许收尾。恢复扫描优先完整 endpoint，损坏不降级；缺少 endpoint 时按 startup 描述停止原服务、撤销身份/数据/模型、恢复 Provider 并持久释放，保留业务输出。**445 项组合回归通过；旧记录兼容修复后最终 90 项专项通过（重叠）**。真实 v4/Hermes 在尚无 endpoint 时，由正式 startup 清理器完成活动服务停止及幂等重试；修复后 v2 真机复验通过，原生工具和签名回执通过，本轮没有模型推理或真实 API 崩溃。临时运行资源清理、既有服务未重启。未知 create、无 InvocationID 的启动、不完整身份交付仍保留；**正式身份签发和 API builder/selector 是下一条关键路径**，实际 API/事件/IAM/审批与原生 CI 继续待办，目标 active、发布门禁 false。[E115 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-request-startup-e115.json)。


E116 最新增量：安全端已实现显式管理登记的固定 scope/时限宿主签发许可，以及根 Runtime Bearer 按原 request/execution 签发独立 v3 身份和先行取消接口。继承已批准 Grant，不增加业务权限；子身份认证、会话、决策与观察均复核父身份及请求期限，会话仅允许派生前缀。签名 attempt→秘密→发行顺序支持同尝试重试，取消先追加审计再撤销，迟到发行拒绝；普通身份、子身份及 sandbox relay 均不能取得签发能力。**Go 全模块/vet、专项 race、261 项 Python 合同测试及四目标共 8 个二进制编译通过**；新 v3 私有样例完成 Python/Go 规范签名对等。修改文件格式检查通过，全仓 `gofmt -l .` 仍报告历史 `.tmp/fx01/refcalc.go`，未改写历史文件。测试使用临时私有状态、合成 Grant 与 HTTP handler；**没有启动新守护进程、Hermes/模型或重启业务 API**。研究宿主客户端、真实签发/交付/清理联调与 API builder/selector 尚未完成，不能据此关闭完整身份签发链。目标 active、总体约 75% 和发布门禁 false 保持。[E116 证据](../evidence/flagship-optimization-20260921/ml-02-runtime-request-identity-issuer-e116-v2.json)；[接线与回退说明](../hermes-request-identity-issuer-runbook.md)。


E117 最新增量：研究宿主客户端消费 E116 签发/取消合同，固定 loopback、禁代理/重定向，先核对原 root/Grant/instance/agent/scope/request/execution/期限/namespace 与确定性 ID，再读指定私有子凭据并独立 self 复核；取消不要求根身份 active。**107 项客户端/绑定/交付相邻测试通过**（42 条既有 Pydantic 告警），ruff/语法/diff 通过。隔离 47811 的两轮真实 HTTP 均通过，最终 v2 使用加固后源码：显式许可、独立会话、跨请求拒绝、取消先于发行、故意丢弃成功响应后原参数重试，以及父身份撤销后两个子身份拒绝/宿主清理通过。合成根 Grant、临时 profile 和管理会话关闭，签名历史保留，守护进程正常退出且端口关闭；原 API/模型/bridge PID 与 invocation 未变。**没有启动 Hermes/沙箱/模型，也未把签发接入正式 API**。持久签发尝试及部分交付恢复、builder/selector、真实 API/IAM/事件和原生 CI 继续待办；目标 active、总体约 75% 和发布门禁 false 保持。[E117 证据](../evidence/flagship-optimization-20260921/ml-02-request-issuer-client-e117.json)。

E119 最新增量：正式构建器串接原 claim 队列、资产、创建、独立签发、v5 监督、Hermes、endpoint 和 route；每阶段前后重验并定时续租，取消等待线程退出后按最高阶段清理，资源确认后按完整原绑定 CAS 收尾。221 项组合回归及最终 CAS 加固后的 24 项构建器测试通过（重叠）；真实 SQLite/文件锁/线程，运行面为替身。现有服务未重启；正式 selector 接入、新构建器真机业务链、实际 API 故障、IAM/事件及原生 CI 继续待办。 目标仍 active，总体约 75% 与发布门禁不变。[E119 证据](../evidence/flagship-optimization-20260921/ml-02-request-builder-e119.json)。

E120 最新增量：显式 qwen38 选择器接入流式/非流式实际 API：预处理前仅核验主体/企业授权/根身份并返回非执行计划，实际 create 阶段再附着原 claim 调用 E119；配置/失权不退回旧 pool，未知启动不走通用释放。204 项组合及最终 74 项 selector/client/启动配置回归通过（重叠），真实 SQLite/测试 HTTP，运行面替身。默认 legacy，在线 API 未加载或启用、原服务未重启。完整真机业务请求、API 故障/未知早期窗口、宿主附属模型出域、IAM/事件及原生 CI 待办。 目标 active、总体约 75% 和发布门禁不变。[E120 证据](../evidence/flagship-optimization-20260921/ml-02-request-selector-e120.json)。

E121 最新增量：宿主图片、记忆 embedding 与 rerank 新增机密请求出域守卫，固定版本化 loopback 地址/模型，禁环境代理与重定向；上下文贯穿预处理、后台任务和线程，流式 yield 后恢复。176 项组合回归通过，含 19 项专项（重叠）；真实本机测试 HTTP 验证代理/重定向/未登记接收端零请求。未调用实际辅助模型、未重启或启用在线 API；其他宿主出口、完整正式请求、IAM/事件与原生 CI 仍待验收。 目标 active、总体约 75% 和发布门禁 false 保持。[E121 证据](../evidence/flagship-optimization-20260921/ml-02-host-auxiliary-egress-e121.json)。

E122 最新增量：正式构建器首次直接贯通真实队列/资产/沙箱/独立签发/v5 监督/Hermes/endpoint，消费原返回 route 完成本地 Qwen 合成标记和桥 200 关联，原 owner 心跳 3 次。原生工具读允许、写拒绝及签名回执通过；磁盘 finalizer 与重试、旧身份 401、数据/模型撤销、Provider 恢复、精确资源和临时库清理通过。55 项相邻回归及 v1 真机通过，既有 API/模型/桥进程未变。仍未从业务 HTTP API 发起；实际入口、API 故障/未知窗口、IAM/审批/事件、宿主其他出域与原生 CI 待办。 目标 active，整体门禁保持 false。[E122 证据](../evidence/flagship-optimization-20260921/ml-02-request-builder-live-e122.json)。

E123 最新增量：修复实际分析路由在 selector 前执行宿主报告/模型控制的绕行；受治理请求改走聊天授权与沙箱路径，拒绝显式或隐式 Host。显式 qwen38 在附件/目录/缓存/claim 前授权，受治理请求禁全局目录与消息 hash 快答，新流式请求遇已有任务返回冲突。175 项组合回归通过，含隔离 SQLite 授权负向和旧公开流程；运行面为替身，在线 API 未加载。真实业务 HTTP、跨 API/授权库恢复隔离、独立 active/history 授权、API 故障、IAM/审批/事件与原生 CI 仍待验收。 目标 active，发布门禁 false。[E123 证据](../evidence/flagship-optimization-20260921/ml-02-governed-analysis-entry-e123.json)。

E124 最新增量：复现并修复跨数据库恢复误回收：新请求在 queue/占位前持久绑定原执行行与无凭据库目标摘要，恢复前校验归属，外库计 foreign，未知来源保留。153 项组合回归通过；真实 v5/Hermes 沙箱运行时，第二个 PostgreSQL 空库及复制过期执行行扫描均未改变原服务、owner、有效租约或外库；之后同一 route 的 Qwen 推理、桥 200、工具回执和正式终态回收通过。两个临时库清理、既有服务未重启。真实业务 HTTP、API 故障/早期未知、IAM/审批/事件及原生 CI 仍待验收。 目标 active、整体门禁 false。[E124 证据](../evidence/flagship-optimization-20260921/ml-02-request-recovery-origin-e124.json)。

E125 最新增量：候选 API 部署模式固定 local/development、18083、临时回环 PostgreSQL、qwen38/confidential_local 和隔离 47811 身份服务；selector 固定模式并在 create 前重验，lifespan 仅启用请求恢复器。**119 项组合回归通过**，包含无效部署在 schema 前拒绝及候选恢复器独立启动/停止。真实 FastAPI/新建 PostgreSQL v3 验证登录、匿名分析 401、分析师发放/撤销授权 403、管理员创建/幂等重试/撤销成功；临时进程与库清理，原 API/模型/桥身份未变。v1/v2 初始化和入口错误保留，未放宽发行包校验。尚未从获授权业务 HTTP 请求贯通 Hermes/模型/终态回收；API 故障、真实 IAM/审批/事件与原生 CI 继续待办。目标 active，整体约 75% 与发布门禁 false 保持。[E125 证据](../evidence/flagship-optimization-20260921/ml-02-candidate-api-deployment-e125.json)。

E126 最新增量：真实独立 API 的获授权非流式分析请求、Hermes/Qwen 推理和 API 自身终态回收首次闭环。v2 真机发现宿主 parse-only 兜底通过文件名模糊匹配返回其他公司解析目录；两项负向先复现，再在机密请求上下文下、目录解析/枚举前拒绝无 scope 兜底，事实核验规则未放宽。修复后的 v3 返回模型标记且桥 200 匹配，执行行 succeeded，诊断清理前 finalizer 已 released；真实 HTTP 授权负向/幂等/撤销仍通过。**170 项组合回归通过**。本次 API/临时库/隔离 daemon 清理、根授权撤销，原主服务未重启；合成输出与私有恢复 journal 留存。失败原响应不公开，v1/v2 脱敏失败保留。流式 API、API 故障/在途撤权、宿主其他检索路径、真实 IAM/审批/事件和原生 CI 继续待办。目标 active、整体候选 false。[E126 证据](../evidence/flagship-optimization-20260921/ml-02-business-api-e126.json)。

E127 最新增量：复用 E126 的真实账号/授权/身份与 API 部署，通过实际 `/api/analysis/chat/stream` 完成 Hermes/Qwen 请求。v1 观察 1 run、5 delta、1 reasoning、3 progress、1 done、0 error，模型标记与桥 200 关联；SSE run/session 与原执行行一致。done 后独立等待 API 自身完成 completed 与 finalizer released，未用诊断停止冒充收尾。62 项相邻回归及另 7 项不重叠证明器测试通过，lint/compile/diff 通过。真实授权负向/幂等/撤销仍通过，临时 API/库/daemon 已清理、原服务未变。API 故障/在途撤权、独立 active/history 授权、其他宿主检索、真实 IAM/审批/事件及原生 CI 待办；目标 active，发布门禁 false。[E127 证据](../evidence/flagship-optimization-20260921/ml-02-streaming-api-e127.json)。

## 阶段状态

| 任务 | 状态 | 当前证据与缺口 |
| --- | --- | --- |
| HOS-UPG-001 Hermes 0.21.0 迁移 | 完成 | 固定 commit、补丁、镜像、原生/业务回归、回滚及公司范围路由均有脱敏证据；详见研究仓迁移报告 |
| SP-01 候选冻结与 doctor | 隔离候选包完成；在线模型不可用阻断 | 活动旧池 lock/doctor 保留原失败；新增机密候选 lock/doctor，候选包六层累计门禁通过。8006 曾服务 Ornith，OS-01 收口时两个模型端点均不可达；候选仍锁定 Nemotron，故在线环境门禁失败，生产与活动池均未推广 |
| HM-01 required security gate | 指定候选完成 | Hermes 0.21 受审 patch 对 required 插件缺失、异常、超时、畸形回包和分发异常 fail-closed；`600418` 真实业务 canary 完成会话登记、正常 allow、越界 deny 与无管理路由验证。生产流量未切换 |
| HM-02 镜像与 profile 接入 | 指定候选完成，常驻推广待定 | v0.21 候选固定并加载 AgentShield adapter，独立 runtime/auth、closed-world tools、公司 pool 和三层 ProfileManifest 已完成；候选已在独立公司 scope 激活验证后停止，未替换 `600519` |
| AS-01 决策桥合同 | 完成（canary 范围） | 严格 JSON 合同、Go 受限 relay、Runtime Identity 在线校验、跨 session、撤销、管理路由隐藏、OpenShell bridge 传输和回滚均有真实脱敏证据；仍不等于生产批准 |
| NW-01 数据分类与出域 | 完成（非生产模板与真实 broker） | v3 签名身份继续绑定 `public_research`/`confidential_local`，并兼容既有 v1/v2；机密 policy 无公网出口路由，broker 防御层对 query/JSON/云 LLM/辅助模型均 403；公开兼容证明 GO |
| DT-01 授权数据范围 | 完成（非生产 scope 与真实 broker） | 短时业务授权快照、v3 `scope_ref`、单公司精确挂载、公开共享目录显式分类和 broker 服务端市场/项目复核已通过；活动旧 pool 未原地迁移，每用户向长驻公司沙箱委派仍作为后续代际设计 |
| ML-01 本地模型路由 | 完成（隔离机密候选） | 受治理 alias、模型/镜像/权重/运行参数摘要、分类绑定和 `cloud_fallback=forbidden` 已落地；机密 Hermes 0.21 候选完成真实推理，移除唯一 8006 路由后明确失败且无成功标记，恢复后健康并清理。活动公司 pool 未切换 |
| ML-02 本地备选候选与容量 | 真实合成链通过；正式业务生命周期与生产门禁仍阻断 | Qwen3.8 已安全切换到宿主 loopback/文件密钥，完整物料与合成推理审计 `host_candidate_ready=true`；独立 OpenShell Provider 错令牌 401/有效 200，Hermes 0.21 合成 run 完成并与 bridge 200 单条回执按标记摘要关联。同一合成企业 scope 沙箱完成公司读写/跨公司拒绝、在线 broker 身份 generation 1→3 与停止前撤权；客户端令牌先行轮换证实旧代 401、新代 200；受监督合成运行又验证创建前独占占位、broker→模型→沙箱停止、新代 Provider 200 及占位释放，探针沙箱、broker 和合成目录均清理。业务库迁移与隔离恢复库授权联调已完成；正式 SIQ IAM/真实业务授权、Qwen 业务 start/stop/定时续期、即时撤权及原生 CI 尚未验收；E84 已验证模型选择报告 MCP、HTTP 拒绝/单次批准、发布与独立读回的合成闭环；E87 已验证候选模型 run 前 systemd 首次检查、自然时钟自动续期和 SIGKILL 自动恢复，正式 API pool 接线仍待验收；Nemotron lock 与活动 binding 未改，整体 `candidate_ready=false` |
| FX-01 效果与发布 | 完成（非生产 canary） | 八类材料和双核验回执绑定；CAS 不可变 Publisher、读回、幂等、改包拒绝与真实 AgentShield EffectEvidence 已通过。批准仍是本地 fixture，未接生产 IAM/业务发布目标 |
| HM-03 委派、恢复与审批 | 完成（隔离候选与合成公开云探针） | 子权限固定收缩至 `file/web`，checkpoint 后身份重验、批准参数重验、定向取消和父中断传播通过；Step 5 Preview 真实父子委派完成。远端写静默归 OS-01，生产 IAM/checkpoint 恢复未外推 |
| OS-01 run 生命周期联动 | 完成（隔离机密候选） | exec/run 执行域分离；停止应答不冒充静默；Hermes `quiesced=true` 后文件稳定；未知/首次终态/404 保留 orphan writer；活动 pool 未迁移 |
| EN-01 SIQ 业务连接 | 完成（隔离跨仓 canary） | v1 无凭据事件、API admission/terminal hook、真实 scope/route 摘要和新 `connectors/siq` 已贯通；跨租户/原始字段拒绝。生产开关、远程 Edge 注册与生产 IAM 未推广 |
| BU-01 受控业务工具 | 完成（隔离 Hermes MCP canary） | 固定 `research.publish_report`/readback、owner-only 单任务工作区、双摘要内部复核、Hermes untrusted write gate、AgentShield 精确批准绑定、拒绝零副作用和幂等通过；覆盖层/第五补丁未推广为活动镜像 |
| OC-01 OpenClaw 对等验证 | 完成（库存负向 + 隔离受控候选） | 实际 2026.9.5 库存档缺最终复查并失败关闭；固定摘要受控副本 20/20，含 BU-01 同名业务工具精确参数允许与摘要变化拒绝。全局运行时未打补丁，生产/上游支持不外推 |
| SP-02 配额与遗留治理 | 完成（真实换代与双槽验证） | 6 个档位覆盖正式、探针、wide、canary/pool 和两个 PoC；遗留 2 台已按身份验证流程停止，gateway scoped-mount patch 已激活；两台新 Hermes 0.21 canary 的租约、manifest、relay v2、状态和探针均通过，`operational_ready=true` |
| CI-01 原生候选门禁 | 实现完成；现场阻断 | 手动自托管工作流固定 DGX Spark/ARM64/GB10、干净仓库、当前 GitHub SHA、实时 doctor、健康 gateway、资源 `operational_ready` 与四组固定回归；SP-02 与 aiohttp 候选锁阻断已关闭，本机仍因三仓 dirty、模型离线及无自托管工作流通过记录而未显示通过 |
| UX-01 任务安全视图 | 完成（本地管理面） | 服务端同快照投影任务/意图、运行模式、模型路由、匿名去向、逐动作授权与 Completion；前端拒绝乐观升级，CI-01 未接入时固定显示未核验。未新增生产候选通过声明 |

## SP-01 实际结果

新增：

- `deploy/dgx-spark/runtime-lock.v1.json`：绑定安全仓/研究仓/Hermes commit，OpenShell CLI/gateway/supervisor 摘要，Hermes patch/image/config，模型、pool、policy/mount 与证据摘要。
- `deploy/dgx-spark/doctor.py` 与 `doctor.sh`：输出配置、可达性、身份、安全行为、推理和业务完成六层结果。
- `deploy/dgx-spark/tests/test_doctor.py`：覆盖严格 JSON、路径逃逸、远端/带凭据探测、摘要漂移、证据替换和累计门禁。

2026-09-21 真机结果：

| 层级 | 结果 | 解释 |
| --- | --- | --- |
| configuration_correct | `fail` | 当前 `data/hermes/home/profiles/siq_analysis/config.yaml` 摘要为 `cd0d6d…`，冻结镜像输入为 `796e1e…`；不自动覆盖用户配置，也不把新源码冒充旧镜像输入 |
| service_reachable | `pass` | gateway、Host、v0.21 pool、旧版对照 canary、模型 loopback/bridge 和 bridge unit 可达 |
| identity_match | `pass` | OpenShell 0.0.83 三二进制、Hermes 0.21.0、镜像、pool binding、模型 ID、policy/mount 与锁一致 |
| security_behavior | `pass` | 锁定证据的 V01–V12 通过；范围仍限于已记录候选与 harness |
| inference_verified | `pass` | SIQ 公司路由后的本地模型 run 完成并精确返回验证标记 |
| business_completed | `pass` | 锁定证据的 V13–V18、三格式报告和缺证据拒绝通过 |

累计 `--require-level business_completed` 返回 1，因为配置漂移不能被后续通过项覆盖。脱敏现场报告位于 `docs/evidence/flagship-optimization-20260921/sp-01-doctor.json`。

## HM-02 ProfileManifest 实际结果

研究仓新增 `scripts/openshell/build_siq_analysis_profile_manifest.py` 与严格 schema，分别核对版本控制源码、Hermes home 静态白名单投影、冻结镜像 `SOURCE_BASELINE` 和活动公司 pool binding。实现不会遍历物化目录中的 auth、session、cache、log、数据库、checkpoint、memory 等运行数据；身份漂移时 `--require-consistent` 返回 3，同时保留脱敏失败清单。

2026-09-21 首次观测时，65 个源静态文件均在物化目录中存在，只有 `config.yaml` 发生变化，源码、物化配置和旧镜像输入三者均不同。随后 HM-01 根据当前物化配置构建候选：源码配置摘要 `1b2ca819…`，物化配置与候选输入摘要均为 `cd0d6d84…`；活动 `600519` canary 仍是旧镜像 `52c265e9…`，最新候选为 `20698cb2…`。该候选只在 `600418` 独立 scope 激活验证后停止。当前 `release_consistent=false`、`production_eligible=false`，不会覆盖源码配置或切换活动流量。

脱敏快照位于 `docs/evidence/flagship-optimization-20260921/hm-02-profile-manifest.json`；生成器测试 6 项通过，schema 验证通过，真实一致性门禁按预期返回 3。

## HM-01 required gate 实际结果

Hermes 0.21 集成新增受审 patch `0002-required-pre-tool-security-gate.patch`。profile 只有显式声明 `plugins.required_pre_tool_call` 才进入强制模式；此时插件未加载、未登记 `pre_tool_call`、回调异常或 `BaseException`、超时、正在运行、畸形结果及 hook 分发异常都返回稳定 block。未声明 required 的原有 profile 保持兼容行为。

研究镜像编译器仅在 v0.21 代际加入固定摘要的 AgentShield adapter，并生成 `enabled + required_pre_tool_call + 10s callback timeout`；v0.13 路径不启用该新增合同。当前候选 `siq/hermes-openshell-siq-analysis:70552c6e6dceb3ff51f9aa2e`、image ID `20698cb2…` 已构建。Hermes 插件回归 86 项通过；真实镜像 smoke 通过原生 plugin manager 和 native dispatcher 验证：没有 relay 身份时 terminal 调用 fail-closed，dispatch 副作用探针未出现。

该候选随后通过 AS-01 relay 在 `600418` 公司 scope 形成正常 allow、越界 deny 和管理路由隐藏回执，验证后干净停止，因此没有替换 `600519` 的活动 binding。脱敏证据位于 `docs/evidence/flagship-optimization-20260921/hm-01-required-gate.json`。

## AS-01 决策桥实际结果

安全仓当前使用 `openshell-decision-relay/v2` 严格合同和无凭据 Go relay；研究仓提供 authority binding 校验、relay 配置构建器、启动器及 pool 生命周期接入。OpenShell v0.0.83 会把受控进程放进 Docker 容器内的第二层网络命名空间，因此早期 `docker --network container:<id>` 回环 FD 方案只能被外层 Docker exec 看到，不能被真实 Hermes 进程访问。最终传输固定为 `verified_docker_bridge_gateway/v1`：启动器复验完整容器 ID、OpenShell 标签、bridge network ID、gateway IP 与容器网络挂载，只绑定已验证 bridge gateway。单实例兼容入口使用 `host.openshell.internal:47611`；pool `28652..28750` 确定性映射到 relay `47612..47710`，每个 policy、沙箱 endpoint 与 relay 配置精确绑定同一端口，relay 上游始终固定为宿主 `127.0.0.1:47611`。

`canary-a501c0de0008` 的真实结果：required adapter 加载、Runtime Identity session 登记、范围内 `read_file` allow、`/etc/shadow` deny、管理路由 404、Hermes 健康、OpenShell 文件边界和公司范围负向全部通过。停止后 pool binding、沙箱、28661 listener 和 bridge relay listener 均消失，`host_runtime_unchanged=true`；既有 600104/600519 端口未停止。隔离 authority proof 另验证跨 session 401、身份撤销后 401、relay UID/GID 1000、零 capability 与 `NoNewPrivs=1`。

脱敏证据位于 `docs/evidence/flagship-optimization-20260921/as-01-decision-relay.json`。扩大回归结果：研究聚焦测试 196 项通过，生命周期兼容测试 111 项通过，Hermes adapter 与 schema 测试通过，AgentShield Go 全模块及 `go vet` 通过。

## NW-01 数据分类与出域实际结果

研究仓新增严格的 `siq.openshell.egress-data-classification-profiles.v1` 合同，以及 `public_research`、`confidential_local` 两个固定模板。Broker Request Identity 当前为 v3，把数据分类和可选企业 `scope_ref` 纳入宿主 HMAC 签名；旧 v1 token 只兼容映射为公开研究模式，v2 保留已签名分类，二者都不能自行升级为企业 scope。审计 scope 对机密请求显式记录 `egress.confidential_local.*`，不保存 URL、query、正文或 token。

OpenShell policy compiler 在机密模式下直接移除 `siq_egress_guard` 公网路由，只保留只读数据 broker、AgentShield relay 和 8004/8006/8007/8013 本地内部服务；`model_route=local_only`。即使 policy 被误放宽，broker 仍依据签名分类拒绝所有公网类别，形成两层 fail-closed。

真机 broker 完成五条用例：公开 GET 200/allow；机密 query GET、未知 JSON POST、MiniMax 云 LLM、Tavily 辅助搜索均 403/deny。v3 回归后 10 条关联审计记录完整，公开历史 boundary proof 仍为 GO。相关单元/集成测试 165 项通过，ruff 与 Python 编译通过。脱敏证据位于 `docs/evidence/flagship-optimization-20260921/nw-01-data-classification-egress.json`。该结果是非生产模板和宿主 broker 证明，尚未把机密模板分配给活动公司 pool；本地模型受治理 alias 由 ML-01 完成。

## DT-01 授权数据范围实际结果

研究仓新增严格的 `siq.openshell.enterprise-data-scope.v1`。业务 API 在 pool admission 后签发并立即复核短时授权快照，把租户、主体哈希、项目、市场、公司、对象范围和数据分类绑定到快照摘要；Hermes run provenance 记录 `scope_ref`、授权快照和分类摘要，不记录用户标识明文。Broker Request Identity v3 对完整 scope 做宿主 HMAC 签名，并拒绝 scope 与分类不一致。

挂载计划 v3 在带 scope 时只读挂载一个公司目录和明确标为 `public_reference` 的市场 `_meta`，不再把整个 `data/wiki` 放入单公司沙箱；分析输出仍为唯一业务可写目录。数据 broker 按签名 scope 服务端复核市场，私有向量集合要求 `project_vector` 权限并由服务端注入精确 `project_tag`；客户端跨项目过滤、无 scope 私有访问以及无法证明记录归属的主键读取全部 fail-closed。

真机严格 broker 完成五条用例：同市场公开数据 200；跨市场、跨项目、无 scope 私有向量和不安全主键读取均 403，5 条关联审计完整。scope/mount/identity/broker/证明器测试 105 项通过，业务 API scope 与 Hermes 路由测试 52 项通过，ruff、Python 编译和差异检查通过。脱敏证据位于 `docs/evidence/flagship-optimization-20260921/dt-01-enterprise-data-scope.json`。

该结果是非生产 scope、编译挂载和宿主 broker 证明。既有 `600104`/`600519` 活动 pool 的旧 mount 与 identity generation 没有被原地修改；业务 API 授权摘要已进入 run provenance，但“每用户权限如何委派给长驻共享公司沙箱”仍需在新 sandbox generation 中选择短生命周期 sandbox 或每租约代理，不能靠替换运行中环境变量实现。

## ML-01 受治理本地模型实际结果

研究仓新增严格的 `siq.model.governed-routes.v1`，把 `siq.local.nemotron-3.5-lightning.nvfp4.v1` 绑定到机密/公开分类、精确 served model、vLLM 镜像摘要、模型与 drafter 摘要、parser、上下文和并发参数，并明确 `cloud_fallback=forbidden`。runtime compiler 同时覆盖主模型、delegation、vision、compression、session search，清空 fallback provider 和云凭据占位。

2026-09-21 在固定候选网关 `siq-openshell-scope-validation` 上构建并 smoke 机密候选 `siq/hermes-openshell-siq-analysis:3d82b38a8022141b9513f3fb`（image `sha256:6914a40e…`）。候选状态按 `public_research`/`confidential_local` 分目录保存，镜像标签、上下文基线、状态记录、策略编译器和生命周期均交叉校验分类，防止公开构建覆盖机密候选。

真实候选使用企业 scope 的 8 个挂载、0 个 OpenShell provider 和无公网出口的 confidential policy。Hermes `/v1/runs` 正常推理完成并精确返回随机标记；仅从该候选的 live policy 移除 8006 后，第二个 run 被接受但终止为 `failed`，成功标记未出现。证明器在 `finally` 中恢复原策略并验证实例健康，随后 lifecycle stop 成功；候选库存归零，主网关、AgentShield、本地模型桥和两个原 canary 均保持健康。API 对外 `model` 字段是 profile alias `siq_analysis`，因此上游模型身份由候选 runtime config、governed route 摘要与 DGX Spark host/bridge 模型证明绑定，不把 API alias 冒充 served model。

脱敏证据位于 `docs/evidence/flagship-optimization-20260921/ml-01-governed-local-model.json`；研究仓原始脱敏证明位于 `artifacts/openshell/flagship/ml01-governed-local-model.sanitized.json` 和 `ml01-confidential-sandbox.sanitized.json`。相关事务、生命周期、Milvus 证明消费、启动门禁和 ML-01 证明回归共 163 项通过。

## FX-01 报告效果与发布实际结果

研究仓新增宿主可信侧 `publish_verified_report.py`。请求必须绑定 preflight、指标快照、证据包、Markdown/JSON/HTML 报告、质量回执和事实核验回执八类材料；发布前重新核对文件类型、inode、link count、大小和摘要，并要求质量回执、事实核验回执与三格式报告摘要一致。批准同时绑定请求、完整材料集、发布目标、核验回执、精确 warning 集合和到期时间。目标通过 expected-version CAS、目标级锁、临时目录、`fsync`、原子 rename、不可变版本和即时读回发布；同一请求幂等返回原版本。

真实 `600104` 2025 分析报告完成三格式生成。过程中发现上游 `three_statements.json` 把“营业成本”和“营业总成本”复用为同一 `operating_cost`，可能使毛利率取错口径，现已拆分为 `operating_cost` 与 `total_operating_cost`，并补充低基数/由负转正说明。质量合同 `ok=true`、`contract_pass=true`、无 failure；状态为 `pass_with_review`，精确复核队列为“利息费用、市场数据、同业样本未聚合”。独立事实核验为 `approve`，critical/warning/suggestion 为 `0/0/4`；本次 PostgreSQL 证据不可用，使用 24 条本地 Wiki 证据，因此没有把该结果提升为生产可发布。

当前权威非生产版本为 `v000003`，发布摘要 `46a16f6918ae…`，独立读回通过；再次提交返回 `idempotent=true` 且仍为 `v000003`。批准后修改 Markdown 会稳定返回 `publication_artifact_digest_mismatch`，恢复原文件后仍收敛到同一版本。测试同时覆盖旧质量/事实回执、过期或 warning 不匹配批准、CAS 漂移、symlink/hardlink、读回篡改和生产目标拒绝。早期 `v000001` 在发现“核验回执未反向绑定报告摘要”后被明确标为 superseded，当前指针不再引用它。

独立 AgentShield 临时实例以真实 `intent/v3`、策略决定、宿主 observer、文件观察和 `effect-evidence/v1` 复核发布：真实 `current.json` 从 v2 原子更新到 v3 后，`completion-status/v1` 为 `verified/effects_verified`；对不存在的输出，即使工具自报 completed，独立观察仍为 `unexpected`，最终状态为 `conflicting/effect_evidence_conflicting`。Publisher 自身只生成独立的 `siq.report-publication-completion/v1` 并写明 `agentshield_ingestion=not_ingested`，不伪造安全产品完成回执。

聚焦回归 80 项通过，ruff、Python 编译和 AgentShield `effectevidence/completion/server` 三个 Go 包测试通过。脱敏证据见 [FX-01 汇总](../evidence/flagship-optimization-20260921/fx-01-report-publication.json)、[AgentShield 效果证明](../evidence/flagship-optimization-20260921/fx-01-agentshield-effect-proof.json)和[发布回执](../evidence/flagship-optimization-20260921/fx-01-publication-receipt.json)。该结果固定为 `non_production_test_fixture`、`production_eligible=false`、`readiness_effect=none`；主 OpenShell pool、主 AgentShield 和当前模型服务均未改动。

## HM-03 委派、恢复与审批实际结果

Hermes 0.21 冻结源码新增 patch `0003-delegation-child-toolset-ceiling.patch`。新配置
`delegation.child_toolsets` 是 operator 控制项，不进入模型可调用参数；子智能体有效权限取父权限与
该列表交集。空列表保持无工具，畸形配置失败关闭。`siq_analysis` 运行配置编译器固定子权限为
`file/web`，并设置单并发、深度 1、关闭 orchestrator、MCP 继承和危险命令自动批准。机密候选
`siq/hermes-openshell-siq-analysis:063ad659f260d2917a57665e` 在无网络、只读 rootfs、移除全部
capability 和 `no-new-privileges` 条件下观察到父工具含 terminal/code execution、子工具仅
`file/web`，定向取消被接收且子对象收到中断。

AgentShield 回归确认 adapter 在每个工具边界重新登记 Runtime Identity：checkpoint 风格恢复后若
身份已撤销，会在进入 decide 前阻断。hold 重试键绑定 `session_id + runtime_task_id + tool +
canonical_params`，任一项变化都拿不到执行预留；预留丢失继续失败关闭。Hermes 原生测试同时覆盖
父中断向活动子任务传播。取消后的远端写静默没有在 HM-03 冒充完成，随后由 OS-01 独立验收关闭。

HM-03 执行时 8006 的 Ornith 与 ML-01 锁定 Nemotron 不一致，因此没有切换或重启本地模型。经用户授权，
补充使用 Step Plan 当前旗舰 `step-5-preview` 执行合成公开数据测试：`/models` 实际列出该
模型，临时 Hermes 0.21 网关健康，
`POST /v1/runs` 返回 202，真实父子委派完成，父、子标记均由独立运行记录观察到。API key 只从
owner-only、Git 忽略的本地 dotenv 进入临时进程环境；proof 不保存提示词、响应正文或凭据。
该结果不改变 `confidential_local` 禁止云回退的合同。

构建 HM-03 后发现 ML-01 runtime lock 曾引用可变的 `current-image.json`。现已把原 Nemotron 镜像
状态和 smoke 回执移入候选 ID 对应的不可变快照路径，lock 继续固定原摘要；在线 candidate doctor
重新得到候选包六层通过、`candidate_package_ready=true`，并因当时的 Ornith/Nemotron 差异将
`live_environment` 判为 fail。HM-03 机密镜像和公开 packaging 镜像分别保留自己的 current 状态，
不会重写 ML-01 历史证明。

验证结果：研究仓 HM-03 聚焦测试 36 项、Hermes 原生测试 159 项、AgentShield adapter 103 项、
candidate doctor 15 项及 17 个 subtest 均通过；Go `runtimeidentity/server` 通过，`runtimeauthz`
当前无独立测试文件；两个 ARM64 候选 image smoke、ruff 和 Python 编译通过。脱敏汇总见
[HM-03 证据](../evidence/flagship-optimization-20260921/hm-03-delegation-recovery.json)。全部结果仍为
`production_eligible=false`、`readiness_effect=none`，活动公司 pool 未迁移。

## OS-01 run 生命周期联动实际结果

Hermes 0.21 冻结源码新增 `0004-api-run-quiescence.patch`，四补丁 bundle 摘要为
`0f8b0de44f60c3a1a44b3e6d273fba69df8243a3f849e1f6d8602d9b71e48887`。`queued/running/stopping`
明确返回 `quiesced=false`；正常完成、失败或协作取消只有在 executor 返回后才返回
`quiesced=true`。若只取消 asyncio 包装层而 worker thread 仍可能运行，状态保持
`cancelled/quiesced=false`，不能释放写者。aiohttp 3.13.3 不再提供 `RequestKey` 的兼容问题也由既有
0001 补丁独立处理，避免导入可选类型失败时连带关闭整个 HTTP 模块。

业务 API 的 `HermesRunStatus` 现在明确标识 `execution_kind=hermes_business_run`。主 run 只有
`write_quiesced=true`，且所有子 run 终态已确认时才允许 pool release；否则释放调用把已绑定租约变为
`orphaned`。API 重启恢复还要求先观察同一精确 run 的非终态，再观察带完整执行回执的静默终态；启动后
首次看到终态、404、身份不确定或回执不完整均保留 orphan writer。安全仓现有
`openshell-task-execution-status/v1` 继续把 `exec` 固定为 `real_sandbox_command`，其本地 stop 只停止 CLI
观察，`remote_stop_confirmed=false`，不会借 Hermes 的业务 run 语义提升为已停止。

新机密候选 `siq/hermes-openshell-siq-analysis:bcbd504e65cc472e63cfb466`、image
`sha256:b5e1b79c822c…` 完成 smoke。镜像内真实 HTTP handlers 以确定性 worker 重现停止竞态，实际状态序列为
`running/quiesced=false → stopping/quiesced=false → cancelled/quiesced=true`。停止应答后仍发生 4 次协作
收尾写入，证明 stop ack 不能作为释放依据；静默终态后 0.8 秒内文件摘要、大小与 mtime 均未变化。

验证结果为 Hermes 原生 154 项、研究 API 生命周期 125 项、研究 OpenShell 生命周期 35 项通过，
AgentShield `internal/openshell` 与 `internal/server` 两个 Go 包通过；ruff、Python 编译、proof schema 和
脱敏扫描通过。candidate doctor 保持 `candidate_package_ready=true`，活动公司 pool 未切换；OS-01 收口时
8006 loopback/bridge 均不可达，因此 `live_environment=fail`。脱敏证据见
[OS-01 证据](../evidence/flagship-optimization-20260921/os-01-run-lifecycle.json)。

## EN-01 SIQ 业务连接实际结果

安全仓新增 `siq.business-security-event/v1` 合同与第 12 个 Go Connector `connectors/siq`。研究 API 在真实 OpenShell admission 和 terminal 生命周期节点接入事件生产者；事件只接受已经绑定 tenant/user、短时授权快照、企业数据 scope、数据分类和 governed model route 的运行。原始 tenant/user/session/run、sandbox 与 audit trace 均转换为域分离 SHA-256 引用，提示词、回复、Bearer token、业务记录和数据库位置不进入出口。

出口使用 owner-only 目录和单链接 `0600` 不可变文件。Connector 无凭据、无网络，不导入研究仓或读取业务数据库；它拒绝空/root scope、通配符、symlink、hardlink、重复 key、未知字段、超限事件、跨租户 scope、run/audit 关联漂移及未静默的成功终态，并且不输出 permission fact。跨仓证明通过实际 Edge `run-once` 与 Connector stdio 协议采集出 1 个 SIQ 业务智能体授权绑定候选和 2 条 admission/terminal 证据，引用完整且审计 run 关联一致；跨租户篡改和原始身份字段均被 `redaction_failure` 拒绝。

研究运行时回归 112 项、事件生产者 6 项、全部 Control API schema 合同、Edge Go、Connector Go、Ruff 和 Python 编译通过。脱敏证明位于研究仓 `artifacts/openshell/flagship/en01-siq-business-connector.sanitized.json`，安全汇总见 [EN-01 证据](../evidence/flagship-optimization-20260921/en-01-siq-business-connector.json)。出口保持 opt-in，远程 Edge 注册仍只声明原四类 Connector，生产服务配置和生产 IAM 未改变，因此继续标记 `production_eligible=false`、`readiness_effect=none`。

## BU-01 受控业务工具实际结果

研究仓新增 MCP stdio 服务和候选覆盖层，只暴露
`mcp__siq_business__research_publish_report`、
`mcp__siq_business__research_verify_published_report` 两个工具。写工具参数固定为 task ID、请求
SHA-256 和批准 SHA-256；路径、命令、URL、SQL 与报告正文均无法由模型传入。服务端只读取
owner-only 单任务目录的固定请求/批准文件，并复用 FX-01 Publisher。

实施中发现前门摘要校验与 Publisher 再开文件之间存在整组换包窗口，现由 Publisher 接收并在自身
打开文件后复核两个 expected digest。新增负向在前门通过后替换一套内部一致的请求和批准，稳定返回
`publication_request_expected_digest_mismatch`，没有产生发布目录。symlink、hardlink、宽权限、task
traversal、摘要漂移及任意 readback key 继续失败关闭。

真实 Hermes 0.21 MCP 注册只发现 allowlist 中两个工具。服务器为 `trust: untrusted`，写工具
`readOnlyHint=false`：首次 deny 没有副作用；accept 后经原生 `model_tools` dispatcher 产生 v1，固定读工具
`readOnlyHint=true` 读回同一摘要，重复发布幂等返回 v1。AgentShield adapter 以精确 MCP 工具名验证 hold
批准绑定 session、runtime task、工具和规范参数，request digest 改变不能取得原批准的执行预留。

现场调用还暴露 Hermes stdio watcher 重复创建未 await 协程的问题。新
`0005-mcp-watcher-coroutine-lifecycle.patch` 只构造并复用一个 watcher awaitable，patch SHA-256 为
`b410492f83a0c210c2860971919cbf9547dd5377667d5dc15729daa14667d9c7`，下一代五补丁 bundle 为
`e091ea2692ac1bf7a1d2a0c0e18be9171eeb08410bdaca2d4f43c790039ded90`。原生 MCP 回归 112 项、
AgentShield adapter 124 项、研究聚焦 37 项通过；五补丁构建上下文生成且三次 mount scan 通过，真实 proof
RuntimeWarning 为 0。

通用 terminal 保持启用和 `command_approval=manual`，Hermes `approvals.mode=off`；其语义继续按
`unknown_requires_external_policy_or_human_approval` 处理，由 required AgentShield gate、OpenShell 边界和
业务服务端合同共同约束，正则命令黑名单不作为授权事实。MCP 覆盖层和第五补丁仍是下一代非生产候选，
没有并入冻结活动 profile、生成替换 ARM64 镜像或迁移活动 pool。脱敏汇总见
[BU-01 证据](../evidence/flagship-optimization-20260921/bu-01-controlled-business-tool.json)。

## OC-01 OpenClaw 对等验证实际结果

本机实际 CLI 为 `OpenClaw 2026.9.5 (ec9c1a1)`。新增
`patches/openclaw/compatibility.v1.json`，把 `upstream-stock` 和 `siq-controlled` 分开登记，并固定
库存目标文件、受控结果、补丁及适配器摘要。库存版本已有 before/after hook、原生 UUID epoch、平台审批和
resolution 通知，但没有批准后执行前的最终参数复查回调；SIQ adapter 因此在进入平台审批前拒绝 hold。
受控启动器只对全新 0700 私有副本应用 `2026.9.5-approval-execution-recheck-v1.patch`，并将兼容清单纳入
`prepare/inspect/run` 门禁。清单补丁摘要被篡改时拒绝，受控副本经公共入口返回精确版本；全局库存文件摘要
保持不变。

真实网关、插件加载器、平台 operator WebSocket 和 before wrapper 完成 **20/20**：库存业务 hold 1、普通
审批 6、授权撤销 2、检查点故障/最终参数变化 9、受控业务工具 2。总计 46 条回执链验签，四条允许路径各
产生且只产生一条 reservation 与 observation；拒绝、取消、失联、撤权、抛错、Promise reject、`undefined`、
非布尔 truthy、五秒超时、取消信号和参数变化均为零执行。

OpenClaw 使用与 BU-01 相同的
`mcp__siq_business__research_publish_report(task_id, request_sha256, approval_sha256)`：精确参数在受控档执行
一次；平台批准后替换 `request_sha256` 则最终复查拒绝。库存档同名工具保持失败关闭。该 OpenClaw executor
只写合成本地标记；真实 Publisher、读回、幂等和拒绝零副作用由 Hermes BU-01 证明，因此不把组合结果宣称为
生产外部效果原子性。

适配器原生场景 50 项、业务合同 harness、研究仓 37 项聚焦回归及 Python/Node 语法检查通过。Step Plan
`step-5-preview` 另以 0600 文件 SecretRef 配置为 OpenClaw 首 fallback，保留原 primary；配置 schema、引用
解析、模型枚举和公开合成 prompt 的 `agent exec` 均通过，主配置不含 StepFun 明文密钥。密钥此前出现在会话
文本中，仍需轮换；该云模型不会进入 `confidential_local` 路由。2026-09-22 再次验证配置和 0600 凭据权限，并用显式模型执行独立公开合成 `agent exec`；命令正常退出、模型身份和预期标记均匹配。脱敏证据见
[OC-01 对等验证](../evidence/flagship-optimization-20260921/oc-01-openclaw-parity.json)与
[Step 5 配置验证](../evidence/flagship-optimization-20260921/oc-01-stepfun-openclaw.json)。

## SP-02 配额与遗留治理实际结果

新增单一资源合同 `infra/openshell/resource-governance/profiles.v1.json`，定义正式业务、canary/pool、wide
pilot、安全探针、Hermes minimal PoC 和 observe PoC 六个档位。每次新建都从合同取得 CPU、内存和 GPU
数量，生成 `0600` 私有租约，并把档位、合同摘要、责任主体、用途和 Unix 到期时间写入 OpenShell labels。
正式 transaction 的 sandbox intent/receipt 绑定租约摘要；启动和状态复核合同与标签，新租约到期后状态降级，
身份验证后的清理仍可执行。OpenShell 0.0.83 没有 per-sandbox 磁盘/PID CLI 参数，因此未虚构对应能力。

只读盘点在 CLI 因 gateway identity 门禁失败时，只允许从 SQLite `mode=ro` 读取四个元数据列，不读取 payload。
两台旧 canary 最初进入忽略提交的 `0600` 私有台账；随后逐台完成身份验证、停止和新 generation 创建，避免按名称强删或复用旧状态。inventory 清空后，事务入口构建、验证并激活目标 gateway patch，再复核进程身份、activation record 和受保护 listener。最终数据库中只有两台新式 canary，`total=2`、`compliant=2`、`requires_action=0`、`payload_column_read=false`，资源审计与 gateway runtime identity 共同给出 `operational_ready=true`。

真实第二槽位启动暴露固定 relay bridge 端口冲突，决策桥因此升级到 v2 的有界按槽位端口。两台当前 canary 的 manifest 均绑定资源档位、完整 hex 合同摘要和到期时间；OpenShell label 使用 43 字符无填充 base64url 保留同一 256 位摘要。沙箱 policy、环境 endpoint 与 relay v2 配置端口一致，上游固定 loopback，scope authority 文件为 0600，容器环境不含明文 AgentShield token。`siq-openshell-control` 升至 0.4.0，`env.sh` 对源码/安装版本漂移失败关闭；首次新槽位还完成了 stop/recreate 演练。

验证包括资源/环境/pool **42 passed**、运行时/生命周期 **135 passed**、relay/policy **60 passed**、研究聚焦 **127 passed** 和另一组聚焦 **94 passed**；AgentShield `go test ./...`、`go vet ./...` 与四个平台交叉编译通过，另有 Python compile、shell 语法、ruff 和双仓 diff 检查。负向覆盖缺失 CPU/内存、意外 GPU、标签/租约篡改、遗留证明过期、SQLite payload 不读取、gateway patch identity 漂移、旧控制包、relay v1 与多槽端口冲突。
脱敏结果见 [SP-02 证据](../evidence/flagship-optimization-20260921/sp-02-resource-governance.json)；恢复顺序见研究仓
`docs/runbooks/openshell/resource-governance.md`。

## SP-01 最终机密候选锁实际结果

最终 ProfileManifest 以版本控制源码作为 v0.21 候选输入，结果为 `candidate_build_consistent=true`；宿主物化配置和活动旧 pool 与候选不同，因此 `release_consistent=false`、`production_eligible=false`。该差异是发布边界，不会被自动修正或覆盖。

新增 `runtime-lock.confidential-candidate.v1.json` 与 `candidate_doctor.py`，固定 patched gateway、Hermes 0.21 镜像和分类、ProfileManifest、required gate patch、候选 lifecycle、NW-01/DT-01、受治理模型 host proof、真实沙箱推理及 8006 路由撤销 proof。镜像 state/smoke 使用候选 ID 下的不可变快照，不再引用会被下一次构建替换的 current 指针。真机检查中，候选包的配置、gateway 构建、身份、数据安全、推理证据及未推广边界六层均为 `pass`，`candidate_package_ready=true`。

初次在线附加检查发现 8006 loopback 与 OpenShell bridge 均返回 `Ornith-1.5-35B-A3B-NVFP4`，而锁定候选是 `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4`；OS-01 收口时两个端点均不可达。两次观测都令 `live_environment=fail`、`current_environment_ready=false`。隔离候选网关本身健康且库存为零。该结果保留操作者模型状态，并阻止历史 Nemotron 证据被误用为当前在线模型证明。脱敏报告见 `docs/evidence/flagship-optimization-20260921/sp-01-confidential-candidate-doctor.json`，最终候选清单见 `sp-01-confidential-candidate-profile-manifest.json`。

## CI-01 原生候选门禁实际结果

新增 `native-candidate-gate.v1.json`、`native_candidate_gate.py` 和只允许手动触发的
`dgx-spark-native-candidate.yml`。runner 必须同时具备 `self-hosted/Linux/ARM64/dgx-spark/siq-openshell`
标签；平台回执复核 DGX Spark 产品名、aarch64/arm64、GB10、当前 GitHub SHA 与三仓洁净绑定。安全仓因
lock 文件无法包含其所在 commit 的自引用哈希，使用“锁定基线必须是当前 clean GitHub SHA 的祖先 +
所有候选 artifact 精确摘要”；研究仓和 Hermes 继续要求 exact HEAD。

最终 verifier 只接受同一 candidate/batch/policy/GitHub SHA 下的新鲜证据：所有 candidate doctor 层级必须
`pass`，资源审计必须 `gateway_status=healthy`、`operational_ready=true` 且 `payload_column_read=false`，
四个固定 suite 的命令摘要、执行器摘要、仓库 HEAD、退出码和私有日志摘要必须一致。原始测试日志只留在
runner 的 `0700` 私有目录，artifact 只上传脱敏 JSON。缺报告、旧报告、漏 suite、dirty tree、错误硬件、
错误标签、模型漂移或 gateway hold 均失败；最终报告固定保留 `production_eligible=false` 和
`deployment_verified=false`。

回归先发现 Hermes `api_server_runs.py` 将 `aiohttp.web` 和可选 `RequestKey` 放在同一个 import try 中；
当前 aiohttp 不再导出后者时，模块把前者也覆盖为 `None`，选择集中的 36 个 `/v1/runs` 场景返回 500。
拆分导入并增加缺失 `RequestKey` 的负向加载测试后，Hermes 固定集 **91 passed**。其余固定集为安全候选
**31 passed**、Hermes adapter **124 passed**、研究 OpenShell **96 passed, 1 skipped**；工作流合同、Action
pin、YAML、Python compile 和 diff 检查通过。

本机平台探针确认 aarch64、DGX Spark、GB10 和标签均符合，但三仓都有本轮未提交变更，因此
`repositories=false`、`ready=false`、退出 1。SP-02 已把 gateway 与资源审计恢复为健康，但不会越过仓库洁净、
模型在线和原生 batch 门禁，也没有生成虚假的 native pass。进一步复核确认锁定机密镜像已包含 aiohttp
兼容修复：SOURCE_BASELINE 中的 0001 补丁摘要与冻结文件一致，candidate lock 新增二者的不可变摘要，doctor
在 `--network none`、只读、无 capability、`no-new-privileges` 容器中导入真实模块并确认 `aiohttp.web` 可用。
更新后的 doctor 为候选包六层 `pass`、`candidate_package_ready=true`，仅两个 8006 实时端点使
`live_environment=fail`；专项测试 **11 passed, 11 subtests passed**。脱敏结论见
[CI-01 证据](../evidence/flagship-optimization-20260921/ci-01-native-candidate-gate.json)。

随后按锁定治理合同尝试启动本地 Nemotron：模型、drafter、配置摘要和 vLLM 镜像均与 route 一致，但当前
并存模型负载下在 CUDA 引擎初始化阶段因内存不足退出。现有 Qwen、embedding 和 reranker 服务均未停止或
重配，也没有降低 0.27 GPU memory fraction、上下文、并发或 parser 参数来制造不一致的 8006 服务；失败
日志保存在 0600 私有目录，公开 CI 证据只记录失败类别和摘要。因此在线门禁继续诚实保持失败。

这次失败探测还暴露了 8006 bridge 的连接任务只由事件循环弱引用，日志出现过悬空协程告警。研究仓桥接器已改为显式持有连接任务，连接完成时消费结果，停机时取消并等待在途 handler，同时成对回收双向 copy 任务。专项测试 **8 passed**，连同 endpoint/route 合同 **31 passed**；user systemd 单元重启后 50 次上游离线连接均快速失败关闭，服务保持 active、任务数回到基线，当前启动周期没有同类告警。该修复提高离线与重启稳定性，不改变 8006 模型仍离线的门禁结论。脱敏证明见
[模型桥生命周期证据](../evidence/flagship-optimization-20260921/ci-01-model-bridge-lifecycle.json)。

同机 8005 Qwen/SGLang 服务还暴露出独立的凭据卫生问题：旧启动入口把 API key 写入脚本默认值和
`--api-key`，宿主 Docker 客户端与容器 Python 进程参数都可见。机器级脚本中的明文已原子迁移到用户私有
`0600` JSON 文件，脚本本身改为 `0700` 且不再包含密钥或密钥参数；研究仓新增安全启动包装器，从只读私密
文件加载凭据、拒绝 CLI/admin key，并通过 `sitecustomize` 脱敏父进程及 spawn 子进程的 SGLang
`ServerArgs` 日志表示。单元测试 **18 passed**，实际 SGLang 镜像内的文件读取、父/子进程脱敏集成验证通过，
版本化启动器与包装器摘要匹配。当前 8005 服务的鉴权健康仍为
200，但为避免未经计划改变其非 loopback 发布地址，本轮没有重启它；两个既有进程仍保留旧 argv，必须在
受控维护窗口用新入口重启后才能关闭运行态暴露。脱敏证据见
[SGLang 凭据传输证据](../evidence/flagship-optimization-20260921/ci-01-sglang-secret-transport.json)。

## ML-02 容量驱动的独立 Qwen3.8 备选候选

2026-09-22 DGX Spark 容量采样显示约 121 GiB 统一内存、103 GiB 已用、18 GiB available，15 GiB swap 几乎耗尽；Qwen3.8 scheduler、embedding/reranker/MinerU 等并存。此前锁定 0.27 GPU fraction 的 Nemotron 在 CUDA 初始化阶段 OOM，因此不应通过缩小锁定参数或暗中停掉其他模型让现有 CI 假通过。研究仓新增**独立** `candidate.v1.json`，以完整字节 SHA-256 锁定 Qwen3.8 主模型、MTP、draft、配置和模板，以及 SGLang 镜像与全部关键推理参数。原 Nemotron `governed-model-routes.json`、其机密镜像指针和活动池均未改写。

只读真机审计器对固定容器执行镜像/参数检查，并通过 Docker 私有 bridge、私密文件中的凭据完成受鉴权模型枚举和合成公开标记推理。**模型可推理**的检查通过；`host_candidate_ready=false`、`candidate_ready=false` 仍由当前非 loopback 发布、旧 argv 密钥、文件型密钥未启用三项主机缺口及机密 route/policy、受鉴权 OpenShell bridge、Hermes 沙箱推理、路由撤销失败关闭四项下游门禁阻断。审计器不会读取企业数据、改变容器或切换路由，返回 1 是预期阻断；专项含既有路由/编译回归 **27 passed**，ruff/编译通过。一次采样未发现 8005 活动 TCP 连接，但这不足以证明没有外部计划任务或其他调用方，重启前仍需核对调用方。脱敏证据见 [ML-02 审计](../evidence/flagship-optimization-20260921/ml-02-qwen38-isolated-candidate-audit.json)，操作与回滚顺序见研究仓 独立候选手册（本机路径：`/home/maoyd/siq-research-engine/docs/runbooks/openshell/qwen38-isolated-candidate.md`）。

后续新增独立 8005 受鉴权代理与 systemd unit：固定 Docker bridge 网关监听、loopback 上游、两个私密文件分离客户端与上游密钥、限制方法/路径/模型/请求与响应大小、关闭上游错误正文转发。安装前与既有 8006 桥的离线夹具共 **24 passed**，ruff、脚本入口和 unit 语法检查通过；这是历史离线阶段。流式响应采用有界缓冲，仍需真实 Hermes 延迟与兼容性验证；这不会把 `authenticated_openshell_model_bridge_verified` 提前标为通过。证据见 [ML-02 代理离线验证](../evidence/flagship-optimization-20260921/ml-02-qwen38-authenticated-bridge.json)。

独立 `qwen38-governed-route.v1` 再把候选物料锁的字节摘要、Qwen 模型 ID/上下文、8005、`confidential_local`、禁止云回退和沙箱客户端令牌环境名纳入路由合同。配置编译器只有显式选择 Qwen 且启用 AgentShield required gate 才允许 8005；模型、委派和辅助模型统一指向该路由，fallback 为空，终端 passthrough 不含令牌。快照入口要求全新 `--fresh --compile-config --require-security-plugin`。机密策略编译器在同一显式候选下仅保留 8005 模型端口，保留 broker 与 AgentShield relay，不保留公网路由；输出必须在独立 Qwen 路径，拒绝复用 Nemotron 镜像状态证明。五组聚焦回归 **78 passed**，合并模型桥相关共 **102 passed**；当前 DGX Spark 的只读 policy dry-run 得到模型端口 `[8005]`、无公网出站，未写入策略或改变活动池。业务沙箱实际应用与正向令牌调用仍未完成；独立协议负向探针见下文。路由编译证据见 [ML-02 路由编译证明](../evidence/flagship-optimization-20260921/ml-02-qwen38-governed-route-compiler.json)。

候选 Provider 清单与 profile 单独落盘，不进入主网关默认 manifest。项目 OpenShell 0.0.83 的 profile lint 接受固定 `host.openshell.internal:8005` 的 `GET /v1/models` 和 `POST /v1/chat/completions`。候选网关当时无 sandbox，Provider v2 从未设置改为 `true`；从单一 0600 宿主 JSON 读取与上游密钥不同的令牌后，`siq-qwen38-bridge` 真机安装和 gateway 导出通过，主网关仍无该 Provider。provider 回归 **32 passed**，ruff/编译通过。该阶段只证明受控凭据入口已注册，**尚未证明 sandbox 内 placeholder 解析或实际推理**；当时独立 bridge unit 尚未启动。见 [ML-02 Provider 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-provider-provision.json)。

随后手动启动 bridge user unit（不设开机启用）。首次启动暴露 systemd 用户文件系统隔离把宿主 root 文件显示为 overflow UID，Docker 二进制所有者校验误拒；现仅在当前用户单 UID `uid_map` 的精确条件下接受该映射。服务稳定监听 `172.23.0.1:8005`，旧 SGLang 仍在 `192.168.2.121:8005`。从 Docker 项目网桥内临时只读容器测试，无/错令牌 401，正确令牌因 loopback 上游未迁移返回空体 502；宿主来源被子网限制拒绝。bridge endpoint、代理和 Provider 相关回归 **75 passed**，ruff 通过。该负向运行证明只覆盖隔离与失败关闭，不覆盖 Hermes sandbox attach、真实模型推理或撤销。见 [ML-02 运行态 bridge 证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-live-bridge-negative.json)。

安全版 Qwen 同名 systemd unit 已版本化但未安装到运行槽位：固定 `PUBLIC_HOST=127.0.0.1`，移除旧 `EnvironmentFile`，沿用锁定镜像和完整 SGLang 参数。启动脚本在删除旧容器前执行快速预检；独立 `--full-artifacts` 复核了完整主/MTP/draft 摘要、镜像 ID/RepoDigest、私密密钥与参数，旧服务真实合成枚举/推理也通过。受限容器内从文件读取密钥和 `ServerArgs` 日志脱敏导入通过，专项回归 **24 passed**，ruff、bash、systemd 验证通过。旧服务最近两小时仍有 13 次请求，最后一次距采样不到一分钟，切换会造成冷启动中断，因此本阶段未停旧服务；全局 `launcher-sources.sha256` 校验仍被另一个已修改 MinerU 文件阻断，Qwen 相关条目单独通过。见 [ML-02 安全切换预备](../evidence/flagship-optimization-20260921/ml-02-qwen38-secure-cutover-preparation.json)。

随后在独立候选网关创建短命协议沙箱：使用锁定 Hermes 0.21 镜像，但不挂载业务目录、不启动 Hermes 网关，只运行受限 Python 模型枚举。Provider 真实挂载，环境值保持 OpenShell 占位符；错误 Bearer 为 401，正确占位符在未迁移的 loopback 上游前得到 502。1 CPU/1 GiB/900 秒资源租约和随机 nonce 绑定，`--no-keep` 后确认候选网关零沙箱；旧 SGLang 与活动池未改。负向与资源治理测试 **9 passed**，ruff 通过。仅关闭了 Provider 沙箱注入的协议负向缺口，不覆盖 Qwen 正向 200、真实 Hermes 推理、业务 scope、AgentShield 或路由撤销。见 [ML-02 Provider 沙箱证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-provider-sandbox-probe.json)。

随后做真实撤销演练：基础 policy 去掉 8005 后，Provider 组合策略仍有端点；基础路由和 Provider 都撤销、有效策略显示零端点时，旧沙箱立即和 2 秒后的请求仍到达桥接服务得到 502，约 10 秒后才变为 403。脚本因此把 `policy_revoke_immediate=false` 记为失败门禁，不能以最终 403 或 Provider 清单为空代替即时断路；见 [ML-02 撤销缺口证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-route-revocation-gap.json)。

接着在旧沙箱仍运行时原子轮换宿主 0600 bridge 客户端令牌；bridge 每次请求重读该文件，本次旧沙箱首个后续请求在 293 毫秒内得到空体 401。旧沙箱删除且候选网关为空后，Provider 更新到 resource version 2；新沙箱重新得到错令牌 401、有效占位符且上游离线 502。相关聚焦回归 **32 passed**、ruff 和脱敏检查通过；这是独立协议代际轮换证明，正式 Qwen 业务 lifecycle 尚未接入令牌先行撤销，也没有真实模型推理。见 [ML-02 令牌撤销证明](../evidence/flagship-optimization-20260921/ml-02-qwen38-token-revocation-mitigation.json)。

已另建 Qwen 专用的 `fresh` 机密 Hermes 运行快照，仅包含编译后的 `config.yaml` 和 manifest，未复制宿主会话或数据库。快照要求安全插件、固定 Qwen 路由、空 fallback 和禁云回退；挂载安全扫描与 **34 passed** 聚焦回归通过，既有 Nemotron 镜像指针保持不变。共享镜像构建器仍绑定 Nemotron 候选状态与 MiniMax 模板，因此不能用于 Qwen；后续独立镜像路径见下文。见 [ML-02 新鲜运行快照](../evidence/flagship-optimization-20260921/ml-02-qwen38-fresh-runtime-snapshot.json)。

初次独立衍生构建发现现有 Nemotron Hermes 0.21 镜像仍是四补丁版本，缺少当前源码的 MCP watcher 生命周期修复；该旧衍生镜像没有进入候选状态。随后在不改 Nemotron 指针的前提下，按精确 lock 生成五补丁 Hermes 0.21 独立基础镜像，再构建 Qwen 衍生镜像，移除 MiniMax auth 模板，把上述 fresh 快照配置和专用启动校验绑定到内容摘要标签；只写 `var/openshell/qwen38/` 的两个独立状态文件。`--network none`、只读根文件系统和合成 OpenShell 占位符下，真实 Hermes 网关达到 Docker `healthy`，启动后 auth 仍为空；Qwen 校验与相关快照/路由回归 **44 passed**，ruff 通过。此阶段是镜像与离线网关启动证明，不含 OpenShell 业务沙箱或 Qwen 正向推理；见 [ML-02 Qwen 专用镜像证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-dedicated-hermes-image.json)。

随后以该专用镜像在候选网关创建 1 CPU/1 GiB 的真实短命 OpenShell 沙箱，不挂业务目录。首次尝试发现 OpenShell 不继承镜像中的运行身份环境，entrypoint 预检失败；保留失败证据后复用正式 Hermes lifecycle 的显式环境注入。修复后镜像配置摘要、entrypoint 预检、Provider v2 占位符与错令牌 401/有效占位符 502 全部通过，沙箱自动清理为零；与相关镜像、快照、路由回归合计 **50 passed**，ruff 和脱敏检查通过。此处尚未启动持久 Hermes 网关，也未做正向 Qwen 推理、企业业务 scope 或令牌先行生命周期撤销。见 [ML-02 专用镜像 OpenShell 探针](../evidence/flagship-optimization-20260921/ml-02-qwen38-dedicated-image-openshell-probe.json)。

再以 1 CPU/2 GiB 的独立最小租约运行持续 Hermes 网关；候选 OpenShell 沙箱内认证 `/health`、空 auth 和 Qwen 编译路由均通过。初次公开合成 run 创建返回 202，最终为 `failed` 且不含成功标记，沙箱按 nonce 清理为零；后续诊断证明这次失败发生在模型请求前，不能视为 loopback 上游离线推理尝试。Hermes API 的 `model` 字段是网关别名 `siq_analysis`，不能拿它代替底层模型身份；首次 verifier 误判的脱敏失败证据已保留，并改用编译配置摘要约束 Qwen route。相关聚焦回归 **59 passed**，ruff 与脱敏检查通过。该初次 run 未到达模型桥；E55 修复后才证明模型桥 502。正向推理、企业 scope、AgentShield 工具动作和正式生命周期撤销仍未证明；见 [ML-02 Hermes/OpenShell 网关探针](../evidence/flagship-optimization-20260921/ml-02-qwen38-hermes-openshell-gateway-bootstrap.json)。

进一步将 token-first 顺序放进持续 Hermes 候选 generation 演练：旧沙箱认证健康且 bridge 基线为 502 时原子轮换宿主 0600 客户端令牌；旧 Provider 的首次后续请求返回桥接空体 401，Hermes 合成 run 创建 202 并以 `failed` 终结。旧沙箱按 nonce 身份清理、候选网关清空后才更新 Provider；新建沙箱认证健康，bridge 重新给出 502，最终两代均删除且网关零沙箱。专项与相邻探针 **22 passed**、ruff 和脱敏检查通过。该证明覆盖候选 Hermes 网关的真实生命周期撤销顺序，但 502 是上游离线失败，run 未与单条 bridge 请求关联；企业业务 scope、正向推理及生产业务 writer 的停止/恢复尚未证明。见 [ML-02 Hermes generation 撤销证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-hermes-generation-revocation.json)。

逐请求回执演练揭示 E53 初次 run 的失败发生在模型请求前：旧式 custom Provider 的显示名与固定路由 ID 不一致，试图在 legacy 列表添加 `provider_key` 又被 Hermes 兼容归一化丢弃；基础镜像的私有运行态子目录也由 root 持有，导致 Provider 解析时 `PermissionError`。现在 Qwen 专用配置改用 keyed `providers`，镜像将运行态子目录交给 sandbox 用户，启动时验证 `logs/curator` 可创建；构建器增加无网络真实 Provider 解析检查。新 `fresh` 快照生成独立镜像后，真实沙箱中的 Hermes Provider 解析和运行态权限通过，合成 run 唯一标记 SHA-256 在 bridge journal 找到一条 502 回执，run 终态 `failed` 且无成功标记；新镜像上的 token-first 代际撤销亦复验通过。旧失败私有证据保留，公开投影已更正 E53 的“推理尝试”结论。**88 passed** 聚焦回归、ruff、bash/systemd 及脱敏检查通过。502 仍表示 loopback SGLang 上游离线；见 [ML-02 Hermes/bridge 逐请求证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-hermes-bridge-trace.json)。

策略与企业 scope 的绑定也已补强：策略编译器接受私有 `0600` scope 引用，并把唯一可写的公司 `analysis` 路径、数据分类和 `company_wiki` 权限与 scope 精确匹配；正式 lifecycle 比对 scoped mount 与策略摘要的同一 scope 摘要及授权快照摘要。DGX Spark 上的可复跑合成证明（本机路径：`/home/maoyd/siq-research-engine/scripts/openshell/prove_qwen38_policy_scope_binding.py`）编译得到只含 8005、无公网路由的策略，跨公司写路径返回拒绝。聚焦及相邻 **170 passed**，ruff、语法和 diff 检查通过。该证明没有挂载真实企业资料，也没有让 Qwen 业务沙箱执行工具；见 [ML-02 策略/scope 绑定](../evidence/flagship-optimization-20260921/ml-02-qwen38-policy-scope-binding.json)。

进一步在候选网关上使用**唯一合成公司目录**应用 8 项 scoped mount 和上述 Qwen 机密策略：真实沙箱内 Hermes 网关健康，授权公司文件读取、任务 `analysis` 写入/读回通过；另一合成公司读取及公司根目录写入均被拒绝。受鉴权模型桥仍为上游离线 502；沙箱按 nonce 删除，临时合成目录、快照、策略和挂载计划均清理，网关回到零沙箱。清理碰撞、未知文件和 inode 替换拒删有 4 项专项测试；扩展后聚焦回归 **136 passed**、ruff 和脱敏检查通过。它证明合成文件 scope 与策略在真实 OpenShell 中生效，尚未证明真实 IAM、AgentShield 工具决策、Qwen 正向推理或正式 writer 停止/恢复。见 [ML-02 scoped sandbox](../evidence/flagship-optimization-20260921/ml-02-qwen38-scoped-sandbox.json)。

该真实候选沙箱又以短时签名身份访问严格模式 broker：合成同市场 `SELECT 1` 返回 200，跨市场、跨项目、无私有 scope、不安全对象读取均返回 403，缺少身份返回 401；五条带身份请求有规范审计回执。首次直连 socket 被沙箱网络拒绝，改用遵循 HTTP 代理的客户端后到达 broker；首次合成对象 scope 不足也保留脱敏失败证据并修正。当前 broker 不在线复查候选 sandbox generation，v3 gateway 声明仍固定为开发网关，故**不能据此宣称即时撤销或候选网关来源证明**。短时令牌经沙箱创建参数注入，正式路径仍需收紧。公开证明见 [ML-02 scoped broker](../evidence/flagship-optimization-20260921/ml-02-qwen38-scoped-broker.json)；真实 IAM、机密资料、Qwen 正向推理和正式 writer 撤销仍未验收。

为收口这一缺口，后续源码已让候选 gateway 成为受限签名字段，并新增宿主私有在线准入表。候选数据请求必须由 broker 逐次比对签名身份和登记的令牌摘要、沙箱、策略、nonce、generation；查询期间持共享锁，撤销持独占锁并等待已准入查询结束。隔离本地 HTTP 的允许 200、撤销后 403、状态损坏 503、无登记或错误 gateway 拒绝，以及并发等待均通过；聚焦及相邻 **124 passed**、ruff 和语法检查通过。该表尚未由 Qwen 生命周期发布/撤销，活动 broker 未重启，真实候选沙箱未重跑；签名 gateway 也不能单独证明网络来源。因此状态仍为**离线合同通过，运行态撤销未验收**。脱敏投影见 [ML-02 broker 在线准入离线合同](../evidence/flagship-optimization-20260921/ml-02-qwen38-broker-online-admission-offline.json)。

E60 将离线合同带入**真实隔离候选沙箱**：策略编译只在 Qwen route 与企业 scope 同时存在时路由至专用 18794；宿主以短时合成 broker 登记签名身份，沙箱通过 OpenShell HTTP 代理执行公开 `SELECT 1` 得 200。候选专用模式拒绝开发网关身份 403；沙箱尚未停止时撤销同一登记，旧 generation 重发被拒，同一沙箱/令牌重试得 403 `broker_admission_denied`。v2 准入表持久保留最高 generation，旧 v1 状态失败关闭；加入候选查询助手后，合成后端与审计均有两次授权调用。令牌值已从创建参数移除，改由 `--upload` 传递宿主 0600 文件；沙箱内权限/归属及启动 shell 读取摘要通过，宿主临时源删除。随后沙箱、合成目录、准入状态与 18794 监听清理，活动 18793 broker 未重启。扩展后 **139 passed** 相关回归、ruff、语法、diff 与脱敏检查通过；[公开证明](../evidence/flagship-optimization-20260921/ml-02-qwen38-broker-online-sandbox.json)。它不证明正式 lifecycle 发布/撤销、网络来源、真实 IAM/数据库、AgentShield 工具决策或 Qwen 正向推理；沙箱 `/proc` 限制了 Hermes 进程环境直接观察，Hermes 原生工具继承身份仍未验收，失败观察证据已保留。模型桥仍返回 502，正式机密业务放行继续阻断。

E61 揭示并修正镜像/助手代际漂移：旧 Qwen 镜像内 `pg_query.py` 固定只接受 18793，首次真沙箱调用得到 `broker_url_not_allowed` 并失败关闭；宿主助手源码随后增加只限 `host.openshell.internal:18794` 的候选地址和固定 `0600` 上传身份文件校验。新 Qwen **派生镜像**将助手源码 SHA-256 纳入构建输入与镜像标签，完成无网络实际文件摘要、Provider 解析和 Hermes 网关启动检查。新镜像的真实候选沙箱直接运行业务助手，登记时退出 0 且合成查询成功，撤销后退出 2 `broker_admission_denied`；原始 HTTP 与助手两条授权请求各一次，撤销后的两条请求均无后端副作用。聚焦与相邻 **139 passed**、ruff、语法、脱敏检查通过；[E61 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-business-helper-candidate-broker.json)。这仍是沙箱内助手进程直调，未通过 Hermes gateway 工具 dispatcher，也未接真实 IAM/数据库或正式 Qwen lifecycle。

E67 将 `confidential_local` pool 准入从“只验证自包含快照”推进到业务库在线检查：新增显式、可撤销的用户/租户/项目/公司/对象范围 grant 表及前向迁移 016；每次进入机密路由读取当前账户启用/批准状态、角色、token 版本、grant 有效期和撤销状态，缺表或无 grant 均拒绝，并在准入失败时释放 pool 租约。隔离 SQLite 授权/撤权、pool 路由、运行生命周期及认证扩展回归 **122 passed**；一项旧认证测试夹具在二次提交后读取过期 ORM 对象的失败已单独复现并修正。migration governance 15→16 追加校验、改动文件专项 lint 和 diff check 通过；[E67 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-live-business-scope-grant.json)。grant 目前无正式 IAM 发放接口，Qwen 续期回调仍为合成，未联动生产 PostgreSQL、真实业务资料或正式 start/stop；所以仍不放行机密业务。

E68 增加研究引擎**仅非生产、显式开启**的本地机密 grant 发放/撤销 API：当前有效 `super_admin` 只能为另一名已批准用户发放，租户由服务端指定，机密分类固定，发放与脱敏审计同事务提交；重复发放请求用 `Idempotency-Key` 与迁移 017 的唯一约束保证只生成一条 grant，改包复用键拒绝，重复撤销不增加审计。真实 API 路由已注册；隔离数据库的发放→在线准入→撤销→拒绝、无认证/普通管理员/自授权及数据库重复键唯一约束边界均有测试。扩展回归 **138 passed、1 个可选 PostgreSQL 用例因环境跳过**，migration governance 15→17 追加校验和专项 lint 通过；见 [E68 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-local-grant-administration.json)与本地候选授权手册（本机路径：`/home/maoyd/siq-research-engine/docs/runbooks/openshell/local-confidential-data-grants.md`）。此接口不能替代 SIQ IAM；撤销尚未即时撤回已在途 sandbox 的 broker 准入，正式 Qwen 续期/生命周期与生产 PostgreSQL 联调仍未完成。

E69 将 E67/E68 的本地业务库授权接到 Qwen lease 既有续期回调：每次 tick 使用新的数据库会话，要求原授权快照仍有效且 scope 摘要一致；隔离候选注册表验证授权期间 generation 1→2、旧令牌拒绝，撤销 grant 后下一 tick 拒绝并撤 broker 准入，新令牌再试被拒。API、路由、认证、迁移及 Qwen lease 组合回归 **149 passed、1 个可选 PostgreSQL 用例跳过**，专项 lint、迁移治理和 diff check 通过；[E69 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-live-grant-renewal-callback.json)。CLI 上传/安装在该用例中是确定性替身，没有真实沙箱、正式定时器、生产 IAM 或 PostgreSQL 联调；撤销仅在下一 tick 生效，尚不能声明即时撤权或全链路放行。

E70 收紧业务授权时间边界：候选初次 lease 登记现在必须传入从业务授权复核取得的截止时间，令牌过期时间越界时拒绝且不登记 broker；每次 tick 的授权窗口取原快照与当前在线 grant 截止时间的较早值。无截止时间的布尔允许、已越界的现有令牌均先撤权，新令牌 TTL 被授权窗口封顶。隔离 API/lease/迁移组合回归 **164 passed、1 个可选 PostgreSQL 用例跳过**，ruff 与 diff check 通过；[E70 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-authorization-window-boundary.json)。正式 start/stop、定时器与实时撤权尚未接入，不能从该离线合同推断生产及时性。

E71 对活动 Qwen3.8 宿主作只读复审：模型、镜像、运行参数和合成推理匹配锁定候选，但监听仍非私有、文件型密钥未生效、进程参数仍含运行密钥；host candidate 和 confidential promotion 均为 false。运行中的 8005 鉴权桥尚无迁移后 loopback 上游的正向推理证明，未重启活动模型。见 [E71 脱敏审计](../evidence/flagship-optimization-20260921/ml-02-qwen38-host-readiness-audit-e71.json)。

E72 在活动模型两小时内仅有本项目合成探针请求、无已建立连接且完整物料预检通过后，备份旧 unit 于宿主 owner-only 目录，安装安全 unit 并执行受控单实例切换。首次启动发现固定 SGLang 镜像的 `ServerArgs` 在解析后只读，旧安全启动器晚注入密钥导致 systemd 重试；立即停止重试，改为在 `ServerArgs.from_cli_args` 物化前注入私有文件密钥，禁止额外 `--config`。27 项启动测试及固定镜像内真实配置解析通过。约 320 秒冷启动后，宿主仅监听 `127.0.0.1:8005`，文件密钥已挂载，argv/environment 不含明文，锁定模型合成推理精确；新 unit 无自动重启，审计 `host_candidate_ready=true`、`candidate_ready=false`。旧 LAN 发布已移除，原 502 和首次失败日志保留；见 [E72 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-secure-host-cutover-e72.json)。安全 unit 仍手动启动且未设为开机启用。

E73 在 DGX Spark 独立 OpenShell 网关完成正向分层证明：Provider 沙箱错令牌 401、有效占位符经受鉴权桥得到精确 Qwen 模型 200；Hermes 0.21 合成 run 返回 202 后 `completed`，唯一标记出现在输出且桥 journal 有对应摘要的单条 200 回执。模型桥客户端令牌先行轮换，旧沙箱后续请求 401，旧沙箱清理后新代 Provider/沙箱为 200。进一步在同一个合成企业 scope 沙箱完成授权公司读取与 analysis 写入、跨公司读取和公司根目录写入拒绝，在线候选 broker 身份 generation 1→3 与停止前撤权；该沙箱的 Hermes run 在 broker 撤权前完成并关联 bridge 200。所有探针沙箱、合成源和临时 broker 监听均清理；相关 67 项测试及 ruff/diff 检查通过。见 [E73 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-positive-sandbox-chain-e73.json)。业务授权和后端仍为合成，正式 Qwen 生命周期、SIQ IAM、PostgreSQL 和 AgentShield 正向工具均未完成，不能据此将 `candidate_ready` 改为 true。

E74 修复模型桥的**在途客户端令牌轮换竞态**：每个 8005 请求从准入到响应发送持跨进程共享锁，轮换持独占锁，等待已准入请求结束后才替换令牌；锁缺失或不安全时空体 503。user systemd unit 使用私有运行目录和 0600 锁，配置重启期间保留锁 inode；旧 unit 已单独备份，新 unit 受控重启，Qwen 模型未重启。阻塞上游的并发测试证明轮换等待在途请求，旧代随后 401、新代 200；真实 Provider 错令牌 401/有效 200，真实 Hermes 代际演练旧沙箱 401、旧 run `failed`、清理后新代 200，网关归零。聚焦及相邻 **59 passed**、ruff/编译/systemd verify 通过；桥与模型仍 active、均无自动重启。见 [E74 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-bridge-inflight-revocation-e74.json)。这项改动没有在真实模型上制造可控在途请求，也未实现每沙箱独立模型令牌；正式业务即时撤权、SIQ IAM/PostgreSQL、Qwen lifecycle 及生产门禁继续阻断。

E75 把 Qwen 候选 lease、逐 tick 在线授权复核与停止前双断路收敛为 `CandidateRunGuard`：每 tick 必须看到候选网关**只有受控沙箱**，失权/清单异常/续期失败时按 broker 撤权→8005 客户端令牌轮换→按 nonce 删除沙箱→复查网关清空顺序处置；任一切断失败仍尝试余下切断，但不报告完成。普通停止与恢复也执行同一顺序，损坏 lease 时先撤 registry，模型和沙箱继续切断。宿主适配器绑定真实候选网关清单、受锁轮换与按 nonce 清理；轮换实现从证明脚本抽成独立模块。并发测试证明在途 broker 查询结束前停止不会走到模型轮换；本地业务库 grant 撤销后下一 guard tick 确实调用模型和沙箱处置回调，异物沙箱和不可观测清单均失败关闭。重叠专项分别为 guard **9 passed**、业务授权/scope **10 passed**、轮换/桥/guard 邻接 **40 passed**，ruff/编译通过。抽离后的轮换模块又在真实 Hermes 沙箱完成旧代 401、旧 run `failed`、新代 200，网关归零；见 [E75 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-business-run-guard-e75.json)。目前仍是可复用监督合同：真实业务沙箱尚未挂接，模型断路回调在 grant 单测中是替身，正式 start/stop/recover 入口、常驻定时进程、API 同步即时撤权、SIQ IAM/PostgreSQL 与 AgentShield 正向业务工具尚未完成。

E76 核对实际研究引擎 `siq_app` PostgreSQL 时发现数据库迁移账本已有 016–019，而研究仓此前未跟踪这四份源码，OpenShell 授权迁移原占 016/017。按实际账本的逐文件 SHA-256 从同源项目恢复 016–019，将尚未执行的授权迁移顺延为 020/021，更新仓库校验清单和运行手册；迁移治理门禁通过。先制作 owner-only、0600 的全库 custom 备份，在临时恢复库完成 020/021 迁移和重复执行空操作；实际库随后应用相同迁移，账本到 21、授权表仍为 **0 条**。第二个临时恢复库用合成管理员和分析师验证无授权拒绝、发放后允许、请求幂等、跨租户拒绝、撤销后拒绝及发放/撤销两条审计，临时库已删除，未更改正式账户或发放正式授权。联调还发现私有 `backend.env` 的两条数据库 URL 使用旧口令，先在私有备份目录保存 0600 原件，再按同文件且与容器一致的 PostgreSQL 口令修正，两个目标库均可连接；口令和 URL 值没有写入证据。聚焦 **21 passed、1 skipped**，ruff/diff 和实际迁移 runner 重复执行通过；[E76 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-postgresql-grant-migration-e76.json)。此项关闭了 schema 与数据库授权函数的真实 PostgreSQL 兼容性缺口，但正式 IAM、运行中即时撤权和 Qwen 生命周期仍未接入。

E77 对 E75 运行 guard 补上跨进程操作锁：此前 `threading.RLock` 只能保护同一监督进程，独立 stop/recover 命令可能与 tick 并发。现在在私有 lease 目录使用 owner-only、0600、拒绝符号链接的文件锁，取得锁后复核 inode；tick 内部错误在持锁时执行 broker→模型→沙箱断路。锁无效或 30 秒超时仍尝试全断路，但返回失败，避免误报已停止。一个独立进程占锁的测试证实 stop 等待释放后才断路；另一个测试证实不安全权限时仍撤 broker、调用模型和沙箱处置。guard 专项 **11 passed**，lease/身份/业务授权邻接 **30 passed**，ruff、编译和 diff 检查通过；[E77 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-cross-process-run-guard-e77.json)。目前还缺网关级启动锁、正式 sandbox 创建事务和常驻监督进程；这项测试不等于真实业务沙箱跨进程停止验收。

E78 新增候选网关单运行所有权控制器：正式创建前先在 0700 根目录写入 0600 `reserved` 占位；现存或损坏占位、不可观测或非空沙箱清单均阻止新启动。创建后仅当清单恰为受控沙箱才可转 `active`；释放会先运行停止回调，再复查网关清空，失败时保留占位供恢复。两个独立进程同时抢占的测试只允许一个成功，异常停止与异物沙箱不会释放占位；所有权锁 30 秒超时时仍尝试断路，但保留占位并报错。host guard 同时增加共享私有操作锁接线能力。owner/guard **16 passed**，扩展邻接 **32 passed**，ruff、编译和 diff 检查通过；[E78 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-gateway-ownership-e78.json)。该模块目前是正式 start/stop/recover 所需的持久原语，还未接入活动候选网关或真实业务沙箱，不把合同测试提升为端到端验收。

E79 将上述所有权和运行 guard 实际接到真实 Qwen 合成企业沙箱证明器的独立 `--supervised-lifecycle` 模式。现场预检确认候选网关及 owner 均为空、Provider 存在、严格身份数据 broker 正常；真实创建前保留 `reserved`，沙箱清单恰好匹配后激活。Hermes 0.21 合成 run `completed` 且唯一标记对应模型桥 200 回执；企业目录读写/跨公司拒绝、数据身份 generation 1→3、旧代拒绝继续通过。退出时实际 guard 撤 broker、轮换 8005 客户端令牌、按 nonce 删除沙箱并复查空清单；重新配置候选 Provider，新的正向沙箱探针再获 200 后释放 owner。临时 broker、合成资料、上传源、证明状态及沙箱均已清理，活动模型和桥 `NRestarts=0`；相邻 **44 passed**，ruff、编译与脱敏检查通过。见 [E79 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-real-supervised-sandbox-e79.json)。这是安全控制在真实 Hermes/OpenShell 上的首次完整受监督合成链，**未使用真实业务 grant 或 SIQ IAM，也没有独立进程的正式 start/stop/recover 与常驻 tick**，所以仍不放行机密候选。

E80 进一步把 PostgreSQL 的真实授权查询接进同一受监督运行。证明器只导出当前 `siq_app` 的 schema 到临时库，不复制生产行；临时库创建两个合成账户、发放一条短时精确 grant，使用业务 API 的授权快照构建该合成企业 scope。真实 Hermes 0.21 run 完成、模型桥 200 回执关联，broker 身份续期到 generation 3；在线业务授权复核在 grant 有效时允许，撤销后下一次 guard tick 实际撤 broker、轮换模型令牌并删除沙箱。Provider 重配、新代 200、owner/网关清空和临时库删除均通过，临时库授权和撤销审计各 1 条，正式库授权保持 **0 条**。相邻 **54 passed**、ruff/编译/diff 与脱敏扫描通过；见 [E80 脱敏证据](../evidence/flagship-optimization-20260921/ml-02-qwen38-postgresql-revocation-e80.json)。业务 broker 的查询后端仍是合成适配器；正式 IAM、生产用户授权、API 同步通知、独立 start/stop/recover 和常驻监督器仍需完成，不能把下一 tick 的撤权证明说成同步即时撤权。

## UX-01 实际结果

任务详情新增 `local-task-security-view/v1` 服务端摘要与响应式安全视图。服务端只消费已验签回执、签名
Intent 和效果证据：业务对象显示 task/intent 引用，缺少受信业务名称时明确不可用；运行模式区分平台、
block/warn/audit-only、模型路由和沙箱绑定；数据去向只显示 filesystem/network/message 域及 SHA-256，不返回路径、
主机、接收方、参数摘录或原文。授权按 action ID 最终状态统计，hold resolution 不重复算等待；allow/redact
必须同时具备 bound Intent 和 valid Authority 才计入已授权。Completion 的 verified 规则不变。

页面把授权、实际效果和候选/部署门禁作为三个结论。当前运行时没有 CI-01 证据合同，因此
`release_assurance=not_evaluated`，明确提示不能替代原生候选门禁、OpenShell 资源审计或生产批准；这与
当前 CI-01 `blocked_before_candidate_verification` 一致，没有在 UI 中硬编码可能过期的“通过”状态。

服务端负向覆盖默认响应不泄露 Purpose、参数摘录、沙箱 ID 和目标明文，旧快照/缺 snapshot/越权/错误方法
拒绝，未归属记录不能升级为可信业务对象或授权。共享 Go/TypeScript fixture 保证响应边界；前端拒绝伪造的
authorized、verified、release passed、明文 destination、业务名称和跨任务绑定。验证结果：
`go test ./...` 通过、`go vet ./...` 通过、Web **233 passed**、`npm run build:local` 通过。脱敏证据见
[UX-01 证据](../evidence/flagship-optimization-20260921/ux-01-task-security-view.json)。

## 下一执行顺序

1. E95–E108 已完成请求目录网关、私有准备/配置、沙箱创建、真实 broker/执行租约监督、身份持久清理、同 cgroup relay/forward、Hermes 引导、请求 HTTP 客户端与原 owner 心跳；最终两轮真实模型完成和两类停止回收通过。接下来按研究仓 `docs/architecture/qwen38-request-runtime-v1.md` 接正式 API 后端分支，完成按请求创建、排队、心跳、终态/恢复与保留业务输出的资源释放；必须显式处理旧 pool 空 binding 快捷分支，不能跳过新后端的所有权检查。保留 E107/E108 超时并继续观测模型延迟，不能把后续成功当作旧失败根因已修复。正式身份签发需来自受批准主体与 Grant，不能借用旧 canary 或让业务组件自动批准。之后完成真实 API 崩溃、模型自主数据工具与正式 IAM/审批验收。当前活动 8005 安全模型继续保留，正式机密流量不切换。
2. 恢复锁定的 8006 Nemotron 服务，或在 ML-02 全部端到端门禁通过后将 Qwen 作为**新候选**重新生成 Hermes 镜像/lock；不能用 ML-02 宿主推理替代原 Nemotron 机密沙箱证明。
3. 三仓形成可审查的干净候选后，在带固定标签的 DGX Spark 自托管 runner 执行 CI-01；失败继续保留 blocked，不把 UX-01 的任务级结果外推为部署通过。

每一阶段保留原始失败、skip、未验证和 canary 标记。没有当前候选原生证据的项目保持未完成。


## E81：Qwen 候选网关的受限决策桥合同

检查实际候选 gateway 配置确认：sandbox namespace 为 `siq-openshell-scope-validation`，
Docker bridge 仍为 `siq-openshell-dev`。旧 relay v2 在 Go 与 Python 中均只接受主网关
namespace 和 `siq-analysis-*` 名称，因此不能直接承载当前 `siq-qwen38-scoped-*` 沙箱。

新增 v3 合同、Go 双版本校验及研究侧显式 `--sandbox-namespace` 生成入口；v3 仅接受
固定候选 namespace 与带 16 位 nonce 的 scoped 沙箱名，保持原 Docker bridge、完整容器
身份、Runtime Identity、会话前缀、七条路由与固定 loopback 上游。v2 继续按原约束工作，
活动 canary 二进制、身份、配置和流量均未切换。

研究侧 relay/authority/相邻生命周期 65 项通过；Control API 全部 schema 合同、Go 全模块
测试、vet、relay/daemon 身份登记与撤销 race 集成、四目标主程序和 relay 编译、Ruff 与
差异检查通过。测试覆盖两版正常转发、跨身份/会话拒绝、管理路由隐藏和在线身份撤销；
容器 namespace 篡改在启动器被拒绝。

这是实际接线前的合同适配，尚未部署 v3 候选 relay、签发该候选身份或完成真实 Hermes
业务工具正向验收。后续应生成独立候选二进制摘要、签发最小 scope 的 Runtime Identity，
再把凭据文件、精确 relay 端口和会话 namespace 接入创建/停止流程。生产和总体门禁不变。
证据：[E81](../evidence/flagship-optimization-20260921/ml-02-qwen38-candidate-relay-contract-e81.json)。


## E82：真实 Qwen 沙箱的 Hermes 原生文件工具授权与撤销

已在实际 OpenShell 候选沙箱内完成 Hermes 0.21 原生 dispatcher 的 `read_file` 允许、
`write_file` 拒绝和独立文件不存在检查。AgentShield 的已验签回执精确绑定本次独立
Runtime Identity/Grant，允许读取具有 observation，写入拒绝原因为 `grant_scope_violation`。
通过真实管理 API 撤销该身份后，原生读取立即阻断，会话登记返回 401。
同一次受监督运行还完成 Qwen 推理、模型桥 200、数据身份续期、撤权停止和 Provider 恢复。

实机发现并修复两处此前直接 HTTP 探针无法覆盖的问题：Hermes adapter 原先只接受
loopback，拒绝 OpenShell 固定别名；取消通用环境代理后又无法经过嵌套网络 policy proxy。
现仅允许合法 managed identity + 绑定 namespace + 精确 relay alias/端口，且要求显式
固定 `SIQ_AGENT_SECURITY_OPENSHELL_PROXY=http://10.200.0.1:3128`；不使用任意环境代理、
NO_PROXY 或重定向。Qwen 新镜像按逐文件锁和镜像内校验包含修复后的适配器，主 context
编译 pin 与下一代 pool 启动环境同步更新，活动 canary 未热更新。

此前公司 canary 的 HTTP allow/deny 证据不等于原生工具 hook 正向证据。本次只补齐
Qwen 指定候选的原生文件工具链，仍不能宣称模型在 HTTP gateway run 中自动选择并执行
受控报告发布 MCP 工具。业务 MCP、正式 SIQ IAM、常驻监督器与完整原生 CI 仍待验收。

验证：适配器 143 项；研究接线/生命周期 67 项；镜像/配置 34 项；Go 全模块、vet、
四目标编译、Ruff、Shell/Python 语法与差异检查通过。扩大回归发现旧镜像资产测试把
创建目标目录误当成批量复制源码，现改为检查禁止整目录输入、仅允许已审核的两个业务
工具文件，34 项重新通过。临时身份/Grant 已撤销，profile、relay、沙箱、owner 与合成
目录已清理；审计/签名历史保留，模型和 bridge 均 active 且 NRestarts=0。

证据：[E82](../evidence/flagship-optimization-20260921/ml-02-qwen38-native-tool-security-e82.json)。
总体目标仍 active，`candidate_ready=false`、`production_eligible=false`。


## E83：Qwen 业务 MCP 镜像依赖与 SDK 2.0 兼容

实机检查发现 E82 的 Qwen 镜像包含业务脚本，但没有可选 MCP SDK，配置也未注册业务
MCP。新增显式 `--qwen38-business-tools`，只接受受治理 Qwen + required gate + fresh
快照，拒绝继承宿主 MCP。服务器限定两个报告工具、独立 `/sandbox/siq-business` 根、
untrusted 写批准、串行调用、禁 sampling 和资源/prompt 暴露。

构建从固定 Hermes uv.lock 锁定九个新增 wheel 的 URL、版本、大小、摘要；与基础镜像
内 uv.lock 摘要现场比对一致。逐 wheel 校验后在无网络 Docker 构建中通过
`--no-index --no-deps --require-hashes` 安装，没有复制宿主虚拟环境或修改活动公司池。
实际发现 MCP SDK 2.0 已移除 FastMCP 入口，业务服务器改用 MCPServer 并兼容 SDK 1.x。
又发现 Hermes 原注解读取只支持 camelCase，误把 SDK 2 的只读工具判为写工具；新增
摘要锁定 `0006` 补丁，兼容 snake_case，缺失/非布尔/冲突保持写批准。原五补丁基础
镜像和 SOURCE_BASELINE 不变，衍生覆盖层单独留痕。

新镜像 `sha256:a4acb1aa38565b94b9d4b935d719371d17d6d1a2566c97ab419f742911f626ae`
已通过 SDK 2.0 真实 stdio discovery、两个工具与读写注解核对、注解拒绝边界、原生
required gate 失败关闭、空 auth 和网关健康。随后真实 OpenShell 沙箱回归完成 Qwen
推理、模型桥 200、原生读允许/越权写拒绝、独立效果检查、签名回执和身份撤销阻断。
受监督停止、模型令牌轮换、Provider 恢复和临时资源清理通过，候选网关库存为零，
18794/47710 无监听，模型和 bridge 保持 active、NRestarts=0。

研究仓相关回归 **118 passed, 1 skipped**；跳过项是 API venv 未装可选 MCP SDK 的
原发现测试，该用例又在现有 SDK 1.26.0 宿主环境执行，业务测试 **7 passed**。
SDK 2.0 另在上述实际镜像验收。旧测试固定批准在 2026-09-22 到期却使用墙钟，现将
测试时钟固定到其 fixture 时间，未修改运行时批准有效期或跳过到期检查。Ruff、编译和
双仓 diff 检查通过。E83 两份 artifact 单独保存，E82 artifact 原字节保留。

证据：[E83](../evidence/flagship-optimization-20260921/ml-02-qwen38-business-mcp-image-e83.json)。
本次关闭的是业务 MCP 的部署与启动缺口；**尚未验证模型经 HTTP run 自动选择报告
MCP、网关 once 审批、实际发布与读回的同一链路**。SIQ IAM、常驻监督器和最终原生
CI 仍待验收。总体目标保持 active，`candidate_ready=false`、`production_eligible=false`。


## E84：模型驱动报告发布全链（2026-09-22）

真实模型第一次调用揭示固定报告 MCP 缺效果描述，AgentShield 正确以未知效果拒绝。
新增严格 `siq-research-business-call/v1` 后，两个工具完整名称、有限 ID/摘要参数与
`/sandbox/siq-business` 根绑定；发布需要读写授权，核验只读。超范围、只有工具名、
只读发布和参数变形均有负向用例。独立 47811 daemon/v4 relay 验证新逻辑，主服务不变。

第二次调用已经获得 AgentShield allow，但没有 HTTP 待审批事件：Hermes 0.21
把 `api_server` 一律列为无人值守，忽略了 `/v1/runs` 注册的按 run 审批回调。
Qwen 候选 0007 补丁仅将非 cron API MCP consent 送往精确回调；缺回调失败关闭。
新镜像离线真实队列验证跨 run、错误 request ID、重放、回调错误和取消；旧镜像同测失败。

修复后真实 Qwen/OpenShell 两轮 run 均完成：拒绝轮准确一个审批且无发布副作用；
单次批准轮完成发布版本 1、调用核验工具并通过独立读回。两个 publish 和一个 verify
决策/observation 精确匹配 run、Grant、参数摘要，签名链通过。原生文件允许/越权拒绝、
身份撤销、broker→模型→沙箱停止顺序、Provider 恢复与新代推理同时复验通过。
临时 daemon/relay/broker 监听消失，候选沙箱及合成资料清理；主 daemon、模型和桥未重启。

Python 相邻回归 100 passed、1 个 API venv 缺可选 MCP 的用例跳过；实际 SDK 2 镜像
发现、调用与读回另有真机通过证据。Schema 4 项、Go relay 三版本身份撤销集成及
四目标双二进制编译通过。完整 Go/静态检查见 E84 证据。

本轮批准文件及资料仍为非生产 fixture，不能替代正式 IAM 和生产发布审批；常驻监督、
独立业务 start/stop/recover 与原生 CI 仍未完成。总体目标继续 active。


## E85：实际业务 API 的持续授权复核（2026-09-22）

保留原服务端 `AuthorizedDataScope` 于内存路由；续租不重发快照，也不从公开摘要
恢复权限。每次心跳、后处理权限检查及创建新 run 前验证原快照时效、主体会话、
租户/项目/公司/市场、分类与双摘要，并验证 pool binding 的 scope/company/run。
机密路由以新数据库会话复核账户、token 版本、精确 grant 和当前权限，十秒复核超时
按拒绝处理；数据库异常只输出类别，不输出连接字符串或参数。

失权进入既有 heartbeat 停止和独立写静默确认；未知 writer 不释放。首次准入已占位
但查询失败/取消时释放未使用租约；明确发生在请求发送前的拒绝亦释放，而请求发送
后响应丢失仍保留 orphan writer。公开旧路由兼容不替代机密路由缺失快照的拒绝。

新增隔离数据库测试覆盖正向续租、撤销、失效账户、过期、跨主体/范围/代际、快照
篡改、超时、取消、运行与后处理阶段停止，以及跨仓导出无原始授权。相关 181 项
测试、ruff、编译与 diff 检查通过。一次角色负向夹具误用了仍具 company.view 的
VIEWER，已按真实权限语义改为撤除权限，并新增 VIEWER 显式授权读的正向兼容测试；
未更改业务权限表。测试从仓库根运行，与受控 API 启动脚本的导入根一致。

此轮 pool/Hermes 传输是替身、数据库为隔离 SQLite；默认 18081 探针不可达，没有
启动或重启业务 API。没有将该结果当作真实运行中 Qwen 双断路、正式 IAM、生产批准、
常驻宿主监督器或同步撤权通过。总体目标保持 active，候选和生产门禁不放行。

### E118：持久签发与部分交付恢复

原请求签发尝试先于 HTTP 持久化；同期限重试、部分交付按根身份取消、失权清理与损坏保留落地。191 项组合回归及隔离守护进程→真实 Hermes/v4→原生工具/签名回执→磁盘清理通过；原服务未重启，无 endpoint/模型推理/正式 API 请求。builder/selector、实际 API 重启、未知早期窗口、IAM/事件及原生 CI 待办。

证据：[E118](../evidence/flagship-optimization-20260921/ml-02-request-issuance-e118.json)。总体约 75%，目标 active，候选与生产门禁保持未放行。
