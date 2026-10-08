"""Synthetic protocol evidence; these tests do not perform network probes."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from app.adapters.openshell.behavior_protocol import (
    BehaviorChallenge,
    challenge_digest,
    validate_behavior_result,
)

NOW = datetime(2026, 10, 8, 0, 0, 15, tzinfo=UTC)


@pytest.fixture
def documents():
    binding = {name: name.replace("_", "-") for name in (
        "tenant_id", "environment_id", "binding_id", "deployment_id", "operation_id", "target",
        "gateway_fingerprint", "policy_revision",
    )}
    binding.update(policy_digest="a" * 64, image_digest="sha256:" + "b" * 64,
                   probe_sha256="c" * 64, protected_execution_sha256="d" * 64)
    challenge = {
        "schema_version": "openshell-behavior-challenge/v1", "verification_id": "opv-" + "a" * 32,
        "nonce": "e" * 64, "binding": binding, "receiver_ipv4": "192.0.2.10", "receiver_port": 8443,
        "allow_path": "/opt/siq/probe-allow", "deny_path": "/opt/siq/probe-deny",
        "attempts": 3, "timeout_ms": 1000,
        "issued_at": "2026-10-08T00:00:00Z", "expires_at": "2026-10-08T00:05:00Z",
    }
    current = {"binding": copy.deepcopy(binding), "enforcement_mode": "unknown",
               "allow_rules": [{"endpoint": "192.0.2.10:8443", "program_path": challenge["allow_path"]}]}
    observations = []
    for index in range(12):
        kind = ("control_before", "allow", "deny", "control_after")[index % 4]
        inside = kind in ("allow", "deny")
        observations.append({
            "round": index // 4, "kind": kind, "nonce": challenge["nonce"],
            "origin": "sandbox_exec" if inside else "control_plane_host", "endpoint": "192.0.2.10:8443",
            "program_path": challenge[kind + "_path"] if inside else "",
            "program_sha256": binding["probe_sha256"] if inside else "",
            "outcome": "connection_refused" if kind == "deny" else "connected", "elapsed_ms": 10,
            "observed_at": f"2026-10-08T00:00:{index + 2:02d}Z",
        })
    result = {
        "schema_version": "openshell-behavior-result/v2", "verification_id": challenge["verification_id"],
        "nonce": challenge["nonce"], "challenge_sha256": challenge_digest(BehaviorChallenge.model_validate(challenge)),
        "started_at": "2026-10-08T00:00:01Z", "finished_at": "2026-10-08T00:00:14Z",
        "before": copy.deepcopy(current), "after": copy.deepcopy(current), "observations": observations,
    }
    return challenge, result, current


def check(documents, *, now=NOW, state="running"):
    challenge, result, current = documents
    return validate_behavior_result(result, challenge, current, now=now, run_state=state)


def test_candidate_accepted_without_creating_deployment_status(documents):
    original = copy.deepcopy(documents)
    assert check(documents) == (True, "behavior_candidate_observations_accepted")
    assert documents == original


def test_wire_contracts_match_valid_fixture(documents):
    directory = Path(__file__).resolve().parents[4] / "packages/contracts"
    schemas = [json.loads((directory / name).read_text()) for name in (
        "openshell-behavior-challenge.v1.schema.json", "openshell-behavior-result.v2.schema.json",
    )]
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)
    for schema, value in zip(schemas, documents[:2], strict=True):
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, registry=registry, format_checker=FormatChecker()).validate(value)


@pytest.mark.parametrize("state", ["prepared", "succeeded", "failed", "unknown", "expired", "consumed", ""])
def test_only_live_durable_state_is_eligible(documents, state):
    assert check(documents, state=state) == (False, "behavior_operation_not_running")


@pytest.mark.parametrize("field", ["tenant_id", "environment_id", "binding_id", "deployment_id", "operation_id",
                                   "target", "gateway_fingerprint", "policy_revision", "policy_digest",
                                   "image_digest", "probe_sha256", "protected_execution_sha256"])
def test_current_scope_or_runtime_drift_rejects_old_evidence(documents, field):
    current = documents[2]
    current["binding"][field] = "f" * 64 if field.endswith(("digest", "sha256")) else "different"
    if field == "image_digest":
        current["binding"][field] = "sha256:" + "f" * 64
    assert check(documents) == (False, "behavior_current_binding_changed")


@pytest.mark.parametrize("side", ["before", "after"])
def test_policy_changed_during_probe_cannot_pass(documents, side):
    documents[1][side]["binding"]["policy_revision"] = "99"
    assert check(documents) == (False, "behavior_readback_changed")


@pytest.mark.parametrize("field", ["nonce", "verification_id", "challenge_sha256"])
def test_replay_from_other_challenge_rejected(documents, field):
    documents[1][field] = "opv-" + "f" * 32 if field == "verification_id" else "f" * 64
    assert not check(documents)[0]


def test_expiry_boundary_rejects_result(documents):
    assert check(documents, now=datetime(2026, 10, 8, 0, 5, tzinfo=UTC)) == (False, "behavior_time_invalid")


def test_future_result_rejected(documents):
    documents[1]["finished_at"] = "2026-10-08T00:00:16Z"
    assert check(documents) == (False, "behavior_time_invalid")


@pytest.mark.parametrize("expiry", ["2026-10-08T00:05:01Z", "2026-10-08T00:00:05Z"])
def test_window_cannot_exceed_cap_or_underfund_planned_timeout(documents, expiry):
    challenge, result, _ = documents
    challenge["expires_at"] = expiry
    result["challenge_sha256"] = challenge_digest(BehaviorChallenge.model_validate(challenge))
    assert check(documents) == (False, "behavior_window_invalid")


@pytest.mark.parametrize("field,value", [("attempts", True), ("timeout_ms", "1000"), ("receiver_port", 65536),
                                        ("receiver_ipv4", "localhost"), ("allow_path", "/opt/../probe"),
                                        ("issued_at", "2026-02-30T00:00:00Z"), ("timeout_ms", float("nan"))])
def test_malformed_challenge_is_bounded_rejection(documents, field, value):
    documents[0][field] = value
    assert check(documents) == (False, "behavior_schema_invalid")


@pytest.mark.parametrize("index,outcome", [(0, "timeout"), (1, "connection_refused"), (2, "connected"),
                                          (2, "dns_failure"), (2, "probe_error"), (3, "connection_reset")])
def test_unreachable_control_and_probe_failures_are_not_defense(documents, index, outcome):
    documents[1]["observations"][index]["outcome"] = outcome
    assert not check(documents)[0]


@pytest.mark.parametrize("field,value", [("nonce", "f" * 64), ("endpoint", "192.0.2.11:8443"),
                                        ("origin", "control_plane_host"), ("program_path", "/opt/other"),
                                        ("program_sha256", "f" * 64), ("round", 1),
                                        ("observed_at", "2026-10-08T00:00:01Z"), ("elapsed_ms", 9000)])
def test_substituted_or_out_of_order_observation_rejected(documents, field, value):
    documents[1]["observations"][2][field] = value
    assert not check(documents)[0]


def test_duplicate_round_cannot_replace_new_measurement(documents):
    observations = documents[1]["observations"]
    observations[4:8] = copy.deepcopy(observations[:4])
    assert check(documents) == (False, "behavior_observation_order_invalid")


def test_missing_round_rejected(documents):
    documents[1]["observations"] = documents[1]["observations"][:8]
    assert check(documents) == (False, "behavior_schema_invalid")


@pytest.mark.parametrize("mode", ["warn", "audit_only"])
def test_advisory_configuration_cannot_gain_enforcement_grade(documents, mode):
    documents[2]["enforcement_mode"] = mode
    documents[1]["before"]["enforcement_mode"] = mode
    documents[1]["after"]["enforcement_mode"] = mode
    assert check(documents) == (False, "behavior_mode_not_block")


def test_deny_program_in_allow_set_is_not_valid_differential(documents):
    extra = {"endpoint": "192.0.2.10:8443", "program_path": documents[0]["deny_path"]}
    for snapshot in [documents[2], documents[1]["before"], documents[1]["after"]]:
        snapshot["allow_rules"].append(extra.copy())
    assert check(documents) == (False, "behavior_differential_invalid")


def test_client_self_reported_success_is_not_a_result(documents):
    documents[1]["enforcement_verified"] = True
    assert check(documents) == (False, "behavior_schema_invalid")


def test_naive_clock_rejected(documents):
    assert check(documents, now=NOW.replace(tzinfo=None)) == (False, "behavior_clock_invalid")
