"""Pure exact allow-pair removal; never approves, persists or deploys a policy."""

from copy import deepcopy

from app.adapters.openshell.contracts import UnsupportedCapability
from app.adapters.openshell.network_change import assess_network_change
from app.adapters.openshell.policy_safety import validate_network_rules


class NetworkRevokePlanError(ValueError):
    """Stable codes, never embed policy content in errors."""


def plan_network_revoke(desired: dict, selections: list[dict]) -> dict:
    if not isinstance(desired, dict):
        raise NetworkRevokePlanError("network_revoke_policy_invalid")
    before = desired.get("network")
    if assess_network_change(before, before) == "unknown":
        raise NetworkRevokePlanError("network_revoke_baseline_unsupported")
    if not isinstance(selections, list) or not 1 <= len(selections) <= 256:
        raise NetworkRevokePlanError("network_revoke_selection_invalid")
    selected = set()
    for item in selections:
        if not isinstance(item, dict) or set(item) != {"endpoint", "binary_path"}:
            raise NetworkRevokePlanError("network_revoke_selection_invalid")
        try:
            rule = validate_network_rules([{
                "endpoint": item["endpoint"], "binary_paths": [item["binary_path"]], "effect": "allow",
            }])[0]
        except (UnsupportedCapability, ValueError, TypeError):
            raise NetworkRevokePlanError("network_revoke_selection_invalid") from None
        pair = (rule["endpoint"], rule["binary_paths"][0])
        if pair in selected:
            raise NetworkRevokePlanError("network_revoke_selection_duplicate")
        selected.add(pair)
    rules = validate_network_rules(before)
    existing = {(rule["endpoint"], path) for rule in rules for path in rule["binary_paths"]}
    if not selected <= existing:
        raise NetworkRevokePlanError("network_revoke_selection_stale")
    after = []
    for rule in rules:
        paths = [path for path in rule["binary_paths"] if (rule["endpoint"], path) not in selected]
        if paths:
            after.append({**rule, "binary_paths": paths})
    if assess_network_change(before, after) != "narrowed":
        raise NetworkRevokePlanError("network_revoke_not_narrowed")
    result = deepcopy(desired)
    result["network"] = after
    return result
