# 当前开发入口

**企业优化转入收口（2026-09-26）：** 按用户要求形成[8 个收口工作包与 ENT 全覆盖清单](enterprise-auto-onboarding-closeout-20260926.md)，同步[总任务书](enterprise-auto-onboarding-taskbook-20260925.md)执行状态。四入口及多页面、框架树已复核；关键剩余是可信安装自动接入、精确角色/技能关系、运行时/共享影响、批量效果及审计、原生恢复和正式交付。先收完当前在途与集成门禁，不继续零散扩展 UI。目标保持 active，未因源码或模拟验证宣称上线/正式发行。历史实施证据见[持续开发记录](enterprise-auto-onboarding-progress-20260925.md)，下方“仅规划”为初次落盘时点。

**企业自动接入与治理优化任务已落盘（2026-09-25）：** 根据用户对 DGX Spark / Linux / OpenShell 安装体验的要求，形成 22 项实施任务，覆盖 Gateway 设备入口、可信安装与后台服务、自动盘点、框架—角色—Skill 关系、OpenShell 权限、批量操作、安全回归及可复现交付。当前只完成任务规划，全部实施项为 `todo`，没有注册设备、上传资产或修改运行服务。优先级、依赖、安全边界与验收标准见[企业优化任务书](enterprise-auto-onboarding-taskbook-20260925.md)。此新任务书不改写下方历史阶段的完成范围。

**个人管理台简化版已部署（2026-09-25）：** 按用户明确部署指令，原 `47611` 实例已切换到 `0.4.0-dev-console`，四入口与权限台浏览器验证通过，原状态、权限、身份及审计保留。企业端未改动，签名包未更新。见[部署与回退记录](personal-console-deployment-20260925.md)。下方“尚未部署”为此前开发阶段时点。

**个人管理台简化（2026-09-25）：** 本轮按用户授权收敛四入口、证据限定角色—Skill 关联浏览，新增签名预览与逐项 CAS/审计的批量撤权；保留旧高级能力及全部安全核心。源码与隔离验证阶段，不替换在线实例、不提交或签发新包。见[实施与验证记录](personal-console-simplification-20260925.md)。

**安装复现准备（2026-09-25）：** 已补同机/远程访问指引、SSH 无桌面 `ui` 行为、Skill 和包内安装说明，干净状态与浏览器验证通过。包含这些增量的新签名包仍待固定源码提交和最终包验收，不能用旧包代替。见[结果与剩余门槛](personal-install-repro-20260925.md)。

**个人端已部署（2026-09-25）：** 用户授权后，原 `47611` 实例已切换至 `0.4.0-dev-connect`；Skill 辅助连接与 24 小时会话完成实际浏览器验证，身份、权限及历史保留，企业实例未改动。见[部署与回退记录](personal-skill-connect-deployment-20260925.md)。下方“未替换在线实例”是部署前时点；源码仍未提交，签名包未更新。

**个人连接增量（2026-09-25）：** 按用户要求实现 Skill 辅助浏览器连接及固定 24 小时管理会话，保留手动配对。Go、前端及隔离浏览器验证通过；本轮未提交、未进入既有签名包、未替换在线实例。范围与验证见[开发记录](personal-skill-connect-20260925.md)。

**源码整合（2026-09-24）：** 用户已授权提交、推送与合并。E163 → E164 的原始提交及本机后续增量已在独立整合分支归档并验证，范围、检查与保留项见[本次整合记录](local-source-integration-20260924.md)。下方早期“未提交/未推送”及“等待提交指令”描述保留其历史时点，不再作为当前源码交付状态。正式签发、真实身份与原生平台验收仍按各自条件推进。

**剩余条件复核（2026-09-24）：** Nemotron 离线且资源紧张，远端 runner 为零；原客户端签发入口与真实业务接入仍缺。已请求本地新候选提交指令，未推送或启动重复测试。见[当前外部条件与接续动作](remaining-environment-gates-20260924.md)。

