# 研究开源开发任务台账

[方案原文](open-source-research-plan-20260908.md) · [机器可读台账](open-source-research-tasks-20260908.json)

原文 18 个阶段已拆分为 **71 项执行任务**，覆盖全部 12 节。
当前状态：`done` 43 项；`not_applicable` 1 项；`todo` 20 项；`in_progress` 6 项；`blocked` 1 项。任务登记不等于工程实施或外部发布完成。

## 基线与执行规则

- 登记基线：`e72e8b36a71ae7f7f1fecd587bbe6eb2353f24d2`；登记分支：`codex/hackathon-final-release-v5`。
- V5 运行源码：`d1277116e8291e72b09b0462a19d0268b68bf46c`；原文档提交独立保留。
- 研究 submission SHA：`尚未确定`。
- 方案 SHA256：`b2e9a1e927c8e90e2994bcfe4beb4d0358e33d638486908ccbfacc5f9a601ab2`。

- JSON 为执行状态事实源，Markdown 是同内容的阅读投影；修改状态时两者同步并重算汇总。
- assignee=null 表示尚未指派，owner_role 仅建议角色；不虚构人员承诺。
- depends_on 表示完成依赖，不阻止先做无依赖的准备部分；不能越过依赖发布结果。
- 执行前核查会话授权；有效授权持续适用，不能因为台账列了决策便再次索要同一授权。
- 条件任务仅有不适用证据才能 not_applicable，未知或等待外部输入保持 todo/blocked。
- recurring 每次执行单独归档证据与时间；整体任务保持持续状态，不作为首轮发行必须永久完成的条件。
- 新实现使用独立研究工作树/分支，不直接在 main 开发，不修改 V5 冻结包、历史 corpus 或原始失败结果。
- planned_outputs 是计划路径，非现有产物证明；evidence 初始为空。
- 任务完成须记录验收对应的验证命令、结果及证据；不能因文件存在、任务登记或推送而自动 done。
- A/B 无模型复现独立于 C 的设备/预算；C 未执行则不发布新 C 实测结论。
- 首轮研究发行完成不等于论文接收、正式 artifact badge 或全部持续维护任务完成。
- planned_validation 仅为预定方法；validation 是实际执行记录，两者不得混淆。

维护方式：修改 JSON 中的任务状态和实际证据后，运行以下命令生成阅读版并校验；不可手改 Markdown 造成漂移。

```bash
python3 scripts/check_research_task_ledger.py --write
python3 scripts/check_research_task_ledger.py
```

状态：`todo`：尚未开始；已有历史能力不能替代本周期验收；`in_progress`：正在执行；`blocked`：有实际阻塞，blocker 写明依赖与下一步；`done`：一次性任务验收通过且 evidence/validation/completed_at 完整；`not_applicable`：仅条件任务或确认不适用的外部能力；有理由、证据与范围，不是跳过难题。

## 待决策事项

这些是执行时要核实的事实或操作范围，不是本次落盘需逐项批准的清单。已有有效授权继续适用。

| ID | 事项 | 建议责任角色 | 适用规则 |
| --- | --- | --- | --- |
| D-01 | 授权主体与权利范围 | rights_holder | 实际权利人确认；不能由提交署名推定。 |
| D-02 | 代码与材料许可采纳 | rights_holder | Apache-2.0/CC BY 4.0 是方案建议，落盘任务本身不执行许可变更。 |
| D-03 | 维护/社区责任及贡献条款 | maintainer | 有真人接收和执行，响应目标、DCO/准则及权限责任得到确认。 |
| D-04 | GitHub 治理设置执行范围 | repository_admin | 沿用届时会话已有有效授权，不重复索要；无授权只完成配置准备。 |
| D-05 | 正式签名或诚实 unsigned 发行策略 | release_maintainer | 密钥缺位不是生成临时发布者密钥的理由；可采用明确 unsigned 研究候选。 |
| D-06 | 对外版本/材料发布范围 | release_maintainer | 核对发布账号、版本、资产和既有有效发布授权。 |
| D-07 | 作者元数据与归档账号 | research_lead | 真实署名由贡献者确认；外部账号连接按实际账号权限处理。 |
| D-08 | 新研究周期、设备与计算预算 | research_lead | 研究执行与付费模型/共享设备操作的范围及预算明确；普通 A/B 路径不因此阻塞。 |
| D-09 | 外部联系及社区内容发布 | research_lead | 明确对象/渠道/内容范围后使用已有有效授权，不能自动群发。 |
| D-10 | 真实凭据处置执行范围 | credential_owner | 只在确认需处置时适用；吊销/轮换和影响系统由所有者授权。 |
| D-11 | 破坏性历史处置 | repository_owner | 只有判定必须重写/删除历史才需该决策；读取与准备不受此门禁阻塞。 |
| D-12 | 论文/评审对外提交 | corresponding_author | 作者、venue、版本、账号及实际提交权限确认，不预设接收结果。 |

## 阶段总览

| 阶段 | 原文任务 | 建议排期 | 子任务数 | 状态 |
| --- | --- | --- | --- | --- |
| O-01 | 确认授权主体、贡献来源与代码/材料边界 | 首周 | 3 | done |
| O-02 | 第三方许可证与 vendored 内容清查 | 首周 | 3 | done |
| O-03 | 历史 seed/凭据复核和处置结论 | 首周 | 4 | done |
| O-04 | LICENSE、材料许可映射和归属文件 | 首周 | 4 | done |
| O-05 | 安全报告渠道、贡献规则、DCO、行为准则 | 首周 | 4 | done |
| O-06 | 主分支保护和平台扫描配置 | 首周 | 4 | done |
| O-07 | A/B/C 三轨复现说明 | 第 2 周 | 5 | in_progress |
| O-08 | 研究导航、dataset card、claims-evidence 表 | 第 2 周 | 5 | done |
| O-09 | CITATION.cff 与真实作者/版本元数据 | 第 2 周 | 3 | done |
| O-10 | 从新 SHA 生成研究候选 | 第 2 周 | 5 | in_progress |
| O-11 | 发布、归档和版本引用验证 | 第 2–4 周 | 4 | blocked |
| O-12 | 收集两组外部复现记录 | 第 2–4 周 | 4 | in_progress |
| O-13 | 发布研究导读与技术报告 | 第 2–4 周 | 4 | in_progress |
| O-14 | 开放讨论与首批贡献任务 | 第 2–4 周 | 3 | done |
| O-15 | 相关工作、研究协议和 pilot | 第 2 月 | 4 | todo |
| O-16 | 公平对照、消融和外部评估集 | 第 2–3 月 | 5 | todo |
| O-17 | 论文及正式 artifact evaluation 材料 | 第 2–3 月 | 4 | todo |
| O-18 | 维护容量、版本支持与贡献者培养 | 持续 | 3 | in_progress |

排期从方案获采纳且负责人落实后起算，不是实际交付日期承诺。

## 验收里程碑

| 门禁 | 达成条件 | 必需任务 | 前置门禁 | 当前 |
| --- | --- | --- | --- | --- |
| G-01 | 许可与历史处置具备首发条件 | O-01.03, O-02.03, O-03.04, O-04.04, O-05.02 | 无 | not_met |
| G-02 | 无需模型的复现与可核验研究候选就绪 | O-07.02, O-07.03, O-07.05, O-08.03, O-08.05, O-09.02, O-10.05 | 无 | not_met |
| G-03 | 首轮研究版公开发布与长期引用闭环 | O-06.02, O-06.03, O-11.04 | G-01, G-02 | not_met |
| G-04 | 外部复现目标达到 | O-12.03 | G-03 | not_met |
| G-05 | 首发传播材料与社区入口齐备 | O-13.04, O-14.03, O-18.01 | G-03 | not_met |
| G-06 | 新研究论文与评审材料可提交 | O-16.05, O-17.02 | G-04 | not_met |

G-01～G-03 为首轮研究发行；G-04 为外部复现；G-05 为传播/社区；G-06 为论文材料可提交。真实投稿/接收由 O-17.03/04 另行记录，持续维护按期跟踪。

## 全量任务

### O-01 · 确认授权主体、贡献来源与代码/材料边界

原文排期：首周。输出路径是计划位置，实际完成以证据为准。

#### O-01.01 · 刷新仓库事实与研究基线

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§2、§12。
- 完成依赖：无；待决策依赖：无。
- 计划产物：`docs/research/baseline-audit.md`；`docs/research/evidence/baseline.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 只读刷新远端 default branch、SHA、许可检测与社区设置
2. 比对 V5 runtime SHA、文档 SHA 和原始提交包，不改写历史身份

验收标准（逐项在实际验证记录中说明结果）：

- 观察有 UTC 时间与 GitHub 读取证据
- 本轮研究工作树/分支与比赛冻结边界明确；新实现不得直接在 main 或冻结制品中进行

计划验证：

- 逐项核对验收条件：观察有 UTC 时间与 GitHub 读取证据；本轮研究工作树/分支与比赛冻结边界明确；新实现不得直接在 main 或冻结制品中进行。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：git status --short --branch；git rev-parse HEAD；env -u GITHUB_TOKEN git ls-remote origin refs/heads/main。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/baseline-audit.md", "docs/research/evidence/baseline.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/baseline-audit.md", "docs/research/evidence/baseline.json"]`。

#### O-01.02 · 建立自有代码和材料来源清单

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§3.1、§3.3。
- 完成依赖：O-01.01；待决策依赖：无。
- 计划产物：`docs/research/rights-inventory.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 按组件及文件族登记作者/雇主/合作方来源和可核实授权材料
2. 区分自有代码、引入片段、AI 辅助提交与第三方作品

验收标准（逐项在实际验证记录中说明结果）：

- 覆盖 Runtime、Secure Agent、Skills、Control API、Edge、Connectors、Web、合同、测试与研究材料
- 未知归属显式 unknown；commit 作者名或工具署名不被当作全部权利证明

计划验证：

- 逐项核对验收条件：覆盖 Runtime、Secure Agent、Skills、Control API、Edge、Connectors、Web、合同、测试与研究材料；未知归属显式 unknown；commit 作者名或工具署名不被当作全部权利证明。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/rights-inventory.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/rights-inventory.json"]`。

#### O-01.03 · 确认授权主体及采用许可的范围

- 状态：`done`；优先级：`P0`；类型：`manual`；责任角色：`rights_holder`；负责人：maoyadongsh。
- 原文依据：§3.2、§3.3、§12。
- 完成依赖：O-01.02, O-02.03；待决策依赖：D-01, D-02。
- 计划产物：`docs/research/rights-decision.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 将来源清单和 Apache-2.0/CC BY 4.0 建议提交有权决定的人确认
2. 记录代码、材料、商标、历史制品和第三方例外的适用范围

验收标准（逐项在实际验证记录中说明结果）：

- 有实际权利确认记录及其范围；不能由代理填造签名或主体
- 未确认文件留在问题清单，不纳入统一授权声明

计划验证：

- 逐项核对验收条件：有实际权利确认记录及其范围；不能由代理填造签名或主体；未确认文件留在问题清单，不纳入统一授权声明。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/rights-decision.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/rights-decision.md"]`。

