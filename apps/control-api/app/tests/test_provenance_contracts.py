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
