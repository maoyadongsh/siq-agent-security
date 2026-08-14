"""Schema 契约测试（设计文档 §32：JSON Schema 测试）。

对 packages/contracts 的五个 Schema 做最小有效样例 + 无效样例校验，
保证合同事实源与实现方（Control API / Edge / Web types.ts）对齐。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

CONTRACTS = Path(__file__).parents[4] / "packages" / "contracts"

SCHEMAS = {
    "candidate": CONTRACTS / "candidate.schema.json",
    "evidence": CONTRACTS / "evidence.schema.json",
    "permission-fact": CONTRACTS / "permission-fact.schema.json",
    "desired-policy": CONTRACTS / "desired-policy.schema.json",
    "event-envelope": CONTRACTS / "event-envelope.schema.json",
}

VALID_EXAMPLES = {
    "candidate": {
        "candidate_id": "hermes:siq_legal_advisor",
        "source_type": "hermes_profile",
        "source_locator": "hermes://profiles/siq_legal_advisor",
        "discovered_at": "2026-08-13T12:00:00Z",
        "name": "siq_legal_advisor",
        "framework": "hermes",
        "evidence_ids": ["ev-1"],
    },
    "evidence": {
        "evidence_id": "ev-1",
        "source_type": "manifest",
        "source_locator": "profiles/x/config.yaml",
        "observed_at": "2026-08-13T12:00:00Z",
        "collected_at": "2026-08-13T12:00:01Z",
        "collector_id": "edge-1",
        "connector_version": "0.1.0",
        "content_hash": "a" * 64,
        "redaction_profile": "siq.redaction.v1",
        "classification": "internal",
        "signature": "f" * 128,
    },
    "permission-fact": {
        "subject": {"type": "agent_instance", "id": "inst_1"},
        "delegated_user": {"user_id": "u1", "token_ref": "del_1"},
        "domain": "network",
        "action": "http.request",
        "resource": {"type": "endpoint", "value": "api.example.com:443"},
        "effect": "allow",
        "state": "effective",
        "authority": "openshell",
        "evidence_ids": ["ev-1"],
    },
    "desired-policy": {
        "policy_id": "pol-1",
        "selector": {"agent_ids": ["agt_1"]},
        "version": 1,
        "status": "validated",
        "enforcement_mode": "audit_only",
    },
    "event-envelope": {
        "event_id": "evt-1",
        "event_type": "agent.candidate.discovered.v1",
        "occurred_at": "2026-08-13T12:00:00Z",
        "tenant_id": "tnt-1",
        "schema_version": 1,
    },
}


def _validate(name: str, instance: dict) -> list:
    schema = json.loads(SCHEMAS[name].read_text())
    return sorted(Draft7Validator(schema).iter_errors(instance), key=lambda e: str(e.message))


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_loads_and_valid_example_passes(name):
    errors = _validate(name, VALID_EXAMPLES[name])
    assert not errors, f"{name} 最小有效样例被拒绝: {[e.message for e in errors]}"


def test_candidate_rejects_orphan_empty_evidence_ids():
    bad = dict(VALID_EXAMPLES["candidate"])
    bad["evidence_ids"] = []
    assert _validate("candidate", bad), "candidate.evidence_ids 必须至少 1 条（§10.2 合同）"


def test_permission_fact_rejects_unknown_state():
    bad = dict(VALID_EXAMPLES["permission-fact"])
    bad["state"] = "trust_me"
    assert _validate("permission-fact", bad), "state 枚举外值必须拒绝"


def test_desired_policy_rejects_unknown_enforcement_mode():
    bad = dict(VALID_EXAMPLES["desired-policy"])
    bad["enforcement_mode"] = "yolo"
    assert _validate("desired-policy", bad), "enforcement_mode 枚举外值必须拒绝"


def test_desired_policy_rejects_plaintext_secret_field():
    bad = dict(VALID_EXAMPLES["desired-policy"])
    bad["secrets"] = [{"ref": "vault://x", "purpose": "demo", "value": "plaintext"}]
    assert _validate("desired-policy", bad), "secret item 必须拒绝 value 等未声明字段"


def test_event_envelope_rejects_missing_tenant():
    bad = dict(VALID_EXAMPLES["event-envelope"])
    del bad["tenant_id"]
    assert _validate("event-envelope", bad), "tenant_id 必填（§18.3 信封）"


def test_evidence_signature_required():
    bad = dict(VALID_EXAMPLES["evidence"])
    del bad["signature"]
    assert _validate("evidence", bad), "evidence.signature 必填（§10.5）"