### O-02 · 第三方许可证与 vendored 内容清查

原文排期：首周。输出路径是计划位置，实际完成以证据为准。

#### O-02.01 · 核对补丁与 vendored 静态资产

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§2、§3.1、§3.3。
- 完成依赖：O-01.01；待决策依赖：无。
- 计划产物：`docs/research/third-party-source-inventory.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 核对 OpenClaw patches 的上游 commit、修改内容及 MIT 原文
2. 核对 Mermaid bundle 的来源、版本、实际 bundle 内组件和所需通知

验收标准（逐项在实际验证记录中说明结果）：

- 每项有路径、来源、版本/commit、摘要、许可、修改状态
- 原版权与许可不被新的项目许可证覆盖；未识别 bundle 内容列为待核查

计划验证：

- 逐项核对验收条件：每项有路径、来源、版本/commit、摘要、许可、修改状态；原版权与许可不被新的项目许可证覆盖；未识别 bundle 内容列为待核查。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/third-party-source-inventory.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/third-party-source-inventory.json"]`。

#### O-02.02 · 核对依赖、字体及其他可分发材料

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§3.1、§3.3、§9。
- 完成依赖：O-01.01；待决策依赖：无。
- 计划产物：`docs/research/third-party-dependency-inventory.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 从锁文件及实际发行内容登记 Python/Go/Web 的分发依赖与字体
2. 区分开发依赖、运行依赖、外部模型/API/镜像以及嵌入文件

验收标准（逐项在实际验证记录中说明结果）：

- 不只登记顶层包；每项明确是否随制品分发及归属义务
- private:true 不被误判为闭源许可；模型权重和外部服务权利不被纳入项目许可

计划验证：

- 逐项核对验收条件：不只登记顶层包；每项明确是否随制品分发及归属义务；private:true 不被误判为闭源许可；模型权重和外部服务权利不被纳入项目许可。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/third-party-dependency-inventory.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/third-party-dependency-inventory.json"]`。

#### O-02.03 · 形成第三方许可兼容性与缺口报告

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`rights_reviewer`；负责人：maoyadongsh。
- 原文依据：§3.1、§3.3。
- 完成依赖：O-02.01, O-02.02；待决策依赖：无。
- 计划产物：`docs/research/license-review.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 合并代码/资产/依赖清单，检查归属文本、来源缺失与分发范围
2. 对无法确认的材料提出补授权、排除分发或替换的可审阅方案

验收标准（逐项在实际验证记录中说明结果）：

- 每项缺口有负责人和处理建议，不把未知写为通过
- 报告明确哪些内容可进入研究制品；建议替换不自动执行

计划验证：

- 逐项核对验收条件：每项缺口有负责人和处理建议，不把未知写为通过；报告明确哪些内容可进入研究制品；建议替换不自动执行。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/license-review.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/license-review.md"]`。

### O-03 · 历史 seed/凭据复核和处置结论

原文排期：首周。输出路径是计划位置，实际完成以证据为准。

#### O-03.01 · 完成当前树、历史和既有制品的凭据复核

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`security_maintainer`；负责人：maoyadongsh。
- 原文依据：§2、§8.3。
- 完成依赖：O-01.01；待决策依赖：无。
- 计划产物：`docs/research/evidence/history-scan-summary.json`；`docs/research/history-review.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 检查 CI 提及的 signing-key seed 历史以及 branches/tags/旧 Release/归档范围
2. 复用已校准扫描器；公开记录只包含路径、摘要、类型和数量

验收标准（逐项在实际验证记录中说明结果）：

- 当前树与历史覆盖范围分开记录；取不到的外部归档标为未核验
- 不输出秘密值，不自动删除或改写历史

计划验证：

- 逐项核对验收条件：当前树与历史覆盖范围分开记录；取不到的外部归档标为未核验；不输出秘密值，不自动删除或改写历史。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/history-scan-summary.json", "docs/research/history-review.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/evidence/history-scan-summary.json", "docs/research/history-review.md"]`。

#### O-03.02 · 判定发现项的真实性、有效性与影响

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`security_maintainer`；负责人：maoyadongsh。
- 原文依据：§8.3。
- 完成依赖：O-03.01；待决策依赖：无。
- 计划产物：`docs/research/history-disposition.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 在受控私密渠道核对发现项属于测试材料、真实凭据或未知
2. 记录是否曾用于正式发行、可触达系统、已知暴露和需处置的范围

验收标准（逐项在实际验证记录中说明结果）：

- 每项有受限证据引用与公开脱敏结论
- 不能因样本格式像测试 key 就直接判定安全；未知项阻止相关发布声明

计划验证：

- 逐项核对验收条件：每项有受限证据引用与公开脱敏结论；不能因样本格式像测试 key 就直接判定安全；未知项阻止相关发布声明。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/history-disposition.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/history-disposition.md"]`。

#### O-03.03 · 处置确认仍有效的真实凭据

- 状态：`not_applicable`；优先级：`P0`；类型：`conditional`；责任角色：`credential_owner`；负责人：未指派。
- 原文依据：§8.3。
- 完成依赖：O-03.02；待决策依赖：D-10。
- 计划产物：`docs/research/evidence/credential-remediation-summary.json`。
- 条件：O-03.02 确认存在需处置的真实凭据。

实施内容：

1. 准备吊销/轮换及受影响制品评估方案
2. 经系统所有者授权后执行并读回失效/替换状态

验收标准（逐项在实际验证记录中说明结果）：

- 有实际撤销/轮换与影响处置记录；删除文件不能替代凭据失效
- 未发现适用真实凭据时仅凭 O-03.02 证据标 not_applicable

计划验证：

- 逐项核对验收条件：有实际撤销/轮换与影响处置记录；删除文件不能替代凭据失效；未发现适用真实凭据时仅凭 O-03.02 证据标 not_applicable。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`["docs/research/history-disposition.md", "docs/research/evidence/credential-remediation-summary.json"]`。

#### O-03.04 · 确认历史保留、勘误或重写的处置结论

- 状态：`done`；优先级：`P0`；类型：`conditional`；责任角色：`security_maintainer`；负责人：maoyadongsh。
- 原文依据：§8.3、§6.2。
- 完成依赖：O-03.02, O-03.03；待决策依赖：D-11。
- 计划产物：`docs/research/history-resolution.md`；`docs/research/evidence/history-resolution.json`。
- 条件：先做处置决策；只有确需破坏性历史操作时 D-11 才适用。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 明确是否需协调 forks、镜像、Release 和归档，准备恢复/通知步骤
2. 仅在确需且有授权时执行历史重写；否则记录无需重写或待外部处置的理由

验收标准（逐项在实际验证记录中说明结果）：

- 保留研究材料与摘要的对应关系，替代版本有勘误说明
- 待处置的真实风险不得用签字例外自动算通过；无须重写不要求实际 force push

计划验证：

- 逐项核对验收条件：保留研究材料与摘要的对应关系，替代版本有勘误说明；待处置的真实风险不得用签字例外自动算通过；无须重写不要求实际 force push。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/history-resolution.md", "docs/research/evidence/history-resolution.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/history-resolution.md", "docs/research/evidence/history-resolution.json"]`。

### O-04 · LICENSE、材料许可映射和归属文件

原文排期：首周。输出路径是计划位置，实际完成以证据为准。

#### O-04.01 · 落地根代码许可与适用范围声明

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§3.2、§3.3。
- 完成依赖：O-01.03；待决策依赖：D-02。
- 计划产物：`LICENSE`；`README.md`；`skills/siq-agent-security/SKILL.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 按已确认决定添加未经改写的标准代码许可文本
2. 同步 README、Skill 与组件适用范围，保留第三方例外

验收标准（逐项在实际验证记录中说明结果）：

- 根许可、组件声明与权利清单一致
- 不修改 V5 RC 或倒填历史许可；现有 Skill 子目录声明的变化先核对其范围

计划验证：

- 逐项核对验收条件：根许可、组件声明与权利清单一致；不修改 V5 RC 或倒填历史许可；现有 Skill 子目录声明的变化先核对其范围。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["LICENSE", "README.md", "skills/siq-agent-security/SKILL.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["LICENSE", "README.md", "skills/siq-agent-security/SKILL.md"]`。

#### O-04.02 · 建立文件级材料许可与 SPDX 映射

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§3.1、§3.3。
- 完成依赖：O-04.01, O-02.03；待决策依赖：无。
- 计划产物：`LICENSES/`；`docs/research/license-map.json`；`docs/research/license-map.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 区分原创文本/图表/清洗数据、代码示例与第三方材料
2. 对确认范围配置 SPDX/许可引用；历史文件逐步核对，不批量覆盖含混目录

验收标准（逐项在实际验证记录中说明结果）：

- 新增分发文件都有许可映射或明确例外
- 可执行测试/脚本不误用材料许可；未授权素材不被标 CC BY

计划验证：

- 逐项核对验收条件：新增分发文件都有许可映射或明确例外；可执行测试/脚本不误用材料许可；未授权素材不被标 CC BY。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["LICENSES/scope.json", "LICENSES/README.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["LICENSES/scope.json", "LICENSES/README.md"]`。

#### O-04.03 · 补齐第三方归属与必要 NOTICE

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§3.3。
- 完成依赖：O-04.01, O-04.02；待决策依赖：无。
- 计划产物：`THIRD_PARTY_NOTICES.md`；`LICENSES/`；`NOTICE（按核查结果有条件添加）`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 根据实际分发清单保留上游 copyright/license/attribution
2. 仅在确有通知内容时加入 NOTICE，并标识修改来源

验收标准（逐项在实际验证记录中说明结果）：

- OpenClaw MIT、Mermaid 与字体所需通知可追溯
- 第三方许可文本可在发行包中找到；不创建假归属或无理由的空 NOTICE

计划验证：

