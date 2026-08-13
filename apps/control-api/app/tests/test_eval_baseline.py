"""评测集基线（§31.1 验收口径的第一步：先有语料和基线分）。

基线分类器（app/classification.py _baseline_classify）为确定性词表实现：
- vocab_match 组应全部正确（词表命中的定义使然）；
- hard 组预期 miss——量化"确定性规则与模型辅助之间的差距"，
  正是设计文档 §11 模型辅助分类存在的理由（90% 准确率目标依赖模型 Provider，Phase 1 后接入）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.classification import _baseline_classify
from app.models import AgentAsset

FIXTURES = Path(__file__).parent / "fixtures" / "eval" / "candidates.json"


def _load_samples() -> list[dict]:
    return json.loads(FIXTURES.read_text())["samples"]


def _asset(name: str) -> AgentAsset:
    return AgentAsset(tenant_id="tnt-A", name=name, framework="hermes", status="candidate")


def _classify_positive(name: str) -> bool:
    output = _baseline_classify(_asset(name))
    return bool(output.get("is_agent_candidate"))


def test_vocab_match_positive_recall_is_full():
    """词表命中的正样本：基线必须 100% 召回（确定性实现）。"""
    positives = [s for s in _load_samples() if s["label"] == "positive" and s["group"] == "vocab_match"]
    assert positives, "fixture 缺 vocab_match 正样本"
    hits = [s for s in positives if _classify_positive(s["name"])]
    assert len(hits) == len(positives), f"vocab 正样本漏检: {[s['name'] for s in positives if s not in hits]}"


def test_vocab_match_negative_precision_is_full():
    """词表组的负样本：基线不得误报为智能体。"""
    negatives = [s for s in _load_samples() if s["label"] == "negative" and s["group"] == "vocab_match"]
    assert negatives, "fixture 缺 vocab_match 负样本"
    false_positives = [s for s in negatives if _classify_positive(s["name"])]
    assert not false_positives, f"vocab 负样本误报: {[s['name'] for s in false_positives]}"


def test_hard_group_documents_model_gap():
    """hard 组（无关键词）预期基线 miss——量化模型辅助的增量价值，禁止悄悄放宽基线阈值来掩盖。"""
    hard_positives = [s for s in _load_samples() if s["label"] == "positive" and s["group"] == "hard"]
    hard_negatives = [s for s in _load_samples() if s["label"] == "negative" and s["group"] == "hard"]
    hits = [s for s in hard_positives if _classify_positive(s["name"])]
    false_positives = [s for s in hard_negatives if _classify_positive(s["name"])]
    # 基线对 hard 正样本的命中数必须低于正样本总数（证明差距存在且未被硬编码掩盖）
    assert len(hits) < len(hard_positives), "hard 正样本被全命中，语料需要更多无关键词样本"
    # hard 负样本不得误报（词表无对应关键词是保证）
    assert not false_positives


def test_eval_report_written_with_current_scores():
    """跑分报告落盘（docs/eval-baseline.md 的数字与此测试同步生成）。"""
    samples = _load_samples()
    positives = [s for s in samples if s["label"] == "positive"]
    negatives = [s for s in samples if s["label"] == "negative"]
    tp = len([s for s in positives if _classify_positive(s["name"])])
    fp = len([s for s in negatives if _classify_positive(s["name"])])
    report = {
        "schema_version": "siq.eval.report.v1",
        "classifier": "baseline",
        "total": len(samples),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "recall_positive": round(tp / len(positives), 3),
        "false_positive_rate": round(fp / len(negatives), 3),
        "gap_note": "hard 组（无关键词）召回为 0——模型辅助分类（§11）接入后重跑本基线",
    }
    out = FIXTURES.parent / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    assert report["recall_positive"] >= 0.4, "基线召回异常低于预期"
    assert report["false_positive_rate"] == 0.0
