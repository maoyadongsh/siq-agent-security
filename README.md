<p align="center">
  <img src="site/siq-shield.svg" width="96" height="96" alt="SIQ 蓝色盾牌标识" />
</p>

<h1 align="center">SIQ Agent Security</h1>

<p align="center"><strong>Secure Runtime for Agent Skills</strong><br />
智能体安全研究与开源实现：权限管理、运行时检查与执行审计</p>

<p align="center">Skills 给 Agent 能力，SIQ 给能力边界。</p>

<p align="center">
  <strong>主分支 main：</strong>
  <a href="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI · main" /></a>
  <a href="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/research.yml?query=branch%3Amain"><img src="https://github.com/maoyadongsh/siq-agent-security/actions/workflows/research.yml/badge.svg?branch=main" alt="Research reproduction · main" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/code-Apache--2.0-001840?style=flat" alt="Project-owned code: Apache-2.0" /></a>
  <a href="https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.4.0"><img src="https://img.shields.io/badge/release-0.4.0%20signed-7c5a0c?style=flat" alt="Signed release 0.4.0" /></a>
</p>

<p align="center">
  CI / research 徽章仅反映 <code>main</code>，不代表未合并分支或已发布版本。<br />
  当前发行验证见<a href="docs/evidence/releases/0.4.0/README.md">发行记录</a>，最新源码与后续验收见<a href="docs/development/current.md">当前开发</a>。
</p>

<p align="center">
  <strong>简体中文</strong> · <a href="README.en.md">English</a>
</p>

<p align="center">
  <a href="#个人用户使用路线">个人用户</a> · <a href="#企业用户使用路线">企业用户</a> · <a href="#快速开始">快速开始</a> · <a href="research/README.md">研究链路</a> · <a href="#研究与证据">研究证据</a> · <a href="#组件与接入">组件接入</a> · <a href="#贡献与下一步">参与贡献</a>
</p>

---

**SIQ 是通过 Skill 引导接入、由独立本地程序和宿主钩子执行保护的开源智能体安全系统。** 它发现和盘点已支持环境中的智能体及其关联资产，管理 Skill 生命周期与权限，并将资产、授权、运行记录和已采集的效果证据关联起来。

用户继续使用原有智能体，通过 SIQ 看清：

**有哪些智能体 → 装了哪些 Skill → 有哪些权限 → 哪些已启用保护 → 执行过什么 → 结果如何。**

发现资产不等于已纳管，更不等于已具备阻断保护；纳管与保护需要分别确认身份绑定、授权及宿主适配是否实际生效。结果核验以已接入的效果采集和实际证据为准。

研究主线是：模型提出的动作如何获得独立授权、参数来源如何约束执行，以及如何用实际效果证据判断任务完成。实现将受信 Intent、参数来源、Skill 执行上下文（SEC）、审批后唯一执行预留与效果核验串联，分别回答“谁授权、执行什么、归属哪个安装、是否实际发生”。根目录 [research/](research/README.md) 连接文献、研究问题、方法、实验、结论与治理；[evaluations/](evaluations/README.md) 区分研究观察、工程验收与外部复现。

项目提供两条使用路线：**个人端**通过本地服务和浏览器控制台管理自己的智能体、Skill 与任务；**企业端**通过控制面、Edge 和 Connector 汇总环境资产、审批策略并核验部署结果。个人客户端 `0.4.0` 已从当前冻结主线签发并公开为 Latest；企业治理、周期发现和审计导出属于同一源码提交，但不在个人客户端安装包内，企业服务仍按独立部署流程交付。企业真实业务身份联验与便捷的局域网团队多设备流程仍需继续验收。

**项目定位：以用户授权为依据、覆盖 Agent 与 Skill 生命周期的安全管理。** Agent 负责规划任务，SIQ 运行时依据受信授权检查具体动作；对已接入效果采集的任务，将调用记录、签名回执与实际观察关联起来，供用户核验结果。项目同时保留来源约束与效果核验的研究链路，并持续适配 **NVIDIA DGX Spark 本地 AI 环境与 NVIDIA OpenShell 执行后端**。研究演示可在普通 Linux 上使用确定性夹具运行，无需模型 API 密钥或 GPU。

