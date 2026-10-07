"""Published evidence must reject tampering even after an unsigned hash is updated."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from verify_native_business_evidence import canonical, verify

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/development/evidence/optimization-20261007/native-working-business-v819-v827.json"


def copy_bundle(tmp_path: Path) -> tuple[Path, dict]:
    doc = json.loads(REPORT.read_text())
    for entry in doc["artifacts"].values():
        (tmp_path / entry["file"]).write_bytes((REPORT.parent / entry["file"]).read_bytes())
    report = tmp_path / REPORT.name
    report.write_text(json.dumps(doc))
    return report, doc


def replace_artifact(report: Path, doc: dict, kind: str, raw: bytes) -> None:
    entry = doc["artifacts"][kind]
    (report.parent / entry["file"]).write_bytes(raw)
    entry["sha256"] = hashlib.sha256(raw).hexdigest()
    report.write_text(json.dumps(doc))


def test_frozen_published_bundle():
    result = verify(REPORT, ROOT / "packages/contracts")
    assert result["receipts"] == 18
    assert result["signed_contexts"] == result["case_decision_bindings"] == 9
    assert not result["original_filesystem_effects_reobserved"]
    assert not result["current_execution_authorized"]


def test_recomputed_receipt_hash_does_not_hide_tampering(tmp_path):
    report, doc = copy_bundle(tmp_path)
    path = tmp_path / doc["artifacts"]["receipts"]["file"]
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["reason"] += " changed"
    rows[0]["hash"] = hashlib.sha256(canonical({k: v for k, v in rows[0].items() if k not in ("hash", "sig")})).hexdigest()
    replace_artifact(report, doc, "receipts", b"\n".join(canonical(row) for row in rows) + b"\n")
    with pytest.raises(InvalidSignature):
        verify(report, ROOT / "packages/contracts")


def test_recomputed_artifact_hash_does_not_hide_context_tampering(tmp_path):
    report, doc = copy_bundle(tmp_path)
    contexts = json.loads((tmp_path / doc["artifacts"]["contexts"]["file"]).read_text())
    for context in contexts.values():
        context["authority"]["grant_digest"] = "a" * 64
    replace_artifact(report, doc, "contexts", canonical(contexts))
    with pytest.raises(InvalidSignature):
        verify(report, ROOT / "packages/contracts")


def test_valid_context_from_another_request_cannot_be_substituted(tmp_path):
    report, doc = copy_bundle(tmp_path)
    contexts = json.loads((tmp_path / doc["artifacts"]["contexts"]["file"]).read_text())
    names = list(contexts)
    contexts[names[0]], contexts[names[1]] = contexts[names[1]], contexts[names[0]]
    replace_artifact(report, doc, "contexts", canonical(contexts))
    with pytest.raises(ValueError, match="context_id_mismatch"):
        verify(report, ROOT / "packages/contracts")


def test_repeating_a_case_cannot_inflate_independent_request_count(tmp_path):
    report, doc = copy_bundle(tmp_path)
    cases = doc["verification"]["cases"]
    cases["duplicate"] = copy.deepcopy(next(iter(cases.values())))
    report.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="duplicate_case_receipt"):
        verify(report, ROOT / "packages/contracts")
