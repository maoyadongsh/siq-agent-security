"""Conservative comparison of the supported network allow-list vocabulary only."""

from app.adapters.openshell.contracts import UnsupportedCapability
from app.adapters.openshell.policy_safety import validate_network_rules


def _grants(rules: object) -> set[tuple[str, str]] | None:
    if not isinstance(rules, list) or len(rules) > 256:
        return None
    pairs = 0
    for rule in rules:
        if not isinstance(rule, dict):
            return None
        paths = rule.get("binary_paths")
        if not isinstance(paths, list) or len(paths) > 128:
            return None
        pairs += len(paths)
        if pairs > 4096:
            return None
    try:
        validated = validate_network_rules(rules)
    except (UnsupportedCapability, ValueError):
        return None
    return {(rule["endpoint"], path) for rule in validated for path in rule["binary_paths"]}


def assess_network_change(before: object, after: object) -> str:
    """Never interpret unrepresentable restrictions as a plain allow rule."""
    old, new = _grants(before), _grants(after)
    if old is None or new is None:
        return "unknown"
    if old == new:
        return "unchanged"
    if new < old:
        return "narrowed"
    if old < new:
        return "expanded"
    return "mixed"