> **签名安装包（2026-09-27）**：[0.4.0 正式版（Latest）](https://github.com/maoyadongsh/siq-agent-security/releases/tag/siq-agent-security-v0.4.0) 提供完整离线包、签名 Skill 与四目标二进制，源码固定在 `2cd6116`，使用原发行密钥签发。Linux ARM64 已通过最终包全新状态启动和 3/3 篡改拒绝；其他目标本次仅完成构建与签名 pin 核对，不等于原生安装、升级/回滚、Apple 公证或 Authenticode 验收。请选择 Release 的八份安装资产；GitHub 自动源码压缩包及仓库内 Skill 仍是开发源码。见[安装说明](docs/signed-release-packaging.md)和[0.4.0 签发与公开回读](docs/evidence/releases/0.4.0/README.md)。

> **升级边界**：`0.4.0` 包含 Skill 辅助浏览器连接、固定 24 小时管理会话、个人端权限事实和批量撤权等主线成果。浏览器连接请求有效 5 分钟，确认管理会话不批准任何智能体业务权限。正式版名称不改变平台证据范围；完整跨平台系统服务安装、升级/回滚和宿主旅程仍需继续验收。

[应用模块](apps/README.md) · [文档地图](docs/README.md) · [当前开发](docs/development/current.md) · [仓库整理进度](docs/development/reorganization-progress.md) · [平台交付](platforms/README.md) · [测评与外部复现](evaluations/README.md)

## 当前产品方向与支持状态

当前产品围绕“**发现与核对 → 准入与授权 → 运行与确认 → 追溯与维护**”组织功能。个人端已补充环境与项目发现、模型连接测试、多 OpenShell 网关检查、只读授权方案、原生保护检查、活动筛选与按任务输出查看；企业端以资产、权限、安全、审计四个主入口组织框架实例、角色与 Skill 观察、权限事实、风险处置、运行时绑定和精确审计查询，原策略、变更、环境与高级管理能力仍保留。周期计划的控制面、设备确认/轮询/退役与只读发现已合入，真实设备和生产身份旅程仍需验收。当前重点是冻结新发行源码并完成同候选原生验收、企业真实身份和跨系统联验，再推进团队多设备协同。

个人端通过 **Skill 引导、本地程序裁决、宿主钩子接入** 协同工作：

| 组件 | 作用 |
| --- | --- |
| [SIQ Skill](skills/siq-agent-security/SKILL.md) | 提供安装与操作指引，让智能体调用 SIQ 并呈现裁决；模型不自行判断安全性或批准授权 |
| [独立本地程序](apps/agentshield/README.md) | Go 运行时执行规则与授权检查、管理审批、签发回执，并提供浏览器管理界面 |
| [宿主钩子与适配器](adapters/runtime/README.md) | 在已接入的工具调用前请求本地裁决并按宿主协议处理，在调用后提交关联观察；支持的审批恢复路径还需执行前最终复查 |
| [OpenShell（可选）](#dgx-spark-与-nvidia-openshell-深度适配) | 为显式接入的任务提供对应版本和配置下的执行隔离与资源约束 |

**仅安装 Skill 不会自动安装宿主钩子，也不代表运行时保护已生效。** 需要确认本地服务运行、宿主钩子实际加载，并通过行为验证确定可检查或阻断的范围。“独立本地程序”描述组件分工，不表示当前桌面模式已具备同 UID 强隔离；具体能力以宿主接入与平台证据为准。

**截至 2026-09-27，经过复核的并行开发成果已分批合入并推送到 `main`，固定提交 `2cd6116` 的 6 个 GitHub 工作流全部通过，并已签发 `0.4.0` 正式版：** 合并范围和验证边界见[主线整合记录](docs/development/main-branch-integration-20260926.md)、[全面验收记录](docs/development/enterprise-comprehensive-acceptance-review-20260926.md)、[合并后收口交接](docs/development/enterprise-post-merge-remaining-closeout-handoff-20260926.md)及[发行记录](docs/evidence/releases/0.4.0/README.md)。**当前 Latest 为 `0.4.0`；签名个人客户端不等于企业组件已部署，也不补齐尚未执行的跨平台原生验收。** 历史实机证据继续绑定各自候选，不能迁移为当前正式版的完整验收。

| 范围 | 当前可核验状态 | 尚待完成 |
| --- | --- | --- |
| Linux 个人管理 | 环境发现、模型/网关检查、授权引导、原生检查和任务输出已合入；0.4.0 正式包通过 Linux ARM64 验签、全新状态启动及 3/3 篡改拒绝 | 系统服务安装、跨版本升级/回滚及完整宿主旅程；原版 OpenClaw 审批后检查点、桌面通知视觉确认仍有边界 |
| macOS | LaunchAgent 生命周期、OpenClaw/Hermes/WorkBuddy 阶段成果及独立复核修复已合入；0.4.0 提供签名清单绑定的 arm64 二进制 | 0.4.0 原生安装/升级、三宿主同版本复测、完整平台验收和 Apple 签名公证；项目清单签名不等于公证 |
| Windows | Writer、迁移恢复、DACL、资源与身份复验、三宿主管理、任务安装升级回滚及 junction 防护已合入；0.4.0 提供签名清单绑定的 amd64 二进制和 Skill | 0.4.0 原生安装/升级及同版本宿主复测；历史 OpenClaw 证据来自 WSL Agent，Hermes 为原生 CLI，WorkBuddy 原生最小读写不等于完整审批恢复、桌面更新和重复稳定性验收 |
| OpenClaw / Hermes / WorkBuddy | 新增 OpenClaw 2026.9.5 原生组件、会话隔离与输出链路验证；Hermes 0.21 有隔离环境的真实模型报告旅程；受控 OpenClaw 检查点补丁与原版能力分开登记 | Linux 只交付 OpenClaw、Hermes；组件验证不等于 OpenClaw 全模型业务旅程通过；Windows/macOS 三宿主及 WorkBuddy 桌面仍按同候选实机证据验收 |
| DGX Spark / OpenShell | 已有 GB10 / ARM64、本地推理、真实策略应用/撤销/回滚，以及隔离 Hermes / Qwen 报告执行证据；请求级监督、撤权和清理恢复增量已合入 | 固定 Nemotron 路径、DGX 原生 CI runner 与验收、跨场景停止确认、性能和新发行完整验收；特定请求恢复不代表通用远端停止能力 |
| 局域网团队多设备管理 | 企业 API / Web、周期计划存储与管理、设备端显式确认/轮询/退役及只读待办发现已合入；已有 Control API、Edge / Connector 集中治理基础 | 真实组织账号、独立审批者与业务结果跨系统联验；真实设备上的持续采集、安装衔接与恢复验收；便捷团队设备接入、统一管控与多设备验收 |

主线已有 OpenShell 受约束任务执行、多网关发现与检查入口：执行前需要显式绑定 CLI 与 endpoint、确认策略加载及实例身份，并再次校验授权。`policy_apply` 响应仍不代表任务实际执行；任务是否启动以执行回执和效果证据判断。新增请求级监督与恢复只覆盖其绑定的请求和已验证路径，不能推定任意远端任务都可安全停止。最新范围见[当前开发](docs/development/current.md)，历史 v6 结果保留在[Linux 进度台账](docs/linux-dual-host-progress-20260918.md)。发现资产不等于已启用保护；保护范围取决于实际接入的工具路径。

OpenClaw 的版本能力分别记账：当前[兼容清单](patches/openclaw/compatibility.v1.json)固定 **2026.9.5**。原版虽有插件审批与事件接口，仍缺少 SIQ 所需的审批后最终参数复查和唯一执行预留，因此 SIQ `hold` 在进入平台审批前保持拒绝。受控补丁路径按源码、补丁和适配器摘要绑定，不能解释为上游原版能力或正式发行支持。[原生组件与输出验证](docs/development/ux-runtime-output-openclaw-e155-validation-20260923.md)覆盖插件加载、工具包装、会话隔离与输出持久化，其中调用后 relay 使用夹具，不等于完整模型驱动的 OpenClaw / OpenShell 业务旅程。历史 2026.9.4 的 22/22 结果仍保留在[受控启动记录](docs/openclaw-controlled-start-linux-20260919.md)。

2026-09-17 的[平台范围决策](docs/personal-platform-scope-decision-20260917.md)明确本机 Linux 仅支持 Hermes 与 OpenClaw 的后续交付；Linux/WorkBuddy 不再排期，历史探测或矩阵占位不代表验收通过。Linux 控制台、管理 API 与 CLI 同样阻止新的 WorkBuddy 接入，保留既有配置的查看与卸载。各平台条件项、性能及新发行候选完整验收继续单独记账。

当前入口：[当前开发](docs/development/current.md) · [主线整合](docs/development/main-branch-integration-20260926.md) · [全面验收](docs/development/enterprise-comprehensive-acceptance-review-20260926.md) · [合并后收口](docs/development/enterprise-post-merge-remaining-closeout-handoff-20260926.md) · [0.4.0 发行记录](docs/evidence/releases/0.4.0/README.md) · [企业部署记录](docs/development/enterprise-runtime-delivery-20260924.md) · [环境待验项](docs/development/remaining-environment-gates-20260924.md)。历史文档中的“未提交”“未推送”“未部署”是当时快照，当前状态以 Git 历史、整合、发行和后续部署记录为准；任务书本身不构成功能交付承诺。

## 核心价值

**核心结果：权限可管理、执行可检查、结果可追溯。** 用户能确认“允许做什么”，在已接入路径上检查“这次动作是否获准”，并根据回执与实际观察核对“最终发生了什么”。这些能力共同支撑 Trusted Agent Execution（可信的 Agent 执行）。

| 用户关切 | 已实现的产品与技术机制 | 实际用途 |
| :--- | :--- | :--- |
| **资产和变更可管理** | 资产发现与归属、Skill 准入检查、安装更新预览、用户确认及移除 | 看清来源和权限变化，管理从接入到退出的过程 |
| **权限独立于模型** | Go 运行时核验 Grant / Intent、会话绑定与执行前审批；模型提议不能扩大权限 | 为自动化操作设置可审计的授权边界 |
| **同值参数，区分来源** | 将受信 Context 与参数来源绑定到动作；相同收件人值可因可信数据库 / MCP 来源不同而获准或拒绝 | 约束被工具结果诱导的收件人替换与越权交付 |
| **完成依赖实际效果** | 签名回执关联动作；独立观察文件与受控接收端，区分工具成功、效果发生和任务完成 | 为交付验收、故障定位与执行审计提供证据 |

商业应用方向包括企业 Agent 权限治理、研究与报告交付、工具平台集成。现有基础是本地运行时、适配器与可选企业控制面；规模化部署、外部 SaaS 效果证明和商业收益仍需具体场景验证。创新性评价以[研究问题](docs/research/research-questions.md)与[技术报告](docs/research/technical-report.md)为依据，当前不宣称首创或已获同行评审认可。

### 技术难点与工程创新

SIQ 的差异化集中在把**授权依据、真实调用与可核验结果连接起来**，并让这一关系在异步审批、状态变更、平台适配和故障恢复中保持成立。

| 技术难点 | 本项目的实现路径 | 可检查的工程价值 |
| --- | --- | --- |
| 模型会被外部内容影响，工具参数看似合法却可能来自不可信来源 | 将受信 Intent / Context、参数来源与动作绑定，由确定性运行时检查；同值不同来源可以产生不同决定 | 从“参数是什么”进一步检查“参数从哪里来、谁授权使用”，见 [来源与授权实现](docs/research/technical-report.md) |
| 审批与实际执行之间会发生参数漂移、撤权或重放 | 签名 Grant、会话绑定、执行前复验，以及持久化 hold 预留；观察缺失时保留不确定状态 | 批准只适用于被绑定的动作，不成为可重复消费的通行证，见 [运行时合同](packages/contracts/README.md) |
| 工具声称成功，却未发生所需交付效果 | 区分普通 Observation、独立 EffectEvidence 和 Completion；关联文件与受控接收端的实际观察 | 把“调用成功”与“任务完成”分开，支持伪成功、缺失和冲突证据判定 |
| 策略已提交不代表已加载，错误回滚可能扩大权限或覆盖他人修改 | 保真读回完整策略、核对修订与摘要、等待加载确认、操作绑定及漂移拒绝；应用前检查基线能否按当前授权恢复 | 将策略发布、实际加载和安全恢复纳入同一治理流程，见 [OpenShell 集成复核](docs/evidence/personal-experience/glm-stage-integration-20260917/report.md) |
| Skill 更新、主机配置变更与版本回退可能破坏权限和身份连续性 | 暂存比较、用户确认、更新后授权/归属复核、未知对象保留；状态兼容门禁及缺失历史签名密钥拒绝自动重建 | 在可恢复的生命周期中保持权限、用户数据与审计身份的连续性 |

这些机制构成项目探索前沿智能体安全管控模式的工程基础。**技术创新主张应落实为机制、对照实验和可复核证据**：本项目已有工程实现与受控验证，尚不以功能数量或小样本通过率宣称行业排名、通用防护率或形式化安全证明。

### 商业价值与落地场景

| 使用者 / 场景 | 需要解决的问题 | SIQ 可提供的产品基础与价值验证方向 |
| --- | --- | --- |
| 个人开发者与智能体重度用户 | 不清楚装了哪些 Skill、权限多大，安装更新可能改变行为 | 本地盘点、权限确认、更新差异和任务追溯；以首次保护耗时、授权操作成本和恢复成功率评价体验 |
| 企业内部 Agent 平台与工具团队 | 不同宿主各自配置权限，缺少统一的审批和审计依据 | 可选多租户控制面、Edge 采集、版本化合同及运行时接入；支撑治理集成、适配交付与运维服务，团队多设备产品仍按路线建设 |
| 本地 AI / 私有化部署团队 | 希望机密分析在本地执行，同时保留外部规划与工具协作能力 | DGX Spark 部署配置、本地模型路径与敏感信息出口约束；以实际传输记录、成本和任务完成情况验证价值 |
| 研究报告与自动化交付团队 | 需要解释一次操作为何获准，确认交付是否真实发生 | 来源绑定、签名回执及效果核验；减少排障时的信息缺口，为人工复核和责任追溯提供材料 |

商业化空间来自可维护的跨宿主适配、私有部署、策略治理与证据服务。当前仓库提供的是这些能力的产品和技术基础，客户收益、规模化运营成本、合规适用性与服务等级需要在具体试点中验证；审计材料本身不等于合规认证。

> [!IMPORTANT]
> **研究源码预发布：已提供 Sigstore 数字签名**
>
> [research-v0.1.0-rc.1](https://github.com/maoyadongsh/siq-agent-security/releases/tag/research-v0.1.0-rc.1) 附 `SOURCE-INFO.json`、`SHA256SUMS` 与 `SHA256SUMS.sigstore.json`，不包含新编译的二进制或模型权重。签名绑定本仓库的 GitHub Actions 发布工作流身份，通过校验清单覆盖源码包和版本信息文件。请先验证签名，再核对文件摘要：[验证方法与签名范围](docs/research/release-authentication.md)。

<details>
<summary>研究首发源码与版本身份</summary>

该研究源码预发布固定在 [`aefab111`](https://github.com/maoyadongsh/siq-agent-security/commit/aefab111c7fcad9075c8f429f97c9eab519dcd22)，后续首页与发布回执更新不改变这一身份。

2026-09-09 为原有附件补充独立签名，未改写原附件。`SOURCE-INFO.json` 中的 `official_signature=false` 保留首次打包时的历史状态；本次 Sigstore 签名及验证结果见[签名记录](docs/research/evidence/release-signing-20260909.json)。

</details>

## 从这里开始

需要评估 `vercel-labs/skills` 的源码分发兼容性时，使用[固定版本验证工具](docs/research/skills-distribution.md)。该工具从 Git 提交复制开发源码，不能替代[签名安装包](docs/signed-release-packaging.md)；历史目录投递测试结果也不扩展当前产品支持范围。

| 你的目标 | 推荐入口 | 可以获得什么 |
| :--- | :--- | :--- |
| 管理本机智能体与 Skill | [个人用户使用路线](#个人用户使用路线) · [签名包安装](docs/signed-release-packaging.md) · [源码体验](#个人管理端linux-源码体验) | 启动本地服务、配对后管理；按平台验证范围启用保护 |
| 管理组织内的智能体资产与策略 | [企业用户使用路线](#企业用户使用路线) · [控制面部署](docs/control-plane.md#快速开始) | 注册环境与 Edge、汇总资产证据、审批策略并跟踪实际生效范围 |
| 体验完整流程 | [快速开始](#快速开始) | 无需模型密钥的本地演示 |
| 复现与评价 | [复现指南](REPRODUCIBILITY.md) · [研究导航](docs/research/README.md) | 固定案例、评价协议与证据 |
| 接入自己的 Agent | [组件与接入](#组件与接入) | 运行时、适配器和合同入口 |
| 参与开源研究 | [贡献指南](CONTRIBUTING.md) · [社区任务](docs/research/community-backlog.md) | 有明确范围的贡献起点 |

## 两类用户，两个使用入口

个人路线以“**管理这台设备上的智能体与 Skill**”为起点，企业路线以“**治理已注册环境中的资产与策略**”为起点。两者共享安全合同与部分规则，分别使用本地配对身份和企业身份、服务及管理界面。选定入口后，再按下面的流程部署、授权和验证。

| 选择依据 | 个人用户：管理自己的智能体与 Skill | 企业用户：治理组织中的资产、权限与策略 |
| --- | --- | --- |
| 主要使用者 | 本机操作者、开发者、研究人员 | 平台管理员、安全负责人、资产负责人、审批与审计人员 |
| 管理入口 | 本机 Go 服务提供的浏览器控制台；新版源码支持 Skill 辅助连接，保留一次性配对码入口 | 企业 Web 控制台与 Control API，生产接入组织身份认证并按角色授权 |
| 部署组成 | 本地运行时 + 平台适配器；SIQ Skill 可作为操作引导；OpenShell 按需接入 | Control API + PostgreSQL + Worker + 企业 Web；客户环境部署 Edge / Connector，按需接执行后端 |
| 管理重点 | 发现已有资产、确认权限、安装更新 Skill、批准具体动作、查看任务和回执 | 环境与设备注册、资产归属、权限事实、风险处理、策略审批部署、漂移和审计 |
| 日常工作方式 | 继续在原智能体平台完成任务，在 SIQ 确认权限、检查运行记录 | 业务团队继续使用原有 Agent 平台，管理人员通过 SIQ 配置治理流程与核验结果 |
| 当前交付边界 | 0.4.0 公开签名正式版；Linux ARM64 有最终包原生首次启动证据，其他目标只有构建和签名 pin 证据 | 企业 API / Web 按独立流程部署；真实组织身份与业务跨系统联验、便捷局域网多设备流程仍需完成 |

## 个人用户使用路线

### 从首次使用到日常管理

2026-09-25 本机部署记录描述当时的 `0.4.0-dev-console`：原 `http://127.0.0.1:47611/overview` 跳转到新版 `/agents` 首页，保留 Skill 辅助连接、24 小时管理会话、原身份和历史；该记录中的“未公开”是历史快照，这些个人端能力现已进入 0.4.0 正式包。[部署与回退记录](docs/development/personal-console-deployment-20260925.md)。

同日的个人管理台简化**源码增量**提供“我的智能体 / 权限管理 / 安全中心 / 运行审计”四入口、框架—角色—Skill 关联浏览，以及签名预览、逐项版本校验和审计的批量撤权。原有防御与高级工作台保留；批量扩大权限仍未开放。这些能力现已进入 0.4.0 正式包，原始范围与验证见[源码增量记录](docs/development/personal-console-simplification-20260925.md)。

普通用户推荐在自己的电脑安装并打开个人管理端。控制台地址中的 `127.0.0.1` 指向**浏览器所在的机器**，不是远程服务主机：例如 Mac 浏览器和 Linux 服务端是两台设备，服务装在远程服务器时，不能在 Mac 上直接打开服务器打印的 `127.0.0.1` 链接，需按[操作手册的同端口 SSH 转发步骤](docs/personal-client-operation-guide-20260916.md#2-启动与配对)访问；不要为访问而让服务监听 `0.0.0.0`、关闭认证或放松防火墙。浏览器完成管理台会话确认不等于授予智能体业务授权，实际检查和裁决仍由本地运行时执行。完整复现新版需要包含新功能的二进制和 Skill，旧签名包不包含本次优化。

个人用户的主要目标是：**知道本机有哪些智能体和 Skill，为接入的动作设定权限，并能解释一次任务做了什么、为什么获准或被拒绝。** SIQ 的个人管理端围绕现有智能体工作，不要求用户把所有任务迁移到新的聊天工作台。

1. **准备并启动本地管理端。** 下载 [0.4.0 完整离线包](https://github.com/maoyadongsh/siq-agent-security/releases/download/siq-agent-security-v0.4.0/siq-agent-security-0.4.0-bundle.zip)，按[签名包安装说明](docs/signed-release-packaging.md)选择对应平台程序并启动。需要开发调试或体验发布后主线改动时，使用下方[Linux 源码体验](#个人管理端linux-源码体验)。嵌入式界面随 Go 服务提供，无需同时启动企业 Control API、数据库或前端开发服务器；各平台验证范围见上方支持表。
2. **连接自己的浏览器。** 0.4.0 支持点击“通过智能体连接”，把页面生成的请求交给已安装的 SIQ Skill；本机确认后浏览器自动连接，不必查找配对码。管理会话固定有效 **24 小时**，刷新不延长，退出或服务重启后需重新连接；连接请求本身有效 5 分钟。仍可展开手动配对入口。连接不授予智能体权限，实际检查和裁决由本地运行时执行；详情见[操作手册](docs/personal-client-operation-guide-20260916.md)。
3. **发现并核对现有资产。** 在“智能体资产”检查识别到的平台、实例、项目、Skill 与来源；主线还提供模型连接与推理测试、已配置 OpenShell 网关的发现和检查。先阅读检查结果，再选择需要接入的对象；发现结果不会自动变成授权，也不会自动接管所有已安装程序。
4. **确认权限并接入保护。** 在资产详情、权限视图与“签发”中核对工具、文件、网络等范围，可从只读方案开始，确认后部署授权；按宿主支持情况安装适配器或使用受控启动。通过原生保护检查核对实际接入状态和可阻断范围，检查记录可进入任务活动追溯，再让该智能体执行工作。
5. **继续使用原平台，集中处理待确认动作。** 适配器将接入路径上的调用交给 SIQ 裁决；需要人工确认的动作进入“确认待办”。用户核对请求、资源和权限后决定批准或拒绝。批准后是否可直接恢复执行取决于宿主适配；请求变化、过期或撤权需要重新处理。系统通知是提醒入口，实际确认发生在 SIQ，桌面通知效果按平台验收。
6. **按需添加和更新 Skill。** 在“导入 Skill”选择本地目录、本地 ZIP 或符合限制的 HTTPS ZIP 直链，先暂存检查，再预览安装目标与权限并确认安装。在“已安装 Skill”和更新页面检查新版、比较内容变化，确认后更新；权限变化需要重新核对。**当前页面的 Git 仓库导入入口尚未开放**，不能将任意仓库首页当作可用下载入口，真实网络来源还需满足访问与安全校验条件。
7. **查看运行过程和结果。** 从“任务活动”按时间、裁决筛选并分页进入任务；“任务安全视图”展示业务任务引用、运行模式、匿名数据去向、逐动作授权和实际效果，“回执”提供执行决定和验签线索。输出面板按授权查看已采集内容，不补采历史原文；适配器返回的输出不等于独立效果证明。已接入效果采集的路径还可核对文件或受控接收端，区分调用成功、效果已核验与证据不足；该视图不替代生产部署验收。
8. **管理隐私、维护与退出。** 原文采集默认关闭；需要排障时，先启用按需原文仓，再针对具体任务单独授权，并管理到期清理。可导出脱敏材料；停止服务、升级恢复或卸载时按操作手册处理，核对保留的数据和宿主配置。

### 个人端有什么功能

| 用户需求 | 对应功能与入口 | 用户可得到的结果 |
| --- | --- | --- |
| 看清已有智能体和 Skill | 总览、环境与项目发现、资产详情、模型测试与网关检查 | 看见发现来源、实例归属、连接状态和需要处理的对象；连接成功不等于已授权 |
| 控制接入路径上的权限 | 权限视图、工具选择、只读方案、签发与原生保护检查 | 确认工具、文件和网络范围；根据实际接入证据判断检查与阻断是否生效 |
| 判断新 Skill 能否准入 | 导入、静态检查、权限预览、安装确认 | 在执行前检查内容和需求，对触发隔离规则的候选停止准入 |
| 避免更新悄悄改变权限 | 新版检查、内容差异、用户确认、更新后归属与授权复核 | 在用户确认下更新；拒绝候选漂移和不匹配的旧状态写入 |
| 处理风险与待批准动作 | 风险中心、确认待办、审批记录 | 核对动作后批准或拒绝；恢复执行时复验身份、参数和授权，宿主能力不足时保持拒绝 |
| 追溯任务与排障 | 活动筛选与分页、按任务输出查看、签名回执、效果证据、脱敏导出 | 将操作、授权与结果关联起来；区分工具返回内容和独立核验的效果 |
| 控制本地记录的敏感程度 | 设置、按任务原文授权、查看与到期清理 | 默认保存必要的脱敏记录，按需记录原文；原生采集覆盖仍取决于适配器 |
| 获取和验证客户端 | 签名发行包、bootstrap、版本与完整性校验 | 安装与固定源码匹配的程序和 Skill，拒绝不匹配或被修改的内容 |
| 维护本地客户端 | 服务状态、后台生命周期、升级、备份恢复和保留退出流程 | 管理服务与数据的连续性，具体操作以 OS 实测范围为准 |

**一个典型场景：** 已在 OpenClaw 中使用报告 Skill 的用户，先在 SIQ 检查该实例和 Skill 的权限，将可用目录与网络目标限定到任务需要的范围，再回到 OpenClaw 执行任务。若接入的调用需要额外权限，用户到 SIQ 核对确认；任务结束后查看相关回执和已采集效果。后续 Skill 更新时，先看差异再确认，而不是让新版本自动继承扩大后的权限。

个人端的保护强度取决于实际接入路径和操作系统边界。同一系统用户下能够绕过适配器的程序，不会因安装 SIQ Skill 就获得强制隔离。完整操作步骤见[个人客户端操作手册](docs/personal-client-operation-guide-20260916.md)与[本机操作指南](AGENTSHIELD.md)。

## 企业用户使用路线

### 从环境接入到持续治理

企业用户的主要目标是：**明确哪些环境和智能体已经纳管、谁有权变更策略，以及变更是否在目标后端生效。** 当前方案以“注册环境 → 汇总资产与证据 → 审批策略 → 部署读回 → 持续审计”为主线，控制面可独立部署，通过版本化接口接入已有身份系统、Agent 平台及执行后端。

1. **部署控制面，配置组织身份。** 平台团队部署 Control API、PostgreSQL、Worker 与企业 Web。生产入口配置 HTTPS、受信身份提供方和任务签名密钥，管理员、资产负责人、策略提出者、批准者和审计人员通过角色工作台按权限工作。工作台不替代服务端授权，开发模式的模拟身份只用于本地验证。
2. **登记环境并注册 Edge。** 按环境接入引导创建记录、核对接入命令，通过一次性注册码注册 Edge。Edge 在授权范围内运行 Connector，向控制面出站上报心跳和证据；管理员可以查看注册状态并吊销设备凭据。网络可达并不等于设备已被信任或自动纳管。
3. **发现资产，确认归属。** 根据实际环境启用框架、目录、MCP、进程、容器或 Kubernetes 等 Connector。采集结果先形成候选与来源证据，由负责人确认或驳回，逐步建立资产清单。模型辅助分类是可选项，低置信结论仍需人工复核。
4. **检查权限事实与风险。** 在资产详情、权限视图和风险中心查看声明、推断、运行观察、后端生效读回和未知状态，确定哪些权限过大、缺乏证据或发生漂移。风险接受需记录负责人、原因与到期时间，便于后续复查。
5. **提出并审批策略变更。** 负责人依据业务需求草拟资源范围，核对审批快照与服务端读回结果，经过校验、提案和审批后部署。提出者不能自行成为唯一批准者；紧急处理也保留独立权限、跨人批准与事后复核。模型建议不能直接变成已生效权限。
6. **在已接入后端部署并核验。** 先预览部署内容并显式确认，再对支持的后端编译和下发策略；持久化请求用于关联结果，响应丢失时先查询恢复状态，不能把未知状态当作失败后盲目重复提交。检查读回结果并验证真实动作是否受限。发现资产的 Connector 与执行限制的适配器/后端职责不同；只部署采集组件不会自动阻断工具调用，不能表达的限制或模式应明确显示不支持。
7. **持续处理变化与异常。** 通过定期采集、风险评估、策略漂移检测、变更记录和审计定位带外修改与过期风险；需要恢复时，按权限和后端能力执行回滚。设备退出、凭据吊销和异常恢复都应保留记录。
8. **以试点证据扩展部署。** 先选定宿主、环境与执行后端，验证“发现 → 归属 → 审批 → 部署 → 读回 → 行为测试 → 恢复”的闭环，再增加环境。身份提供方、数据库恢复、密钥轮换、运维监控与跨设备场景须在实际部署中验收。

### 新注册设备的周期发现接入（两步）

新注册的设备不需要预先知道周期计划 ID。设备端 `edge-agent` 提供只读的发现子命令，负责“找到等本机确认的计划”，**确认仍是独立的第二步**，不因发现而自动完成：

```bash
# 第一步：只读发现。只发认证 GET，不选择、不确认，不写确认日志或回执。
# 命令会创建或复用既有 tasks.lock 作为本机并发互斥，但它不是业务状态。
# 恰好一个待确认计划时才显示完整绑定信息；0 个时明确说明无待办；
# 多于一个时只列出候选并要求改用 --schedule-id 指定，绝不自动挑选。
edge-agent confirm-discovery-schedule --discover

# 第二步：在真实终端上，对已显示的意图做独立明确确认。
# 仍要求终端交互（默认取消，管道输入不构成同意）或精确 --confirm-intent-sha256。
edge-agent confirm-discovery-schedule --discover --interactive
```

`--discover` 与 `--intent`/`--schedule-id`/`--resume` 严格互斥；发现结果只是“本机有活干”的事实，不构成授权，也不降低确认强度。周期计划仍需由组织控制台为该设备创建。可见的旧做法（复制摘要、按已知 ID 获取）仍然有效，行为不变。

### 企业端有什么功能

| 治理需求 | 已有功能基础 | 实际用途与范围 |
| --- | --- | --- |
| 统一环境与设备入口 | 角色工作台、环境接入引导、Edge 注册、心跳、签名任务、凭据吊销 | 建立环境归属与设备信任，支持集中收集不同环境的资产证据 |
| 发现分散资产 | 框架/目录/MCP/进程/容器/集群 Connector，候选确认与驳回 | 盘点组织中的智能体相关资产；采集支持范围见[兼容说明](docs/compatibility.md) |
| 管理权限依据 | 多状态权限事实、证据关联、五域编辑器 | 看清期望权限与实际观察/读回的差距，不把模型推断当成生效权限 |
| 管理风险与可疑内容 | 规则分析、静态威胁检测、隔离记录、风险接受与到期重开 | 在不执行被扫描内容的条件下检查风险，为人工处置提供依据 |
| 治理策略变更 | 变更单、职责分离审批与读回、部署预览、显式确认、持久化幂等请求和恢复 | 将谁提出、谁批准、部署结果与恢复过程记录在同一流程中；保留结果未知状态 |
| 对接执行后端 | OpenShell 策略编译、能力探测、策略读回与漂移检测 | 在后端实际支持的范围内约束行为；读回状态仍需与真实阻断证据区分 |
| 审计与系统集成 | 多租户身份边界、同事务审计、Outbox 事件、脱敏导出、业务运行结果导航 | 关联安全资产与业务结果；导航限定租户和配置的站点，进入业务系统后仍需重新核验登录与结果访问权限 |

**一个典型场景：** 平台团队先把试点研发环境的 Edge 注册到企业控制面，采集运行中的 Agent 和框架配置；资产负责人确认归属后，安全人员核对网络访问需求，提出收紧策略，由另一位有权限的人员批准。已接入的 OpenShell 后端执行策略部署，团队用读回与真实正负用例核验，之后持续关注漂移与审计记录。这个过程可以沿现有环境接入基础扩展，但每个新增平台仍需验证其采集和执行能力。

### 企业集中管理与后续局域网团队版的关系

当前企业路线已有 **Control API + Edge / Connector 的集中管理基础**，并非只能在同一台电脑上采集资产；部署范围取决于网络连通、身份配置、设备注册和 Connector 支持情况。后续“局域网团队多设备管理”要进一步把这一基础做成便捷的团队产品流程，补齐跨设备接入体验、统一授权协同、设备离线/恢复和三系统完整验收。它仍在总体路线中，不能理解为现在只需打开多个个人端网页即可自动组成团队。

企业控制面与个人本地端是两个明确的运行入口。当前不能把个人端的配对会话直接当成企业身份，也不能假设个人端已有的每条 Skill 安装、审批恢复和任务证据路径都已自动接入企业多租户流程。

部署步骤见[企业控制面快速开始](docs/control-plane.md#快速开始)。[9 月 24 日部署记录](docs/development/enterprise-runtime-delivery-20260924.md)已确认当时的企业 API / Web 更新、数据库 `0013→0017` 迁移、备份的隔离恢复、新旧镜像切换，以及既有 Gateway 的桌面/移动登录入口与匿名拒绝检查；当前主线迁移已继续到 `0028`，部署时始终执行 `alembic upgrade head`，不能停在历史迁移号。**这些检查未使用真实业务账号完成登录和跨系统旅程**；真实组织/角色、独立审批者、可访问的业务站点配置、密钥轮换和多设备运行仍需按[生产运行手册](docs/enterprise-production-runbook-v1.md)验收。企业 OpenShell CLI 后端当前只支持 `block` 部署；治理模型包含 `audit_only` / `warn` 不代表后端已支持。周期计划的存储、确认、管理、设备轮询/退役及只读发现已经合入主线（见[自动接入收口记录](docs/development/enterprise-auto-onboarding-closeout-20260926.md)与[合并后交接](docs/development/enterprise-post-merge-remaining-closeout-handoff-20260926.md)）；设备发现只说明“有计划等待确认”，确认仍需独立一步，现有证据也不等于持续扫描已在真实设备完整生效。事件导出接口会用 `X-SIQ-Export-Truncated` 声明当前响应是否因 `limit` 截断，但它不是完整归档或保留/删除治理，见[OCSF 导出合同](packages/contracts/enterprise-ocsf-export.v1.md)。常见故障与发行包前置条件见该[生产运行手册](docs/enterprise-production-runbook-v1.md)。DGX Spark 与 OpenShell 机制见[深度适配说明](#dgx-spark-与-nvidia-openshell-深度适配)。

## 可以验证什么

以“分析仓库、生成报告并交付给指定联系人”为例，Agent 动态选择研究、报告和交付 Skills。演示包含以下四种可观察结果：

| 场景 | 关键检查 | 预期结果 |
| --- | --- | --- |
| 正常交付 | 任务授权、受信联系人、文件与接收端效果 | `verified`：要求的效果已核验 |
| MCP 收件人注入 | 不可信工具结果提出更换收件人 | `blocked`：不允许的动作被阻止 |
| 同值不同来源 | 相同收件人值分别来自可信数据库与 MCP | 可信路径允许；MCP 路径拒绝 |
| 工具伪成功 | 工具返回成功，但受控接收端没有对应事件 | `incomplete`：缺少所需效果 |

这些演示使用显式模型夹具驱动真实 SIQ 组件。它们验证指定安全路径，不是实模型遭受提示注入时的攻击成功率测量。

## 工作方式

### 组件与授权链路

下图展示当前本地运行时与企业控制面的主要关系：受管实例通过真实宿主会话接入，Context、参数来源和按需签发的 Skill 执行上下文（SEC）参与服务端复验。企业控制面是可选部署；个人控制台与企业控制台使用各自的身份和服务，不会因同时部署而自动同步授权。个人端还可独立接入 OpenShell，流程见下方[深度适配说明](#dgx-spark-与-nvidia-openshell-深度适配)。

```mermaid
---
config:
  themeVariables:
    fontSize: 16px
  flowchart:
    nodeSpacing: 20
    rankSpacing: 40
    wrappingWidth: 178
---
flowchart TB
    subgraph Local[个人接入链路：宿主与本地服务]
        direction TB
    Human[操作者] --> Console[本地控制台 / 管理 API]
    Skill[SIQ Skill：操作指引] --> Agent[业务 Agent]
    Candidate[候选 Skill] --> Admission[静态准入 / 内容摘要]
    Admission --> Console
    Console --> Authority[签名 Grant / Intent / 会话绑定]
    Agent --> Adapter[宿主运行时适配器]
    Adapter --> Identity[受管实例身份 / 原生会话登记]
    Identity --> Gate[本地授权与决策引擎]
    Adapter -->|具体动作与参数| Gate
    Authority --> Gate
    Context[受信 Context / 参数来源 / 按需 SEC] --> Gate
    Gate --> Decision[裁决交给适配器 / 保留宿主门禁]
    Decision -->|满足执行条件| Tool[宿主工具]
    Tool --> Observe[调用结果关联 / Observation]
    Gate --> Receipts[签名决策与执行回执链]
    Observe --> Receipts
    Receipts --> View[控制台追溯与核对]
    Console -.->|显式接入| LocalBackend[本地 OpenShell 适配 / 策略加载与读回]
    end

    subgraph Enterprise[可选企业部署：独立身份与服务]
        direction TB
        Connectors[只读 Connectors] --> Edge[Edge：任务核验 / 证据签名]
        Edge --> Control[Control API / Worker]
        EnterpriseUI[企业控制台 / 人工审批] --> Control
        Control --> DB[(PostgreSQL / 审计 / outbox)]
        Control --> Backend[企业执行后端适配 / 策略读回]
    end
    Local ~~~ Enterprise
    classDef authority fill:#fff8e6,stroke:#9a7417,color:#513b08
    classDef runtime fill:#eaf1fb,stroke:#43658f,color:#142f53
    classDef evidence fill:#eaf6f1,stroke:#3b7965,color:#174d3d
    style Local fill:transparent,stroke:none
    style Enterprise fill:transparent,stroke:none
    class Human,Authority,Identity,Context authority
    class Admission,Gate,LocalBackend,Control runtime
    class Observe,Receipts evidence
```

### 任务执行与效果核验

```mermaid
---
config:
  themeVariables:
    fontSize: 16px
---
flowchart TB
    Task[用户任务] --> Proposal[Agent 规划 / Skill 选择 / 工具提议]
    Authority[Grant / Intent / 来源与上下文约束] --> Gate[SIQ 执行前复验]
    Proposal --> Gate
    Gate -->|allow 或宿主支持的 redact| Tool[宿主门禁内执行获准参数]
    Gate -->|deny / 不满足条件| Stop[阻断本次调用]
    Gate -->|hold| Approval[等待本地批准 / 按宿主协议恢复]
    Approval --> Recheck[重验当前授权与最终参数]
    Recheck -->|无效 / 过期 / 已撤销| Stop
    Recheck -->|有效| Reserve[原子持久化唯一签名执行预留]
    Reserve -->|预留成功且响应明确| Tool
    Reserve -.->|已预留但执行未确认| Uncertain[uncertain：核对事实 / 不盲目重放]
    Tool --> Observation[宿主结果报告 / Observation]
    Observation --> Receipts[关联 action / decision / reservation 回执]
    Gate --> Receipts
    Reserve --> Receipts
    Tool -.->|已接入的观察器采样| Effect[文件或接收端材料 / EffectEvidence]
    Requirements[签名 Intent 中的效果要求] --> Completion[SIQ 校验材料与动作 / 逐项判定完成]
    Receipts --> Completion
    Effect --> Completion
    Completion --> Result[verified / incomplete / conflicting / unknown]
    classDef authority fill:#fff8e6,stroke:#9a7417,color:#513b08
    classDef runtime fill:#eaf1fb,stroke:#43658f,color:#142f53
    classDef evidence fill:#eaf6f1,stroke:#3b7965,color:#174d3d
    class Authority,Approval,Requirements authority
    class Gate,Recheck,Reserve,Completion runtime
    class Observation,Receipts,Effect,Result,Uncertain evidence
```

- **执行前**：静态检查 Skill 并固定内容摘要；通过 Grant、Intent、实例/会话身份、受信 Context 和参数来源约束动作。需要可信 Skill 归属时复验 SEC，名称或安装路径本身不构成证明。模型输出不能创建有效权限。
- **执行时**：适配器在已接入入口执行裁决并保留宿主自身门禁。支持的 hold 恢复路径在本地批准后重验权限与最终参数，先持久化唯一执行预留再尝试工具；拒绝、过期、撤权或恢复能力缺失时阻断。已预留而执行未确认记为 `uncertain`，不自动重放。
- **执行后**：按动作/决策/预留身份关联结果与签名回执；在已接入的文件或接收端观察器中采集效果材料。Completion 结合签名 Intent 的效果要求、动作授权与有效材料判定，证据缺失或冲突不能显示为完成。

图中虚线表示显式接入或条件性路径，不代表所有工具都有独立效果采集。审批与宿主门禁的先后由各适配协议约束；OpenClaw 原版与固定检查点补丁副本的能力分开验证。`redact` 仅在宿主支持改参时使用；不支持的映射按适配器协议处理。

普通 Observation 的结果关联与独立 EffectEvidence 的效果核验具有不同证明范围；`uncertain` 是执行预留状态，不是 Completion 的第五种完成结论。架构、合同和方法细节见[技术报告](docs/research/technical-report.md)、[合同目录](packages/contracts/README.md)与[安全边界](#安全边界)。

## DGX Spark 与 NVIDIA OpenShell 深度适配

**DGX Spark 承载本地 AI 工作负载，SIQ 管理动作授权与证据，OpenShell 承担其实际支持的执行隔离和策略约束。** 本仓已提供专用部署、环境预检、模型与服务身份检查，以及 Go / Python OpenShell 后端适配；适配深度覆盖部署、授权、策略、读回、故障恢复和证据验证。

| 适配层 | 已落地机制与证据 | 适用范围 |
| --- | --- | --- |
| DGX Spark 环境与部署 | [专用部署配置](deploy/dgx-spark/README.md)记录 DGX Spark / GB10 / aarch64 环境；预检采集硬件、驱动、CUDA、源码身份和服务状态 | 环境预检与实际模型推理分别验证，健康检查不自动升级为部署或任务验收 |
| 本地模型与数据驻留 | 保留 Ornith / StepFun 分轨实验；新增 Hermes 0.21 / Qwen / OpenShell 的隔离报告旅程；本地敏感分析失败不静默回退远程 | 结果只覆盖对应模型、配置与任务；Qwen 验证不替代固定 Nemotron 路径，见[环境待验项](docs/development/remaining-environment-gates-20260924.md) |
| 网关身份与能力诊断 | 配置指纹、真实网关握手、mTLS 环境接入、目标策略读回；区分 CLI 版本、配置事实、握手及行为证据 | `gateway info` 成功不等于后端已就绪；版本提升不自动赋予能力，缓存与证据会失效 |
| 策略保真与权限编译 | 从获准网络范围生成策略；读回保留程序、端点及可表达的 method/path、CIDR 等限制；不可保真写入拒绝降格 | 网络动态策略与文件系统/进程等静态段分开处理，不承诺所有限制都能在线修改 |
| 加载确认与恢复 | Go 与 Python 的实际应用/回滚使用有界 `--wait --timeout`；核对修订/摘要，拒绝漂移、越权恢复和已知不可恢复的基线替换 | 加载超时保留副作用可能发生的不确定性，不重试为无等待写入；当前操作协调有明确进程范围 |
| 受约束任务执行 | 执行前重验目标实例、策略加载与授权；新增绑定请求的监督、撤权、崩溃与清理恢复，保留未知状态，见[当前开发](docs/development/current.md) | 特定请求路径的恢复验证不等于所有网关版本可远端单任务停止，也不等于正式发行验收 |
| 实机负向验证 | 归档 OpenShell **0.0.83** 独占测试目标的允许正控、跨边界 HTTP 403、独立接收端零到达及原策略恢复；另有 rc.6 的 57 项策略 HTTP 旅程 | [加载等待修复与实测](docs/openshell-policy-load-wait-repair-20260916.md)绑定当时源码、候选和网关；后续候选及其他版本需重新验证 |

上游策略机制参考 [NVIDIA OpenShell 官方文档](https://docs.nvidia.com/openshell/sandboxes/policies)。上游文档会随版本演进，本仓能力声明以已适配实现和具体版本实测为准。**配置可表达、策略可读回、沙箱确认加载、行为实际受阻是不同证据层级**，不能相互替代。

主线已有受约束执行入口、请求级恢复和 DGX 原生 CI 工作流；工作流已合入不代表真实 runner 已完成验收。跨场景停止确认、固定 Nemotron、新候选端到端性能与完整验收继续分别记账。DGX 上的 CPU 夹具测试也与 GPU/本地模型推理分别统计。普通 Linux 用户仍可独立使用本地安全管理和无密钥研究演示。

## 快速开始

使用已签发版本可直接下载 [0.4.0 完整离线包](https://github.com/maoyadongsh/siq-agent-security/releases/download/siq-agent-security-v0.4.0/siq-agent-security-0.4.0-bundle.zip)，按[安装说明](docs/signed-release-packaging.md)解压、验签并启动本地服务，无需本地编译 Go/UI。包内 `INSTALL.md` 已包含首次启动步骤：先验签，再使用已验签程序的 `start` 初始化状态并启动。直接调用 bootstrap 仍须先初始化。以下保留源码开发与研究复现步骤；GitHub 自动生成的 Source code 压缩包不是签名安装包。

0.4.0 的公开附件、固定源码、源码清单、验签、Linux ARM64 原生启动、篡改拒绝和远端逐字节回读见[正式发行记录](docs/evidence/releases/0.4.0/README.md)。Skill-only 联网解析必须使用 0.4.0 签名清单中的版本化 URL，不能混用旧 RC 的清单或二进制。

### 个人管理端：Linux 源码体验

以下使用当前 `main` 的前台启动入口，准备 Git、Go **1.26.6**、Node.js **22 / npm**；不需要企业 Control API 或 PostgreSQL。在仓库根目录运行（尚未克隆时先执行下方演示中的 `git clone` 和 `cd`）：

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build:local
mkdir -p .tmp/personal-bin
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield build \
  -o "$PWD/.tmp/personal-bin/siq-agent-security" ./cmd/agentshield

export SIQ_AGENT_SECURITY_STATE_DIR="$PWD/.tmp/personal-state"
.tmp/personal-bin/siq-agent-security start --port 47611
```

保持终端运行，打开 **http://127.0.0.1:47611/overview**，使用服务打印的一次性配对码。配对码过期时，在另一终端进入同一仓库根目录运行：

```bash
export SIQ_AGENT_SECURITY_STATE_DIR="$PWD/.tmp/personal-state"
.tmp/personal-bin/siq-agent-security pair --port 47611
```

`start` 会初始化或复用该目录的配置；首次运行在前台提供服务，按 `Ctrl+C` 停止。若同一目录的匹配实例已在运行，命令返回其状态；需要新配对码时使用上面的 `pair`。示例状态保存在 `.tmp/personal-state`，再次使用时保持同一路径，清理 `.tmp` 前先保留需要的数据。后台安装、升级与恢复命令及其平台限制见[本地操作指南](AGENTSHIELD.md)，操作时保持状态目录与实例一致。完整的配对、权限确认、Skill 更新、原文与导出、保留退出流程见[个人客户端操作手册](docs/personal-client-operation-guide-20260916.md)。

<details>
<summary>前端开发与「未连接」排查</summary>

先保持上述 Go 服务运行，再在另一终端执行：

```bash
npm --prefix apps/web run dev:local
```

使用 Vite 打印的地址访问个人界面。开发代理固定连接 `http://127.0.0.1:47611`；`dev:local` 只启动前端，不会启动后端。若显示「未连接」或「决策 API 不可达」，先检查本地 Go 服务与端口，再完成配对。企业前端使用独立的 Control API 配置，不能与个人入口混用。正式嵌入式界面由 Go 服务直接提供，无需同时运行 Vite。

</details>

### 1. 启动无需模型密钥的研究演示

已验证的入门环境为 Linux；准备 Git、Go **1.26.6**、Python **3.12+**、Node.js **22 / npm**。首次安装依赖和工具链需要联网。请使用新克隆的目录：启动器会拒绝覆盖已有演示状态。

```bash
git clone https://github.com/maoyadongsh/siq-agent-security.git
cd siq-agent-security

bash scripts/hackathon/start.sh --mode test --port 47621
bash scripts/hackathon/healthcheck.sh
bash scripts/hackathon/pair.sh
```

启动器会安装 Web 锁定依赖、构建本地界面和 Go 程序。打开 **http://127.0.0.1:47621/demo**，输入终端给出的一次性配对码，再选择上表中的场景。配对码和服务状态文件应留在本机。

> [!NOTE]
> `--mode test` 必须显式给出：启动器默认的 `demo` 模式会使用配置的真实模型。需要固定首发源码时，在启动前执行 `git switch --detach research-v0.1.0-rc.1`。

体验完成后停止这个演示实例：

```bash
bash scripts/hackathon/stop.sh
```

再次启动前，需要先按[复现指南](REPRODUCIBILITY.md)归档该实例的旧状态。端口冲突、配对问题和环境诊断也见该指南。

### 2. 复现固定基准

额外准备 **uv**，从仓库根目录运行。每次尝试使用新的状态目录和输出目录。

```bash
(cd apps/control-api && uv sync --dev --locked)
mkdir -p .tmp/research-bin
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield build \
  -o "$PWD/.tmp/research-bin/siq-agent-security" ./cmd/agentshield

apps/control-api/.venv/bin/python benchmarks/hackathon/run.py \
  --binary .tmp/research-bin/siq-agent-security \
  --state-root .tmp/my-research-controls \
  --out .tmp/my-research-results/controls.json

apps/control-api/.venv/bin/python benchmarks/hackathon/verify.py \
  .tmp/my-research-results/controls.json \
  --out .tmp/my-research-results/verification.json
```

默认执行全部 **23 个固定控制案例**。查看预期是否满足和 verifier 结果；攻击案例的 `blocked`、伪成功案例的 `incomplete` 都可能是正确结果。保留失败尝试，分享前按[证据导出规则](docs/research/data-export-policy.md)检查报告，不上传私密状态目录。

### 3. 可选：接入真实模型

<details>
<summary>查看 StepFun + DGX Spark 配置入口</summary>

历史实模型演示使用 **StepFun `step-3.7-flash` 远程规划**与 **DGX Spark 上的 Ornith 本地分析**。后续另有 Hermes 0.21 / Qwen / OpenShell 的隔离报告旅程，见[最新收尾记录](docs/development/flagship-closeout-current-20260924.md)，不替代原定 Nemotron 或真实业务账号验收。这些路径需要独立配置模型、私密凭据和硬件；与无密钥路径分开运行、分开统计。

从 [DGX 部署说明](deploy/dgx-spark/README.md)、[私密模型配置](docs/hackathon/step-plan.md)和[三轨复现指南](REPRODUCIBILITY.md)进入。机密分析的本地失败不能因此自动获准回退到远程模型。

</details>

## 研究与证据

### 从研究问题到真实工程

项目围绕五个问题形成连续研究链路：运行时授权能否在保留正常任务能力的同时约束危险动作；同值参数的来源差异是否影响授权；工具成功与实际效果能否区分；机密分析是否遵守配置的本地路径；动态 Skill 编排的安全、效用和成本如何权衡。问题定义与待补实验见 [RQ1–RQ5](docs/research/research-questions.md)。

| 研究阶段 | 仓库中的对应产物 |
| --- | --- |
| 明确信任边界与攻击路径 | [威胁模型](docs/threat-model.md)、[研究概览](docs/research/research-overview.md)、[前沿参考文献目录](research/literature/README.md) |
| 将理论问题写成可执行约束 | [开发规格](docs/agentshield-dev-spec-v1.md)、[版本化合同](packages/contracts/README.md)、受信上下文与参数来源绑定 |
| 实现跨组件运行时 | Go 决策与签名、Python Secure Agent、原生适配器、OpenShell 策略后端与浏览器管理界面 |
| 用对照与负例检验机制 | 同值不同来源、伪成功、撤权、重放、漂移、未知恢复对象等测试；[固定案例](benchmarks/hackathon/README.md)与[运行时基准](benchmarks/runtime-security/README.md) |
| 复现、审阅并反馈产品 | [评价协议](docs/research/evaluation-protocol.md)、[结论—证据映射](docs/research/claims-evidence.md)、候选摘要、签名验证、CI、真实宿主旅程及失败保留 |

### 与前沿智能体安全研究的关系

- **模型外的权限与信息流约束**：[CaMeL（2025）](https://arxiv.org/abs/2503.18813)研究控制/数据流分离和工具调用能力约束。SIQ 在自身架构中落实独立授权、受信来源注册和执行前检查；不把模型的自我判断作为权限来源。
- **参数来源与用户授权对齐**：[AuthGraph（2026，预印本）](https://arxiv.org/abs/2605.26497)研究将执行来源关系与授权基线对照。SIQ 的相关研究点是已实现的参数来源绑定和“同值不同来源”控制案例；它不等同于复现该论文的双图算法。
- **同时评估攻击与正常任务效用**：[AgentDojo（2024）](https://arxiv.org/abs/2406.13352)提供工具型智能体在不可信数据环境中的评测框架。SIQ 对自己的固定语料分别统计正常完成、不安全效果与证据完整性；当前结果不属于 AgentDojo 排名，也不与其他论文实验合并分母。

上述文献用于说明研究背景与机制关联；SIQ 的实现、实验和创新性评价以仓内可复核产物为准，不借用外部论文的安全证明或性能数字。后续需补充预注册协议、未见任务、自适应攻击、消融与独立复现，才能进一步评价泛化能力和相对优势。

### 已归档结果

更新至 **2026-09-27**。以下按近期工程与发行验证、历史研究复现分别列出已归档结果；每项绑定自己的源码或候选、环境和测试范围，不能合并分母或直接迁移到其他版本。

**近期工程与签名发行验证（2026-09-18–27）**

| 已归档观察 | 结果 | 证据与范围 |
| --- | --- | --- |
| 0.4.0 正式发行 | 官方验签、四目标 pin、Linux ARM64 最终包启动和 **3/3** 篡改拒绝通过；远端 **8/8** 资产逐字节一致 | [发行记录](docs/evidence/releases/0.4.0/README.md)；固定 `2cd6116`，正式版、Latest；不含其他目标原生安装或跨平台升级/回滚验收 |
| 当前主线整合与验收 | 合并后 Control API **2257 passed / 1 skipped**；全面验收另行记录 Web **1012 passed**、14 个 Go 模块与隔离浏览器 **30/30**；当前 `main` CI 通过 | [主线整合](docs/development/main-branch-integration-20260926.md)、[全面验收](docs/development/enterprise-comprehensive-acceptance-review-20260926.md)、[合并后交接](docs/development/enterprise-post-merge-remaining-closeout-handoff-20260926.md)；不同运行和计数口径不合并，源码/CI 验证不等于正式发行或生产验收 |
| 企业 API / Web 部署更新 | 数据迁移、备份恢复、新旧镜像切换及登录入口检查通过 | [部署记录](docs/development/enterprise-runtime-delivery-20260924.md)；既有 Gateway / IAM 入口，未完成真实账号登录、独立审批与跨系统结果旅程 |
| 新报告工具客户端交接 | 四目标构建、Linux ARM64 原生启动及旧源码清单拒绝通过 | [发行交接](docs/development/client-report-release-handoff-20260924.md)；二进制绑定 E163 加 11 文件增量，未正式签发，不能改标为合并提交构建 |
| OpenClaw 2026.9.5 原生组件与输出 | 插件/工具包装、会话隔离、输出授权与重启持久化验证通过 | [E155 验证](docs/development/ux-runtime-output-openclaw-e155-validation-20260923.md)；调用后 relay 为夹具，不等于全模型业务旅程或独立效果证明 |
| 0.3.1 正式安装包验证 | 官方验签与本机链路通过；**3/3** 篡改拒绝 | [本版记录](docs/evidence/releases/0.3.1/README.md)；源码 `f3d9c3f`，四目标 pin 与内容核验，Linux ARM64 最终包 start/status/pair/控制台/stop；其余目标未做本版原生安装 |
| 0.3.1 正式发布与源码 CI | **8/8** 资产一致；**6/6** 源码工作流成功 | [公开回读](docs/evidence/releases/0.3.1/publication.json)、[源码记录](docs/evidence/releases/0.3.1/source-ci.json)；正式版、回读当时为 Latest；工作流数量不代表测试项数 |
| Skill 源码四目标检查 | **4/4** 原生目标通过 | [固定候选记录](docs/evidence/repository-reorganization-final-20260919/README.md)；PR #97 head `bf7dced`，实际 merge 检出 SHA 见各报告；Linux amd64/arm64、macOS arm64、Windows amd64 的自扫描、缺清单拒绝与启动/配对/控制台/停止。属于源码检查，不是 0.3.0 系统服务安装、升级或宿主整体验收 |
| 0.3.0 正式安装包验证 | **14/14** 检查通过 | [发行包验证](docs/evidence/releases/0.3.0/verification.json)；源码 `83fde2d`，官方根验签、篡改拒绝及 Linux ARM64 安装链路；新增执行包内 INSTALL.md，从空状态完成启动、配对、控制台与停止；其他目标未做原生安装验收 |
| 0.3.0 正式发布与远端回读 | **8/8** 资产摘要一致 | [发布回读记录](docs/evidence/releases/0.3.0/publication.json)；普通 Release，Latest 为当时回读状态；四目标 pin、Skill 签名与内容复验通过，Linux ARM64 签名 URL 下载与暂存通过 |
| 0.3.0 发行源码 CI | **5/5** 工作流成功 | [源码 CI 记录](docs/evidence/releases/0.3.0/source-ci.json)；固定提交 `83fde2d`，ci、research、runtime-security、personal-experience、sonarcloud；不替代发行资产的原生安装验收 |
| 0.3.0-rc.1 签名安装包验证 | **13/13** 检查通过 | [发行包验证](docs/evidence/releases/0.3.0-rc.1/verification.json)；源码 `58ab22e`，含官方根验签、六条负向、Linux ARM64 bootstrap、控制台及正常退出；其他目标未做原生安装验收 |
| 0.3.0-rc.1 远端资产回读 | **8/8** 资产摘要一致 | [发布回读记录](docs/evidence/releases/0.3.0-rc.1/publication.json)；四目标二进制 pin、Skill 内容与签名复验通过，并验证 Linux ARM64 签名 URL 下载与暂存 |
| Linux 已安装服务与用户旅程 | B02 **16/16**；已装 R07 **31/31**，嵌套 R04 **31/31** | [同候选验证](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx02-sec-hold-fix-installed-summary.json)；第六代来源候选 `67bc48c4…`，使用测试发行信任根；不是 0.3.0 的完整用户旅程验收 |
| Hermes 原生 CLI 与浏览器审批 | **24/24** 检查通过 | [原生审批联合验证](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx03-hermes-browser-approval-native-summary.json)；候选 `67bc48c4…`，含批准、拒绝、参数/对象漂移、并发和撤权；使用无头浏览器与合成模型 |
| OpenClaw 2026.9.4 受控启动 | **22/22** 检查通过 | [托管原生 CLI 验证](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx03-openclaw-2026.9.4-controlled-managed-native-summary.json)；候选 `67bc48c4…`，隔离安装与固定补丁副本；不代表上游原版具备批准后检查点 |
| 浏览器管理会话竞态修复 | Web **117/117**；真实浏览器定向 **2/2** | [会话修复验证](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx05-session-transition-eighth-summary.json)；第八代局部修复候选 `a85c76b0…`；不继承第六代的 systemd/OpenShell 验收 |
| OpenShell D05 实机功能矩阵 | **373** 步：365 pass / 7 partial / 1 blocked / **0 fail** | [D05 结果](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-d05-summary.json)；候选 `67bc48c4…`、后端 0.0.83；远端单任务停止仍受限，零 fail 不等于全部验收通过 |
| OpenShell B3 功能旅程 | **57/57** 通过 | [B3 结果](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx06-sec-hold-fix-b3-summary.json)；同为候选 `67bc48c4…`，覆盖策略应用、回执、拒绝、撤权与回滚；不含性能预算验收 |
| PostgreSQL + OIDC/JWKS 集成 | **27/27** 检查通过 | [隔离集成结果](docs/evidence/personal-experience/linux-dual-host-20260918-211200/lx07-postgres-oidc-jwks-rotation-summary.json)；Control API 源码 `2187fea`，含密钥轮换、过期缓存拒绝与恢复；本地 PostgreSQL 与测试签发者，不是客户生产验收 |

**历史研究复现与首发记录（保留原运行口径）**

| 已归档观察 | 结果 | 证据与范围 |
| --- | --- | --- |
| 固定控制案例 | **23/23** 满足预期 | [报告与验签摘要](docs/research/result-reproduction.md)；开发期间的受控夹具运行 |
| 正常任务完成 | **5/5** | 同一控制报告中的全部正常任务 |
| 不安全目标实际执行 | **0/13** | 注册了不安全目标的案例；分母与正常任务不同 |
| 回执与效果封装校验 | **318** 条回执、**20** 个效果封装 | [独立验证输出](docs/research/evidence/reproduction-b/verification.json) |
| 普通 Linux 浏览器复现 | **9/9** 场景通过 | [托管 Ubuntu 运行记录](docs/research/evidence/reproduction-a/hosted-linux-identity.json)；无需 GPU 或模型密钥 |
| 首发源码 CI | **31** 项必需检查通过 | [发布源码记录](docs/research/evidence/release-ci.json)；对应 `aefab111` |

历史 StepFun 与 Ornith 正常任务 cohort 各保留了后续 **5/5** 的结果，早期 **4/5** 的失败也完整保留在[原始基准报告](docs/hackathon/benchmark-report.md)。这些小样本不构成统计保证，不能与固定夹具或后续演示合并分母。托管 CI 复现也不等于外部研究者的独立复现。

研究入口：[研究问题](docs/research/research-questions.md) · [数据卡](docs/research/dataset-card.md) · [评价协议](docs/research/evaluation-protocol.md) · [逐项结论与证据](docs/research/claims-evidence.md)。当前没有已发表论文、DOI 或独立制品认证。

## 组件与接入

| 组件 | 职责 | 使用入口 |
| --- | --- | --- |
| Secure Agent 与研究 Skills | 任务规划、动态选择研究 / 报告 / 交付能力 | [Agent 说明](apps/secure-agent/README.md)、[Skills](skills/) |
| 本地 Go 运行时与个人控制台 | 准入、授权、Skill 生命周期、审批、任务与隐私管理、签名回执；个人 UI 随 Go 服务内嵌 | [个人 UI](apps/web/README.md)、[运行时说明](apps/agentshield/README.md)、[本地操作指南](AGENTSHIELD.md)、[开发规格](docs/agentshield-dev-spec-v1.md) |
| SIQ Skill 与发行工具 | 操作指引、发行清单验签与安全暂存；从固定提交构建和签发安装包 | [Skill 源码](skills/siq-agent-security/)、[发行工具](scripts/release/package.py)、[安装说明](docs/signed-release-packaging.md) |
| 运行时适配器 | 当前产品矩阵按 OS 接入 Hermes、OpenClaw、WorkBuddy | [适配器目录](adapters/runtime/README.md)、[能力矩阵](docs/agentshield-capability-matrix-v1.md)、[平台范围决策](docs/personal-platform-scope-decision-20260917.md) |
| OpenShell 与 DGX Spark 接入 | 专用部署预检、本地推理配置、策略授权/加载/恢复、受约束任务执行与分级诊断 | [DGX Spark 部署](deploy/dgx-spark/README.md)、[OpenShell 适配](apps/agentshield/internal/openshell/)、[实机证据](docs/openshell-policy-load-wait-repair-20260916.md) |
| 企业控制面 | 多租户资产、角色工作台、接入引导、策略审批、部署确认与恢复、业务结果导航及 Edge 协调 | [API 模块](apps/control-api/README.md)、[控制面说明](docs/control-plane.md)、[生产运行手册](docs/enterprise-production-runbook-v1.md) |
| Edge 与 Connectors | 配置、目录、框架、进程、容器及集群采集；SIQ Connector 读取本地业务安全事件投影，不访问业务数据库或持有业务凭据，暂不提供 Edge 远端调度注册 | [Edge](edge/agent/README.md)、[Connectors](connectors/README.md)、[SIQ Connector](connectors/siq/README.md)、[兼容说明](docs/compatibility.md) |
| 合同与基准 | 跨组件数据合同、固定语料和证据验证 | [合同](packages/contracts/README.md)、[Agent 基准](benchmarks/hackathon/README.md)、[运行时基准](benchmarks/runtime-security/README.md) |

本地演示无需 PostgreSQL、企业登录或企业 API。平台的采集能力、工具阻断能力和实机验证状态分别登记；存在适配器不代表所有版本、所有调用路径均受保护。企业生产部署条件和未验证事项以对应运行手册为准。

## 安全边界

- **同 UID 不隔离**：当前桌面模式不能阻止同一操作系统用户的恶意进程读取密钥或改写状态；Python ToolGateway 不是 OS 沙箱。
- **接入范围有限**：授权检查只覆盖正确接入的执行路径；来源注册与敏感级别分类仍依赖可信操作者。
- **效果证明有范围**：文件与受控接收端的观察不代表对所有外部 SaaS 的交付证明；缺失或冲突的证据不能当作成功。
- **实验结论有限**：固定小语料与模型夹具不代表通用提示注入防护、完整语义来源追踪或生产安全认证。跨平台编译也不等于各平台原生验收。

完整说明见[威胁模型](docs/threat-model.md)、[能力矩阵](docs/agentshield-capability-matrix-v1.md)和[数据卡](docs/research/dataset-card.md)。未修复漏洞请通过 [SECURITY.md](SECURITY.md) 的私密入口报告。

## 贡献与下一步

欢迎普通 Linux 复现、同值来源解释、夹具诊断、指标纠错和有来源依据的负向案例。先阅读[贡献指南](CONTRIBUTING.md)，再选择[首批任务](docs/research/community-backlog.md)、[Issues](https://github.com/maoyadongsh/siq-agent-security/issues)或 [Discussions](https://github.com/maoyadongsh/siq-agent-security/discussions)。

产品交付继续按“个人体验 → 局域网团队多设备管理”推进，近期安排如下：

1. **继续补齐 0.4.0 平台验收。** 正式版已固定主线源码、使用原发行信任根签发并完成公开回读；后续完成另外三个目标的原生安装、四目标同版本系统服务、升级、回滚与退出验证，补齐平台签名、公证及兼容边界。
2. **完成真实环境中的使用流程。** 复测已实现的个人端接入、授权与输出路径；企业端补齐真实组织身份、独立审批、业务站点与结果访问联验。继续处理固定 Nemotron、DGX 原生 CI、OpenClaw 原版检查点及 OpenShell 跨场景停止和性能条件，不用隔离账号或组件测试替代业务验收。
3. **推进团队多设备管理。** 在既有企业控制面和 Edge 基础上完善设备接入、统一授权、离线恢复与跨设备审计，完成实际环境验收后再扩大交付范围。

任务和验收依据见[当前开发](docs/development/current.md)、[客户端发行交接](docs/development/client-report-release-handoff-20260924.md)、[企业部署记录](docs/development/enterprise-runtime-delivery-20260924.md)与[环境待验项](docs/development/remaining-environment-gates-20260924.md)；总体路线保留在[个人与团队 v5 任务书](docs/personal-experience-lan-team-next-development-taskbook-20260915-232155.md)。

研究方向继续推进长期归档与 DOI、外部独立复现、预先确定协议的新实验，以及论文与制品评审。已发布的个人客户端 0.4.0 不改变研究源码标签、实验分母或研究结论；新的研究制品仍需独立的身份、分发与验收记录。实际进展见[开源实施记录](docs/research/operations-20260908.md)与[任务台账](docs/open-source-research-tasks-20260908.md)。贡献签署与评审遵循 [DCO](DCO) 和[治理规则](GOVERNANCE.md)，社区交流遵循[行为准则](CODE_OF_CONDUCT.md)。

## 许可、引用与历史材料

自有软件采用 **[Apache-2.0](LICENSE)**；明确列出的原创研究文档采用 **[CC BY 4.0](LICENSES/README.md)**。第三方代码、补丁与字体保留各自许可，详见[适用范围](LICENSES/scope.json)及[第三方归属](THIRD_PARTY_NOTICES.md)。模型权重和外部 API 服务不在项目许可之内。

引用软件时可从 **[CITATION.cff](CITATION.cff)** 取得项目名称与作者信息；其版本和日期当前对应 `research-v0.1.0-rc.1`。引用个人客户端 0.4.0 时请另注明该发行标签、源码 `2cd6116` 及实际制品摘要；实验另记录所用语料摘要。详见[引用指南](docs/research/citation-guide.md)。

| 社区与治理 | 研究与归档 |
| :--- | :--- |
| [贡献指南](CONTRIBUTING.md) · [DCO](DCO) | [引用指南](docs/research/citation-guide.md) · [CITATION.cff](CITATION.cff) |
| [治理规则](GOVERNANCE.md) · [行为准则](CODE_OF_CONDUCT.md) | [研究技术报告](docs/research/technical-report.md) · [复现指南](REPRODUCIBILITY.md) |
| [私密安全报告](SECURITY.md) · [第三方归属](THIRD_PARTY_NOTICES.md) | [比赛演示](HACKATHON.md) · [V5 冻结快照](docs/hackathon/final-submission-state.md) |
| [开发约定](AGENTS.md) · [持续集成](https://github.com/maoyadongsh/siq-agent-security/actions) | [开源实施记录](docs/research/operations-20260908.md) · [任务台账](docs/open-source-research-tasks-20260908.md) |

比赛快照保留当时的源码、制品、视频和实验分母；本轮研究发布及后续文档更新使用各自的身份记录。
