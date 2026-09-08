"""Effect structure is separate from observer authorization and correlation."""
import copy
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from jsonschema import Draft202012Validator, FormatChecker


def validator():
    path = Path(__file__).parents[4] / "packages/contracts/effect-evidence.v1.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def record():
    # Structural fixture only; the placeholder signature has no signing authority.
    return {
        "schema_version": "effect-evidence/v1", "effect_evidence_id": "eff-1",
        "action_id": "action-1", "decision_receipt_id": "rcp-1",
        "effect_type": "file.write", "resource_ref": "filesystem:sha256:" + "b" * 64,
        "execution_state": "completed",
        "source": {"type": "host_observer", "source_id": "observer-1", "independence": "host_independent"},
        "coverage": "partial", "result": "expected", "evidence_digest": "a" * 64,
        "observed_at": "2026-09-08T01:00:00Z", "signing_schema": "local_canonical/v1",
        "signature": "0" * 128,
    }


def test_required_correlation_and_closed_record():
    v = validator()
    good = record()
    v.validate(good)
    for field in good:
        missing = copy.deepcopy(good)
        del missing[field]
        assert list(v.iter_errors(missing)), field
    for field, value in [("observed_at", "yesterday"), ("evidence_digest", "plaintext"),
                         ("completed", True), ("signature", "unsigned")]:
        assert list(v.iter_errors({**good, field: value})), field


@pytest.mark.parametrize("source_type,independence", [("tool_report", "self_reported"), ("unknown", "unknown")])
def test_self_report_cannot_claim_verified_effect(source_type, independence):
    v = validator()
    good = record()
    good.update(source={"type": source_type, "source_id": "source-1", "independence": independence},
                coverage="unknown", result="unknown")
    v.validate(good)
    for level in ["host_independent", "external_independent"]:
        forged = copy.deepcopy(good)
        forged["source"]["independence"] = level
        assert list(v.iter_errors(forged))
    for field, value in [("coverage", "full"), ("result", "expected")]:
        assert list(v.iter_errors({**good, field: value}))


