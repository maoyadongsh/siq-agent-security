"""Published evidence must reject tampering even after an unsigned hash is updated."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from verify_native_business_evidence import (
    canonical,
    native_grant_digest,
    validators,
    verify,
    verify_context_revocations,
    verify_grant_transition,
    verify_live_grants,
)

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


def context_revocation_fixture():
    key, sign, *_ = grant_transition_fixture()
    context_id = "sec-" + "a" * 32
    # The outer verifier authenticates the contexts first; this helper only
    # exercises the exact binding of a tombstone to that verified inventory.
    contexts = {context_id: {"signature": "a" * 128, "issued_at": "2026-10-08T05:00:00Z"}}
    tombstone = sign({
        "schema_version": "skill-execution-context-revocation/v2",
        "context_id": context_id, "issuer_id": "local-admin",
        "revoked_at": "2026-10-08T05:00:01Z", "context_signature": "a" * 128,
        "signing_schema": "local_canonical/v1",
    })
    schema = validators(ROOT / "packages/contracts")["skill-execution-context-revocation.v2.schema.json"]
    return key, sign, contexts, tombstone, schema


def test_signed_context_revocation_is_bound_to_exact_context():
    key, _, contexts, tombstone, schema = context_revocation_fixture()
    verify_context_revocations(canonical({tombstone["context_id"]: tombstone}), key, contexts, 1, schema)


def test_recomputed_tombstone_artifact_hash_cannot_hide_changed_revocation():
    key, _, contexts, tombstone, schema = context_revocation_fixture()
    tombstone["revoked_at"] = "2026-10-08T05:00:02Z"
    with pytest.raises(InvalidSignature):
        verify_context_revocations(canonical({tombstone["context_id"]: tombstone}), key, contexts, 1, schema)


@pytest.mark.parametrize("change,reason", [
    ({"context_id": "sec-" + "b" * 32}, "context_revocation_identity_mismatch"),
    ({"context_signature": "b" * 128}, "context_revocation_signature_binding_mismatch"),
    ({"revoked_at": "2026-10-08T04:59:59Z"}, "context_revocation_time_invalid"),
])
def test_validly_signed_wrong_tombstone_cannot_revoke_another_context(change, reason):
    key, sign, contexts, tombstone, schema = context_revocation_fixture()
    tombstone = sign({**tombstone, **change})
    with pytest.raises(ValueError, match=reason):
        verify_context_revocations(canonical({tombstone["context_id"]: tombstone}), key, contexts, 1, schema)


def test_context_revocation_count_cannot_be_boolean():
    key, _, contexts, tombstone, schema = context_revocation_fixture()
    with pytest.raises(ValueError, match="context_revocation_count_mismatch"):
        verify_context_revocations(canonical({tombstone["context_id"]: tombstone}), key, contexts, True, schema)


def live_grant_fixture():
    key, sign, snapshots, *_ = grant_transition_fixture()
    live = {"skill": snapshots["skill_before"], "agent": snapshots["agent_baseline"]}
    binding = {"skill": "skill", "agent": "agent"}
    authorities = {role: {"grant_id": binding[role], "grant_digest": native_grant_digest(grant)}
                   for role, grant in live.items()}
    contexts = {"context": {"authority": authorities["skill"], "agent_authority": authorities["agent"]}}
    return key, sign, live, binding, contexts


def test_signed_live_grants_are_bound_to_context_authorities():
    key, _, live, binding, contexts = live_grant_fixture()
    verify_live_grants(canonical(live), key, binding, contexts, {})


@pytest.mark.parametrize("status", ["pending_approval", "revoked"])
def test_signed_inactive_grant_cannot_be_presented_as_live(status):
    key, sign, live, binding, contexts = live_grant_fixture()
    live["skill"] = sign({**live["skill"], "status": status})
    with pytest.raises(ValueError, match="live_grant_status_invalid"):
        verify_live_grants(canonical(live), key, binding, contexts, {})


def test_valid_live_grants_cannot_be_substituted_across_contexts():
    key, _, live, binding, contexts = live_grant_fixture()
    contexts["context"]["authority"]["grant_id"] = "other"
    with pytest.raises(ValueError, match="live_grant_context_binding_mismatch"):
        verify_live_grants(canonical(live), key, binding, contexts, {})


def test_live_grant_digest_binds_exact_signed_permissions():
    key, sign, live, binding, contexts = live_grant_fixture()
    live["skill"] = sign({**live["skill"], "facts": []})
    with pytest.raises(ValueError, match="live_grant_context_binding_mismatch"):
        verify_live_grants(canonical(live), key, binding, contexts, {})


def test_no_skill_receipt_still_requires_matching_agent_authority():
    key, _, live, binding, contexts = live_grant_fixture()
    receipts = {"row": {"native_invocation": {
        "contexts": [], "no_skill": True,
        "agent_authority": {"grant_id": "agent", "grant_digest": "0" * 64},
    }}}
    with pytest.raises(ValueError, match="live_grant_receipt_binding_mismatch"):
        verify_live_grants(canonical(live), key, binding, contexts, receipts)


def test_native_grant_digest_matches_go_generic_float_numbers():
    grant = {"desired_policy_ref": {"version": 2}, "status": "approved"}
    expected = hashlib.sha256(b'{"desired_policy_ref":{"version":2.0},"status":"approved"}').hexdigest()
    assert native_grant_digest(grant) == expected
    assert hashlib.sha256(canonical(grant)).hexdigest() != expected


CONTEXT_REPORT = ROOT / "docs/development/evidence/optimization-20261007/native-context-boundary-v855-v859.json"


def test_real_context_revocation_bundle_includes_partial_case_without_claiming_success():
    result = verify(CONTEXT_REPORT, ROOT / "packages/contracts")
    assert result["receipts"] == 10 and result["signed_contexts"] == 3
    assert result["signed_context_revocations"] == 1 and result["signed_live_grants"] == 2
    assert result["case_decision_bindings"] == 4
    assert not result["post_revocation_execution_reobserved"]
    document = json.loads(CONTEXT_REPORT.read_text())
    assert document["accepted_cases"] == ["v855", "v856", "v858"]
    assert not document["supplementary_v859"]["passed"]


def test_real_context_revocation_tampering_fails_after_artifact_rehash(tmp_path):
    report, doc = copy_bundle(tmp_path, CONTEXT_REPORT)
    path = tmp_path / doc["artifacts"]["context_revocations"]["file"]
    tombstones = json.loads(path.read_text())
    next(iter(tombstones.values()))["context_signature"] = "0" * 128
    replace_artifact(report, doc, "context_revocations", canonical(tombstones))
    with pytest.raises(InvalidSignature):
        verify(report, ROOT / "packages/contracts")


@pytest.mark.parametrize("binding,reason", [
    ("context_revocation_count", "context_revocation_binding_missing"),
    ("live_grant_ids", "live_grant_binding_missing"),
])
def test_optional_context_artifacts_must_not_be_silently_ignored(tmp_path, binding, reason):
    report, doc = copy_bundle(tmp_path, CONTEXT_REPORT)
    del doc["verification"][binding]
    report.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match=reason):
        verify(report, ROOT / "packages/contracts")
