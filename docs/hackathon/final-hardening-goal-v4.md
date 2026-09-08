# 当前开发目标：Final Hardening & Competition Freeze V4

更新：2026-09-08。用户指定的完整要求已按原始字节保存在 [V4 原文](final-hardening-requirements-v4.md)。本文件负责当前目标与执行入口，[开发任务台账](final-hardening-tasks-v4.md)负责逐项实施和验收；[JSON 台账](final-hardening-tasks-v4.json)是可更新的任务状态事实源。

用户已明确要求持续完成 V4 全部开发与可执行交付。**目标登记完成不等于 V4 工程完成。** 59 项工程任务现已完成，远端 CI、clean RC、实机验证与真实视频证据见[最终报告](final-hardening-report.md)。4 项 external/manual 保持未执行。原文 §81 的完整工程交付链是最终验收要求。

## 基线与来源

| 项目 | 记录 |
| --- | --- |
| repository | `maoyadongsh/siq-agent-security` |
| starting_sha | `9b4aaeae1a089b54fbbc50c33cdb72616be2b1b1` |
| base branch | `codex/dgx-spark-hackathon-v3` |
| development branch | `codex/hackathon-final-hardening-v4` |
| branch synchronization | `git fetch --all --prune`、比赛分支 `git pull --ff-only` 成功；远端 HEAD 与上述 SHA 一致 |
| initial worktree | 干净；已检查最近十条提交，从最新比赛分支创建 V4 分支 |
| source document SHA256 | `60ef74152619b72bcc27123067a500f02b5f861f15086edb3621b9d218df0fc4` |
| original title | DGX Spark Agent Skills Hackathon — Final Hardening & Competition Freeze V4 |
| original sections | §0–§83，共 84 节，全部映射至任务 |
| task inventory | 63 项；2 项基线/审计完成，61 项待执行，其中 4 项为 external/manual |
| implementation evidence | [Current-State Audit](final-hardening-audit.md) 为初始审计；新实现与实际验证见[开发进度](final-hardening-progress-v4.md) |

以上数量为登记快照；后续以 JSON 中的逐项状态与证据为准。V4 覆盖 V3 中固定三步计划、主备模型叙事、dirty-source 候选、视频非必需等相冲突的开发目标；V3 的源码、签名协议和历史证据继续复用，不能重贴 V4 已验收标签。`main` 集成历史不改变本轮指定的 V3 分支基线。

## 四个目标

1. 收紧 Model Egress / DGX Locality：敏感度由可信 operator/config 决定；远程规划与本地敏感研究分离，每次切换和调用可审计。
2. 从固定 Pipeline 升级为受约束动态 Skill 编排：模型选择闭集中的合法 1/2/3 项组合，确定性依赖校验与 SIQ 授权始终有效。
3. 完成 Release / CI / Governance Hardening：真实 PR CI、冻结精确提交、干净源码构建、可验证 RC 身份；治理设置按外部人工动作管理。
4. 冻结比赛 Demo / Evidence / Submission Package：五主题证据入口、唯一主故事、真实 2–3 分钟视频和可重复演示。

目标架构：StepFun 处理非敏感任务规划，DGX 本地模型承担敏感分析，Agent 执行受约束 Skills，SIQ 独立授权有后果的工具动作；工具报告与 EffectEvidence 分离后再判断 Completion。该段描述目标架构，当前实现差距见审计。

## 八项不变量

| ID | 约束 |
| --- | --- |
| INV-1 | Agent may propose actions, but may not manufacture authority. |
| INV-2 | Model output = proposal/data，不能成为 authority。 |
| INV-3 | MCP / Web / Tool / Memory 不自动获得 trusted provenance。 |
| INV-4 | Tool success 不等于 verified real-world effect。 |
| INV-5 | Unknown evidence remains UNKNOWN. |
| INV-6 | Security-sensitive egress 必须有明确 trust boundary。 |
| INV-7 | 远程模型调用不能成为绕开 SIQ 出网治理的隐式通道。 |
| INV-8 | 模型可以选择 Skills，不能绕过确定性依赖、Authority 和 ToolGateway。 |

## 执行顺序与完成规则

严格遵循原文：**Model Egress → Dynamic Skills → Regression → PR + Remote CI → Clean RC → Evidence Index → Demo Freeze / Video**。C/F 的硬件、locality、计划和故障 UI 属于必需验收面，应在最终回归前集成；不为 P1 可视化扩展比赛外模块。打包脚本的修改先随工程提交测试，实际候选构建必须等待该精确提交远端 CI green。证据索引最终定稿依赖实际候选和新回归结果。

任务路径：`V4-SCOPE → V4-A1…A8 → V4-B1…B7 → C/F → V4-I1…I7 → V4-D1/D2 → V4-D4…D8 → V4-E1…E4 → G/H/J → V4-REPORT → V4-ACCEPT`。具体依赖以任务台账为准；不存在根据旧文档自动完成任务的捷径。

每项任务从 `todo` 进入 `in_progress`，记录实际验证命令、时间、source SHA、结果和证据路径后才能转 `done`。阻塞时填写原因，独立工程继续。已有代码可以直接复用，但须满足本轮验收再结项；`implemented` 不等于 `evidenced`，旧样本不等于新代码回归。

最终至少满足原文六组 DoD：Model Egress、Skills、Release、Evidence、Demo、Video。保留精确源码/CI/构建/视频身份；报告区分冻结构建提交与后续文档提交，避免将构建前后不同源码写成同一身份。最终状态不得用测试通过或本地构建替代远端 CI、真实 DGX 推理、视频录制。

PR 从 V4 提交至 V3，保持审阅状态，不自行 merge。可冻结已经通过 CI 的 PR 精确 head 用于 clean checkout，无需为了打包绕过审阅。候选目标为 `siq-agent-security-v0.3.0-rc.1`，若仓库命名规则冲突按现有 convention；不发布 stable。

## 外部动作与范围边界

独立跟踪 `V4-EXT-GOV`（main 保护）、`V4-EXT-SIGN`（正式签名）、`V4-EXT-RELEASE`（官方 RC 发布）、`V4-EXT-VIDEO`（视频上传）。没有明确授权不改 repository settings；存在 admin 能力不等于已获授权。没有正式签名条件就标注 unsigned release candidate，不能用测试密钥或历史签名冒充。没有权限时记录精确人工步骤，继续其余工程。

本轮不新增：Managed Linux full implementation、Multi-Agent Delegation DAG、General Sandbox Engine、Universal SaaS Effect Verification、Neural Taint、General Memory IFC、New Enterprise Authority Plane、New microservice、New Agent framework。

除解决明确 bug，不重构：Intent contracts、Provenance signing、EffectEvidence signing、Receipt chain、Control Plane、Adapters、OpenShell。内部 TaskPlan V2 的版本化调整不应扩散成安全内核重写。

完成全部必需 DoD 后 **STOP FEATURE DEVELOPMENT**。最终只追求稳定、清楚、真实、可重复、有证据；原文 §80 的最终产品声明以完成全部验收为前提。

## 本次落盘校验

已校验原文与附件逐字节一致及 SHA256；63 项任务 ID 唯一、依赖引用有效且无环，84 节覆盖无遗漏，ME-01–08 / SP-01–08 齐全。Markdown 与 JSON 任务集合一致，23 个新文档本地链接可解析，`git diff --check` 通过。仅两项已完成任务填写实际证据，其余均待执行。本次未运行应用功能测试，也未创建提交、推送、PR 或 RC。