- 逐项核对验收条件：OpenClaw MIT、Mermaid 与字体所需通知可追溯；第三方许可文本可在发行包中找到；不创建假归属或无理由的空 NOTICE。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["NOTICE", "THIRD_PARTY_NOTICES.md", "docs/research/third-party-source-inventory.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["NOTICE", "THIRD_PARTY_NOTICES.md", "docs/research/third-party-source-inventory.json"]`。

#### O-04.04 · 校验源码与制品的许可一致性

- 状态：`done`；优先级：`P0`；类型：`validation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§3.3、§9。
- 完成依赖：O-04.02, O-04.03；待决策依赖：无。
- 计划产物：`docs/research/evidence/license-validation.json`；`现有打包/静态检查入口（必要增量）`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 校验许可映射路径、未知项、引用和打包包含关系
2. 为漏带已要求的许可通知或未映射发行文件建立必要校验

验收标准（逐项在实际验证记录中说明结果）：

- 不能因根 LICENSE 存在就判全仓通过
- 所有许可缺口已解决或被明确排除出此次分发范围；验证命令与范围记录完整

计划验证：

- 逐项核对验收条件：不能因根 LICENSE 存在就判全仓通过；所有许可缺口已解决或被明确排除出此次分发范围；验证命令与范围记录完整。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：核对实际分发文件与 license-map/THIRD_PARTY_NOTICES 一致；缺失许可通知或未映射文件必须拒绝通过。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_source_release_scope", "evidence": ["docs/research/evidence/source-package-validation.json"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/evidence/source-package-validation.json"]`。

### O-05 · 安全报告渠道、贡献规则、DCO、行为准则

原文排期：首周。输出路径是计划位置，实际完成以证据为准。

#### O-05.01 · 起草 SECURITY 与受理流程

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.3、§12。
- 完成依赖：O-01.01；待决策依赖：D-03。
- 计划产物：`SECURITY.md`；`docs/research/security-response-process.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 列出维护版本、私密报告渠道、必要材料、清洗、协调披露和修复步骤
2. 让真实接收者确认三工作日/十工作日等内部目标及执行责任

验收标准（逐项在实际验证记录中说明结果）：

- 未确认目标不写成 SLA；未启用入口不宣称可用
- 有实际负责人；未修复漏洞不要求提交公开 PoC

计划验证：

- 逐项核对验收条件：未确认目标不写成 SLA；未启用入口不宣称可用；有实际负责人；未修复漏洞不要求提交公开 PoC。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["SECURITY.md", "docs/research/security-response-process.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["SECURITY.md", "docs/research/security-response-process.md"]`。

#### O-05.02 · 启用并验证私密漏洞报告入口

- 状态：`done`；优先级：`P0`；类型：`external_manual`；责任角色：`repository_admin`；负责人：maoyadongsh。
- 原文依据：§8.3。
- 完成依赖：O-05.01；待决策依赖：D-04。
- 计划产物：`docs/research/evidence/private-reporting-readback.json`；`SECURITY.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 准备 GitHub private vulnerability reporting 设置
2. 经既有有效治理授权执行并检查入口、权限及接收流程

验收标准（逐项在实际验证记录中说明结果）：

- 实际 API/UI readback 证明可用；不对外投递虚构漏洞
- SECURITY 指向真实入口，受理者确认接收责任

计划验证：

- 逐项核对验收条件：实际 API/UI readback 证明可用；不对外投递虚构漏洞；SECURITY 指向真实入口，受理者确认接收责任。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/private-reporting-readback.json", "SECURITY.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/evidence/private-reporting-readback.json", "SECURITY.md"]`。

#### O-05.03 · 建立贡献规则、DCO 和贡献检查

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.1、§8.2。
- 完成依赖：O-04.01, O-07.01；待决策依赖：D-03。
- 计划产物：`CONTRIBUTING.md`；`DCO`；`.github/（DCO 校验配置，如采用）`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 记录按组件开发/测试命令、负向测试和复现贡献方式
2. 采用确认后的 DCO Signed-off-by 流程，声明其不是版权转让，不补造历史签署

验收标准（逐项在实际验证记录中说明结果）：

- 贡献者能在无模型/发布密钥环境走通常规校验
- 不强加未采纳 CLA；DCO 配置如依赖外部 App 则先完成权限决策

计划验证：

- 逐项核对验收条件：贡献者能在无模型/发布密钥环境走通常规校验；不强加未采纳 CLA；DCO 配置如依赖外部 App 则先完成权限决策。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["CONTRIBUTING.md", "DCO"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["CONTRIBUTING.md", "DCO"]`。

#### O-05.04 · 建立治理、行为准则及署名规则

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.2、§10.2。
- 完成依赖：O-01.03；待决策依赖：D-03。
- 计划产物：`GOVERNANCE.md`；`CODE_OF_CONDUCT.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 说明维护者任免、研究协议评审、利益冲突、合并/发布与申诉规则
2. 区分代码贡献、数据贡献、致谢、论文作者与推荐引用

验收标准（逐项在实际验证记录中说明结果）：

- 明确单维护者现实，不宣称现有独立复审
- 执行/申诉渠道有人负责；不在 Apache 之外追加强制论文引用条件

计划验证：

- 逐项核对验收条件：明确单维护者现实，不宣称现有独立复审；执行/申诉渠道有人负责；不在 Apache 之外追加强制论文引用条件。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["GOVERNANCE.md", "CODE_OF_CONDUCT.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["GOVERNANCE.md", "CODE_OF_CONDUCT.md"]`。

### O-06 · 主分支保护和平台扫描配置

原文排期：首周。输出路径是计划位置，实际完成以证据为准。

#### O-06.01 · 准备治理设置与所需 job contexts

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`repository_admin`；负责人：maoyadongsh。
- 原文依据：§2、§9。
- 完成依赖：O-01.01；待决策依赖：无。
- 计划产物：`docs/research/repository-settings-plan.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 读取实际 CI job contexts、现有规则和 CODEOWNERS
2. 准备 PR、status checks、conversation resolution、禁止 force push、绕过权限的逐项配置

验收标准（逐项在实际验证记录中说明结果）：

- 不把工作流名当作全部 required job contexts
- 包含配置影响、适用分支、回滚方案及读回步骤

计划验证：

- 逐项核对验收条件：不把工作流名当作全部 required job contexts；包含配置影响、适用分支、回滚方案及读回步骤。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/repository-settings-plan.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/repository-settings-plan.md"]`。

#### O-06.02 · 实施并核验主分支保护

- 状态：`done`；优先级：`P0`；类型：`external_manual`；责任角色：`repository_admin`；负责人：maoyadongsh。
- 原文依据：§9。
- 完成依赖：O-06.01；待决策依赖：D-04。
- 计划产物：`docs/research/evidence/branch-protection-readback.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 按审阅后的配置实施保护和 CODEOWNERS 强制规则
2. 核查绕过主体、force push 与合并条件

验收标准（逐项在实际验证记录中说明结果）：

- 有实际规则 readback，CODEOWNERS 文件本身不当作已强制
- 只有授权范围内设置发生变更，缺权限保持 blocked

计划验证：

- 逐项核对验收条件：有实际规则 readback，CODEOWNERS 文件本身不当作已强制；只有授权范围内设置发生变更，缺权限保持 blocked。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/branch-protection-readback.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/evidence/branch-protection-readback.json"]`。

#### O-06.03 · 实施平台扫描与依赖安全更新

- 状态：`done`；优先级：`P0`；类型：`external_manual`；责任角色：`repository_admin`；负责人：maoyadongsh。
- 原文依据：§2、§9。
- 完成依赖：O-06.01；待决策依赖：D-04。
- 计划产物：`.github/dependabot.yml（如需）`；`docs/research/evidence/platform-security-readback.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 逐项规划并启用 secret scanning、push protection、依赖安全更新
2. 检查权限/功能可用性并与现有 gitleaks/锁定依赖配合

验收标准（逐项在实际验证记录中说明结果）：

- 每项有开启或不可用的真实理由，不能用自建扫描替代平台读回
- 不可用项显式处理，不自动视为已启用；更新不跳过受影响检查

计划验证：

- 逐项核对验收条件：每项有开启或不可用的真实理由，不能用自建扫描替代平台读回；不可用项显式处理，不自动视为已启用；更新不跳过受影响检查。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/platform-security-readback.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/evidence/platform-security-readback.json"]`。

#### O-06.04 · 审计 fork PR 与模型/签名凭据边界

- 状态：`done`；优先级：`P0`；类型：`validation`；责任角色：`security_maintainer`；负责人：maoyadongsh。
- 原文依据：§5、§9。
- 完成依赖：O-06.01；待决策依赖：无。
- 计划产物：`.github/workflows/（必要最小修正）`；`docs/research/evidence/ci-trust-boundary-review.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 检查不受信 PR 的 token 权限、事件、缓存/制品和受控执行路径
2. 隔离真实模型、共享 DGX 与发布密钥，复用现有 CI

验收标准（逐项在实际验证记录中说明结果）：

- 常规 PR 无需付费模型和 GPU；不受信代码不能取得受保护执行权限
- 如修改流程，有针对相应越界风险的检查；未修改也记录实际审阅证据

计划验证：

- 逐项核对验收条件：常规 PR 无需付费模型和 GPU；不受信代码不能取得受保护执行权限；如修改流程，有针对相应越界风险的检查；未修改也记录实际审阅证据。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：按实际 workflow 事件与 token 权限审阅 fork PR；确认无 provider/签名密钥或共享 DGX 的不受信执行路径。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/ci-trust-boundary-review.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/evidence/ci-trust-boundary-review.json"]`。

### O-07 · A/B/C 三轨复现说明

原文排期：第 2 周。输出路径是计划位置，实际完成以证据为准。

#### O-07.01 · 编写三轨复现总入口与依赖说明

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§5、§6。
- 完成依赖：O-01.01；待决策依赖：无。
- 计划产物：`REPRODUCIBILITY.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 复用现有启动器和基准命令，列 Go/Python/Node/OS 及锁定依赖
2. 分别写 A 演示、B 控制基准、C 实模型要求和全新 state/output 路径

验收标准（逐项在实际验证记录中说明结果）：

- A/B 不要求模型 key 或 DGX；首次安装联网要求明示
- 功能/统计复现与逐字节构建复现区分，失败诊断可执行

计划验证：

- 逐项核对验收条件：A/B 不要求模型 key 或 DGX；首次安装联网要求明示；功能/统计复现与逐字节构建复现区分，失败诊断可执行。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["REPRODUCIBILITY.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["REPRODUCIBILITY.md"]`。

#### O-07.02 · 在普通 Linux 验证 fixture 演示路径 A

- 状态：`done`；优先级：`P0`；类型：`validation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§5。
- 完成依赖：O-07.01；待决策依赖：无。
- 计划产物：`docs/research/evidence/reproduction-a/`；`REPRODUCIBILITY.md`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 以显式 test 模式运行 normal、MCP、same-value、fake-success
2. 检查浏览器配对、真实 SIQ 结果和 receiver 读回，保留环境与命令

验收标准（逐项在实际验证记录中说明结果）：

- 无需模型密钥并且没有真实 provider 调用；fixture 标识可见
- 成功任务完成、攻击被拒、缺失效果不当成功，失败也归档

计划验证：

- 逐项核对验收条件：无需模型密钥并且没有真实 provider 调用；fixture 标识可见；成功任务完成、攻击被拒、缺失效果不当成功，失败也归档。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：./scripts/hackathon/start.sh --mode test；./scripts/hackathon/healthcheck.sh；复用 browser-smoke.py 的 normal/MCP/same-value/fake-success 断言，state/output 必须是新的隔离路径。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/reproduction-a/hosted-linux-identity.json", "docs/research/evidence/reproduction-a/hosted-linux-browser.json"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/evidence/reproduction-a/hosted-linux-identity.json", "docs/research/evidence/reproduction-a/hosted-linux-browser.json"]`。

#### O-07.03 · 验证固定基准与离线证据路径 B

- 状态：`done`；优先级：`P0`；类型：`validation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§5、§6.1。
- 完成依赖：O-07.01；待决策依赖：无。
- 计划产物：`docs/research/evidence/reproduction-b/`；`REPRODUCIBILITY.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 复用 hackathon/runtime-security 执行器与 verifier，使用固定 corpus
2. 记录二进制/corpus/verifier 摘要、全部尝试和验签统计

验收标准（逐项在实际验证记录中说明结果）：

- 全部必需场景覆盖且重算指标与原始记录一致；子集明确 partial
- 不将随报告公钥当外部身份保证，也不把缺失效果证据改写为无效果

计划验证：

- 逐项核对验收条件：全部必需场景覆盖且重算指标与原始记录一致；子集明确 partial；不将随报告公钥当外部身份保证，也不把缺失效果证据改写为无效果。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：依 benchmarks/hackathon/README.md 和 benchmarks/runtime-security/README.md 的现有命令运行固定 corpus；分别调用对应 verifier 重算统计。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/reproduction-b/", "REPRODUCIBILITY.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/evidence/reproduction-b/", "REPRODUCIBILITY.md"]`。

#### O-07.04 · 配置并验证实模型与 DGX 路径 C

- 状态：`todo`；优先级：`P1`；类型：`validation`；责任角色：`maintainer`；负责人：未指派。
- 原文依据：§5、§4.1。
- 完成依赖：O-07.01, O-06.04；待决策依赖：D-08。
- 计划产物：`docs/research/evidence/reproduction-c/`；`REPRODUCIBILITY.md`。

实施内容：

1. 使用批准预算和真实 provider/硬件，记录模型、时间、配置和错误
2. 复用 canary 与本地失败测试，分别记录 StepFun 规划和 DGX 分析

验收标准（逐项在实际验证记录中说明结果）：

- 没有调用/硬件的部分标 unverified，不能 fixture 冒充实模型
- 机密 canary 不进入远程 transport，本地失败不获准 fallback；不要求输出逐字等于旧样本

计划验证：

- 逐项核对验收条件：没有调用/硬件的部分标 unverified，不能 fixture 冒充实模型；机密 canary 不进入远程 transport，本地失败不获准 fallback；不要求输出逐字等于旧样本。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：复用 scripts/hackathon/locality_checkpoint.py；采用实际本地 transport 故障，记录 CONFIDENTIAL canary 与远程请求数。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[]`。
实际证据：`[]`。

#### O-07.05 · 完成三轨环境矩阵与故障说明

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§5、§6.1。
- 完成依赖：O-07.02, O-07.03；待决策依赖：无。
- 计划产物：`docs/research/environment-matrix.md`；`REPRODUCIBILITY.md`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 整合 A/B 结果和 C 的实际可用/未运行状态
2. 列出平台、依赖安装、端口、provider、权限、verifier 错误的诊断步骤

验收标准（逐项在实际验证记录中说明结果）：

- 普通 Linux 复现不被写成全部 OS 原生验收
- C 未运行不会阻塞无 GPU 的 A/B 文档，但 C 的新实测结论不得发布

计划验证：

- 逐项核对验收条件：普通 Linux 复现不被写成全部 OS 原生验收；C 未运行不会阻塞无 GPU 的 A/B 文档，但 C 的新实测结论不得发布。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/environment-matrix.md"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/environment-matrix.md"]`。

### O-08 · 研究导航、dataset card、claims-evidence 表

原文排期：第 2 周。输出路径是计划位置，实际完成以证据为准。

#### O-08.01 · 建立研究入口、定位与问题映射

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§1、§4.1、§6。
- 完成依赖：O-01.01；待决策依赖：无。
- 计划产物：`docs/research/README.md`；`docs/research/research-questions.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 以现有项目名称和 RQ1–RQ5 建立研究导航
2. 关联既有代码/证据及待补实验，保留企业组件为可选表面

验收标准（逐项在实际验证记录中说明结果）：

- 候选研究问题不标为已发表创新；不新增框架或拆仓
- 研究入口引用 canonical 数据，不形成第二套比赛 current truth

计划验证：

- 逐项核对验收条件：候选研究问题不标为已发表创新；不新增框架或拆仓；研究入口引用 canonical 数据，不形成第二套比赛 current truth。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/README.md", "docs/research/research-questions.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/README.md", "docs/research/research-questions.md"]`。

#### O-08.02 · 编制数据卡与公开清洗规则

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§3.1、§6.1。
- 完成依赖：O-02.03, O-03.02；待决策依赖：无。
- 计划产物：`docs/research/dataset-card.md`；`docs/research/data-export-policy.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 登记合成/真实来源、任务分布、许可、重复/污染与限制
2. 定义公共证据白名单、身份清洗和受限资料引用规则

验收标准（逐项在实际验证记录中说明结果）：

- 不公开 token/seed/原始状态或未经许可的数据
- 每项数据有使用范围与可追溯来源；测试 fixtures 与真实模型 cohort 分开

计划验证：

- 逐项核对验收条件：不公开 token/seed/原始状态或未经许可的数据；每项数据有使用范围与可追溯来源；测试 fixtures 与真实模型 cohort 分开。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/dataset-card.md", "docs/research/data-export-policy.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/dataset-card.md", "docs/research/data-export-policy.md"]`。

#### O-08.03 · 建立逐项结论与证据映射

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§1、§4.2、§6.1、§10.2。
- 完成依赖：O-08.01, O-08.02；待决策依赖：无。
- 计划产物：`docs/research/claims-evidence.md`；`docs/research/claims-evidence.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 为每条对外实证结论绑定源码、实验、指标分母和 canonical 证据
2. 注明 missing/unknown、同 UID、受控 observer、小样本及未验证范围

验收标准（逐项在实际验证记录中说明结果）：

- 冻结数字和早期 4/5 失败完整保留
- 同值来源、Completion 和 locality 的结论有各自证据，不混用 fixture 与实模型成功率

计划验证：

- 逐项核对验收条件：冻结数字和早期 4/5 失败完整保留；同值来源、Completion 和 locality 的结论有各自证据，不混用 fixture 与实模型成功率。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/claims-evidence.md", "docs/research/claims-evidence.json"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/claims-evidence.md", "docs/research/claims-evidence.json"]`。

#### O-08.04 · 记录当前基线评价协议与复算方法

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§6.1、§4.2。
- 完成依赖：O-07.03, O-08.03；待决策依赖：无。
- 计划产物：`docs/research/evaluation-protocol.md`；`docs/research/result-reproduction.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 记录现有基线任务、排除、超时/重试、重复与分母口径
2. 复用 verifier/指标输出生成表格，不复制第二个执行引擎

验收标准（逐项在实际验证记录中说明结果）：

- 历史已经运行的实验称 retrospective protocol，不伪称预注册
- 表格可由已归档数据复算；更强研究协议另由 O-15 建立

计划验证：

- 逐项核对验收条件：历史已经运行的实验称 retrospective protocol，不伪称预注册；表格可由已归档数据复算；更强研究协议另由 O-15 建立。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evaluation-protocol.md", "docs/research/result-reproduction.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/evaluation-protocol.md", "docs/research/result-reproduction.md"]`。

#### O-08.05 · 定义研究制品身份清单及版本规则

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§6.1、§6.2、§9。
- 完成依赖：O-08.02, O-08.04；待决策依赖：无。
- 计划产物：`docs/research/artifact-manifest-spec.md`；`docs/research/artifact-layout.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 定义 runtime/docs/corpus/verifier/toolchain/platform/digest 的独立身份字段
2. 规划源码、数据、视频、附件、许可、引用的归档布局及替代/勘误方式

验收标准（逐项在实际验证记录中说明结果）：

- 不自引用制品本身哈希；外层 checksum 单独存在
- 字段复用已有 source-info/evidence manifest，额外研究字段不复制原始证据

计划验证：

- 逐项核对验收条件：不自引用制品本身哈希；外层 checksum 单独存在；字段复用已有 source-info/evidence manifest，额外研究字段不复制原始证据。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/artifact-manifest-spec.md", "docs/research/artifact-layout.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/artifact-manifest-spec.md", "docs/research/artifact-layout.md"]`。

### O-09 · CITATION.cff 与真实作者/版本元数据

原文排期：第 2 周。输出路径是计划位置，实际完成以证据为准。

#### O-09.01 · 确认软件与论文署名元数据

- 状态：`done`；优先级：`P1`；类型：`manual`；责任角色：`research_lead`；负责人：maoyadongsh。
- 原文依据：§6.1、§6.2、§8.2、§12。
- 完成依赖：O-01.02；待决策依赖：D-07。
- 计划产物：`docs/research/authorship-decision.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 由实际贡献者确认姓名、角色、ORCID（如有）与软件贡献归属
2. 将论文作者资格、软件作者、致谢分别记录

验收标准（逐项在实际验证记录中说明结果）：

- 不从 Git 用户名虚构真实姓名、作者顺序或 ORCID
- 未发表论文不填接收状态或虚构 DOI

计划验证：

- 逐项核对验收条件：不从 Git 用户名虚构真实姓名、作者顺序或 ORCID；未发表论文不填接收状态或虚构 DOI。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/authorship-decision.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/authorship-decision.md"]`。

#### O-09.02 · 编制并验证 CITATION.cff

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§6.2。
- 完成依赖：O-09.01, O-08.05；待决策依赖：无。
- 计划产物：`CITATION.cff`；`docs/research/evidence/citation-validation.json`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 使用已确认软件作者/版本/仓库元数据，按 CFF 规范校验
2. 没有实际 DOI 时省略该字段，后续真实引用单独记录

验收标准（逐项在实际验证记录中说明结果）：

- CFF 解析/校验通过，字段对应真实对象
- 不伪称 default branch 引用按钮已经生效；发行日期与版本须在发布时复核

计划验证：

- 逐项核对验收条件：CFF 解析/校验通过，字段对应真实对象；不伪称 default branch 引用按钮已经生效；发行日期与版本须在发布时复核。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：采用实施时核验的官方 CFF schema 校验解析与字段；DOI/作者/版本必须对应真实事实。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["CITATION.cff"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["CITATION.cff"]`。

#### O-09.03 · 设计版本引用、项目入口和 DOI 对应关系

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§6.2。
- 完成依赖：O-09.02；待决策依赖：无。
- 计划产物：`docs/research/citation-guide.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 给出实验引用具体版本、项目引用长期入口、论文 preferred-citation 的规则
2. 说明注册后引用更新产生新文档提交，不回写改变冻结身份

验收标准（逐项在实际验证记录中说明结果）：

- 示例中的占位符明确为示例且不能进入正式发行元数据
- 软件、论文、源码归档和数据/视频记录不会共享虚构的同一 DOI

计划验证：

- 逐项核对验收条件：示例中的占位符明确为示例且不能进入正式发行元数据；软件、论文、源码归档和数据/视频记录不会共享虚构的同一 DOI。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/citation-guide.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/citation-guide.md"]`。

### O-10 · 从新 SHA 生成研究候选

原文排期：第 2 周。输出路径是计划位置，实际完成以证据为准。

#### O-10.01 · 确定研究发行范围与身份更新流程

- 状态：`done`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§9、§6.1。
- 完成依赖：O-04.04, O-07.05, O-08.05；待决策依赖：无。
- 计划产物：`docs/research/release-scope.md`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 明确此次分发是本地 Runtime 研究链路还是包含企业组件
2. 制定新 SHA/未占用 tag 的选择和 main 集成后的重新构建规则

验收标准（逐项在实际验证记录中说明结果）：

- 新许可后的版本与旧 V5 RC 分开；不覆盖任何历史 tag
- 研究 work branch、基线及变更范围有记录；冻结比赛制品保持原样

计划验证：

- 逐项核对验收条件：新许可后的版本与旧 V5 RC 分开；不覆盖任何历史 tag；研究 work branch、基线及变更范围有记录；冻结比赛制品保持原样。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_source_release_scope", "evidence": ["docs/research/release-scope.md"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/release-scope.md"]`。

#### O-10.02 · 按实际发行范围补齐 SBOM 与归属包

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§9、§3.3。
- 完成依赖：O-10.01, O-02.02；待决策依赖：无。
- 计划产物：`scripts/hackathon/package_rc.py（必要增量）`；`docs/research/evidence/sbom-scope.json`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 复用已有 CycloneDX/source-info/inventory，按选定分发范围核查覆盖
2. 若分发企业组件则补其实际依赖，若不分发则明确排除

验收标准（逐项在实际验证记录中说明结果）：

- 旧 scoped RC SBOM 不被宣称全仓供应链完整
- 缺少已分发组件或通知时校验失败；增量有必要的打包验证

计划验证：

- 逐项核对验收条件：旧 scoped RC SBOM 不被宣称全仓供应链完整；缺少已分发组件或通知时校验失败；增量有必要的打包验证。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_source_release_scope", "evidence": ["docs/research/evidence/sbom-scope.json", "scripts/research/package_source.py", "scripts/research/test_package_source.py"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/evidence/sbom-scope.json", "scripts/research/package_source.py", "scripts/research/test_package_source.py"]`。

#### O-10.03 · 完成发布者认证与构建证明方案

- 状态：`done`；优先级：`P0`；类型：`engineering`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§9。
- 完成依赖：O-10.01, O-06.04；待决策依赖：D-05。
- 计划产物：`docs/research/release-authentication.md`；`docs/research/evidence/signing-readiness.json`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 核对现有 publisher key 支持，形成 signed/unsigned 的准确发布状态
2. 评估 artifact attestations 的价值与身份校验；仅采用时扩展既有工作流

验收标准（逐项在实际验证记录中说明结果）：

- 不使用 test/development/temporary key 认证正式候选
- hash、GitHub 构建来源证明、现有 publisher 信任规则和实验真实性分别说明；可接受诚实 unsigned 研究候选

计划验证：

- 逐项核对验收条件：不使用 test/development/temporary key 认证正式候选；hash、GitHub 构建来源证明、现有 publisher 信任规则和实验真实性分别说明；可接受诚实 unsigned 研究候选。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_source_release_scope", "evidence": ["docs/research/release-authentication.md", "docs/research/evidence/signing-readiness.json"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/release-authentication.md", "docs/research/evidence/signing-readiness.json"]`。

#### O-10.04 · 执行新研究 SHA 的 CI 与受影响回归

- 状态：`in_progress`；优先级：`P0`；类型：`validation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§9。
- 完成依赖：O-10.02, O-10.03, O-09.02, O-03.04, O-05.02, O-06.04；待决策依赖：无。
- 计划产物：`docs/research/evidence/release-ci.json`；`docs/research/evidence/release-regression.json`。

实施内容：

1. 先完成许可/文档/打包增量审阅，按用户实际授权提交集成流程
2. 针对最终选定 SHA 运行真实 ci/runtime-security 与必要本地检查，保留命令/job/run ID

验收标准（逐项在实际验证记录中说明结果）：

- 旧 d127711 CI 不冒充新研究 SHA 的结果；最终源码变动触发相应重验
- 仅文档变更做链接/格式检查，打包或安全变更执行相应有意义验证，不盲目重复全部检查

计划验证：

- 逐项核对验收条件：旧 d127711 CI 不冒充新研究 SHA 的结果；最终源码变动触发相应重验；仅文档变更做链接/格式检查，打包或安全变更执行相应有意义验证，不盲目重复全部检查。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：go test ./... / go test -race ./... / go vet ./...（仅受影响 Go module；保留实际 cwd）；复用现有 ci/runtime-security 对最终 SHA 运行；文档仅做链接/格式校验，打包增量运行现有 package tests。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[]`。
实际证据：`["docs/research/release-scope.md", "docs/research/publication-plan.md"]`。

#### O-10.05 · 从干净源码构建并验收研究候选

- 状态：`in_progress`；优先级：`P0`；类型：`validation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§9、§6.1。
- 完成依赖：O-10.04；待决策依赖：无。
- 计划产物：`docs/research/evidence/research-rc.json`；`研究候选包（Git 之外）`。

实施内容：

1. 用新冻结源码复用打包器，核对源码构建前后干净、版本与文件库存
2. 验证各分发目标、内外 checksums、SBOM/许可/身份/研究导航，并解包运行无模型路径

验收标准（逐项在实际验证记录中说明结果）：

- 最终 SHA 具备成功 CI；制品指向实际源码而非 dirty-source manifest
- 原生验收与 cross-build 区分；包内不含秘密/私密状态；启动后包未污染

计划验证：

- 逐项核对验收条件：最终 SHA 具备成功 CI；制品指向实际源码而非 dirty-source manifest；原生验收与 cross-build 区分；包内不含秘密/私密状态；启动后包未污染。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：git status --porcelain（构建前后均为空）；python3 scripts/hackathon/package_rc.py --out <新候选目录> --verify-only；sha256sum -c SHA256SUMS（候选内和外层分别核查，记录 cwd）。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[]`。
实际证据：`["docs/research/release-scope.md", "docs/research/publication-plan.md"]`。

### O-11 · 发布、归档和版本引用验证

原文排期：第 2–4 周。输出路径是计划位置，实际完成以证据为准。

#### O-11.01 · 准备可审阅的研究发布与归档材料

- 状态：`in_progress`；优先级：`P0`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§6.2、§9、§10.1。
- 完成依赖：O-10.05, O-09.03；待决策依赖：无。
- 计划产物：`docs/research/release-notes.md`；`docs/research/publication-plan.md`。

实施内容：

1. 准备 prerelease 说明、资产清单、精确 tag 命令、归档映射和引用元数据
2. 列出未执行状态、缺少外部复现与已知边界

验收标准（逐项在实际验证记录中说明结果）：

- 材料可独立审阅，版本/哈希/许可一致
- 没有发布授权时仍完成准备；不生成假 Release URL 或 DOI

计划验证：

- 逐项核对验收条件：材料可独立审阅，版本/哈希/许可一致；没有发布授权时仍完成准备；不生成假 Release URL 或 DOI。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`["docs/research/release-scope.md", "docs/research/publication-plan.md"]`。

#### O-11.02 · 发布新研究版本至 GitHub

- 状态：`in_progress`；优先级：`P0`；类型：`external_manual`；责任角色：`release_maintainer`；负责人：maoyadongsh。
- 原文依据：§9、§6.2。
- 完成依赖：O-11.01, O-06.02, O-06.03；待决策依赖：D-06。
- 计划产物：`docs/research/evidence/github-research-release.json`。

实施内容：

1. 按有效 publisher 授权再次核对 SHA、远端 tag 和全部资产
2. 创建新 prerelease 并读回版本/资产摘要和签名状态

验收标准（逐项在实际验证记录中说明结果）：

- 实际 Release URL 和资产校验通过；不覆盖既有 tag 或旧文件
- 若要求集成后 main 为源码，须先回 O-10.04/05 重冻重建，不直接沿用分支包

计划验证：

- 逐项核对验收条件：实际 Release URL 和资产校验通过；不覆盖既有 tag 或旧文件；若要求集成后 main 为源码，须先回 O-10.04/05 重冻重建，不直接沿用分支包。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`["docs/research/release-scope.md", "docs/research/publication-plan.md"]`。

#### O-11.03 · 连接归档账号并保存实际研究制品

- 状态：`blocked`；优先级：`P0`；类型：`external_manual`；责任角色：`archive_account_owner`；负责人：未指派。
- 原文依据：§6.2。
- 完成依赖：O-11.01；待决策依赖：D-06, D-07。
- 计划产物：`docs/research/evidence/archive-upload.json`。
- 实际阻塞：当前无已连接的 Zenodo/长期归档账号或归档认证；继续其他仓库工作，不生成占位 DOI。。

实施内容：

1. 审阅 Zenodo 等账号权限并在获准后连接、归档选定版本
2. 逐项检查源码、研究数据、视频和二进制附件实际存在，必要时采用关联记录

验收标准（逐项在实际验证记录中说明结果）：

- 不默认 GitHub 源码快照包含 Release 所有附件
- 处理失败真实保留；无账号/发布授权时保持 blocked 而非生成假 DOI

计划验证：

- 逐项核对验收条件：不默认 GitHub 源码快照包含 Release 所有附件；处理失败真实保留；无账号/发布授权时保持 blocked 而非生成假 DOI。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`["docs/research/citation-policy.md"]`。

#### O-11.04 · 核验 DOI、默认分支引用和长期下载

- 状态：`todo`；优先级：`P0`；类型：`validation`；责任角色：`release_maintainer`；负责人：未指派。
- 原文依据：§6.2、§10.1。
- 完成依赖：O-11.02, O-11.03, O-09.03；待决策依赖：无。
- 计划产物：`docs/research/evidence/archive-verification.json`；`docs/research/citation-guide.md`。

实施内容：

1. 验证 DOI 解析、版本元数据、实际归档文件与下载哈希
2. 在获准集成 CITATION.cff 后读回默认分支引用入口，并记录该文档提交的独立身份

验收标准（逐项在实际验证记录中说明结果）：

- 实际评估版本与其 DOI 对应；未归档附件明确列出
- 仅实测通过的对象标为已归档/可引用；引用更新不改写冻结制品

计划验证：

- 逐项核对验收条件：实际评估版本与其 DOI 对应；未归档附件明确列出；仅实测通过的对象标为已归档/可引用；引用更新不改写冻结制品。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：实际下载归档的每项文件并比对已冻结哈希；验证 DOI 解析和版本关系；读取默认分支 CITATION.cff 并检查引用入口。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[]`。
实际证据：`[]`。

### O-12 · 收集两组外部复现记录

原文排期：第 2–4 周。输出路径是计划位置，实际完成以证据为准。

#### O-12.01 · 准备外部复现模板与清洗同意说明

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.1、§10.1、§10.2。
- 完成依赖：O-07.05, O-08.02, O-05.03；待决策依赖：无。
- 计划产物：`.github/ISSUE_TEMPLATE/reproduction.yml`；`docs/research/external-reproduction-guide.md`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 模板收集版本、环境、命令、摘要、偏差与失败原因
2. 说明公开字段、清洗流程、身份/联系方式可选及结果使用同意

验收标准（逐项在实际验证记录中说明结果）：

- 不要求提交私密状态或 token；维护者和外部运行分开标识
- 可提交失败或部分复现，不预设全部结果必须通过

计划验证：

- 逐项核对验收条件：不要求提交私密状态或 token；维护者和外部运行分开标识；可提交失败或部分复现，不预设全部结果必须通过。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/external-reproduction-template.md"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/external-reproduction-template.md"]`。

#### O-12.02 · 联系并安排两组外部复现者

- 状态：`todo`；优先级：`P1`；类型：`external_manual`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§1、§10.1。
- 完成依赖：O-12.01, O-11.04；待决策依赖：D-09。
- 计划产物：`docs/research/evidence/reproducer-coordination-summary.json`。

实施内容：

1. 准备邀请文字、资源要求与可选复现轨道
2. 获得联系授权后发送给明确对象，确认至少一组非作者与实际复现安排

验收标准（逐项在实际验证记录中说明结果）：

- 没有实际联系/回复不称已招募；不公开未同意身份
- 外部复现者不由维护者自测冒充；必要访问预算单独确认

计划验证：

- 逐项核对验收条件：没有实际联系/回复不称已招募；不公开未同意身份；外部复现者不由维护者自测冒充；必要访问预算单独确认。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-12.03 · 收集、核验并归档两组外部复现

- 状态：`todo`；优先级：`P1`；类型：`external_manual`；责任角色：`external_reproducer`；负责人：未指派。
- 原文依据：§1、§6.2、§10.2。
- 完成依赖：O-12.02；待决策依赖：无。
- 计划产物：`docs/research/evidence/external-reproductions/`；`docs/research/external-reproduction-report.md`。

实施内容：

1. 核查运行来源、版本、报告摘要与复算结果，记录外部环境差异
2. 保留失败和部分结果；由贡献者确认可公开材料

验收标准（逐项在实际验证记录中说明结果）：

- 至少两组真实外部记录，其中至少一组非作者
- 达不到目标保持未完成；成功率分母包括已提交失败尝试，不声称获正式 artifact badge

计划验证：

- 逐项核对验收条件：至少两组真实外部记录，其中至少一组非作者；达不到目标保持未完成；成功率分母包括已提交失败尝试，不声称获正式 artifact badge。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：采用收到的公共报告及其记录的源码/corpus/verifier 版本复算；确认独立身份与公开同意，不将维护者代跑计入外部复现。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[]`。
实际证据：`[]`。

#### O-12.04 · 修复复现阻塞并发布可追溯勘误

- 状态：`todo`；优先级：`P1`；类型：`conditional`；责任角色：`maintainer`；负责人：未指派。
- 原文依据：§10.2、§6.2。
- 完成依赖：O-12.03；待决策依赖：无。
- 计划产物：`docs/research/reproduction-errata.md`；`受影响文档/验证工具（按真实问题确定）`。
- 条件：外部复现中发现需修复的真实阻塞。

实施内容：

1. 按依赖、配置、平台、模型和 verifier 分类处理外部反馈
2. 做必要最小修正和相应验证，记录结果变化及新版本身份

验收标准（逐项在实际验证记录中说明结果）：

- 不修改旧原始数据以消除失败
- 若无阻塞则记录证据并标 not_applicable，不制造无意义代码改动

计划验证：

- 逐项核对验收条件：不修改旧原始数据以消除失败；若无阻塞则记录证据并标 not_applicable，不制造无意义代码改动。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

### O-13 · 发布研究导读与技术报告

原文排期：第 2–4 周。输出路径是计划位置，实际完成以证据为准。

#### O-13.01 · 编写英文研究导读与中文首页导航

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§1、§4、§10.1。
- 完成依赖：O-08.01, O-08.03, O-09.03；待决策依赖：无。
- 计划产物：`README.md`；`docs/research/research-overview.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 首页突出问题、架构、fixture 入口、三个实验、边界与引用
2. 保留企业组件入口；使用已有最终架构，不改演示 UI

验收标准（逐项在实际验证记录中说明结果）：

- 首次读者可定位无 key 复现与证据入口
- 名称/支持状态一致，不把研究原型宣传为普遍安全保证

计划验证：

- 逐项核对验收条件：首次读者可定位无 key 复现与证据入口；名称/支持状态一致，不把研究原型宣传为普遍安全保证。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["README.md", "docs/research/research-overview.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["README.md", "docs/research/research-overview.md"]`。

#### O-13.02 · 形成可核验的方法技术报告

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`research_lead`；负责人：maoyadongsh。
- 原文依据：§4、§10.1。
- 完成依赖：O-08.04, O-08.03；待决策依赖：无。
- 计划产物：`docs/research/technical-report.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 解释独立授权、Value+Provenance 和 Effect/Completion，逐项关联结果
2. 注明当前受控样本、历史失败、尚未补齐的相关工作与实验证据

验收标准（逐项在实际验证记录中说明结果）：

- 每项实证结论含总体/分母/协议/证据；未同行评审状态清楚
- 不以 RQ 代替已确立创新，不虚构论文接收状态

计划验证：

- 逐项核对验收条件：每项实证结论含总体/分母/协议/证据；未同行评审状态清楚；不以 RQ 代替已确立创新，不虚构论文接收状态。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/technical-report.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/technical-report.md"]`。

#### O-13.03 · 核对首发视频及其代码和署名边界

- 状态：`todo`；优先级：`P1`；类型：`validation`；责任角色：`maintainer`；负责人：未指派。
- 原文依据：§6.2、§10.1。
- 完成依赖：O-10.01, O-02.03；待决策依赖：无。
- 计划产物：`docs/research/evidence/research-video-identity.json`；`docs/research/video-guide.md`。

实施内容：

1. 优先沿用 V5 已有视频，检查哈希、可播放、录制源码与研究源码差异
2. 仅当录制内容已失真或不可用才准备新录像方案

验收标准（逐项在实际验证记录中说明结果）：

- 不为轻微文案改动反复录制；UI/模型/硬件声明对应实际录像
- 媒体许可和署名核清，视频留在正式媒体/制品位置而非 Git 大对象

计划验证：

- 逐项核对验收条件：不为轻微文案改动反复录制；UI/模型/硬件声明对应实际录像；媒体许可和署名核清，视频留在正式媒体/制品位置而非 Git 大对象。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-13.04 · 发布导读、技术报告和演示入口

- 状态：`todo`；优先级：`P1`；类型：`external_manual`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§10.1。
- 完成依赖：O-13.01, O-13.02, O-13.03, O-11.04, O-12.01；待决策依赖：D-06, D-09。
- 计划产物：`docs/research/evidence/research-announcement.json`。

实施内容：

1. 在首发五件套齐备后准备实际发布内容与渠道
2. 经相应公开发布授权后执行并登记链接和版本

验收标准（逐项在实际验证记录中说明结果）：

- 依赖的制品/归档/引用真实可访问，外部复现不足则直说等待复现
- 未授权不发布帖子或群发消息；截图/视频不携带私密信息

计划验证：

- 逐项核对验收条件：依赖的制品/归档/引用真实可访问，外部复现不足则直说等待复现；未授权不发布帖子或群发消息；截图/视频不携带私密信息。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

### O-14 · 开放讨论与首批贡献任务

原文排期：第 2–4 周。输出路径是计划位置，实际完成以证据为准。

#### O-14.01 · 建立六类 Issue 与 PR 审阅模板

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.1、§8.2。
- 完成依赖：O-05.02, O-05.03, O-12.01；待决策依赖：无。
- 计划产物：`.github/ISSUE_TEMPLATE/`；`.github/PULL_REQUEST_TEMPLATE.md`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 覆盖复现、新案例、指标纠错、兼容性、文档和研究提案
2. 提示漏洞走私密入口，PR 列明来源、测试和证据

验收标准（逐项在实际验证记录中说明结果）：

- 表单可解析，复现/研究提案不强制填造安全结论
- 不在模板要求提供密钥或全量状态文件

计划验证：

- 逐项核对验收条件：表单可解析，复现/研究提案不强制填造安全结论；不在模板要求提供密钥或全量状态文件。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_documented_scope", "evidence": [".github/ISSUE_TEMPLATE", ".github/PULL_REQUEST_TEMPLATE.md"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`[".github/ISSUE_TEMPLATE", ".github/PULL_REQUEST_TEMPLATE.md"]`。

#### O-14.02 · 准备五类首批贡献任务

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.1、§10.1。
- 完成依赖：O-14.01；待决策依赖：无。
- 计划产物：`docs/research/community-backlog.md`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 落盘普通 Linux 复现、same-value 验证、fixture 诊断、分母复算、负向测试任务
2. 为每项给出入口、完成标准和审阅人，不新增框架/沙箱

验收标准（逐项在实际验证记录中说明结果）：

- 每项可独立开始并有真实验收方法
- 新增案例不会修改 V5 分母，安全修复必须证明旧行为被拒

计划验证：

- 逐项核对验收条件：每项可独立开始并有真实验收方法；新增案例不会修改 V5 分母，安全修复必须证明旧行为被拒。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/community-backlog.md"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/community-backlog.md"]`。

#### O-14.03 · 开启 Discussions 并发布首批社区任务

- 状态：`done`；优先级：`P1`；类型：`external_manual`；责任角色：`repository_admin`；负责人：maoyadongsh。
- 原文依据：§2、§8.1、§10.1。
- 完成依赖：O-14.02, O-05.04；待决策依赖：D-03, D-04, D-09。
- 计划产物：`docs/research/evidence/community-launch.json`。
- 完成时间：2026-09-08T15:06:01.179243+00:00。

实施内容：

1. 按确认的讨论分类、维护责任与治理授权设置入口
2. 经授权创建实际 Issues/讨论入口并核验链接

验收标准（逐项在实际验证记录中说明结果）：

- 平台设置有 readback，发布内容与落盘任务对应
- 无人维护或未获联系授权时不宣称社区运营已启动

计划验证：

- 逐项核对验收条件：平台设置有 readback，发布内容与落盘任务对应；无人维护或未获联系授权时不宣称社区运营已启动。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际执行/文件/读取回执审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/evidence/community-launch.json"], "limitations": "首个发行是源码预发布，不声称新二进制分发/原生验收；托管 CI 不代表外部研究者独立复现。"}]`。
实际证据：`["docs/research/evidence/community-launch.json"]`。

