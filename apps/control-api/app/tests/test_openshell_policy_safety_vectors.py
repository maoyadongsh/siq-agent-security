"""Go/Python shared O01 policy-fidelity vectors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.adapters.openshell.contracts import AdapterError, UnsupportedCapability
from app.adapters.openshell.policy_safety import (
    gateway_network_to_rules,
    network_rules_to_gateway,
    parse_policy_output,
    policy_digest,
    static_policy_digest,
)

FIXTURE = Path(__file__).resolve().parents[4] / "testdata/openshell-policy-safety.v2.json"


def _vectors() -> dict:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert document["schema"] == "openshell-policy-safety-vectors/v2"
    return document


@pytest.mark.parametrize("case", _vectors()["read_cases"], ids=lambda case: case["name"])
def test_shared_policy_read_vectors(case: dict):
    if case["expect"] == "reject":
        with pytest.raises(AdapterError):
            parse_policy_output(case["output"])
        return
    policy, revision = parse_policy_output(case["output"])
    assert revision == case["revision"]
    assert policy == case["policy"]
    assert policy_digest(policy) == case["policy_digest"]
    assert static_policy_digest(policy) == case["static_digest"]
    assert gateway_network_to_rules(policy["network_policies"])[0]["effect"] == "allow"


@pytest.mark.parametrize("case", _vectors()["network_cases"], ids=lambda case: case["name"])
def test_shared_network_compile_vectors(case: dict):
    if case["expect"] == "reject":
        with pytest.raises(UnsupportedCapability) as exc:
            network_rules_to_gateway([case["rule"]])
        if canary := case.get("secret_canary"):
            assert canary not in str(exc.value)
        return
    assert network_rules_to_gateway([case["rule"]]) == case["gateway"]
