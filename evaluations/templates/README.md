# 记录提交要求

正文模板复用[研究外部复现模板](../../docs/research/external-reproduction-template.md)；不另复制一份。提交前明确公开许可、贡献者身份与关系、资助、允许公开的材料范围。

机器记录使用 [catalog.json](../catalog.json) 的 `siq-evaluation-catalog/v1`：稳定 ID、类型、关系、实际候选（完整 SHA 或明确记录的局部/dirty 身份）、独立的证据/集成提交、OS/架构/运行形态、宿主/后端与模型模式、结果分母、失败/重跑原记录、限制、证据路径和 SHA-256。未记载字段用 null 或 `not_recorded`，不从后来提交补造当时身份。

结果列表中的 metric 是具体计数名称，value/total 不自动解释为“通过率”；例如 unsafe_materialized 的 0/13 是有定义的效果观察。工作流数、回执数、用例数和附件数不能互加。D05 的各状态必须分别保存，partial/blocked 不显示为通过。

此格式是仓库导航索引，不替代 QA 合同或自动产生 supported。新增索引必须通过本地守卫；原证据不能为适应模板而改写。原始状态放在隔离私有目录，审核后再新增独立公开摘要。后续更正需新记录、supersedes 和原对象摘要，不能就地修饰失败。
