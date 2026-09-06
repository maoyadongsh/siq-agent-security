"""DEV06-A: field-level match oracle for the shared regex rulepack layer.

The frozen fixture is produced by scripts/gen_threat_match_oracle_v1.py.
This test asserts the live Python analyzer still matches every frozen field
(content_sha256, detected_type, labelled line/excerpt/excerpt_sha256) and that
AST-only rule_ids stay outside the shared contract.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.threat_analysis import analyze

FIXTURES = Path(__file__).parent / "fixtures" / "threat"
CORPUS = FIXTURES / "corpus.json"
ORACLE = FIXTURES / "match_oracle_v1.json"

PYTHON_ONLY = {
    "threat-py-os-system",
    "threat-py-subprocess-shell",
    "threat-py-ctypes-load",
    "threat-py-syntax-parse-failed",
}


def _load_corpus_by_id() -> dict[str, dict]:
    return {s["id"]: s for s in json.loads(CORPUS.read_text(encoding="utf-8"))["samples"]}


def _load_oracle() -> dict:
    return json.loads(ORACLE.read_text(encoding="utf-8"))


def test_oracle_schema_and_coverage():
    oracle = _load_oracle()
    assert oracle["schema"] == "threat_match_oracle/v1"
    assert set(oracle["python_only_rule_ids"]) == PYTHON_ONLY
    corpus = _load_corpus_by_id()
    vector_ids = {v["sample_id"] for v in oracle["vectors"]}
    assert vector_ids == set(corpus), "oracle vectors must cover every corpus sample"


def test_python_matches_oracle_fields():
    oracle = _load_oracle()
    corpus = _load_corpus_by_id()
    for vec in oracle["vectors"]:
        sample = corpus[vec["sample_id"]]
        content = sample["content"].encode("utf-8")
        result = analyze(content, filename=sample.get("filename"))
        assert hashlib.sha256(content).hexdigest() == vec["content_sha256"], vec["sample_id"]
        assert result.detected_type == vec["detected_type"], vec["sample_id"]

        shared = {m.rule_id: m for m in result.matches if m.rule_id not in PYTHON_ONLY}
        python_only = {m.rule_id for m in result.matches if m.rule_id in PYTHON_ONLY}
        assert sorted(shared) == vec["shared_rule_ids"], vec["sample_id"]
        assert sorted(python_only) == vec["python_only_rule_ids"], vec["sample_id"]

        expected = vec["expected_shared_match"]
        if expected is None:
            if sample["label"] in ("malicious", "benign_known_fp"):
                raise AssertionError(f"{vec['sample_id']}: labelled sample missing expected_shared_match")
            continue
        got = shared.get(expected["rule_id"])
        assert got is not None, f"{vec['sample_id']}: missing {expected['rule_id']}"
        assert got.line == expected["line"], vec["sample_id"]
        assert got.excerpt == expected["excerpt"], vec["sample_id"]
        assert got.excerpt_sha256 == expected["excerpt_sha256"], vec["sample_id"]
        assert got.severity == expected["severity"], vec["sample_id"]
        assert got.confidence == expected["confidence"], vec["sample_id"]


def test_benign_vectors_have_empty_shared_hits():
    oracle = _load_oracle()
    for vec in oracle["vectors"]:
        if vec["label"] != "benign":
            continue
        assert vec["expected_shared_match"] is None
        assert vec["shared_rule_ids"] == []
