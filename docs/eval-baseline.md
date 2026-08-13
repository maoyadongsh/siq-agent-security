# 评测集基线（§31.1 验收口径）

> 日期：2026-08-13。语料：`apps/control-api/app/tests/fixtures/eval/`；跑分：`app/tests/test_eval_baseline.py`（每次运行自动生成 report.json）。

## 目的

设计文档 §31.1 的验收数字（召回 100%、误报 ≤5%、准确率 ≥90%）需要评测集才有意义。本基线是第一步：**先有受控语料和诚实基线分**，再谈模型辅助分类的目标。

## 语料定义

| 组 | 含义 | 样本 |
| --- | --- | --- |
| positive/vocab_match | 智能体候选，名称含基线词表关键词（advisor/auditor/controller/expert 等） | siq_legal_advisor、finance-auditor、risk-controller、sector-expert、research-assistant、company-strategist |
| positive/hard | 智能体候选，名称**无**关键词（需模型语义理解） | deal_review_bot、risk_probe_runner |
| negative/vocab_match | 普通服务，名称与智能体无关 | postgres-backup、nginx-proxy、redis-cache、cron-cleaner |
| negative/hard | 普通服务，名称可能带迷惑词 | file_sync_worker、log_rotator |

标注流程：人工标注 + `schema_version` 版本化；语料变更需同步跑分并更新本文档数字。

## 当前基线分（确定性词表分类器）

| 指标 | 值 | 说明 |
| --- | --- | --- |
| positive 召回 | **6/8 = 0.75** | vocab_match 组 6/6（词表命中保证）；hard 组 0/2（预期 miss） |
| 负样本误报率 | **0%** | 4/4 vocab + 2/2 hard 均未误报 |
| 与 §31.1 目标的差距 | 召回差 0.25（全部来自 hard 组） | 模型辅助分类（§11）接入后的增量价值就在这 0.25 |

## 结论

1. 确定性基线**绝不误报**（误报率 0 ≤ 5% 目标已满足）；
2. hard 组召回为 0 —— 诚实量化了"无模型分类器"的能力边界；
3. §31.1 的 90% 准确率/100% 召回目标依赖模型 Provider（`customer-provider`/`managed` 模式，§11.4）——接入后重跑本基线；
4. 本基线的四个测试把"差距必须存在"写死（hard 组不得被硬编码掩盖），防止任何人通过调词表把数字做漂亮。

## 后续

- SIQ Connector（D3-D5）就绪后：用 SIQ 6 个真实 Agent 定义扩充语料（真实分布，非合成）；
- 模型 Provider 接入后：同一语料跑模型分类，与基线对照（§11.3 的可追溯重跑）。
