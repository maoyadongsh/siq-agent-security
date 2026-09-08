"""Template §90: explicit structural negatives; signatures need runtime verification."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[4]
SCOPE = {"platform": "hermes", "session_id": "s1", "agent_id": "a1", "task_id": "t1"}
ISSUER = {
    "issuer_id": "issuer-1", "local_key_ref": "local-state",
    "allowed_source_types": ["USER"], "max_trust_level": "authoritative",
    "scope": SCOPE, "expires_at": "2026-09-08T01:00:00Z",
}
SIGNING = {"signing_schema": "local_canonical/v1", "signature": "0" * 128}
# Placeholder signatures are schema fixtures only, not evidence of authority.
FIXTURES = {
    "provenance-assertion": json.loads(
        (ROOT / "apps/agentshield/testdata/contracts/provenance-assertion.sample.json").read_text()
    ),
    "trusted-source-issuer": ISSUER,
    "provenance-issuer-record": {"schema_version": "provenance-issuer-record/v1", "issuer": ISSUER, **SIGNING},
    "provenance-issuer-revocation": {
        "schema_version": "provenance-issuer-revocation/v1", "issuer_id": "issuer-1",
        "issuer_digest": "a" * 64, "revoked_at": "2026-09-08T00:30:00Z", **SIGNING,
    },
    "provenance-report-request": {
        "report_id": "r1", "platform": "hermes", "session_id": "s1", "agent_id": "a1",
        "source": {"type": "MCP", "source_id": "server-tool"}, "content": {"value": "fixture"},
    },
    "provenance-select-request": {
        "parent_id": "p1", "pointer": "/value", "platform": "hermes", "session_id": "s1",
        "agent_id": "a1", "content": {"value": "fixture"},
    },
    "parameter-provenance": {"parameter_path": "/value", "provenance_refs": ["p1"]},
}


def validator(name):
    schema = json.loads((ROOT / f"packages/contracts/{name}.v1.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def object_paths(value, schema, path=()):
    """Visit constrained objects, deliberately excluding arbitrary report content."""
    if schema.get("type") != "object":
        return
    yield path, schema
    for key, child in schema.get("properties", {}).items():
        if key in value and isinstance(value[key], dict):
            yield from object_paths(value[key], child, (*path, key))


def at(value, path):
    for key in path:
        value = value[key]
    return value


@pytest.mark.parametrize("name", FIXTURES)
def test_required_and_closed_objects(name):
    v = validator(name)
    good = FIXTURES[name]
    v.validate(good)
    for path, schema in object_paths(good, v.schema):
        for field in schema.get("required", []):
            bad = copy.deepcopy(good)
            del at(bad, path)[field]
            assert list(v.iter_errors(bad)), (name, path, field)
        bad = copy.deepcopy(good)
        at(bad, path)["caller_authority"] = "admin"
        assert list(v.iter_errors(bad)), (name, path)


ID_BAD = ["", "../forged", "x" * 129]
TIME_BAD = ["yesterday", "2026-02-30T00:00:00Z", "2026-09-08T00:00:00"]
ISSUER_NEGATIVES = [
    ("issuer_id", ID_BAD), ("allowed_source_types", [[], ["CUSTOM"], ["USER", "USER"]]),
    ("max_trust_level", ["trust-me"]), ("scope.task_id", ["", "x" * 257]),
    ("expires_at", TIME_BAD), ("revoked_at", TIME_BAD), ("local_key_ref", ["caller-key"]),
]
CASES = {
    "trusted-source-issuer": ISSUER_NEGATIVES,
    "provenance-issuer-record": [("issuer." + p, values) for p, values in ISSUER_NEGATIVES]
    + [("signature", ["", "g" * 128])],
    "provenance-assertion": [
        ("provenance_id", ID_BAD), ("issuer", ID_BAD), ("signature", ["", "g" * 128]),
        ("content_digest", ["", "a" * 63, "G" * 64]), ("issued_at", TIME_BAD), ("expires_at", TIME_BAD),
        ("source.type", ["CUSTOM"]), ("source.trust", ["trust-me"]),
        ("source.source_id", ["", "x" * 257]), ("scope.session_id", ["", "x" * 257]),
        ("parents", [["../bad"], ["p1", "p1"], [f"p{i}" for i in range(33)]]),
    ],
    "provenance-issuer-revocation": [
        ("issuer_id", ID_BAD), ("signature", ["", "g" * 128]),
        ("issuer_digest", ["", "G" * 64]), ("revoked_at", TIME_BAD),
    ],
    "provenance-report-request": [
        ("report_id", ID_BAD), ("session_id", ["", "x" * 257]),
        ("source.type", ["USER", "TRUSTED_IAM", "CUSTOM"]),
        ("source.trust", ["trusted", "authoritative"]), ("source.source_id", ["", "x" * 257]),
    ],
    "provenance-select-request": [
        ("parent_id", ID_BAD), ("session_id", ["", "x" * 257]),
        ("pointer", ["", "value", "/bad~x", "/" + "x" * 1024]),
    ],
    "parameter-provenance": [
        ("parameter_path", ["", "value", "/bad~x", "/" + "x" * 1024]),
        ("provenance_refs", [[], ["../bad"], ["p1", "p1"], [f"p{i}" for i in range(33)]]),
    ],
}


@pytest.mark.parametrize(
    "name,path,values", [(name, path, values) for name, rows in CASES.items() for path, values in rows]
)
def test_invalid_authority_fields(name, path, values):
    v = validator(name)
    for value in values:
        bad = copy.deepcopy(FIXTURES[name])
        keys = path.split(".")
        at(bad, keys[:-1])[keys[-1]] = value
        assert list(v.iter_errors(bad)), (name, path, value)


@pytest.mark.parametrize("name,path,value", [
    ("provenance-assertion", "parents", [f"p{i}" for i in range(32)]),
    ("parameter-provenance", "provenance_refs", [f"p{i}" for i in range(32)]),
    ("parameter-provenance", "parameter_path", "/" + "x" * 1023),
    ("provenance-select-request", "pointer", "/" + "x" * 1023),
    ("trusted-source-issuer", "issuer_id", "x" * 128),
    ("provenance-report-request", "session_id", "x" * 256),
])
def test_capacity_boundary_is_accepted(name, path, value):
    good = copy.deepcopy(FIXTURES[name])
    good[path] = value
    validator(name).validate(good)
