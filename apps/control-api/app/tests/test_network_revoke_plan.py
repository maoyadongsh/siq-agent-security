"""Independent set oracle: retained grants must equal old minus exact selection."""

from copy import deepcopy
from itertools import combinations

import pytest

from app.network_revoke_plan import NetworkRevokePlanError, plan_network_revoke


def rule(host="api.example:443", paths=None, **extra):
    return {"endpoint": host, "binary_paths": paths or ["/usr/bin/curl"], "effect": "allow", **extra}


def choice(host="api.example:443", path="/usr/bin/curl"):
    return {"endpoint": host, "binary_path": path}


def test_remove_all_duplicate_grants_preserving_other_policy_fields():
    desired = {"network": [rule(paths=["/usr/bin/curl", "/usr/bin/wget"], rule_name="first"), rule()],
               "selector": {"agent_ids": ["a"]}, "enforcement_mode": "block", "version": 2,
               "filesystem": {"read_only": ["/data"]}, "status": "effective"}
    original = deepcopy(desired)
    result = plan_network_revoke(desired, [choice()])
    assert result == {**original, "network": [rule(paths=["/usr/bin/wget"], rule_name="first")]}
    assert desired == original
    result["selector"]["agent_ids"].append("another")
    assert desired == original


def test_last_allow_removed_is_explicit_empty_not_missing_or_null():
    assert plan_network_revoke({"network": [rule()]}, [choice()])["network"] == []


@pytest.mark.parametrize("network", [None, {}, [rule(effect="deny")], [rule(allowed_ips=["127.0.0.1"])],
                                     [rule(binary_paths=[])], [rule()] * 257])
def test_unrepresentable_or_unbounded_baseline_rejected(network):
    with pytest.raises(NetworkRevokePlanError, match="baseline_unsupported"):
        plan_network_revoke({"network": network}, [choice()])


@pytest.mark.parametrize("selections", [[], None, [choice()] * 257, [{}], [dict(choice(), effect="deny")],
                                        [choice(path="relative")], [choice(host="*")]])
def test_invalid_selections_rejected(selections):
    with pytest.raises(NetworkRevokePlanError, match="selection_invalid"):
        plan_network_revoke({"network": [rule()]}, selections)


def test_stale_and_duplicate_selections_are_not_silent_success():
    with pytest.raises(NetworkRevokePlanError, match="selection_stale"):
        plan_network_revoke({"network": [rule()]}, [choice(path="/usr/bin/other")])
    with pytest.raises(NetworkRevokePlanError, match="selection_duplicate"):
        plan_network_revoke({"network": [rule()]}, [choice(), choice()])


def test_all_nonempty_subsets_obey_independent_subtraction_oracle():
    pairs = [("a.example:443", "/bin/a"), ("a.example:443", "/bin/b"),
             ("b.example:443", "/bin/a"), ("b.example:443", "/bin/b")]
    desired = {"network": [rule("a.example:443", ["/bin/a", "/bin/b"]),
                           rule("b.example:443", ["/bin/a", "/bin/b"])]}
    for size in range(1, len(pairs) + 1):
        for subset in combinations(pairs, size):
            result = plan_network_revoke(desired, [choice(host, path) for host, path in subset])
            remaining = {(row["endpoint"], path) for row in result["network"] for path in row["binary_paths"]}
            assert remaining == set(pairs) - set(subset)
            assert remaining < set(pairs)


def test_revoke_plan_compiles_as_explicit_dynamic_removal_against_fake_readback():
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.policy_safety import network_rules_to_gateway
    from app.tests.test_openshell_policy_operations import BASE_POLICY, StatefulRunner

    source = {"policy_id": "p", "version": 1, "selector": {"agent_ids": ["a"]},
              "enforcement_mode": "block", "network": [rule()]}
    gateway = deepcopy(BASE_POLICY)
    gateway["network_policies"] = network_rules_to_gateway(source["network"])
    runner = StatefulRunner(gateway)
    backend = OpenShellCliBackend(runner=runner, env_script="")
    planned = plan_network_revoke(source, [choice()])
    compiled = backend.compile(planned)
    assert compiled.artifact["network_policies"] == []
    plan = backend.plan_change("s1", compiled)
    assert plan.kind == "dynamic"
    assert plan.network_change == "narrowed"
    assert plan.expected_revision == "4"
    assert runner.set_calls == 0
    assert runner.policy == gateway
