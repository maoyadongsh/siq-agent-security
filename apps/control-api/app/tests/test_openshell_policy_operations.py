"""O01/O02 operation-bound update and rollback tests for the Python CLI backend."""

from __future__ import annotations

import threading
from dataclasses import replace

import pytest
import yaml

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError, RevisionConflict
from app.adapters.openshell.operation_registry import PolicyOperationRegistry

BASE_POLICY = {
    "version": 1,
    "filesystem_policy": {"include_workdir": True, "read_only": ["/usr"], "read_write": ["/sandbox"]},
    "landlock": {"compatibility": "hard_requirement", "abi": 6},
    "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"},
    "extension_guard": {"mode": "strict"},
}


def _output(revision: int, policy: dict) -> str:
    return f"Version: {revision}\nActive: {revision}\n---\n" + yaml.safe_dump(policy, sort_keys=False)


class StatefulRunner:
    def __init__(self, policy: dict | None = None, revision: int = 4):
        self.policy = yaml.safe_load(yaml.safe_dump(policy or BASE_POLICY))
        self.revision = revision
        self.get_calls = 0
        self.set_calls = 0
        self.get_hook = None
        self.post_set_revision: int | None = None
        self.submitted: list[dict] = []
        self._lock = threading.Lock()

    def __call__(self, args: list[str]) -> tuple[int, str, str]:
        if tuple(args) == ("gateway", "info"):
            return 0, "Gateway Info\n  Gateway version: 0.0.104\n", ""
        if tuple(args) == ("status",):
            return 0, "Server Status\n  Gateway: siq-openshell-dev\n  Gateway version: 0.0.104\n", ""
        if tuple(args) == ("policy", "get", "s1", "--full"):
            with self._lock:
                self.get_calls += 1
                if self.get_hook is not None:
                    self.get_hook(self)
                return 0, _output(self.revision, self.policy), ""
        if tuple(args[:2]) == ("policy", "set"):
            with self._lock:
                self.set_calls += 1
                with open(args[4], encoding="utf-8") as stream:
                    self.policy = yaml.safe_load(stream)
                self.submitted.append(self.policy)
                self.revision = self.post_set_revision or (self.revision + 5)
                return 0, f"✓ Policy version {self.revision} submitted (hash: abcdef123456)\n", ""
        return 1, "", "unexpected command"


def _compiled(backend: OpenShellCliBackend, endpoint: str = "api.example.com:443"):
    return backend.compile(
        {
            "policy_id": "p",
            "version": 1,
            "selector": {"agent_ids": ["a"]},
            "network": [{"endpoint": endpoint, "effect": "allow", "binary_paths": ["/usr/bin/curl"]}],
            "enforcement_mode": "block",
        }
    )


def _applied():
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
    compiled = _compiled(backend)
    receipt = backend.apply_dynamic("s1", backend.plan_change("s1", compiled), "4")
    assert runner.set_calls == 1 and receipt.backend_revision == "9"
    return runner, backend, receipt


def test_no_op_apply_and_rollback_are_zero_write():
    policy = yaml.safe_load(yaml.safe_dump(BASE_POLICY))
    policy["network_policies"] = {
        "siq_as_rule_0": {
            "name": "siq-as-rule-0",
            "endpoints": [{"host": "api.example.com", "port": 443}],
            "binaries": [{"path": "/usr/bin/curl"}],
        }
    }
    runner = StatefulRunner(policy, revision=7)
    backend = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
    compiled = _compiled(backend)
    receipt = backend.apply_dynamic("s1", backend.plan_change("s1", compiled), "7")
    rollback = backend.rollback("s1", receipt)
    assert receipt.result == "no_op" and rollback.result == "no_op"
    assert runner.set_calls == 0


def test_forged_restart_revoked_and_drifted_rollback_are_zero_write():
    runner, backend, receipt = _applied()
    with pytest.raises(AdapterError, match="receipt_mismatch"):
        backend.rollback(
            "s1",
            replace(receipt, base_policy_digest="0" * 64),
            authorizer=lambda _auth: True,
        )
    assert runner.set_calls == 1

    restarted = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
    with pytest.raises(AdapterError, match="operation_unknown"):
        restarted.rollback("s1", receipt, authorizer=lambda _auth: True)
    assert runner.set_calls == 1

    with pytest.raises(AdapterError, match="authorization_failed"):
        backend.rollback("s1", receipt, authorizer=lambda _auth: False)
    assert runner.set_calls == 1

    runner.revision = 10
    with pytest.raises(AdapterError, match="external_drift"):
        backend.rollback("s1", receipt, authorizer=lambda _auth: True)
    assert runner.set_calls == 1