### O-15 · 相关工作、研究协议和 pilot

原文排期：第 2 月。输出路径是计划位置，实际完成以证据为准。

#### O-15.01 · 检索相关工作并确定可比较贡献

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§4.1、§7.9。
- 完成依赖：O-08.01；待决策依赖：无。
- 计划产物：`docs/research/related-work.md`；`docs/research/comparison-matrix.json`。

实施内容：

1. 以论文和系统一手资料核查威胁模型、策略输入、执行覆盖、效果核验与实验开放性
2. 记录检索日期、版本、可运行条件与具体差异

验收标准（逐项在实际验证记录中说明结果）：

- 没有实现/协议可公平对齐的系统不进入量化比较
- 候选贡献措辞由实际比较支持，不写未经核查的首创声明

计划验证：

- 逐项核对验收条件：没有实现/协议可公平对齐的系统不进入量化比较；候选贡献措辞由实际比较支持，不写未经核查的首创声明。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-15.02 · 预先定义新研究评价与统计协议

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§7.1、§7.3、§7.4、§7.5、§7.8。
- 完成依赖：O-15.01, O-08.04；待决策依赖：D-08。
- 计划产物：`docs/research/protocols/r1.md`；`docs/research/protocols/r1.json`。

实施内容：

1. 锁定任务族、模型版本、条件、生成参数、预算、超时/重试/排除和分析方法
2. 定义 proposal/attempt/materialization/effect/completion、缺失数据与分组统计

