# 个人体验需求、实现与验收基线

- 日期：2026-09-10，Asia/Shanghai。
- 对应 UX-000；目标依据：[独立任务书](personal-experience-lan-team-development-taskbook-20260910-145507.md)。
- 源码基线 `a2f95c6fad1a04c776d57c4d4b9fd89b85c69b33`；实现继续在既有工作区增量落盘。
- 初始已有未提交内容：Web Vitest 4.1.11 的 package/lock 改动及任务书；均保留。任务书 §3.2 记载的既有路由与依赖修复不重新包装为本次新功能。
- 新周期由仓库 AGENTS.md 登记；比赛、研究发布和签名制品的历史证据保留。此基线不授权提交、推送、发布或修改远端治理。

## 需求追踪

“已落盘”仅描述有源码和对应验证的增量，不代表该行完整验收。持续状态与具体结果见 [开发台账](personal-experience-development-progress-20260910.md)。

| 决策 | 对应任务 | 现有实现位置与本轮增量 | 完整验收证据与当前缺口 |
| --- | --- | --- | --- |
| D01 现有项目优化 | UX-000、002；所有任务 | `apps/agentshield/internal/`、`apps/web/src/local/`、`packages/contracts/`；ADR-019–024 | 代码审查确认复用原决策、Grant、回执；Go/Web/合同回归。当前无第二套服务或决策引擎 |
| D02 先个人后团队 | UX-003–015，LAN-001–006 | 独立 Go embed 与 loopback API；团队沿用现有 control-api/Edge | 不启动企业服务的完整个人旅程；个人通过后再验收设备注册与下发。团队尚未开始 |
| D03 三系统 | UX-001、003、014、015 | Go stdlib，四目标交叉构建；开发启动辅助脚本 | Windows/macOS/Linux 安装、登录启动、重启、升级、卸载实机证据；当前只有 Linux arm64 运行证据 |
| D04 三平台 | UX-001、005、006、015 | inventory、原生适配器、独立 WorkBuddy Connector；接入诊断增加 WorkBuddy 待验证行 | 每组合正常/拒绝路径；本机 OpenClaw/Hermes 原生工具链已有部分证据，WorkBuddy 桌面未实测 |
| D05 发现/管控/安装/追溯 | UX-005、007、009–012 | 发现流程、稳定安装 ID、共享关系和统一权限编辑已落盘；复用 admission/grant/receipt/completion | 发现→确认→权限→执行→结果端到端；可信 Skill 绑定、安装事务和任务聚合仍需实现 |
| D06 原生优先 | UX-001、006、007 | OpenClaw/Hermes 插件；Hermes 实例定位、原生启用和产品运行自检已落盘，UI/API 使用真实公开 CLI 验证 | Linux 独立 profile 正常/拒绝/取消/失效通过；其他平台与 OS 自检待验收，未证明日常已有会话或全平台保护 |
| D07 检查后启用 | UX-005–009 | 扫描不启用钩子；配置与运行状态分离；接入和自检均预览后同会话确认，文件事务可恢复 | Hermes 自检临时范围已绑定明确确认；完整运行授权编辑与跨 OS 恢复仍待验收 |
| D08 SIQ 统一审批 | UX-007、008 | 复用 `/v1/hold`、动作身份与授权检查；会话恢复已落盘 | 系统通知→SIQ 窗口→一次性授权→执行前重查；完整通知和批准窗口旅程待实现 |
| D09 本地脱敏追溯 | UX-011、013 | 既有签名回执及效果证据；新诊断不输出凭据和配置正文 | 任务归属、结果强度、独立原文开关、保留期和删除；原文保持关闭，不能混入原审计链 |
| D10 确认后更新 | UX-010、014 | 现有内容摘要变化触发复核/撤权；安装 ID 不随内容改变 | 自动版本检查、差异、人工确认、原子切换、失败恢复、旧授权失效；更新产品旅程待实现 |
| D11 统一安全安装 | UX-009、010 | 复用 admission、policy-exec 和文件摘要 | Git/下载/本地的固定内容检查与安装、来源验证、路径/解包负向；原平台安装拦截逐平台实测 |

## 当前可确认的平台范围

