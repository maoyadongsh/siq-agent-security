from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, fields

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.durable_operations import DurablePolicyOperations, OperationContext
from app.models import OpenShellOperation
from app.tests.test_openshell_policy_operations import BASE_POLICY, StatefulRunner, _compiled
from app.tests.test_operation_journal import database as database
from app.tests.test_operation_journal import deployment
from app.tests.test_sealed_snapshot import ORIGIN, cipher


def backend(database, runner, *, before_apply=None, deployment_id=None):
    values = {field.name: asdict(ORIGIN)[field.name] for field in fields(OperationContext)}
    if deployment_id is not None:
        values['deployment_id'] = deployment_id
    context = OperationContext(**values)
    registry = DurablePolicyOperations(database, database.kw["bind"], cipher(), context,
        actor_type="user", actor_id="synthetic", before_apply=before_apply)

    def execute(args):
        if args[:2] == ["policy", "get"]:
            args = [*args[:2], "s1", *args[3:]]
        return runner(args)

    return OpenShellCliBackend(runner=execute, env_script="", operation_registry=registry)


def apply(adapter):
    compiled = _compiled(adapter)
    plan = adapter.plan_change(ORIGIN.target, compiled)
    return adapter.apply_dynamic(ORIGIN.target, plan, plan.expected_revision)


def state(database):
    with database() as session:
        return session.scalar(select(OpenShellOperation.state))


def test_new_backend_instance_rolls_back_exactly_once_with_concurrent_replay(database):
    runner = StatefulRunner()
    receipt = apply(backend(database, runner))
    assert state(database) == "applied"

    def restore(_):
        return backend(database, runner).rollback(ORIGIN.target, receipt, authorizer=lambda _: True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(restore, range(2)))
    assert sum(bool(r.evidence.get("replayed")) for r in results) == 1
    assert runner.set_calls == 2 and runner.policy == BASE_POLICY
    assert state(database) == "rolled_back"
    assert backend(database, runner).rollback(ORIGIN.target, receipt).evidence["replayed"] is True
    assert runner.set_calls == 2


def test_lost_apply_acknowledgement_is_unknown_and_never_replayed(database):
    runner = StatefulRunner()

    def lost_ack(args):
        result = runner(args)
        return (1, "", "synthetic lost ack") if args[:2] == ["policy", "set"] else result

    with pytest.raises(AdapterError):
        apply(backend(database, lost_ack))
    assert state(database) == "unknown" and runner.set_calls == 1
    with pytest.raises(AdapterError):
        apply(backend(database, runner))
    assert runner.set_calls == 1


@pytest.mark.parametrize("stage", ["apply", "rollback"])
def test_sudden_exit_after_external_write_retains_inflight_marker(database, stage):
    class SimulatedTermination(BaseException):
        pass

    runner = StatefulRunner()

    def terminate(args):
        result = runner(args)
        if args[:2] == ["policy", "set"]:
            raise SimulatedTermination
        return result

    if stage == "apply":
        with pytest.raises(SimulatedTermination):
            apply(backend(database, terminate))
        assert state(database) == "applying" and runner.set_calls == 1
        with pytest.raises(AdapterError):
            apply(backend(database, runner))
        assert runner.set_calls == 1
    else:
        receipt = apply(backend(database, runner))
        with pytest.raises(SimulatedTermination):
            backend(database, terminate).rollback(ORIGIN.target, receipt, authorizer=lambda _: True)
        assert state(database) == "rollback_pending" and runner.set_calls == 2
        with pytest.raises(AdapterError, match="openshell_recovery_outcome_unconfirmed"):
            backend(database, runner).rollback(ORIGIN.target, receipt, authorizer=lambda _: True)
        assert runner.set_calls == 2


def test_fresh_authorization_denial_prevents_external_write(database):
    runner = StatefulRunner()

    def denied():
        raise AdapterError("synthetic authorization revoked")

    with pytest.raises(AdapterError):
        apply(backend(database, runner, before_apply=denied))
    assert state(database) == "prepared" and runner.set_calls == 0


def test_revoked_rollback_authorization_keeps_applied_state(database):
    runner = StatefulRunner()
    receipt = apply(backend(database, runner))
    with pytest.raises(AdapterError, match="openshell_rollback_authorization_failed"):
        backend(database, runner).rollback(ORIGIN.target, receipt, authorizer=lambda _: False)
    assert state(database) == "applied" and runner.set_calls == 1


def test_rollback_still_works_after_257_later_completed_operations(database):
    runner = StatefulRunner()
    receipt = apply(backend(database, runner))
    with database.begin() as session:
        session.add_all(deployment(f"noop-{i}") for i in range(257))
    for i in range(257):
        later = apply(backend(database, runner, deployment_id=f"noop-{i}"))
        assert later.result == "no_op"
    assert runner.set_calls == 1
    restored = backend(database, runner).rollback(ORIGIN.target, receipt, authorizer=lambda _: True)
    assert restored.result == "restored" and runner.policy == BASE_POLICY and runner.set_calls == 2


@pytest.mark.parametrize("fault_state,expected_calls,expected_state", [
    ("prepared", 0, None), ("applied", 1, "unknown"),
])
def test_database_commit_failure_respects_external_effect_boundary(
    database, fault_state, expected_calls, expected_state,
):
    runner = StatefulRunner()
    failed = False

    def reject_commit(session):
        nonlocal failed
        if session.get_bind() is database.kw["bind"] and not failed:
            if session.scalar(select(OpenShellOperation.state)) == fault_state:
                failed = True
                raise OperationalError("synthetic commit fault", {}, RuntimeError("database unavailable"))

    event.listen(database.class_, "before_commit", reject_commit)
    try:
        with pytest.raises(AdapterError, match="openshell_recovery_unavailable"):
            apply(backend(database, runner))
    finally:
        event.remove(database.class_, "before_commit", reject_commit)
    assert failed and runner.set_calls == expected_calls and state(database) == expected_state
