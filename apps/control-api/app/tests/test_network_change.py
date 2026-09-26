from copy import deepcopy
from dataclasses import replace

import pytest

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.network_change import assess_network_change
from app.tests.test_openshell_policy_operations import StatefulRunner, _compiled


def rule(endpoint="example.org:443", paths=None, **extra):
    return {"endpoint": endpoint, "effect": "allow", "binary_paths": paths or ["/usr/bin/curl"], **extra}


@pytest.mark.parametrize("before,after,expected", [
    ([], [], "unchanged"),
    ([rule()], [], "narrowed"),
    ([], [rule()], "expanded"),
    ([rule()], [rule("other.org:443")], "mixed"),
    ([rule(paths=["/bin/a", "/bin/b"])], [rule(paths=["/bin/b"])], "narrowed"),
    ([rule(paths=["/bin/b"])], [rule(paths=["/bin/a", "/bin/b"])], "expanded"),
    ([rule(rule_name="old"), rule()], [rule(rule_name="new")], "unchanged"),
    ([rule(paths=["/bin/b", "/bin/a"])], [rule(paths=["/bin/a", "/bin/b"])], "unchanged"),
    ([rule()], [rule(), rule("other.org:443")], "expanded"),
    ([rule(), rule("other.org:443")], [rule()], "narrowed"),
])
def test_allow_set_comparison_without_mutating_inputs(before, after, expected):
    saved = deepcopy((before, after))
    assert assess_network_change(before, after) == expected
    assert (before, after) == saved


@pytest.mark.parametrize("invalid", [
    None, {}, [None], [rule(effect="deny")], [rule(endpoint="invalid")], [rule(endpoint="host:²")],
    [rule(paths=["relative"])], [rule(allowed_ips=["10.0.0.0/8"])],
    [rule(method="GET", path="/safe")], [rule(protocol="rest")],
    [rule(enforcement="enforce")], [rule(request_body_credential_rewrite=False)],
    [rule(unknown=True)], [rule()] * 257, [rule(paths=["/bin/a"] * 129)],
    [rule(paths=["/bin/a"] * 128)] * 33,
])
def test_unrepresentable_or_over_budget_never_classified_as_safe(invalid):
    assert assess_network_change(invalid, []) == "unknown"
    assert assess_network_change([], invalid) == "unknown"


def test_plan_assessment_uses_same_readback_and_never_writes():
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="")
    compiled = _compiled(backend)
    before = runner.get_calls
    plan = backend.plan_change("s1", compiled)
    assert runner.get_calls == before + 1
    assert plan.expected_revision == "4"
    assert plan.network_change == "expanded"
    # Absent writer segment cannot be interpreted as a revoke-all request.
    absent = replace(compiled, artifact={})
    assert backend.plan_change("s1", absent).network_change == "unknown"
    generation = replace(compiled, artifact={**compiled.artifact, "filesystem_policy": {"new_field": True}})
    assert backend.plan_change("s1", generation).network_change == "unknown"
    assert runner.set_calls == 0


def test_live_l7_restrictions_are_not_stripped_to_infer_narrowing():
    runner = StatefulRunner()
    runner.policy["network_policies"] = {
        "restricted": {
            "endpoints": [{"host": "api.example.com", "port": 443, "rules": [
                {"allow": {"method": "GET", "path": "/safe"}}
            ]}],
            "binaries": [{"path": "/usr/bin/curl"}],
        }
    }
    backend = OpenShellCliBackend(runner=runner, env_script="")
    compiled = _compiled(backend)
    assert backend.plan_change("s1", compiled).network_change == "unknown"
    assert backend.plan_change("s1", replace(compiled, artifact={"network_policies": []})).network_change == "unknown"
    assert runner.set_calls == 0