def test_shared_signed_effect_sample():
    path = Path(__file__).parents[4] / "apps/agentshield/testdata/contracts/effect-evidence.sample.json"
    sample = json.loads(path.read_text())
    validator().validate(sample)
    signature = bytes.fromhex(sample.pop("signature"))
    canonical = json.dumps(sample, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    key = Ed25519PrivateKey.from_private_bytes(bytes([7]) * 32)
    key.public_key().verify(signature, canonical)
    assert key.sign(canonical) == signature


def test_atomic_state_envelope_requires_incident_and_request_binding():
    root = Path(__file__).parents[4] / "packages/contracts"
    schema = json.loads((root / "effect-evidence-record.v1.schema.json").read_text())
    # Resolve the committed local contract without network access.
    schema["properties"]["evidence"] = json.loads((root / "effect-evidence.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    good = {"schema_version": "effect-evidence-record/v1", "evidence": record(),
            "finding_code": "", "request_digest": "c" * 64, "task_id": "task-1",
            "signing_schema": "local_canonical/v1", "signature": "0" * 128}
    v.validate(good)
    for field in ["finding_code", "request_digest", "task_id", "evidence"]:
        bad = dict(good)
        del bad[field]
        assert list(v.iter_errors(bad))
    assert list(v.iter_errors({**good, "finding_code": "completed"}))


def test_observer_submission_and_management_contracts():
    root = Path(__file__).parents[4] / "packages/contracts"
    v = Draft202012Validator(json.loads((root / "effect-observer-request.v1.schema.json").read_text()))
    good = {"source": record()["source"], "scope": {"platform": "hermes", "session_id": "s1",
            "agent_id": "a1", "task_id": "t1"}, "expires_in": 60}
    v.validate(good)
    for ttl in [0, 3601]:
        assert list(v.iter_errors({**good, "expires_in": ttl}))
    forged = copy.deepcopy(good)
    forged["source"]["independence"] = "external_independent"
    assert list(v.iter_errors(forged))
    assert list(v.iter_errors({**good, "scope": {"task_id": "t1"}}))
    submit = Draft202012Validator(json.loads((root / "effect-evidence-submit.v1.schema.json").read_text()))
    submit.validate({**record(), "signature": ""})
    assert list(submit.iter_errors(record()))


def test_file_material_retains_only_bounded_metadata():
    root = Path(__file__).parents[4] / "packages/contracts"
    schema = json.loads((root / "file-observation.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    absent = {"resource_ref": "filesystem:sha256:" + "a" * 64, "exists": False,
              "digest": "", "size": 0, "mtime": "", "captured_at": "2026-09-08T01:00:00Z"}
    present = {**absent, "exists": True, "digest": "b" * 64, "size": 4,
               "mtime": "2026-09-08T01:00:01Z", "captured_at": "2026-09-08T01:00:02Z"}
    good = {"before": absent, "after": present, "expected_digest": "b" * 64,
            "execution_state": "completed", "result": "expected"}
    v.validate(good)
    for field, value in [("path", "/private/report"), ("content", "secret"),
                         ("size", 16777217), ("digest", "plaintext")]:
        assert list(v.iter_errors({**good, "after": {**present, field: value}}))
    assert list(v.iter_errors({**good, "before": {**absent, "size": 1}}))


def test_file_lifecycle_cannot_upload_fake_snapshots():
    root = Path(__file__).parents[4] / "packages/contracts"
    v = Draft202012Validator(json.loads((root / "file-observation-begin.v1.schema.json").read_text()))
    good = {"observation_id": "file-1", "action_id": "action-1", "decision_receipt_id": "rcp-1",
            "path": "/work/report", "expected_digest": "a" * 64, "max_bytes": 1024}
    v.validate(good)
    for field, value in [("before", {}), ("source", {}), ("max_bytes", 16777217), ("observation_id", "../file")]:
        assert list(v.iter_errors({**good, field: value}))
    finish = Draft202012Validator(json.loads((root / "file-observation-finish.v1.schema.json").read_text()))
    finish.validate({"path": "/work/report"})
    assert list(finish.iter_errors({"path": "/work/report", "after": {"exists": True}}))


def test_signed_intent_effect_requirements_are_explicit_and_optional():
    root = Path(__file__).parents[4]
    schema = json.loads((root / "packages/contracts/intent-contract.v3.schema.json").read_text())
    v = Draft202012Validator(schema)
    sample = json.loads((root / "apps/agentshield/testdata/contracts/intent-contract.v3.sample.json").read_text())
    v.validate(sample)  # historical V3 omission remains valid
    req = {"requirement_id": "write-report", "effect_type": "file.write",
           "resource_ref": "filesystem:sha256:" + "a" * 64, "expected_digest": "b" * 64,
           "minimum_independence": "host_independent", "minimum_coverage": "partial"}
    v.validate({**sample, "effect_requirements": [req]})
    assert list(v.iter_errors({**sample, "effect_requirements": None}))
    for field in req:
        missing = dict(req)
        del missing[field]
        assert list(v.iter_errors({**sample, "effect_requirements": [missing]}))


def test_completion_response_has_no_caller_writable_completed_flag():
    path = Path(__file__).parents[4] / "packages/contracts/completion-status.v1.schema.json"
    schema = json.loads(path.read_text())
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    good = {"schema_version": "completion-status/v1", "task_id": "task-1", "status": "incomplete",
            "reason_code": "effect_evidence_missing", "requirements": [{"requirement_id": "write-report",
            "status": "incomplete", "reason_code": "effect_evidence_missing", "evidence_ids": []}], "incident_ids": []}
    v.validate(good)
    assert list(v.iter_errors({**good, "completed": True}))
    assert list(v.iter_errors({**good, "status": "success"}))


def test_network_material_keeps_server_event_without_request_plaintext():
    root = Path(__file__).parents[4] / "packages/contracts"
    schema = json.loads((root / "network-observation.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    received = {"scheme": "http", "host": "127.0.0.1", "port": "12345",
                "resolved_target": "127.0.0.1:12345", "request_id": "oracle-1-1",
                "request_digest": "a" * 64, "received_at": "2026-09-08T01:00:00Z"}
    good = {"requested_scheme": "http", "requested_host": "localhost", "requested_port": "12344", "received": received}
    v.validate(good)
    for field, value in [("body", "secret"), ("url", "http://private/?token=secret"), ("host", "remote.example")]:
        assert list(v.iter_errors({**good, "received": {**received, field: value}}))


def test_network_submission_binds_material_without_caller_authority():
    root = Path(__file__).parents[4] / "packages/contracts"
    schema = json.loads((root / "network-observation-submit.v1.schema.json").read_text())
    # Resolve the local contract without allowing remote retrieval in this test.
    schema["properties"]["observation"] = json.loads((root / "network-observation.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    v = Draft202012Validator(schema)
    good = {"observation_id": "network-1", "action_id": "action-1", "decision_receipt_id": "rcp-1",
            "observation": {"requested_scheme": "http", "requested_host": "localhost", "requested_port": "12345",
            "received": {"scheme": "http", "host": "127.0.0.1", "port": "12345",
            "resolved_target": "127.0.0.1:12345", "request_id": "oracle-1-1",
            "request_digest": "a" * 64, "received_at": "2026-09-08T01:00:00Z"}}}
    v.validate(good)
    for field, value in [("source", {}), ("authorized", True), ("scope", {}), ("observation_id", "../escape")]:
        assert list(v.iter_errors({**good, field: value}))
    for field in good:
        missing = dict(good)
        del missing[field]
        assert list(v.iter_errors(missing))


def test_network_completion_requires_endpoint_and_external_observer():
    root = Path(__file__).parents[4] / "packages/contracts"
    req = {"requirement_id": "receive", "effect_type": "network.request",
           "resource_ref": "network:sha256:" + "a" * 64, "expected_digest": "b" * 64,
           "minimum_independence": "external_independent", "minimum_coverage": "partial",
           "expected_endpoint": {"scheme": "http", "host": "127.0.0.1", "port": "12345"}}
    intent = json.loads((root / "intent-contract.v3.schema.json").read_text())
    for schema in [json.loads((root / "effect-verification-requirement.v1.schema.json").read_text()),
                   intent["properties"]["effect_requirements"]["items"]]:
        v = Draft202012Validator(schema)
        v.validate(req)  # Runtime additionally checks host digest and port range.
        for field, value in [("expected_endpoint", None), ("minimum_independence", "host_independent"),
                             ("resource_ref", "filesystem:sha256:" + "a" * 64), ("effect_type", "file.write")]:
            assert list(v.iter_errors({**req, field: value}))
        missing = dict(req)
        del missing["expected_endpoint"]
        assert list(v.iter_errors(missing))
