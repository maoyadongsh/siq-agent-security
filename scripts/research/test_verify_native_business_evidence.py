"""Published evidence must reject tampering even after an unsigned hash is updated."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from verify_native_business_evidence import canonical, verify, verify_grant_transition

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/development/evidence/optimization-20261007/native-working-business-v819-v827.json"
GRANT_REPORT = ROOT / "docs/development/evidence/optimization-20261007/native-skill-grant-effect-v853-v854.json"


def copy_bundle(tmp_path: Path, source: Path = REPORT) -> tuple[Path, dict]:
    doc = json.loads(source.read_text())
    for entry in doc["artifacts"].values():
        (tmp_path / entry["file"]).write_bytes((source.parent / entry["file"]).read_bytes())
    report = tmp_path / source.name
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


def grant_transition_fixture():
    key = Ed25519PrivateKey.generate()

    def sign(value):
        body = {k: v for k, v in value.items() if k != "signature"}
        return {**body, "signature": key.sign(canonical(body)).hex()}

    before = {"grant_id": "skill", "status": "approved", "facts": ["narrow-write"]}
    snapshots = {
        "skill_before": sign(before),
        "skill_after": sign({**before, "status": "revoked"}),
        "agent_baseline": sign({"grant_id": "agent", "status": "deployed"}),
    }
    binding = {"skill_grant_id": "skill", "agent_grant_id": "agent"}
    cases = {"request": {"receipt_hash": "receipt"}}
    receipts = {"receipt": {"native_invocation": {
        "agent_authority": {"grant_id": "agent"},
        "contexts": [{"authority": {"grant_id": "skill"}}],
    }}}
    return key.public_key(), sign, snapshots, binding, cases, receipts


@pytest.mark.parametrize("status", ["approved", "deployed", "effective"])
def test_signed_grant_transition_accepts_live_agent_states(status):
    key, sign, snapshots, binding, cases, receipts = grant_transition_fixture()
    snapshots["agent_baseline"] = sign({"grant_id": "agent", "status": status})
    verify_grant_transition(canonical(snapshots), key, binding, cases, receipts)


def test_grant_tampering_cannot_be_hidden_by_unsigned_artifact_hash():
    key, _, snapshots, binding, cases, receipts = grant_transition_fixture()
    snapshots["skill_after"]["status"] = "approved"
    with pytest.raises(InvalidSignature):
        verify_grant_transition(canonical(snapshots), key, binding, cases, receipts)


@pytest.mark.parametrize("change,reason", [
    ({"grant_id": "another-skill"}, "grant_transition_identity_mismatch"),
    ({"status": "approved"}, "grant_transition_status_mismatch"),
    ({"facts": ["broader-write"]}, "grant_transition_permissions_changed"),
])
def test_validly_signed_other_grant_state_cannot_replace_revocation(change, reason):
    key, sign, snapshots, binding, cases, receipts = grant_transition_fixture()
    snapshots["skill_after"] = sign({**snapshots["skill_after"], **change})
    with pytest.raises(ValueError, match=reason):
        verify_grant_transition(canonical(snapshots), key, binding, cases, receipts)


def test_grant_transition_must_belong_to_actual_receipt_context():
    key, _, snapshots, binding, cases, receipts = grant_transition_fixture()
    receipts["receipt"]["native_invocation"]["contexts"][0]["authority"]["grant_id"] = "other"
    with pytest.raises(ValueError, match="grant_transition_case_binding_mismatch"):
        verify_grant_transition(canonical(snapshots), key, binding, cases, receipts)


def test_real_grant_effect_bundle_verifies_signed_states():
    result = verify(GRANT_REPORT, ROOT / "packages/contracts")
    assert result["receipts"] == 5 and result["signed_contexts"] == 2
    assert result["signed_grant_snapshots"] == 3
    assert not result["grant_transition_order_reobserved"]


def test_real_grant_snapshot_tampering_fails_after_artifact_rehash(tmp_path):
    report, doc = copy_bundle(tmp_path, GRANT_REPORT)
    path = tmp_path / doc["artifacts"]["grant_snapshots"]["file"]
    snapshots = json.loads(path.read_text())
    snapshots["skill_after"]["status"] = "approved"
    replace_artifact(report, doc, "grant_snapshots", canonical(snapshots))
    with pytest.raises(InvalidSignature):
        verify(report, ROOT / "packages/contracts")


def test_grant_artifact_without_binding_is_not_silently_ignored(tmp_path):
    report, doc = copy_bundle(tmp_path, GRANT_REPORT)
    del doc["verification"]["grant_transition"]
    report.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="grant_transition_binding_missing"):
        verify(report, ROOT / "packages/contracts")