验收标准（逐项在实际验证记录中说明结果）：

- 新协议在正式实验前有不可混淆的版本与摘要
- 历史 V5 结果不伪称预注册；同任务重复不当独立任务样本；新 provider 单独 cohort

计划验证：

- 逐项核对验收条件：新协议在正式实验前有不可混淆的版本与摘要；历史 V5 结果不伪称预注册；同任务重复不当独立任务样本；新 provider 单独 cohort。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-15.03 · 锁定调参集、评价集与新案例接纳规则

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§7.1、§7.5、§7.8。
- 完成依赖：O-15.02, O-08.02；待决策依赖：D-08。
- 计划产物：`docs/research/protocols/r1-dataset-split.json`；`docs/research/dataset-card.md`。

实施内容：

1. 区分 pilot/调参、最终评价及独立未见样本
2. 记录重复/污染检测与案例版本，保持 V5 语料身份不变

验收标准（逐项在实际验证记录中说明结果）：

- 分组与任务身份可追溯，测试集不随结果调优
- 未知新案例独立计数，不能追溯修改旧 benchmark 总体

计划验证：

- 逐项核对验收条件：分组与任务身份可追溯，测试集不随结果调优；未知新案例独立计数，不能追溯修改旧 benchmark 总体。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-15.04 · 运行 pilot 并冻结正式实验规模

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§7.5、§7.7。
- 完成依赖：O-15.03；待决策依赖：D-08。
- 计划产物：`docs/research/evidence/r1-pilot/`；`docs/research/protocols/r1-finalization.md`。

