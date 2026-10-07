"""Go online wire samples and exact native host application contracts."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[4]
NAMES = ("native-host-connection", "native-host-publish", "native-host-published",
         "native-host-verification", "native-host-verified")


@pytest.mark.parametrize("name", NAMES)
def test_native_host_online_go_samples(name):
    schema = json.loads((ROOT / "packages/contracts" / f"{name}.v1.schema.json").read_text())
    sample = json.loads((ROOT / "apps/agentshield/testdata/contracts" / f"{name}-v1.sample.json").read_text())
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    validator.validate(sample)
    assert list(validator.iter_errors(sample | {"model_authorized": True}))
    for field in schema["required"]:
        assert list(validator.iter_errors({k: v for k, v in sample.items() if k != field}))
    assert list(validator.iter_errors(sample | {"schema_version": "unknown/v1"}))
    if "subject" in sample:
        altered = copy.deepcopy(sample)
        altered["subject"]["grant_id"] = "model-selected"
        assert list(validator.iter_errors(altered))


def test_native_publish_lifecycle_variants_reject_authority_claims():
    schema = json.loads((ROOT / "packages/contracts/native-host-publish.v1.schema.json").read_text())
    sample = json.loads((ROOT / "apps/agentshield/testdata/contracts/native-host-publish-v1.sample.json").read_text())
    validator = Draft7Validator(schema)
    source = {"schema_version": "native-skill-source/v1",
              "skill_file": {"path_sha256": "a" * 64, "sha256": "b" * 64, "bytes": 42},
              "content_file": {"path_sha256": "a" * 64, "sha256": "b" * 64, "bytes": 42},
              "text_sha256": "b" * 64, "decoding": "utf-8-sig-replace-universal-newlines/v1", "cache_hit": False}
    events = [sample["event"], {"kind": "skill_source", "load_id": "nload-" + "a" * 32,
                              "parent_load_id": "", "source": source},
              {"kind": "call_prepare", "tool": "read_file", "tool_call_id": "call",
               "request_binding": "b" * 64, "load_id": ""},
              {"kind": "call_finish", "tool_call_id": "call", "request_binding": "b" * 64}, {"kind": "task_end"}]
    for event in events:
        validator.validate(sample | {"event": event})
        for field in ("allow", "grant_id", "context_id", "no_skill", "verification_url"):
            assert list(validator.iter_errors(sample | {"event": event | {field: "untrusted"}}))
    assert list(validator.iter_errors(sample | {"event": events[1] | {"parent_load_id": None}}))