**企业候选已部署（2026-09-24）：** 原平台安全 API/Web 已更新，实际数据库升至 0017；备份恢复、新旧镜像切回、原 Gateway 与桌面/手机登录页检查通过。企业代码部署已完成，真实账号/跨站业务联调和导航 origin 仍待接入。[当前运行身份、失败记录与恢复命令](enterprise-runtime-delivery-20260924.md)。

**客户端发行接续（2026-09-24）：** 新报告工具 ARM64 二进制已通过两条隔离原生启动流程；打包前源码清单校验已实测拒绝旧 E163 提交，18 项发行测试通过。正式源码提交、签发及签名升级仍待完成。[结果与具体交接命令](client-report-release-handoff-20260924.md)。

**当前收尾状态（2026-09-24）：** 报告工具客户端增量已通过 Go 44 包、共享合同校验及四目标构建；仍为未签名准备产物。主 API/Web 健康。剩余工作统一以[当前收尾清单](flagship-closeout-current-20260924.md)为准；下方早期部署状态仅为历史记录。

**2026-09-24 主 API 与页面切换完成：** 新主服务在 18081 运行，15173 已接入；两类恢复器真实就绪，实际主端口应急转接及新版冷启动恢复通过。沿用宿主运行方式与原 legacy 权限，不再以控制面容器化/AppArmor 改动为发布前提。报告工具授权、真实身份和正式发行仍待完成。[当前服务身份、降级恢复及结束条件](main-api-cutover-20260924.md)。
**2026-09-24 宿主依赖与恢复检查：** 固定源码的十项宿主连接、五项恢复器检查通过；默认 Docker AppArmor 拒绝用户服务管理，连接成功仅在一次性 unconfined 诊断中成立。原主恢复锁仍有效，未切主 API；服务管理约束仍须落实。[准确验证范围](api-host-runtime-readiness-20260924.md)。
**2026-09-24 API 恢复基线：** 1,637 项固定源码已在原路径容器挂载、独立恢复库下完成首次启动及冷启动，六项检查通过，容器/临时库清理。原主服务仍在运行；这证明当前版本可冷启动，不代表原旧进程的源码恢复或主 API 已切换。[范围与结果](fixed-api-recovery-baseline-20260924.md)。
**2026-09-24 镜像交付：** 当前请求沙箱镜像已切到真实报告 v8 候选，新→旧→新演练通过。主 API 的 994 项源码归档与待应用配置已准备，未停止旧主进程；报告工具的实际权限变更已形成具体变更单并请求用户决定。主 API 切换、真实身份和正式发行继续待办。见[切换结果与剩余条件](runtime-image-delivery-20260924.md)。
**2026-09-24 宿主切换完成：** 原端口 AgentShield 已升级，恢复原 Hermes 根配置；三份现有绑定通过业务消费端严格校验，历史身份/权限及 31 条签名回执保持完整。主 API、当前沙箱镜像、企业生产联调与正式发行仍未完成。见[实际切换、回退与剩余项](host-daemon-upgrade-20260924.md)。
**E171 两个未知启动窗口通过真机验收：** 沙箱创建结果未保存、监督 invocation 未保存时，API 到期后均保留原占位且不重放；诊断独立核对本次观察并补齐记录后才收敛清理。32 项测试通过，临时库/进程已清理，原服务及预览未重启。[报告](business-unknown-startup-e171-20260923.md)。这不等于未知状态自动恢复。

**E170 已创建沙箱的早期 API 崩溃通过：** 在原 create 成功后、身份/监督启动前 SIGKILL 测试 API；同库重启后自然租约到期，API 自行回收并记录失权。48 项诊断测试通过，原服务及预览未重启，临时资源清理；未知创建和缺失 invocation 等窗口仍待验收。[报告](business-early-crash-e170-20260923.md)。