实施内容：

1. 在获准新研究周期和预算内运行 pilot，保留所有尝试
2. 按观察变异、任务相关性、估计目标及预算决定正式规模与不确定性报告方法

验收标准（逐项在实际验证记录中说明结果）：

- 有先后时间、实际计算/预算依据和协议差异记录
- 不选取有利样本大小来包装 5/5，不把 pilot 重作盲测结果

计划验证：

- 逐项核对验收条件：有先后时间、实际计算/预算依据和协议差异记录；不选取有利样本大小来包装 5/5，不把 pilot 重作盲测结果。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

### O-16 · 公平对照、消融和外部评估集

原文排期：第 2–3 月。输出路径是计划位置，实际完成以证据为准。

#### O-16.01 · 准备公平对照和受控消融条件

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§7.2、§7.9。
- 完成依赖：O-15.04, O-06.04；待决策依赖：D-08。
- 计划产物：`benchmarks/（新版本实验配置与必要小增量）`；`docs/research/evidence/r1-baseline-review.json`。

实施内容：

1. 在同任务/工具/模型预算条件下定义提示约束、运行时授权、来源和效果层的比较
2. 仅在隔离合成 fixture 中容许消融；复用现有 harness

验收标准（逐项在实际验证记录中说明结果）：

- 任何关闭保护的实验不能进入用户安装模式、默认安全配置或共享生产服务
- 对照差异与权限范围可审阅；不可运行的比较不报量化结果

