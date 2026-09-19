# 研究与复现

本页把研究问题、文献线索、产品机制和可核验的实验连接起来。产品的安装与运行说明见 [README](../README.md)；[复现指南](../REPRODUCIBILITY.md)解释如何复算固定语料。这里的关联用于定位材料，不表示某篇文献验证了 SIQ 的产品效果，也不替代论文原文的审读或引用信息核验。

| 研究问题 | 文献与理论线索 | 当前实现入口 | 评价方法、结果与边界 |
| --- | --- | --- | --- |
| Agent 的工具提议如何受独立授权约束？ | [Agent Security is a Systems Problem](<../Frontier References on Agent Security/2605.18991v2-Agent Security is a Systems Problem.pdf>)；[Symbolic Guardrails](<../Frontier References on Agent Security/2604.15579v2-Don't Make Models Guess Security and Safety：Symbolic Guardrails for Domain-Specific AI Agents.pdf>) | [本机安全规格](../docs/agentshield-dev-spec-v1.md)；[企业合同](../packages/contracts/) | [研究问题 RQ1](../docs/research/research-questions.md)；[固定控制与证据](../docs/research/claims-evidence.md)。固定样本不能外推一般防护率。 |
| 同一参数值的来源是否改变授权结果？ | [Aligning Provenance with Authorization](<../Frontier References on Agent Security/2605.26497v1-Aligning Provenance with Authorization：A Dual-Graph Defense for LLM Agents.pdf>)；[Provenance-Bound Context Attestation](<../Frontier References on Agent Security/ssrn-6938859-Provenance-Bound Context Attestation and Deterministic Policy Authorization for Agentic AI Actions.pdf>) | [Secure Agent](../apps/secure-agent/)；[本机运行时](../apps/agentshield/) | [RQ2 与同值不同源对照](../docs/research/research-questions.md)；[主张—证据映射](../docs/research/claims-evidence.md)。已配置来源身份的对照不等于通用语义来源识别。 |
| 工具声称成功与实际效果怎样区分？ | [Beyond Binary Success](<../Frontier References on Agent Security/ssrn-7035858-Beyond Binary Success：Propagation Profiles for LLM Agent Security Traces.pdf>)；[SafeClawBench](<../Frontier References on Agent Security/2606.18356v1-SafeClawBench：Separating Semantic, Audit-Evidence, and Sandbox Harm in Tool-Using LLM Agents.pdf>) | [效果证据与回执规格](../docs/agentshield-dev-spec-v1.md)；[固定语料](../benchmarks/hackathon/) | [RQ3](../docs/research/research-questions.md)；[受控接收端对照](../docs/research/claims-evidence.md)。未观察到效果与证明没有效果是两种不同状态。 |
| 多宿主与隔离后端的能力如何分层声明？ | [Agent Security Needs Redefinition](<../Frontier References on Agent Security/2607.22024v1-Agent Security Needs Redefinition through a Holistic Framework.pdf>)；[Two-Plane Approach](<../Frontier References on Agent Security/Runtime Security for Agentic Systems A Practical Two-Plane Approach for OpenClaw-Class Agents.pdf>) | [运行时适配器](../adapters/runtime/)；[OpenShell 接入](../apps/agentshield/internal/openshell/)；[平台范围决策](../docs/personal-platform-scope-decision-20260917.md) | [Linux 双宿主当前候选任务书](../docs/linux-dual-host-integration-development-taskbook-20260918-205119.md)与[阶段进度](../docs/linux-dual-host-progress-20260918.md)。配置、读回、加载和行为拦截分别验收；Linux 交付范围只有 OpenClaw/Hermes。 |

完整的本仓研究设计、数据口径、技术报告、历史失败与复现记录见下方材料索引；原始文献文件保留在根目录的 [Frontier References on Agent Security](<../Frontier References on Agent Security/>)。该目录包含不同来源和发表状态的材料，文件名不构成已同行评审或允许再分发的声明。引用前应核查原文、版本和权属；本仓的软件引用政策见 [citation policy](../docs/research/citation-policy.md)。

当前产品代码合并、组件测试、真实宿主验收与正式发行分别记账。贡献者实验也不自动等同独立第三方测评。[主张—证据表](../docs/research/claims-evidence.md)和各批次原始报告保留候选、语料、失败与限制；没有 DOI、论文接受或普遍安全保证的声明。

## 研究路线

研究材料位于根目录 `research/`，与 `apps/`、`docs/` 平级。沿以下顺序阅读；每页连接问题、方法、实现、协议与证据，正文只维护一份。

[文献与理论线索](literature/README.md) → [研究问题 RQ1–RQ5](questions/README.md) → [方法与威胁边界](methods/README.md) → [实验设计与复现](experiments/README.md) → [发现与局限](findings/README.md)。[研究治理](governance/README.md)贯穿引用、贡献、数据与发布。

现有研究价值在于提供可运行的独立授权机制、来源与动作绑定、效果证据及可核查的受控实验；方法适用性和效用仍受任务、来源登记、观察器与运行环境限制，不把工程实现称为已获同行评审的创新。

## 材料索引

[文献目录](literature/README.md) · [评测与验收](../evaluations/README.md) · [平台交付](../platforms/README.md) · [当前开发](../docs/development/current.md)

| 研究资产 | 唯一正文 / 证据位置 |
| --- | --- |
| 问题与协议 | [研究问题](../docs/research/research-questions.md)、[回顾性评测协议](../docs/research/evaluation-protocol.md)；不冒称预注册 |
| 数据与主张 | [数据卡](../docs/research/dataset-card.md)、[主张—证据](../docs/research/claims-evidence.md)、[技术报告](../docs/research/technical-report.md) |
| 复现 | [运行指南](../REPRODUCIBILITY.md)、[归档复现](../docs/research/result-reproduction.md)、[贡献者固定案例运行](../docs/research/core-scenarios-reproduction-20260911.md) |
| 贡献与引用 | [贡献指南](../CONTRIBUTING.md)、[社区任务](../docs/research/community-backlog.md)、[引用政策](../docs/research/citation-policy.md)、[许可](../LICENSES/README.md) |
| 发布与治理 | [JSON 台账](../docs/open-source-research-tasks-20260908.json)、[生成视图](../docs/open-source-research-tasks-20260908.md)、[发布操作](../docs/research/operations-20260908.md)、[Skill 分发实验](../docs/research/skills-distribution.md) |
| 独立复现 | [外部结果入口](../evaluations/external/README.md)、[原始提交模板](../docs/research/external-reproduction-template.md) |

正文保留在 `docs/research/`，此处是唯一研究总览；根 `RESEARCH.md` 与旧总览只作稳定导航。已有导航足以消除入口歧义，当前不移动协议、技术报告、权属文件或证据，不复制第二份结论。文献索引标记未知的作者、来源核查与再分发权，不由文件名补造已发表/已评审信息。

研究源码版 `research-v0.1.0-rc.1` 与比赛 V5 保持各自冻结身份。客户端正式版 0.3.0 不更新研究分母、DOI 或独立复现状态。没有登记的外部结果保持待开展；协作者设备验证和托管 CI 均不作为独立第三方认证。
