"""Evidence validation must not accept missing or unrelated successful calls."""

import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from openshell_integrity_probe import validate_receipts


def evidence():
    return {"signed_chain_verified": True, "receipt_count": 3, "receipts": [
        {"schema_version": "runtime-receipt/v3", "tool": tool, "tool_call_id": call, "action": "allow"}
        for tool, call in [("skill_view", "integrity-load"), ("write_file", "integrity-before"),
                           ("write_file", "integrity-after-attempts")]]}


def test_exact_pre_drift_sequence_is_required():
    validate_receipts(evidence())


@pytest.mark.parametrize("variant", ["empty", "missing", "extra", "truthy", "wrong_call", "wrong_tool", "deny", "old_schema"])
def test_invalid_or_unrelated_receipts_rejected(variant):
    value = copy.deepcopy(evidence())
    if variant == "empty":
        value["receipts"] = []
    elif variant == "missing":
        value["receipts"].pop()
    elif variant == "extra":
        value["receipts"].append(value["receipts"][-1])
    elif variant == "truthy":
        value["signed_chain_verified"] = "true"
    else:
        key, replacement = {"wrong_call": ("tool_call_id", "integrity-drift"), "wrong_tool": ("tool", "terminal"),
                            "deny": ("action", "deny"), "old_schema": ("schema_version", "runtime-receipt/v2")}[variant]
        value["receipts"][-1][key] = replacement
    with pytest.raises(RuntimeError, match="integrity_receipt_sequence_invalid"):
        validate_receipts(value)