**E169 失败退出清理自动重试已闭环：** 修复后 189 项组合、16 项诊断测试通过；真机身份服务中断导致 ExecStopPost 与 API 扫描实际失败，恢复依赖后由 API 自动回收，原失败记录保留。临时资源清理，主服务及预览未重启。[报告](business-cleanup-retry-e169-20260923.md)。

**E168 本机预览已启动：** <http://127.0.0.1:15173> 连接新 API 18084，结果路由、匿名拒绝、桌面/手机登录页及撤回后重启通过。旧主 API 未变；预览保留恢复门禁，未完成正式任务执行切换或真实账号验收。[报告](business-preview-delivery-e168-20260923.md)。

**E167 实际业务库部署前置完成：** 完整私有备份已恢复演练，在线 API 所用 siq_app 的 022/023 已应用，官方审计 current、重复迁移无变更。API 未重启且健康 200，现有过期运行记录保留；API/Web 新代码仍待协调部署。[报告](business-database-delivery-e167-20260923.md)。

**E166 在途撤权验收：** 初始输出流逐事件授权复核已修复，真实撤权拒读/停止/回收与正常 SSE 正向回归均通过；262 项测试通过，原在线服务未替换。[报告](business-grant-revoke-e166-20260923.md)。E165/E166 关闭各自指定故障路径，其他原目标门禁仍未完成。

**E165 原业务故障验收进展：** 真实模型输出后 API SIGKILL/同库重启回收通过，原执行失权、子凭据撤销及资源回收已独立确认；在途业务 grant 撤销等剩余条件仍待验收。[报告](business-api-crash-e165-20260923.md)。冻结客户端与企业端候选未变。

**2026-09-23 统一交付状态：** 客户端与企业端既有功能已冻结，交付包与候选提交已复核；正式签发/升级、业务故障验收、生产集成与原生 CI 仍未完成。当前状态及剩余结束条件统一见 [交付状态](flagship-delivery-status-20260923.md)，不再用早期百分比估算代表当前进度。

**E164 企业既有代码收尾。** 独立候选 `4a4bcd0` 已通过 API 1071 项、PostgreSQL 11 项、Edge/Connector 测试与四目标编译、企业 Web 构建；未上线或改实际数据库。[交付边界](enterprise-source-freeze-e164-20260923.md)。客户端仍固定 E163，签发入口待提供。

E163 交接补充：固定候选前端 53 文件/290 项通过；旧版 0.3.1 八资产已验签并完成 Linux ARM64 临时启动验证。当前发行步骤等待受控签发环境的具体入口，签名升级/回滚仍未执行。[签发交接命令](client-signing-handoff-e163.md)。

**E163 客户端开发收尾。** 固定本地候选提交 `fd02384d6de5f96a849f9d04bbfbfaff38cf6148`，独立源码 44 包、前端重建一致和四平台发行构建通过；主工作树保留，未推送/发布。待具体受控签发入口后执行签发与签名安装/升级验收；本轮不再加功能，原总目标后续项仍未完成。见 [收尾与交接](client-release-freeze-e163-20260923.md)。

**E162 既有发现故障验收。** E162 已修复不可读目录被预览接受的问题，真实后台发现故障/恢复 9 项、既有双框架接入 53 项、Go 44 包及四目标构建通过；提供更新体验包，正式签名安装/升级仍待完成。 见 [修复与交付记录](ux-discovery-recovery-e162-validation-20260923.md)。

**E161 本地体验候选收尾（2026-09-23）。** E161 已完成 DGX Spark 后台接入体验候选：修复首次 setup 身份初始化和 Hermes 原生卸载后重装；真实后台接入浏览器 53 项、Hermes/OpenClaw 原生各 12 项及各 8 项生命周期检查、Go 44 包与四目标构建通过。新体验包已解压验收。此轮候选完成，正式签名安装/升级、在线业务部署和原总目标缺口仍独立待办；不扩展本轮功能。 见 [交付说明与结束线](ux-background-setup-e161-validation-20260923.md)。

