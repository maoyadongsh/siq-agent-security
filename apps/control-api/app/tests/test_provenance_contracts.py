"""Closed provenance contracts; runtime issuer verification is a separate gate."""
import copy
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[4] / "packages/contracts"


def test_issuer_requires_one_key_and_explicit_scope():
    v = validator("trusted-source-issuer")
    good = {
        "issuer_id": "issuer-1", "local_key_ref": "local-state",
        "allowed_source_types": ["USER"], "max_trust_level": "authoritative",
        "scope": {"platform": "hermes", "session_id": "s1", "agent_id": "a1", "task_id": "t1"},
        "expires_at": "2026-09-08T01:00:00Z",
    }
    v.validate(good)
    external = dict(good)
    del external["local_key_ref"]
    external["public_key"] = "A" * 43 + "="
    v.validate(external)
    for changes in [
        {"public_key": "A" * 43 + "="}, {"local_key_ref": "caller"},
        {"scope": {"platform": "hermes"}}, {"allowed_source_types": ["USER", "USER"]},
    ]:
        assert list(v.iter_errors({**good, **changes})), changes
    missing = dict(good)
    del missing["local_key_ref"]
    assert list(v.iter_errors(missing))


def validator(name):
    schema = json.loads((ROOT / f"{name}.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_report_cannot_select_authority():
    v = validator("provenance-report-request")
    good = {
        "report_id": "r1", "platform": "hermes", "session_id": "s1", "agent_id": "a1",
        "source": {"type": "MCP", "source_id": "endpoint/tool"}, "content": {"value": "fixture"},
    }
    v.validate(good)
    for field in ["issuer", "signature", "task_id"]:
        assert list(v.iter_errors({**good, field: "forged"}))
    for source in [
        {"type": "USER", "source_id": "caller"},
        {"type": "MCP", "source_id": "caller", "trust": "trusted"},
    ]:
        assert list(v.iter_errors({**good, "source": source}))


def test_selection_cannot_supply_selected_output_or_trust():
    v = validator("provenance-select-request")
    good = {
        "parent_id": "prov-1", "pointer": "/recipient", "platform": "hermes",
        "session_id": "s1", "agent_id": "a1", "content": {"recipient": "fixture"},
    }
    v.validate(good)
    for field in ["value", "trust", "issuer", "task_id"]:
        assert list(v.iter_errors({**good, field: "forged"}))
    for pointer in ["", "recipient", "/bad~x"]:
        assert list(v.iter_errors({**good, "pointer": pointer}))


def test_signed_registry_and_revocation_envelopes():
    issuer = {
        "issuer_id": "issuer-1", "local_key_ref": "local-state",
        "allowed_source_types": ["MCP"], "max_trust_level": "untrusted",
        "scope": {"platform": "hermes", "session_id": "s1", "agent_id": "a1", "task_id": "t1"},
        "expires_at": "2026-09-08T01:00:00Z",
    }
    for name, payload in [
        ("provenance-issuer-record", {"issuer": issuer}),
        ("provenance-issuer-revocation", {
            "issuer_id": "issuer-1", "issuer_digest": "a" * 64, "revoked_at": "2026-09-08T00:30:00Z",
        }),
    ]:
        v = validator(name)
        record = {"schema_version": name + "/v1", "signing_schema": "local_canonical/v1",
                  "signature": "0" * 128, **payload}
        v.validate(record)
        for field in record:
            bad = dict(record)
            del bad[field]
            assert list(v.iter_errors(bad)), field
        assert list(v.iter_errors({**record, "trusted": True}))


def test_parameter_binding_cannot_supply_trust():
    v = validator("parameter-provenance")
    good = {"parameter_path": "/recipient", "provenance_refs": ["prov-1"]}
    v.validate(good)
    for changes in [
        {"trust": "authoritative"}, {"source_type": "USER"},
        {"parameter_path": "/bad~x"}, {"provenance_refs": []},
        {"provenance_refs": ["prov-1", "prov-1"]},
    ]:
        assert list(v.iter_errors({**good, **changes})), changes


def test_assertion_taxonomy_and_parent_budget():
    v = validator("provenance-assertion")
    good = {
        "schema_version": "provenance-assertion/v1", "provenance_id": "prov-1",
        "source": {"type": "MCP", "source_id": "server-tool-result", "trust": "untrusted"},
        "scope": {"platform": "hermes", "session_id": "s1", "agent_id": "a1", "task_id": "t1"},
        "content_digest": "a" * 64, "parents": [], "derivation": "direct",
        "issued_at": "2026-09-08T00:00:00Z", "expires_at": "2026-09-08T01:00:00Z",
        "issuer": "report-issuer", "signing_schema": "local_canonical/v1", "signature": "0" * 128,
    }
    # Schema conformance is not a valid cryptographic signature or authority.
    v.validate(good)
    for field in good:
        bad = dict(good)
        del bad[field]
        assert list(v.iter_errors(bad)), field
    for field, value in [("type", "CUSTOM"), ("trust", "trust-me"), ("role", "admin")]:
        bad = copy.deepcopy(good)
        bad["source"][field] = value
        assert list(v.iter_errors(bad)), field
    v.validate({**good, "parents": [f"p-{i}" for i in range(32)]})
    assert list(v.iter_errors({**good, "parents": [f"p-{i}" for i in range(33)]}))
