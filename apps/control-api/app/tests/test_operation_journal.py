"""Private journal transactions, source isolation and recovery-material retention."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.adapters.openshell.operation_journal import JournalError, OperationJournal
from app.db import Base
from app.models import (
    AgentAsset,
    AgentInstance,
    AuditEvent,
    ChangeRequest,
    Deployment,
    DesiredPolicy,
    Environment,
    OpenShellOperation,
    RuntimeBinding,
    Tenant,
)
from app.tests.test_sealed_snapshot import ORIGIN, POLICY, cipher


def seed(sessions):
    with sessions.begin() as session:
        session.add(Tenant(id=ORIGIN.tenant_id, name="synthetic"))
        session.flush()
        session.add(Environment(id=ORIGIN.environment_id, tenant_id=ORIGIN.tenant_id, name="synthetic"))
        session.add(AgentAsset(id="a", tenant_id=ORIGIN.tenant_id, name="synthetic"))
        session.add(DesiredPolicy(id="p", tenant_id=ORIGIN.tenant_id, name="synthetic", selector={}))
        session.flush()
        session.add(AgentInstance(id="i", tenant_id=ORIGIN.tenant_id, asset_id="a"))
        session.add(
            ChangeRequest(
                id="c", tenant_id=ORIGIN.tenant_id, policy_id="p", proposer_user_id="u", idempotency_key="synthetic"
            )
        )
        session.flush()
        session.add(
            RuntimeBinding(
                id=ORIGIN.binding_id,
                tenant_id=ORIGIN.tenant_id,
                environment_id=ORIGIN.environment_id,
                agent_instance_id="i",
                asset_id="a",
                backend=ORIGIN.backend,
                backend_target_id=ORIGIN.target,
            )
        )
        session.flush()
        session.add(deployment(ORIGIN.deployment_id))


def deployment(deployment_id):
    return Deployment(
        id=deployment_id,
        tenant_id=ORIGIN.tenant_id,
        environment_id=ORIGIN.environment_id,
        runtime_binding_id=ORIGIN.binding_id,
        change_request_id="c",
        execution_backend=ORIGIN.backend,
        target=ORIGIN.target,
        to_revision="synthetic",
        status="pending",
    )


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'journal.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    seed(sessions)
    yield sessions
    engine.dispose()


def journal(sessions, origin=ORIGIN):
    return OperationJournal(sessions, cipher(), origin, actor_type="user", actor_id="synthetic-user")


def test_durable_fact_survives_new_registry_and_preserves_exact_policy(database):
    first = journal(database).prepare(POLICY)
    assert first.state == "prepared" and first.epoch == 0
    assert "only-a-test-secret" not in repr(first)
    second = journal(database).read()
    assert second == first and second.policy == POLICY
    assert journal(database).prepare(POLICY) == first
    with database() as session:
        row = session.get(OpenShellOperation, ORIGIN.operation_id)
        assert "only-a-test-secret" not in json.dumps(row.sealed_snapshot)
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1


def test_lifecycle_and_cas_reject_stale_worker(database):
    j = journal(database)
    j.prepare(POLICY)
    j.transition(expected_state="prepared", expected_epoch=0, state="applying")
    with pytest.raises(JournalError, match="operation_transition_conflict"):
        journal(database).transition(expected_state="prepared", expected_epoch=0, state="applying")
    j.transition(
        expected_state="applying", expected_epoch=1, state="applied", revision="2", digest=ORIGIN.expected_digest
    )
    j.transition(expected_state="applied", expected_epoch=2, state="rollback_pending")
    fact = j.transition(
        expected_state="rollback_pending",
        expected_epoch=3,
        state="rolled_back",
        revision="3",
        digest=ORIGIN.base_digest,
    )
    assert fact.restored_revision == "3" and fact.epoch == 4
    with database() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 5


def test_concurrent_workers_only_one_transition(database):
    journal(database).prepare(POLICY)

    def worker(_):
        try:
            return journal(database).transition(expected_state="prepared", expected_epoch=0, state="applying").state
        except JournalError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(worker, range(2))) == ["applying", "operation_transition_conflict"]


def test_unknown_has_no_automatic_retry_edge(database):
    j = journal(database)
    j.prepare(POLICY)
    j.transition(expected_state="prepared", expected_epoch=0, state="applying")
    j.transition(expected_state="applying", expected_epoch=1, state="unknown")
    with pytest.raises(JournalError, match="operation_transition_invalid"):
        j.transition(expected_state="unknown", expected_epoch=2, state="applying")


def test_audit_failure_rolls_back_intent_and_transition(database, monkeypatch):
    import app.adapters.openshell.operation_journal as module

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    original = module.audit
    monkeypatch.setattr(module, "audit", fail)
    with pytest.raises(RuntimeError):
        journal(database).prepare(POLICY)
    with pytest.raises(JournalError, match="operation_unknown"):
        journal(database).read()
    monkeypatch.setattr(module, "audit", original)
    journal(database).prepare(POLICY)
    monkeypatch.setattr(module, "audit", fail)
    with pytest.raises(RuntimeError):
        journal(database).transition(expected_state="prepared", expected_epoch=0, state="applying")
    assert journal(database).read().state == "prepared"
    assert journal(database).read().epoch == 0


@pytest.mark.parametrize("field", ["tenant_id", "deployment_id", "operation_id"])
def test_foreign_scope_cannot_read(database, field):
    journal(database).prepare(POLICY)
    with pytest.raises(JournalError, match="operation_unknown"):
        journal(database, replace(ORIGIN, **{field: "foreign"})).read()


def test_origin_tampering_and_delete_are_rejected(database):
    journal(database).prepare(POLICY)
    with pytest.raises(IntegrityError), database.begin() as session:
        session.delete(session.get(Deployment, ORIGIN.deployment_id))
    with database.begin() as session:
        row = session.get(OpenShellOperation, ORIGIN.operation_id)
        row.origin = {**row.origin, "target": "other-target"}
    with pytest.raises(JournalError, match="operation_origin_conflict"):
        journal(database).read()


def test_more_than_old_cache_capacity_remains_recoverable(database):
    journal(database).prepare(POLICY)
    with database.begin() as session:
        session.add_all(deployment(f"other-{i}") for i in range(257))
    for i in range(257):
        journal(database, replace(ORIGIN, operation_id=f"opo-{i}", deployment_id=f"other-{i}")).prepare(POLICY)
    assert journal(database).read().policy == POLICY


def test_noop_and_digest_constraints(database):
    origin = replace(ORIGIN, expected_digest=ORIGIN.base_digest)
    j = journal(database, origin)
    j.prepare(POLICY)
    with pytest.raises(JournalError, match="operation_noop_mismatch"):
        j.transition(
            expected_state="prepared", expected_epoch=0, state="applied", revision="2", digest=origin.base_digest
        )
    with pytest.raises(JournalError, match="operation_digest_mismatch"):
        j.transition(expected_state="prepared", expected_epoch=0, state="applied", revision="1", digest="d" * 64)
    assert (
        j.transition(
            expected_state="prepared", expected_epoch=0, state="applied", revision="1", digest=origin.base_digest
        ).state
        == "applied"
    )


@pytest.mark.parametrize("name", ["environment_id", "binding_id", "target"])
def test_prepare_refuses_deployment_identity_mismatch(database, name):
    with pytest.raises(JournalError, match="operation_deployment_conflict"):
        journal(database, replace(ORIGIN, **{name: "different"})).prepare(POLICY)
    with database() as session:
        assert session.scalar(select(func.count()).select_from(OpenShellOperation)) == 0
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 0


def test_prepare_cannot_attach_to_foreign_tenant(database):
    with pytest.raises(JournalError, match="operation_deployment_unavailable"):
        journal(database, replace(ORIGIN, tenant_id="foreign")).prepare(POLICY)


def test_one_operation_per_deployment_enforced_by_database(database):
    journal(database).prepare(POLICY)
    with pytest.raises(IntegrityError):
        journal(database, replace(ORIGIN, operation_id="opo-other")).prepare(POLICY)
    with database() as session:
        assert session.scalar(select(func.count()).select_from(OpenShellOperation)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == 1