核查日期：2026-09-19。仓库调整启动基线为 `main@1173042`；整理工具首批为 `ea0024f`，后续固定候选及 PR 见 [RA 台账](reorganization-progress.md)。开始工作前以 `git fetch origin main`、`git status --short --branch` 和 `git rev-parse HEAD origin/main` 确认自己检出的身份；本页不是移动分支指针。正式客户端 `0.3.1` 的源码固定 `f3d9c3f`，研究源码版仍为 `aefab111`。

本页维护当前范围和下一动作，逐步执行日志仍由各原始台账维护。历史 `personal-experience-current.md` 的 v3/v4 入口与早期“未提交”状态不再是启动依据；平台阶段记录仍保留其证据作用。

| 工作范围 / 责任角色 | 有效任务与权威入口 | 当前实施 / 证据状态 | 下一动作及限制 |
| --- | --- | --- | --- |
| 个人与企业易用性 / 当前用户体验优先任务 | [首次使用与接入任务书](user-experience-onboarding-taskbook-20260923.md)、[DGX Spark 执行台账](flagship-optimization-progress-20260921.md) | [E132](ux-permission-journey-e132-validation-20260923.md)：真实后端浏览器 49 项及前端 243 项通过；弹窗内检查、两平台权限旅程、OpenClaw 原生文件工具与结果前置完成；已安装发行版未变 | [E133](ux-hermes-native-journey-e133-validation-20260923.md) 补齐 Hermes 页面接入后原生自检；[E134](ux-runtime-record-link-e134-validation-20260923.md) 补齐自检结果直达记录；[E135](ux-activity-filters-e135-validation-20260923.md) 补齐时间/裁决筛选与翻页返回；[E136](ux-openshell-discovery-e136-validation-20260923.md) 补齐已配置 OpenShell 网关的发现/选中/策略读取；[E137](ux-model-connections-e137-validation-20260923.md) 补齐显式模型配置发现与服务列表检查（含真实 Step 5）；[E138](ux-model-inference-e138-validation-20260923.md) 补齐模型回答测试（真实 Step 5、22 项浏览器及 15 项列表回归）；[E139](ux-openshell-gateways-e139-validation-20260923.md) 补齐已登记多网关选择、PATH 接续与真实策略读回（18/19 项浏览器、15 项原入口回归）；[E140](ux-project-hermes-e140-validation-20260923.md) 补齐已登记项目 Hermes 角色/Skill/模型接续、真实安装自检与记录（26 项浏览器、13 项模型回归）；[E141](ux-permission-tools-e141-validation-20260923.md) 补齐中文工具勾选/只读方案与预览恢复，编辑/双平台接入/权限替换卸载 20/53/17 项通过；[E142](ux-result-evidence-e142-validation-20260923.md) 补齐结果解释、证据直达/重试与模态键盘操作，32 项结果、53 项双平台及 20 项编辑回归通过；[E143](ux-enterprise-onboarding-e143-validation-20260923.md) 补齐企业接入核心流程与 Edge 签名上传修复，Hermes/OpenClaw 各 15 项、个人结果回归 32 项通过；[E144](ux-enterprise-candidate-review-e144-validation-20260923.md) 接续候选处理/用途/权限入口和未知结果核对，两框架各 28 项、个人结果 32 项通过；[E145](ux-enterprise-workspace-e145-validation-20260923.md) 补齐组织角色工作台、真实导航权限与总览计数，工作台 16 项、两框架各 28 项和个人结果 32 项通过；[E146](ux-enterprise-change-review-e146-validation-20260923.md) 完成审查快照、审批独立读回与未知结果核对，审批浏览器 12 项及原有回归通过；[E147](ux-enterprise-change-execution-e147-validation-20260923.md) 补齐逐单部署与审计、失败证据解释、未知结果核对，修正查询参数导致页面状态丢失；新浏览器 13 项与原流程回归通过。[E148](ux-enterprise-deployment-preview-e148-validation-20260923.md) 已补部署预览、明确确认、提交重验和中文拒绝原因，新增浏览器 16 项通过，[E149](ux-openshell-live-preview-e149-validation-20260923.md) 已查清证书目录上下文并通过真实预览 8 项、多网关页面 19 项；版本解析/限制读回/目录指纹修复已完成，尚未执行运行时策略写入。[E150](ux-deployment-recovery-e150-validation-20260923.md) 已补唯一持久请求、刷新/丢响应恢复、执行前复查与 PostgreSQL 并发验证，部署恢复浏览器 17 项通过。[E151](ux-openshell-live-deployment-e151-validation-20260923.md) 已补真实页面下发/撤销与沙箱行为对照 12 项，修复空网络读回误报，API 1063 项和 Go 44 包通过。[E152](ux-runtime-output-provenance-e152-validation-20260923.md) 已补原生采集输出来源认证与内部隔离查询，Go 44 包及合同 269 项通过。[E153](ux-runtime-output-view-e153-validation-20260923.md) 已接受控已采集输出目录/正文查看，浏览器 11 项和原结果 32 项通过。[E154](ux-runtime-output-native-e154-validation-20260923.md) 已完成 Hermes 原生输出到页面 12 项、输出回归 11 项及正文可读性修复。[E155](ux-runtime-output-openclaw-e155-validation-20260923.md) 已完成 OpenClaw 原生输出到页面、双框架回归及正文优化。[E156](ux-business-result-access-e156-validation-20260923.md) 已补业务源独立读取与合同。[E157](ux-business-result-retention-e157-validation-20260923.md) 补已提交生成回复的持久归属和跨进程重授权；[E158](ux-business-install-baseline-e158-validation-20260923.md) 已修复历史 015 前置表缺失，完整组合 273 项通过；未部署生产。[E159](ux-business-result-page-e159-validation-20260923.md) 接通研究业务端回复→结果页→授权 API，浏览器 12 项通过。[E160](ux-business-result-history-e160-validation-20260923.md) 已补持久目录与 Linux ARM64 体验包。按用户要求停止扩展范围，优先交付及安装接入验收；保留终态提交前恢复、正式产物归属、业务连接与报告导航、人工结案/安全重试/执行端主动核验、用途与差异、筛选/批量审阅、项目 OpenShell 上下文、角色分配/生产 IAM、安装及发行验收 |
| 仓库组织 / 主线维护者 | [调整方案](../repository-architecture-reorganization-proposal-20260918-095230.md)、[RA 进度](reorganization-progress.md) | 用户已授权持续实施；冻结/路径守卫已建立 | 本轮导航、15 条测评索引、发行工具及 Skill 说明已实现；四目标源码检查和恢复演练通过；集成身份见 RA 台账 |
| 个人端与 LAN / 产品维护者 | [个人/团队 v5 总任务书](../personal-experience-lan-team-next-development-taskbook-20260915-232155.md)、[接续进度](../personal-experience-closure-progress-20260913.md) | 个人实现与分批验证已合入；N09 跨平台全量验收仍未关闭 | 先个人验收；LAN-001–006 不因企业基础存在而记完成 |
| Linux / Linux 维护者 | [LX00–LX10 任务书](../linux-dual-host-integration-development-taskbook-20260918-205119.md)、[进度](../linux-dual-host-progress-20260918.md)、[跨平台交接](../linux-dual-host-platform-handoff-20260918.md) | 第六代功能与第八代 UI 修复候选独立记账；范围为 OpenClaw/Hermes | 原版 OpenClaw 检查点、桌面视觉、性能与完整验收按原台账处理；已取消 12 小时补充腿不恢复为阻塞 |
| macOS / macOS 维护者 | [M01–M11 剩余任务](../personal-macos-luke-remaining-development-20260917.md)、[阶段集成](../evidence/personal-experience/macos-stage-review-fixes-20260917/report.md) | 阶段实现已合入，不能借用 Linux 新核心验证关闭同候选复测 | OpenClaw/Hermes/WorkBuddy 原生安装升级与共享核心复测；Apple 公证另记 |
| Windows / Windows 维护者 | [平台任务书](../personal-windows-sunbo-taskbook-20260913-202355.md)、[整合复核](../windows-main-integration-review-20260919.md)、[后续源码/发行边界](../skill-source-release-boundary-20260919.md) | #80–#83/#90 已合入；旧文档的 junction 待签阻塞已解除 | 新候选原生安装/升级、宿主复测；OpenClaw 的 WSL Agent 与原生 Windows 分列 |
| 客户端发行 / 发行维护者 | [打包与安装](../signed-release-packaging.md)、[0.3.1 记录](../evidence/releases/0.3.1/README.md) | 普通 Release、Latest；最终包验签与 Linux ARM64 启动、3/3 篡改拒绝、8/8 回读、6/6 源码工作流分别记账 | [通用验包与回读](../../scripts/release/README.md)已实现；新版本原生验收继续，不重签或覆盖 0.3.0 |
| 研究 / 研究维护者 | [研究 JSON 台账](../open-source-research-tasks-20260908.json)、[生成视图](../open-source-research-tasks-20260908.md)、[研究入口](../../RESEARCH.md) | 状态来自 JSON 台账及对应验证器 | 外部复现、长期归档/DOI、新实验协议等按原任务推进，不复制完成数 |
| 企业与 Edge / 企业维护者 | [控制面](../control-plane.md)、[运维模板](../enterprise-production-runbook-v1.md)、[Edge](../../edge/agent/) | 产品基础与隔离生产配置 smoke 存在；客户生产验收另记 | 真实 IdP、部署运维及多设备条件按场景验证，不查询兄弟仓库数据库 |

