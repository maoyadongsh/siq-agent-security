"""Provider grammar permits proposals only; host validation remains mandatory."""

import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[4]
PLAN = {"goal": "Review", "skills": [
    {"name": "secure-research", "input": {
        "repository": "example/project", "question": "Review", "scope": ["README.md"]}},
    {"name": "secure-report", "input": {"path": "/workspace/report.md"}},
    {"name": "secure-delivery", "input": {"contact": "Alice"}},
]}


def validator(name):
    schema = json.loads((ROOT / "packages/contracts" / f"model-{name}.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


@pytest.mark.parametrize("name,proposal", [
    ("task-plan", PLAN),
    ("research-proposal", {"findings": ["One finding"], "summary": "Review complete"}),
    ("recipient-selection", {"candidate_index": 0}),
])
def test_valid_proposals_and_authority_rejection(name, proposal):
    check = validator(name)
    check.validate(proposal)
    for key in ("allow", "signature", "intent", "provenance", "effective"):
        with pytest.raises(jsonschema.ValidationError):
            check.validate({**proposal, key: True})


def test_plan_cannot_reorder_skip_or_add_skills():
    for skills in (PLAN["skills"][::-1], PLAN["skills"][:2], PLAN["skills"] + PLAN["skills"][:1]):
        with pytest.raises(jsonschema.ValidationError):
            validator("task-plan").validate({**PLAN, "skills": skills})
    for level in ("skill", "input"):
        plan = copy.deepcopy(PLAN)
        target = plan["skills"][0]
        if level == "input":
            target = target["input"]
        target["allow"] = True
        with pytest.raises(jsonschema.ValidationError):
            validator("task-plan").validate(plan)


@pytest.mark.parametrize("value", [-1, True, "0", None])
def test_recipient_selection_rejects_invalid_index(value):
    with pytest.raises(jsonschema.ValidationError):
        validator("recipient-selection").validate({"candidate_index": value})


def test_private_provider_configuration_schema():
    schema = json.loads((ROOT / "packages/contracts/hackathon-provider-config.schema.json").read_text())
    jsonschema.Draft7Validator.check_schema(schema)
    check = jsonschema.Draft7Validator(schema)
    bundle = {"endpoint": "http://127.0.0.1:8006/v1", "model": "test-model", "api_key": ""}
    config = {"schema_version": "hackathon-provider-config/v1", "primary": "stepfun", "backup": "ornith",
              "providers": {"stepfun": bundle, "ornith": bundle}}
    check.validate(config)
    for change in ({"primary": "fixture"}, {"providers": {}}, {"allow": True}):
        with pytest.raises(jsonschema.ValidationError):
            check.validate({**config, **change})