def test_apply_detects_prewrite_and_postwrite_drift():
    prewrite = StatefulRunner()
    backend = OpenShellCliBackend(runner=prewrite, operation_registry=PolicyOperationRegistry())
    compiled = _compiled(backend)
    plan = backend.plan_change("s1", compiled)

    def drift_on_third_get(runner: StatefulRunner) -> None:
        if runner.get_calls == 3:
            runner.revision = 5

    prewrite.get_hook = drift_on_third_get
    with pytest.raises(AdapterError, match="prewrite_policy_drift"):
        backend.apply_dynamic("s1", plan, "4")
    assert prewrite.set_calls == 0

    postwrite = StatefulRunner()
    post_backend = OpenShellCliBackend(runner=postwrite, operation_registry=PolicyOperationRegistry())
    post_compiled = _compiled(post_backend)
    post_plan = post_backend.plan_change("s1", post_compiled)

    def drift_after_set(runner: StatefulRunner) -> None:
        if runner.set_calls and runner.get_calls >= 4:
            runner.revision = 10

    postwrite.get_hook = drift_after_set
    with pytest.raises(AdapterError, match="postwrite_revision_drift"):
        post_backend.apply_dynamic("s1", post_plan, "4")
    assert postwrite.set_calls == 1


def test_shared_registry_serializes_target_and_rejects_stale_writer():
    runner = StatefulRunner()
    registry = PolicyOperationRegistry()
    backends = [OpenShellCliBackend(runner=runner, operation_registry=registry) for _ in range(2)]
    compiled = [_compiled(backend) for backend in backends]
    plans = [backend.plan_change("s1", artifact) for backend, artifact in zip(backends, compiled, strict=True)]
    barrier = threading.Barrier(3)
    results: list[object] = []

    def apply(index: int) -> None:
        barrier.wait()
        try:
            results.append(backends[index].apply_dynamic("s1", plans[index], "4"))
        except Exception as exc:  # capture the competing stale writer
            results.append(exc)

    threads = [threading.Thread(target=apply, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert runner.set_calls == 1
    assert sum(isinstance(result, RevisionConflict) for result in results) == 1
    assert sum(not isinstance(result, Exception) for result in results) == 1


def test_rollback_detects_prewrite_and_postwrite_drift():
    prewrite, backend, receipt = _applied()

    def revoke_by_drift(_authorization) -> bool:
        prewrite.revision = 10
        return True

    with pytest.raises(AdapterError, match="rollback_prewrite_drift"):
        backend.rollback("s1", receipt, authorizer=revoke_by_drift)
    assert prewrite.set_calls == 1

    postwrite, post_backend, post_receipt = _applied()
    postwrite.post_set_revision = 15

    def drift_after_restore(runner: StatefulRunner) -> None:
        if runner.set_calls == 2:
            runner.revision = 16

    postwrite.get_hook = drift_after_restore
    with pytest.raises(AdapterError, match="postwrite_revision_drift"):
        post_backend.rollback("s1", post_receipt, authorizer=lambda _auth: True)
    assert postwrite.set_calls == 2


def test_static_plan_compares_values_not_field_presence():
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
    same = backend.compile(
        {
            "policy_id": "p",
            "version": 1,
            "selector": {"agent_ids": ["a"]},
            "filesystem": {"read_only": ["/usr"], "read_write": ["/sandbox"]},
            "enforcement_mode": "block",
        }
    )
    assert same.needs_generation is True
    assert backend.plan_change("s1", same).kind == "dynamic"
    changed = backend.compile(
        {
            "policy_id": "p",
            "version": 1,
            "selector": {"agent_ids": ["a"]},
            "filesystem": {"read_only": ["/usr", "/opt"], "read_write": ["/sandbox"]},
            "enforcement_mode": "block",
        }
    )
    assert backend.plan_change("s1", changed).kind == "generation"