## 协作与历史替代

- 2026-09-23 用户提供的外部深度检查已完成[逐项复核与采纳决议](security-review-arbitration-20260923.md)：API 单测 969 项通过，app 范围 Ruff 仍有 2 处行超长；接受回执性能、pending 完整性、摘要来源、编码片段和设备吊销等修复方向，Edge 重定向提升为 P1。该文档列出最小修复与验收要求；用户指定纳入任务书 SEC-F01–SEC-F10 后续清单，不插队替代原开发任务。E138 已修正上述两处 app lint，其他缺陷仍待办；Host Sensor/风险聚合独立排期，不改写当前 UX 与 DGX Spark 的完成状态。
- [整合审计](../local-development-integration-audit-20260919.md)已经核查旧本地来源；旧目录脏状态不表示尚需整树合并。独有新增内容仍需重新审查，保留原现场。
- [Windows 分支索引](../windows-branch-pr-status-20260918.md)已收敛为历史兼容入口；旧待合并栈与整合报告的待签状态按源码/发行边界后续记录判定替代范围。
- #68 云开发环境按既定要求保留，不合并、不关闭、不删除，不阻塞本轮整理。
- 采用独立工作树和范围明确的 PR；同一路径先协调。任务提示使用仓库相对路径，不依赖某个维护者的 HOME 或 worktree 名称。
- 规范/合同、产品实现与证据不一致时先核对所属规格；导航不产生 effective 权限，也不把发布标签当原生验收证据。

## 仓库检查

```bash
python3 scripts/repository/check.py --base origin/main
python3 -m unittest discover -s scripts/repository -p 'test_*.py' -v
python3 scripts/check_research_task_ledger.py
python3 scripts/research/check_metadata.py
python3 scripts/check_capability_honesty.py
```

从仓库根执行。第一条需本地已有 base 提交；CI 使用 PR base 或 push-before。外部网页可达性独立检查，离线路径守卫不会触发服务、下载或签名。

[工具职责与稳定入口](tools.md) · [历史材料与当前状态](history.md) · [研究路线](../../research/README.md)
