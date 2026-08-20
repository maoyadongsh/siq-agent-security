"""威胁检测基线（docs/detection-baseline.md 的量化数字由本文件生成，同步 CI 回归）。

与 test_threat_analysis.py 的关系：那边是"每条规则至少一正一负"的单元测试，
证明规则本身可命中/不误命中；本文件是独立语料驱动的基线评测，回答"把这些规则
作为一个整体扫描一批更接近真实文件的样本，召回率/误报率是多少"——方法论对齐
test_eval_baseline.py（同一仓库对分类器的诚实基线做法），只是评测对象换成
威胁检测引擎。

语料定义与设计取舍见 fixtures/threat/corpus.json 的 "labeling" 字段。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from app.threat_analysis import analyze

FIXTURES = Path(__file__).parent / "fixtures" / "threat" / "corpus.json"


def _load_samples() -> list[dict]:
    return json.loads(FIXTURES.read_text())["samples"]


def _rule_ids(sample: dict) -> set[str]:
    result = analyze(sample["content"].encode(), filename=sample.get("filename"))
    return {m.rule_id for m in result.matches}


def test_corpus_has_at_least_20_malicious_samples_covering_all_categories():
    """基线的最低语料规模门槛：防止未来语料被悄悄削薄导致数字失去意义。"""
    samples = _load_samples()
    malicious = [s for s in samples if s["label"] == "malicious"]
    assert len(malicious) >= 20, f"恶意语料样本数不足 20: {len(malicious)}"
    categories = {s["category"] for s in malicious}
    assert categories == {
        "download-exec",
        "credential-access",
        "persistence",
        "obfuscation",
        "network",
        "prompt-injection",
        "python-dangerous",
    }, f"恶意语料类别覆盖不全: {sorted(categories)}"


def test_malicious_corpus_full_recall_per_sample():
    """每条恶意样本必须命中其标注的 rule_id（逐样本断言，定位到具体失败样本而非只报总分）。"""
    malicious = [s for s in _load_samples() if s["label"] == "malicious"]
    missed = [s["id"] for s in malicious if s["rule_id"] not in _rule_ids(s)]
    assert not missed, f"以下恶意样本未被对应规则命中（漏报回归）: {missed}"


def test_benign_corpus_zero_surprise_false_positives():
    """benign 组样本必须零命中；benign_known_fp 组是已登记的已知限制，单独校验而非静默排除。"""
    samples = _load_samples()
    benign = [s for s in samples if s["label"] == "benign"]
    assert benign, "fixture 缺 benign 样本"
    surprises = {s["id"]: _rule_ids(s) for s in benign if _rule_ids(s)}
    assert not surprises, f"benign 样本出现意外命中（新增误报，需要人工核实规则是否过宽）: {surprises}"

    known_fp = [s for s in samples if s["label"] == "benign_known_fp"]
    for s in known_fp:
        hits = _rule_ids(s)
        assert s["rule_id"] in hits, (
            f"已知误报样本 {s['id']} 未再命中 {s['rule_id']}——"
            "如果规则已收窄修复，请从 corpus.json 移除该样本并更新 docs/detection-baseline.md"
        )


def test_detection_baseline_report_written_with_current_scores():
    """跑分报告落盘（docs/detection-baseline.md 的数字与此测试同步生成）。"""
    samples = _load_samples()
    malicious = [s for s in samples if s["label"] == "malicious"]
    benign = [s for s in samples if s["label"] == "benign"]
    known_fp = [s for s in samples if s["label"] == "benign_known_fp"]

    by_category: dict[str, list[dict]] = defaultdict(list)
    for s in malicious:
        by_category[s["category"]].append(s)

    recall_by_category = {}
    for category, items in sorted(by_category.items()):
        hits = sum(1 for s in items if s["rule_id"] in _rule_ids(s))
        recall_by_category[category] = round(hits / len(items), 3)

    total_hits = sum(1 for s in malicious if s["rule_id"] in _rule_ids(s))
    benign_fp_count = sum(1 for s in benign if _rule_ids(s))
    known_fp_hits = sum(1 for s in known_fp if s.get("rule_id") in _rule_ids(s))

    report = {
        "schema_version": "siq.threat.baseline.report.v1",
        "analyzer": "app.threat_analysis.analyze",
        "malicious_total": len(malicious),
        "benign_total": len(benign),
        "known_fp_total": len(known_fp),
        "recall_overall": round(total_hits / len(malicious), 3),
        "recall_by_category": recall_by_category,
        "surprise_false_positive_rate": round(benign_fp_count / len(benign), 3),
        "known_false_positive_recall": round(known_fp_hits / len(known_fp), 3) if known_fp else None,
        "gap_note": "语料为逐规则构造样本，量化的是'规则能否在更接近真实文件的上下文中稳定命中'，"
        "不是野外恶意样本的统计分布；已知限制（如 threat-net-hardcoded-c2 对 socket.bind 的过泛匹配）"
        "单独统计，不计入 surprise_false_positive_rate。",
    }
    out = FIXTURES.parent / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    assert report["recall_overall"] == 1.0, "基线召回不足，规则可能被意外破坏"
    assert report["surprise_false_positive_rate"] == 0.0, "出现未登记的新误报"
    assert all(v == 1.0 for v in recall_by_category.values()), f"存在类别召回不足: {recall_by_category}"
