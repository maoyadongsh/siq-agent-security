"""New WorkBuddy shapes and shared namespace vectors; no signature attestation."""

import copy
import hashlib
import json

import pytest

from app.tests.test_windows_resource_profile_contracts import (
    CONTRACTS,
    _candidate,
    _read,
    _validator,
)


def test_workbuddy_native_identity_shared_vectors():
    vectors = json.loads(
        (CONTRACTS / "fixtures/workbuddy_native_identity_v1_examples.json").read_text(encoding="utf-8")
    )
    for case in vectors:
        session = case["host_session_id"]
        call = case["host_call_id"]
        assert (
            case["session_id"]
            == "workbuddy-session/v1:"
            + hashlib.sha256(("workbuddy-native-session/v1\0" + session).encode()).hexdigest()
        )
        assert (
            case["tool_call_id"]
            == "workbuddy-call/v1:"
            + hashlib.sha256(("workbuddy-native-call/v1\0" + session + "\0" + call).encode()).hexdigest()
        )
        for name, field in [
            ("workbuddy-native-session.v1", "session_id"),
            ("workbuddy-native-call.v1", "tool_call_id"),
        ]:
            check = _validator(name + ".schema.json")
            check.validate(case[field])
            for bad in [session, case[field].upper(), case[field] + "a"]:
                assert list(check.iter_errors(bad))


@pytest.mark.parametrize("kind", ["grant.v2", "local-runtime-identity.v2", "local-runtime-identity-issued.v2"])
def test_workbuddy_windows_chain_requires_new_profile(kind):
    value = _candidate(kind)
    target = value["identity"] if "identity" in value else value
    target["platform"] = "workbuddy"
    if kind == "grant.v2":
        value["subject"]["type"] = "agent_instance"
        value.pop("skill", None)
    check = _validator(kind + ".schema.json")
    check.validate(value)
    for field in ["filesystem_profile"]:
        bad = copy.deepcopy(value)
        selected = bad["identity"] if "identity" in bad else bad
        selected.pop(field)
        assert list(check.iter_errors(bad))
    if kind != "grant.v2":
        legacy = _read("local-runtime-identity-issued.json" if "issued" in kind else "local-runtime-identity.json")
        selected = legacy["identity"] if "identity" in legacy else legacy
        selected["platform"] = "workbuddy"
        assert list(_validator(kind.replace("v2", "v1") + ".schema.json").iter_errors(legacy))


def test_workbuddy_list_rejects_legacy_branch():
    value = _candidate("local-runtime-identity-issued.v2")["identity"]
    value["platform"] = "workbuddy"
    check = _validator("local-runtime-identities.v2.schema.json")
    response = {"schema_version": "local-runtime-identities/v2", "items": [value]}
    check.validate(response)
    value.pop("filesystem_profile")
    value["grant_ref"].pop("permission_digest_schema")
    assert list(check.iter_errors(response))


def test_workbuddy_enrolled_v2_strict_shape():
    value = _read("local-runtime-session-enrolled.json")
    value.update(
        schema_version="local-runtime-session-enrolled/v2",
        platform="workbuddy",
        session_id="workbuddy-session/v1:" + "a" * 64,
    )
    check = _validator("local-runtime-session-enrolled.v2.schema.json")
    check.validate(value)
    for field in check.schema["required"]:
        bad = dict(value)
        bad.pop(field)
        assert list(check.iter_errors(bad))
    for platform in ["hermes", "openclaw"]:
        assert list(check.iter_errors({**value, "platform": platform}))
    assert list(check.iter_errors({**value, "session_id": "raw-session"}))


def test_workbuddy_managed_config_and_hook_are_closed():
    value = dict(
        schema_version="workbuddy-managed-hook/v1",
        runtime_identity_id="ri-" + "a" * 32,
        instance_id="hi-" + "b" * 32,
        agent_id="hri-" + "b" * 32,
        credential_path="C:/State/runtime-identity-secrets/ri-" + "a" * 32 + ".token",
        endpoint="http://127.0.0.1:47611",
        enforcement_mode="block",
        state_dir="C:/State",
    )
    check = _validator("workbuddy-managed-hook.v1.schema.json")
    check.validate(value)
    for field in check.schema["required"]:
        bad = dict(value)
        bad.pop(field)
        assert list(check.iter_errors(bad))
    assert list(check.iter_errors({**value, "token": "forbidden"}))
    check = _validator("workbuddy-command-hook-input.v1.schema.json")
    hook = dict(
        hook_event_name="PreToolUse",
        session_id="host-session",
        tool_use_id="call",
        call_id="call",
        tool_name="read_file",
        tool_input={"UntrustedUserKey": 1},
    )
    check.validate(hook)
    check.validate({**hook, "hook_event_name": "PostToolUse", "tool_response": {}})
    assert list(check.iter_errors({**hook, "hook_event_name": "PostToolUse"}))
    assert list(check.iter_errors({**hook, "cwd_authority": "C:/"}))
    assert list(check.iter_errors({**hook, "session_id": " bad"}))


def test_workbuddy_instances_capability_and_plan_are_versioned():
    check = _validator("local-adapter-instances.v2.schema.json")
    value = dict(
        schema_version="local-adapter-instances/v2",
        platform_changes=False,
        native_available=False,
        managed_runtime_available=False,
        instances=[],
        issues=[],
    )
    check.validate(value)
    value.pop("managed_runtime_available")
    assert list(check.iter_errors(value))
    check = _validator("local-adapter-plan.v4.schema.json")
    value = dict(
        schema_version="local-adapter-plan/v4",
        plan_id="ap-" + "a" * 32,
        plan_digest="b" * 64,
        platform="workbuddy",
        action="install",
        expires_at="2026-09-18T00:00:00Z",
        changes=[],
        next_steps=[],
        restart_required=True,
        runtime_verified=False,
        instance_id="hi-" + "c" * 32,
        instance_name="default",
        native_enable=False,
        runtime_identity_id="ri-" + "d" * 32,
    )
    check.validate(value)
    assert list(check.iter_errors({**value, "platform": "hermes"}))
    assert list(_validator("local-adapter-plan.v3.schema.json").iter_errors(value))
