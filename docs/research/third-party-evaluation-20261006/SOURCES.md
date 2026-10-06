# SIQ 合并测评方案的来源与采纳记录

版本 1.1，2026-10-06。配套[主方案](../third-party-evaluation-plan-20261006.md)。本页区分产品事实、外部方法和本方案设计决定，不提供测评结果。

## 1 仓内事实来源

设计核对的本地基线为 `5470ab3780f2228d77b0dd856553ea9e666de815`，工作区 dirty。下面链接用于定位，正式执行仍须保存选定候选的对应文件摘要。

| ID | 来源 | 支持的范围 |
| --- | --- | --- |
| L01 | [README](../../../README.md) | 产品路线与已披露平台边界，不替代新候选验收 |
| L02 | [威胁模型](../../threat-model.md)、[能力档位](../../agentshield-capability-profiles-v1.md) | 同 UID、信任组件、证据与隔离边界；其中历史条目须结合候选核对 |
| L03 | [运行时基准](../../../benchmarks/runtime-security/README.md)、[执行器](../../../benchmarks/runtime-security/run.py) | 21 对/42 场景的当前开发语料及决策/效果层差异 |
| L04 | [应用基准](../../../benchmarks/hackathon/README.md)、[执行器](../../../benchmarks/hackathon/run.py) | 23 控制、fixture 与模型 cohort、既有分母和留档语义 |
| L05 | [回顾性评价协议](../evaluation-protocol.md) | 旧研究结果是回顾性说明，不充当新实验预注册 |
| L06 | [Completion 实现](../../../apps/agentshield/internal/completion/evaluate.go) | 当前 unknown/not_required、incomplete、conflicting、verified 的判定结构 |
| L07 | [OpenShell 执行合同](../../../packages/contracts/openshell-task-execution.v1.md)、[实现](../../../apps/agentshield/internal/openshell/task_exec.go) | policy_apply 与真实任务执行分开；不推导远端原子执行/停止保证 |
| L08 | [适配器入口](../../../adapters/runtime/README.md) | 宿主、审批恢复与真实工具路径的边界 |
| L09 | [外部复现索引](../../../evaluations/external/README.md)、[提交要求](../../../evaluations/templates/README.md) | 外部复现登记和独立性类别；本方案不新增完成记录 |
| L10 | [受控效果观察器](../../../demo/fixtures/effect-oracle/README.md) | 接收端材料不等于通用 absence 证明或独立机构管理的 attestor |

## 2 官方外部方法来源

资料在本轮对话的 2026-10-06 研究/复核中查阅；以下是方法来源入口，不能当作固定实验依赖。执行时另锁 commit/revision、工具版本和页面/文件摘要。

| ID | 来源 | 使用方式 |
| --- | --- | --- |
| X01 | [AgentDojo 仓库](https://github.com/ethz-spylab/agentdojo) | 首选公开攻击/防御基准；固定版本枚举任务 |
| X02 | [AgentDojo pipeline](https://agentdojo.spylab.ai/concepts/agent_pipeline/)、[functions runtime](https://agentdojo.spylab.ai/concepts/functions_runtime/) | 薄适配与真实工具执行入口；保留官方评分器 |
| X03 | [SafeClawBench 论文](https://arxiv.org/abs/2606.18356)、[全文指标](https://arxiv.org/html/2606.18356v1) | 语义、审计和可执行损害分层；HarmEvidence 的全 Core 分母 |
| X04 | [SafeClawBench 数据与执行说明](https://huggingface.co/datasets/sairights/safeclawbench) | 核对 Exec fixtures 与执行文件；与论文/代码口径有差异时显式记录 |
| X05 | [SafeClawArena 官方仓库](https://github.com/sunblaze-ucb/SafeClawArena) | 四攻击面、容器和 canary；宿主版本变化须重跑同环境基线 |
| X06 | [Promptfoo Python Provider](https://www.promptfoo.dev/docs/providers/python/) | 可选包装既有 runner；持久 worker 要求每例显式隔离 |
| X07 | [Promptfoo 数据处理](https://www.promptfoo.dev/docs/red-team/troubleshooting/data-handling/) | 生成/评分/遥测/分享分开核对，禁远程生成不是断网保证 |
| X08 | [garak 运行机制](https://reference.garak.ai/en/latest/how.html) | 探针/检测器只作补充，真实效果另由外部判定器验证 |
| X09 | [OWASP Agentic Top 10](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) | 威胁覆盖分类，非产品认证或全覆盖背书 |

统计口径、240/1,440 执行规模、5 个百分点效用界限、复核比例和阶段工作量是本方案设计选择，不声称由上述资料证明是通用标准或已具备统计效力。置信区间的假设和实现须在正式协议中固定并校验。

## 3 用户提供材料

输入包括 `SIQ_Agent_Security_后续演进开发规划_20260920-101313.md` 和题为“SIQ 第三方安全测评方案 v1.0”、标注 2026-09-17 的粘贴文本。它们是规划和评审输入，不是当前候选结果。附件引用的 S1–S10/U1–U11 未附完整引用表，本任务包以 L/X 编号明确实际核对来源，不继承缺失编号的证据效力。

附件提及的 case_matrix、交接文档和 SOW 未随粘贴文本提供；本目录中的对应文件由此次合并重新设计产生，不冒称原附件或已实现工具。

## 4 采纳决议

| 输入思路 | 决议 | 合并位置 |
| --- | --- | --- |
| 外部 oracle 与内部 EVC 分开 | 采纳并落实独立存储/权限校准 | 主方案 §4，TP02，EV01–EV08 |
| 用户可见完成误报 | 采纳，UI 与 Agent 分列 | 主方案 §4.5/§11，EV08 |
| 单谓词来源消融 | 采纳，统一命名 A-PROV | 主方案 §5，TP03，PB01 |
| 事件级观察 | 采纳，缺事件覆盖不能判过程无害 | 主方案 §4.2，EV08/IN02/IN06 |
| 外部隐藏集和结论权限 | 采纳并补 SOW | 主方案 §8.4，EVALUATOR_SOW |
| 测评交付与产品通过分开 | 采纳 | 主方案 §13，SOW §7 |
| 30 类机制规范 | 映射到产品组，改独立命名空间 | case_matrix 与主方案 §6.5 |
| 240 次最小包 | 保留为可选独立隐藏 cohort，独立任务单位 20 | 预注册模板与主方案 §8.4 |
| Promptfoo 为主线 | 调整为可选外围接口，先做核心测量 | 主方案 §8.5，TP09 |
| garak 探针 | 采纳为补充，不混入核心效果分母 | 同上 |
| 旧主线 SHA、PR 五例和比例 | 仅作历史线索，不作为当前结果 | 主方案 §2 |
| 旧投稿截止日期、已有匿名 Artifact | 不并入执行主线；新投稿任务另核规则 | SOW §9 |
| 7–10 日整体工期 | 不作承诺，按环境与阶段估算 | 主方案 §16 |

## 5 验证范围

本轮只编辑方案任务包。验证包括本地链接、JSON 可解析性、30 族与 24 产品组映射、实验组命名、样本规模算术、命令语法和已有修改保护。没有执行产品测试、模型调用、外部测评或生产变更；文档和 JSON 的校验不增加安全证据数量。
