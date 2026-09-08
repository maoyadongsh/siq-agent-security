"""Validate the complete paired corpus before running expensive fixtures."""
import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).parent
REQUIRED = {
    "recipient_injection", "destination_host_injection", "filesystem_hijacking", "forged_cwd",
    "forged_user", "forged_iam", "mcp_parameter_control", "missing_provenance", "expired_provenance",
    "wrong_task_replay", "cross_session_replay", "revoked_intent", "approval_revoked", "fake_tool_success",
    "denied_observed_effect", "http_redirect", "conflicting_evidence", "provenance_capacity",
}


def validate():
    schema = json.loads((ROOT / "scenario.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    pairs, seen, categories = {}, set(), set()
    for path in sorted((ROOT / "scenarios").glob("*.json")):
        scenario = json.loads(path.read_text())
        validator.validate(scenario)
        if scenario["id"] in seen or path.stem != scenario["id"]:
            raise ValueError("duplicate scenario or mismatched filename")
        seen.add(scenario["id"])
        pair = pairs.setdefault(scenario["pair_id"], {})
        if scenario["kind"] in pair:
            raise ValueError("duplicate pair role")
        pair[scenario["kind"]] = scenario
        categories.add(scenario["category"])
    if len(pairs) < 20 or not REQUIRED <= categories:
        raise ValueError("required paired attack coverage missing")
    for pair in pairs.values():
        if set(pair) != {"attack", "benign"}:
            raise ValueError("attack lacks benign control")
        if pair["attack"]["category"] != pair["benign"]["category"]:
            raise ValueError("control category differs")
    return {"pairs": len(pairs), "scenarios": len(seen), "categories": len(categories)}


if __name__ == "__main__":
    print(json.dumps(validate(), indent=2))
