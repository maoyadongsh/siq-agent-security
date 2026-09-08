"""Remaining V1 contracts: real public fixtures plus structural rejection cases."""
import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[4]
CONTRACTS = ROOT / "packages/contracts"
SAMPLES = ROOT / "apps/agentshield/testdata/contracts"
ARCHIVE = json.loads((ROOT / "docs/evidence/provenance-v1/recovery-completion-20260908.json").read_text())


def sample(name):
    return json.loads((SAMPLES / name).read_text())


NETWORK = {
    "requested_scheme": "http", "requested_host": "127.0.0.1", "requested_port": "12345",
    "received": {"scheme": "http", "host": "127.0.0.1", "port": "12345",
                 "resolved_target": "127.0.0.1:12345", "request_id": "request-1",
                 "request_digest": "a" * 64, "received_at": "2026-09-08T00:00:00Z"},
}
EFFECT = ARCHIVE["effect_record"]["evidence"]
PENDING = sample("file-observation-pending.sample.json")
FIXTURES = {
    "context-assertion.v1": sample("context-assertion.sample.json"),
    "effect-evidence.v1": EFFECT,
    "effect-evidence-submit.v1": EFFECT | {"signature": ""},
    "tool-effect-report.v1": EFFECT | {"signature": "", "coverage": "unknown", "result": "unknown",
        "source": {"type": "tool_report", "source_id": "fixture-tool", "independence": "self_reported"}},
    "effect-evidence-record.v1": ARCHIVE["effect_record"],
    "effect-observer-request.v1": {"source": PENDING["source"], "scope": PENDING["scope"], "expires_in": 60},
    "effect-observer-revocation.v1": ARCHIVE["observer_revocation"],
    "effect-verification-requirement.v1": ARCHIVE["signed_intent"]["effect_requirements"][0],
    "completion-status.v1": ARCHIVE["completion"],
    "file-observation.v1": ARCHIVE["effect_record"]["file_observation"],
    "file-observation-begin.v1": {
        "observation_id": "observation-1", "action_id": "action-1", "decision_receipt_id": "receipt-1",
        "path": "/work/report", "expected_digest": "a" * 64, "max_bytes": 1024,
    },
    "file-observation-finish.v1": {"path": "/work/report"},
    "file-observation-pending.v1": PENDING,
    "file-observation-recovery.v1": sample("file-observation-recovery-1.sample.json"),
    "file-observation-recovery-request.v1": {
        "observation_id": "observation-1", "observer_id": "observer-" + "a" * 32, "expected_owner": "b" * 64,
    },
    "network-observation.v1": NETWORK,
    "network-observation-submit.v1": {
        "observation_id": "observation-1", "action_id": "action-1", "decision_receipt_id": "receipt-1",
        "observation": NETWORK,
    },
    "intent-contract.v3": ARCHIVE["signed_intent"],
    "intent-revocation.v1": sample("intent-revocation.sample.json"),
    "intent-revoke-request.v1": {"expected_intent_digest": "a" * 64},
}


def inline(schema):
    """Resolve only committed same-directory references; no network retrieval."""
    if isinstance(schema, list):
        return [inline(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        name = schema["$ref"]
        assert Path(name).name == name and name.endswith(".schema.json")
        return inline(json.loads((CONTRACTS / name).read_text()))
    return {key: inline(value) for key, value in schema.items()}


def validator(name):
    schema = inline(json.loads((CONTRACTS / f"{name}.schema.json").read_text()))
    cls = Draft7Validator if "draft-07" in schema.get("$schema", "") else Draft202012Validator
    cls.check_schema(schema)
    return cls(schema, format_checker=FormatChecker())


def nodes(value, schema, path=()):
    yield path, value, schema
    for component in schema.get("allOf", []):
        yield from nodes(value, component, path)
    if isinstance(value, dict):
        for key, child in schema.get("properties", {}).items():
            if key in value:
                yield from nodes(value[key], child, (*path, key))
    elif isinstance(value, list) and isinstance(schema.get("items"), dict):
        for index, child in enumerate(value):
            yield from nodes(child, schema["items"], (*path, index))


def at(value, path):
    for key in path:
        value = value[key]
    return value


@pytest.mark.parametrize("name", FIXTURES)
def test_valid_and_closed_required_objects(name):
    good = FIXTURES[name]
    v = validator(name)
    v.validate(good)
    for path, value, schema in nodes(good, v.schema):
        if not isinstance(value, dict):
            continue
        for field in schema.get("required", []):
            bad = copy.deepcopy(good)
            del at(bad, path)[field]
            assert list(v.iter_errors(bad)), (name, path, field)
        if schema.get("additionalProperties") is False:
            bad = copy.deepcopy(good)
            at(bad, path)["caller_authority"] = True
            assert list(v.iter_errors(bad)), (name, path)


@pytest.mark.parametrize("name", FIXTURES)
def test_invalid_signed_fields_taxonomy_and_capacity(name):
    good = FIXTURES[name]
    v = validator(name)
    for path, value, schema in nodes(good, v.schema):
        bad_values = []
        if schema.get("format") == "date-time":
            bad_values += ["2026-02-30T00:00:00Z", "not-a-date", "2026-09-08T00:00:00"]
        if "enum" in schema:
            bad_values.append("UNRECOGNIZED")
        if "pattern" in schema:
            # Signed IDs/digests/refs must not accept arbitrary caller metadata.
            bad_values.append("@invalid value!")
        if "minLength" in schema and schema["minLength"] > 0:
            bad_values.append("")
        if "maxLength" in schema:
            bad_values.append("x" * (schema["maxLength"] + 1))
        if "minimum" in schema:
            bad_values.append(schema["minimum"] - 1)
        if "maximum" in schema:
            bad_values.append(schema["maximum"] + 1)
        if "const" in schema:
            bad_values.append("wrong-constant")
        if isinstance(value, list):
            if schema.get("minItems", 0) > 0:
                bad_values.append([])
            if "maxItems" in schema:
                bad_values.append([copy.deepcopy(value[0]) if value else "item"] * (schema["maxItems"] + 1))
        for replacement in bad_values:
            bad = copy.deepcopy(good)
            at(bad, path[:-1])[path[-1]] = replacement
            assert list(v.iter_errors(bad)), (name, path, replacement)