| 运行环境 | OpenClaw | Hermes | WorkBuddy |
| --- | --- | --- | --- |
| Linux arm64（本机） | 2026.5.12；原生加载器、前置包装器、文件工具和后置 relay 的合成调用通过；非完整会话/审批 | 源码 `42f0c8179e30cf6ba4cba0a8f2852e609f717773`，版本输出候选 2026.8.31；原生加载器、工具调度器和公开 CLI 合成会话通过；非用户真实会话/审批 | 桌面应用不可用，独立待实测；不替换成 CodeBuddy |
| Linux amd64 | 仅 SIQ 交叉构建通过，平台运行待测 | 同左 | 同左，且需先确认上游可用运行形态 |
| Windows amd64 | 仅 SIQ 交叉构建通过；原生/WSL 分开验证 | 同左 | 桌面独立验证待提供环境 |
| macOS arm64 | 仅 SIQ 交叉构建通过，平台运行待测 | 同左 | 桌面独立验证待提供环境 |
| macOS Intel 及其他架构 | 按 UX-001 明确支持范围、最低 OS 与上游版本；当前无构建/实机证据 | 同左 | 同左 |

证据：[环境清单](evidence/personal-experience/environment-20260910.json)、[Hermes 原生调用](evidence/personal-experience/hermes-native-20260910.json)、[OpenClaw 原生调用](evidence/personal-experience/openclaw-native-20260910.json)。两项原生用例使用隔离配置、合成操作者与真实本机平台代码，验证指定调用边界；没有把用户当前实例标为已保护。文件位置、加载选项与宿主版本均需随接入实例重新确认。

## 规格增量与交付索引

| 增量 | 规格与合同 | 实现和证据 |
| --- | --- | --- |
| 服务身份与会话恢复 | [ADR-019](adr/0019-local-session-recovery.md)，`local-client-session.v1`，开发规格 §3.11 | `internal/server/session.go`、CLI `local_session.go`、本地 App/api；会话与启动证据见台账 |
| 首次发现与安装身份 | [ADR-020](adr/0020-personal-discovery-and-skill-identity.md)，`local-discovery.v1`，开发规格 §3.10.1 | inventory/ledger/discovery HTTP/组件，发现浏览器与本机只读证据见台账 |
| 接入配置诊断 | [ADR-021](adr/0021-adapter-configuration-diagnosis.md)，`local-adapter-diagnostics.v1` | adapterinstall/diagnostics、平台响应与设置/绑定页；运行自检使用独立 `local-runtime-check.v1`，不把配置就绪当成运行成功 |
| 接入变更与恢复 | [ADR-022](adr/0022-adapter-change-plan-and-recovery.md)，`local-adapter-plan.v1` | 文件规划、确认、加密恢复、审计与卸载归属；M4 故障与浏览器证据见台账 |
| Hermes 实例与原生启用 | [ADR-023](adr/0023-hermes-instance-integration.md)，`local-adapter-instances.v1`、`local-adapter-plan.v2` | 共享实例解析、按实例操作、公开 CLI 副本处理及 UI；M5 浏览器、原生调用、跨版本升级证据见台账 |
| 授权期限与自检前置 | [ADR-024](adr/0024-native-runtime-check.md)，`grant-expiry-edit.v1` | Grant 期限签名/审计与决策执行、签发页编辑已落盘；公开 Hermes CLI 会话有独立合成证据，产品实例自检控制器仍待实现 |

## 不得遗失的后续工作

1. 安装和系统生命周期：非默认端口提示、Vite 联合会话、无需开发环境的原生启动/停止/恢复、托盘或等价入口、三系统安装包。
2. 发现：继续覆盖 Hermes 之外的平台自定义根、扫描取消/超时、移除范围与历史资产语义、平台版本过滤规则。
3. 接入：继续其他平台原生自检、自动重启、跨 OS 恢复与更多历史记录兼容。M4/M5 已实现配置预览、加密恢复、Hermes 原生启用和实例选择，M7 已实现 Hermes 产品自检、清理和漂移失效；不据此宣称整个 UX-006 完成。
4. 权限与批准：期限编辑、签名/审计和到期执行已实现；M8 修正资源边界，M9 统一编辑通过 Linux 验证，M10 固定会话 Grant 选择已接入 Hermes 自检并通过原生验证。普通任务自动接入、实例/Skill 实际加载的可信关联、通知与统一确认仍待完成。原生平台不能提供 Skill 归属时需准确显示未归属，不使用模型自报；旧无 grant_ref 绑定仍保留原隐式查找语义。
5. 安装更新、追溯、隐私与交付：按任务书 UX-009–015 完整实现；当前仅基础模块存在，不能据此记任务完成。
6. 团队：完成个人验收后按 LAN-001–006 做身份、定向/批量任务、策略版本、结果、离线与撤销，不把现有共享任务领取当成广播。

这些缺口已有任务与验收位置，外部环境不足不阻止仓库内实现继续推进。UX-000 完成表示需求追踪与基线产物完成，不表示产品功能全部完成。