计划验证：

- 逐项核对验收条件：任何关闭保护的实验不能进入用户安装模式、默认安全配置或共享生产服务；对照差异与权限范围可审阅；不可运行的比较不报量化结果。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-16.02 · 补充未见来源与效果故障实验案例

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_contributor`；负责人：未指派。
- 原文依据：§4.1、§7.1、§7.6。
- 完成依赖：O-16.01；待决策依赖：D-08。
- 计划产物：`benchmarks/（新 corpus 版本）`；`docs/research/evidence/r1-case-review.json`。

实施内容：

1. 围绕 provenance、observer 故障和任务范围补充批准的新案例
2. 标明来源错误属于可信假设损坏还是实现缺陷，保持正负配对

验收标准（逐项在实际验证记录中说明结果）：

- 每案有明确观测 oracle、实际效果范围与成功标准
- 无泛化 shell/新安全框架，V5 cases 和记录原样保留

计划验证：

- 逐项核对验收条件：每案有明确观测 oracle、实际效果范围与成功标准；无泛化 shell/新安全框架，V5 cases 和记录原样保留。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-16.03 · 执行正式控制/模型 cohort 与 locality 评价

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§7.3、§7.4、§7.6、§7.8。
- 完成依赖：O-16.02；待决策依赖：D-08。
- 计划产物：`docs/research/evidence/r1-runs/`。

实施内容：

1. 按冻结协议分 cohort 执行并保存原始已清洗结果
2. 分开模型拒绝、运行时拒绝、准备失败、超时和效果缺失，保留 provider/分类/硬件信息

验收标准（逐项在实际验证记录中说明结果）：

- 所有尝试有日志与身份，重试不覆盖第一次失败
- C 轨实际调用的权限预算有效；公共日志不含秘密和未经授权数据

计划验证：

- 逐项核对验收条件：所有尝试有日志与身份，重试不覆盖第一次失败；C 轨实际调用的权限预算有效；公共日志不含秘密和未经授权数据。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-16.04 · 完成统计、成本分解与数据复算

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§7.3、§7.5、§7.7、§10.2。
- 完成依赖：O-16.03；待决策依赖：无。
- 计划产物：`docs/research/r1-results.md`；`docs/research/evidence/r1-analysis/`；`benchmarks/（必要分析脚本）`。

实施内容：

1. 按协议输出各阶段结果、分母、缺失值及任务分组的不确定性
2. 分别统计模型、授权、回执/持久化、工具/效果耗时及实测调用成本

验收标准（逐项在实际验证记录中说明结果）：

- 表格可重算，不把 repeated seeds 伪装独立任务
- 成本使用当时实际用量/账单口径，模型输出与文件效果质量不混淆；必要分析测试覆盖缺失与分母

计划验证：

- 逐项核对验收条件：表格可重算，不把 repeated seeds 伪装独立任务；成本使用当时实际用量/账单口径，模型输出与文件效果质量不混淆；必要分析测试覆盖缺失与分母。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：用冻结原始结果重算分母、unknown/missing、重试及任务分组统计；必要的分析校验应覆盖空总体、缺失记录和重复任务。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[]`。
实际证据：`[]`。

#### O-16.05 · 独立审阅新实验的结论与负面结果

- 状态：`todo`；优先级：`P1`；类型：`review`；责任角色：`research_reviewer`；负责人：未指派。
- 原文依据：§7、§8.2。
- 完成依赖：O-16.04；待决策依赖：无。
- 计划产物：`docs/research/r1-review.md`；`docs/research/claims-evidence.md`。

实施内容：

1. 核对协议偏差、数据泄漏、所有失败、消融解释与可比性
2. 优先由非实验作者审阅，并更新结论边界和未来版本证据映射

验收标准（逐项在实际验证记录中说明结果）：

- 独立人员缺位时明确 self-review，不冒充已独立验证
- 旧结论与新结果并存，修正有版本/勘误；不覆写历史

计划验证：

- 逐项核对验收条件：独立人员缺位时明确 self-review，不冒充已独立验证；旧结论与新结果并存，修正有版本/勘误；不覆写历史。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

### O-17 · 论文及正式 artifact evaluation 材料

原文排期：第 2–3 月。输出路径是计划位置，实际完成以证据为准。

#### O-17.01 · 选择投稿方向并核对当前政策

- 状态：`todo`；优先级：`P1`；类型：`research`；责任角色：`research_lead`；负责人：未指派。
- 原文依据：§10.1、§6.2。
- 完成依赖：O-15.01；待决策依赖：无。
- 计划产物：`docs/research/venue-assessment.md`。

实施内容：

1. 在准备投稿时查验具体 venue 的当前 CFP、时间、匿名、预印本和材料政策
2. 记录是否适合 technical report、demo、workshop 或完整论文及理由

验收标准（逐项在实际验证记录中说明结果）：

- 来源为实际最新一手规则；不沿用设计日假定期限
- 已公开源码/视频/作者信息对匿名策略的影响明确，不承诺未核查的投稿资格

计划验证：

