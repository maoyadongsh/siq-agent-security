"""评测集基线（§31.1 验收口径的第一步：先有语料和基线分）。

基线分类器（app/classification.py _baseline_classify）为确定性实现：
- vocab_match 组应全部正确（词表命中的定义使然）；
- P1-10 起 hard 组正样本由 framework 确定性信号（hermes/openclaw/pi/embedded）检出——
  这不是词表放宽，信号来自 Edge 采集的结构化元数据；模型辅助分类（§11）的剩余差距
  是"名称无关键词且无框架信号"的样本（当前语料未覆盖）。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.classification import _baseline_classify
from app.models import AgentAsset

FIXTURES = Path(__file__).parent / "fixtures" / "eval" / "candidates.json"


def _load_samples() -> list[dict]:
    return json.loads(FIXTURES.read_text())["samples"]


def _asset(sample: dict) -> AgentAsset:
    """按语料标注的 framework 构造资产（语料无 framework 信息的样本按 unknown 处理）。"""
    return AgentAsset(
        tenant_id="tnt-A",
        name=sample["name"],
        framework=sample.get("framework") or "unknown",
        status="candidate",
    )


def _classify_positive(sample: dict) -> bool:
    output = _baseline_classify(_asset(sample))
    return bool(output.get("is_agent_candidate"))


def test_vocab_match_positive_recall_is_full():
    """词表命中的正样本：基线必须 100% 召回（确定性实现）。"""
    positives = [s for s in _load_samples() if s["label"] == "positive" and s["group"] == "vocab_match"]
    assert positives, "fixture 缺 vocab_match 正样本"
    hits = [s for s in positives if _classify_positive(s)]
    assert len(hits) == len(positives), f"vocab 正样本漏检: {[s['name'] for s in positives if s not in hits]}"


def test_vocab_match_negative_precision_is_full():
    """词表组的负样本：基线不得误报为智能体。"""
    negatives = [s for s in _load_samples() if s["label"] == "negative" and s["group"] == "vocab_match"]
    assert negatives, "fixture 缺 vocab_match 负样本"
    false_positives = [s for s in negatives if _classify_positive(s)]
    assert not false_positives, f"vocab 负样本误报: {[s['name'] for s in false_positives]}"


def test_hard_group_detected_via_framework_signal():
    """hard 组正样本（名称无关键词、framework=hermes）由 P1-10 框架信号检出。

    负样本（framework=none）不得误报——检出只能来自确定性信号，不允许靠放宽词表做高数字。
    """
    hard_positives = [s for s in _load_samples() if s["label"] == "positive" and s["group"] == "hard"]
    hard_negatives = [s for s in _load_samples() if s["label"] == "negative" and s["group"] == "hard"]
    hits = [s for s in hard_positives if _classify_positive(s)]
    false_positives = [s for s in hard_negatives if _classify_positive(s)]
    assert len(hits) == len(hard_positives), (
        f"hard 正样本应被框架信号检出: {[s['name'] for s in hard_positives if s not in hits]}"
    )
    assert not false_positives


def test_eval_report_written_with_current_scores():
    """跑分报告落盘（docs/eval-baseline.md 的数字与此测试同步生成）。"""
    samples = _load_samples()
    positives = [s for s in samples if s["label"] == "positive"]
    negatives = [s for s in samples if s["label"] == "negative"]
    tp = len([s for s in positives if _classify_positive(s)])
    fp = len([s for s in negatives if _classify_positive(s)])
    report = {
        "schema_version": "siq.eval.report.v1",
        "classifier": "baseline",
        "total": len(samples),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "recall_positive": round(tp / len(positives), 3),
        "false_positive_rate": round(fp / len(negatives), 3),
        "gap_note": "P1-10 起 hard 组由 framework 确定性信号检出；模型辅助（§11）的剩余差距为"
        "无名称关键词且无框架信号的样本（当前语料未覆盖）",
    }
    out = FIXTURES.parent / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    assert report["recall_positive"] >= 0.4, "基线召回异常低于预期"
    assert report["false_positive_rate"] == 0.0