- 逐项核对验收条件：来源为实际最新一手规则；不沿用设计日假定期限；已公开源码/视频/作者信息对匿名策略的影响明确，不承诺未核查的投稿资格。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-17.02 · 形成论文、署名确认与研究制品评审包

- 状态：`todo`；优先级：`P1`；类型：`documentation`；责任角色：`authors`；负责人：未指派。
- 原文依据：§4、§6.1、§6.2、§10.1。
- 完成依赖：O-16.05, O-17.01, O-09.01, O-12.03；待决策依赖：D-07。
- 计划产物：`docs/research/paper/`；`docs/research/artifact-evaluation-guide.md`。

实施内容：

1. 根据真实实验组织方法、相关工作、结果、负面结果、威胁与复现步骤
2. 由作者确认署名及发布权，制品绑定实际论文评估版本

验收标准（逐项在实际验证记录中说明结果）：

- 论文每项实证结论可追溯；当前未发表/未接收状态明确
- 评审包无需秘密账户材料，不能自颁 ACM 等正式 badge

计划验证：

- 逐项核对验收条件：论文每项实证结论可追溯；当前未发表/未接收状态明确；评审包无需秘密账户材料，不能自颁 ACM 等正式 badge。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

#### O-17.03 · 执行经授权的论文与 artifact 提交

- 状态：`todo`；优先级：`P1`；类型：`external_manual`；责任角色：`corresponding_author`；负责人：未指派。
- 原文依据：§6.2、§10.1、§12。
- 完成依赖：O-17.02；待决策依赖：D-12。
- 计划产物：`docs/research/evidence/paper-submission.json`；`docs/research/evidence/artifact-submission.json`。

实施内容：

1. 在作者和账号授权、venue 规则及材料清单满足后执行提交
2. 记录真实版本、提交回执和材料校验结果

验收标准（逐项在实际验证记录中说明结果）：

- 无实际回执不标已投稿，提交不等于接收/评审通过
- 材料隐私和匿名策略符合实际规则，不自动对外发送

计划验证：

- 逐项核对验收条件：无实际回执不标已投稿，提交不等于接收/评审通过；材料隐私和匿名策略符合实际规则，不自动对外发送。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。
- 计划验证命令或方法（含占位符时不可原样执行）：核对实际 venue 规则与提交内容摘要，并保存真实提交编号/回执；没有外部回执不得通过。。执行时填入实际路径、版本与范围，保存退出码/结果和证据。

实际验证：`[]`。
实际证据：`[]`。

#### O-17.04 · 记录评审结果、修订和真实引用

- 状态：`todo`；优先级：`P1`；类型：`external_manual`；责任角色：`corresponding_author`；负责人：未指派。
- 原文依据：§6.2、§10.1。
- 完成依赖：O-17.03；待决策依赖：无。
- 计划产物：`docs/research/publication-status.md`；`CITATION.cff（实际发表后才更新）`。

实施内容：

1. 收到真实评审后记录结果、修订、材料版本和获颁标识（如有）
2. 按正式发表信息更新论文引用，不修改原软件制品身份

验收标准（逐项在实际验证记录中说明结果）：

- 接收、DOI 和 badge 均有外部证据；未收到则等待
- 拒稿/失败不隐藏，不将投稿状态改成发表

计划验证：

- 逐项核对验收条件：接收、DOI 和 badge 均有外部证据；未收到则等待；拒稿/失败不隐藏，不将投稿状态改成发表。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`[]`。

### O-18 · 维护容量、版本支持与贡献者培养

原文排期：持续。输出路径是计划位置，实际完成以证据为准。

#### O-18.01 · 确定维护容量和版本支持基线

- 状态：`done`；优先级：`P1`；类型：`documentation`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.2、§8.3、§10.2。
- 完成依赖：O-05.01, O-05.04；待决策依赖：D-03。
- 计划产物：`docs/research/maintenance-plan.md`；`SECURITY.md`；`GOVERNANCE.md`。
- 完成时间：2026-09-08T14:57:14.153352+00:00。

实施内容：

1. 确认现实维护人数、值守责任、支持版本与复审能力
2. 定义新增维护者、权限授予/撤销与扩大承诺的条件

验收标准（逐项在实际验证记录中说明结果）：

- 单维护者状态诚实，支持周期和内部目标由真人接受
- 无第二维护者不声称双人独立审批已运行

计划验证：

- 逐项核对验收条件：单维护者状态诚实，支持周期和内部目标由真人接受；无第二维护者不声称双人独立审批已运行。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[{"method": "实际文件/来源/命令或 GitHub API readback 审核", "result": "passed_for_documented_scope", "evidence": ["docs/research/maintenance-plan.md", "SECURITY.md", "GOVERNANCE.md"], "limitations": "范围、未知项和未实施部分保留在各证据文档；不等于全研究计划完成。"}]`。
实际证据：`["docs/research/maintenance-plan.md", "SECURITY.md", "GOVERNANCE.md"]`。

#### O-18.02 · 定义并汇总研究社区指标

- 状态：`in_progress`；优先级：`P1`；类型：`recurring`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§1、§10.2。
- 完成依赖：O-12.01, O-08.03；待决策依赖：无。
- 计划产物：`docs/research/community-metrics.md`；`docs/research/evidence/community-metrics/`。
- 周期：每月汇总一期；每期有独立记录，计划持续而非永久 done。

实施内容：

1. 定义外部复现成功率、结论追溯率、阻塞原因、有效贡献和引用口径
2. 收集公开或获同意的聚合结果，Stars/下载仅作辅助

验收标准（逐项在实际验证记录中说明结果）：

- 分母包含已提交失败尝试，维护者自测单列
- 不默认采集个人环境或联系方式遥测；没有数据时报告无数据

计划验证：

- 逐项核对验收条件：分母包含已提交失败尝试，维护者自测单列；不默认采集个人环境或联系方式遥测；没有数据时报告无数据。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`["docs/research/community-metrics.md"]`。

#### O-18.03 · 开展版本维护、勘误和维护者培养

- 状态：`in_progress`；优先级：`P1`；类型：`recurring`；责任角色：`maintainer`；负责人：maoyadongsh。
- 原文依据：§8.2、§9、§10.2。
- 完成依赖：O-18.01, O-14.01；待决策依赖：无。
- 计划产物：`docs/research/maintenance-log.md`；`GOVERNANCE.md`；`SECURITY.md`。
- 周期：每月一次维护回顾，事件驱动处理真实漏洞与复现故障。

实施内容：

1. 定期复查依赖漏洞、复现阻塞、Issue 受理和证据链接
2. 培养第二维护者，按可核实贡献调整职责并保留变更记录

验收标准（逐项在实际验证记录中说明结果）：

- 每期记录实际处理/未解决事项，不假定没有风险
- 涉及新发布或权限变更继续核对有效授权；不自动恢复比赛功能开发

计划验证：

- 逐项核对验收条件：每期记录实际处理/未解决事项，不假定没有风险；涉及新发布或权限变更继续核对有效授权；不自动恢复比赛功能开发。全部适用条件满足，并写入实际 validation/evidence；未执行不算通过。

实际验证：`[]`。
实际证据：`["docs/research/maintenance-log.md", "GOVERNANCE.md", "SECURITY.md"]`。

## 原文覆盖矩阵

| 原文节 | 对应任务 |
| --- | --- |
| §1 | O-08.01, O-08.03, O-12.02, O-12.03, O-13.01, O-18.02 |
| §2 | O-01.01, O-02.01, O-03.01, O-06.01, O-06.03, O-14.03 |
| §3 | O-01.02, O-01.03, O-02.01, O-02.02, O-02.03, O-04.01, O-04.02, O-04.03, O-04.04, O-08.02, O-10.02 |
| §4 | O-07.04, O-08.01, O-08.03, O-08.04, O-13.01, O-13.02, O-15.01, O-16.02, O-17.02 |
| §5 | O-06.04, O-07.01, O-07.02, O-07.03, O-07.04, O-07.05 |
| §6 | O-03.04, O-07.01, O-07.03, O-07.05, O-08.01, O-08.02, O-08.03, O-08.04, O-08.05, O-09.01, O-09.02, O-09.03, O-10.01, O-10.05, O-11.01, O-11.02, O-11.03, O-11.04, O-12.03, O-12.04, O-13.03, O-17.01, O-17.02, O-17.03, O-17.04 |
| §7 | O-15.01, O-15.02, O-15.03, O-15.04, O-16.01, O-16.02, O-16.03, O-16.04, O-16.05 |
| §8 | O-03.01, O-03.02, O-03.03, O-03.04, O-05.01, O-05.02, O-05.03, O-05.04, O-09.01, O-12.01, O-14.01, O-14.02, O-14.03, O-16.05, O-18.01, O-18.03 |
| §9 | O-02.02, O-04.04, O-06.01, O-06.02, O-06.03, O-06.04, O-08.05, O-10.01, O-10.02, O-10.03, O-10.04, O-10.05, O-11.01, O-11.02, O-18.03 |
| §10 | O-05.04, O-08.03, O-11.01, O-11.04, O-12.01, O-12.02, O-12.03, O-12.04, O-13.01, O-13.02, O-13.03, O-13.04, O-14.02, O-14.03, O-16.04, O-17.01, O-17.02, O-17.03, O-17.04, O-18.01, O-18.02, O-18.03 |
| §11 | O-01.01, O-01.02, O-01.03, O-02.01, O-02.02, O-02.03, O-03.01, O-03.02, O-03.03, O-03.04, O-04.01, O-04.02, O-04.03, O-04.04, O-05.01, O-05.02, O-05.03, O-05.04, O-06.01, O-06.02, O-06.03, O-06.04, O-07.01, O-07.02, O-07.03, O-07.04, O-07.05, O-08.01, O-08.02, O-08.03, O-08.04, O-08.05, O-09.01, O-09.02, O-09.03, O-10.01, O-10.02, O-10.03, O-10.04, O-10.05, O-11.01, O-11.02, O-11.03, O-11.04, O-12.01, O-12.02, O-12.03, O-12.04, O-13.01, O-13.02, O-13.03, O-13.04, O-14.01, O-14.02, O-14.03, O-15.01, O-15.02, O-15.03, O-15.04, O-16.01, O-16.02, O-16.03, O-16.04, O-16.05, O-17.01, O-17.02, O-17.03, O-17.04, O-18.01, O-18.02, O-18.03 |
| §12 | O-01.01, O-01.03, O-05.01, O-09.01, O-17.03 |

## 执行入口

实施开始时先刷新 O-01.01，再开展 O-01.02、O-02.01/02、O-03.01、O-06.01、O-07.01、O-08.01 的准备。某个外部事项等待确认时，继续无依赖的本地准备；不能跨过未满足依赖发布结果。
