"""Real local transactions and simulated collectors; no external probe traffic."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import event, func, select

from app.adapters.openshell.behavior_journal import BehaviorJournal, BehaviorJournalError
from app.adapters.openshell.behavior_protocol import BehaviorChallenge, challenge_digest
from app.models import AuditEvent, Deployment, OpenShellBehaviorOperation, OpenShellOperation, RuntimeBinding, Tenant
from app.tests.test_openshell_behavior_protocol import NOW
from app.tests.test_openshell_behavior_protocol import documents as documents
from app.tests.test_operation_journal import database as database
from app.tests.test_operation_journal import journal as apply_journal
from app.tests.test_sealed_snapshot import ORIGIN, POLICY, cipher

CLAIM_TIME = NOW.replace(second=0)

@pytest.fixture
def ready(database, documents):
    j = apply_journal(database)
    j.prepare(POLICY)
    j.transition(expected_state="prepared", expected_epoch=0, state="applying")
    j.transition(expected_state="applying", expected_epoch=1, state="applied",
                 revision="2", digest=ORIGIN.expected_digest)
    challenge, result, current = documents
    for field in ("tenant_id", "environment_id", "binding_id", "deployment_id", "operation_id",
                  "target", "gateway_fingerprint"):
        challenge["binding"][field] = getattr(ORIGIN, field)
    challenge["binding"].update(policy_revision="2", policy_digest=ORIGIN.expected_digest)
    current["binding"] = copy.deepcopy(challenge["binding"])
    result["before"] = copy.deepcopy(current)
    result["after"] = copy.deepcopy(current)
    result["challenge_sha256"] = challenge_digest(BehaviorChallenge.model_validate(challenge))
    with database.begin() as session:
        deployment = session.get(Deployment, ORIGIN.deployment_id)
        deployment.status = "effective"
        deployment.verification = {"level": "readback_verified"}
        deployment.receipt = {"operation_id": ORIGIN.operation_id, "target": ORIGIN.target,
                              "endpoint_fingerprint": ORIGIN.gateway_fingerprint,
                              "backend_revision": "2", "applied_policy_digest": ORIGIN.expected_digest}
    return documents


def journal(database, *, now=CLAIM_TIME, tenant=ORIGIN.tenant_id):
    return BehaviorJournal(database, cipher(), tenant_id=tenant, deployment_id=ORIGIN.deployment_id,
                           actor_type="user", actor_id="synthetic", clock=lambda: now)


def finish(database, claim, result, current):
    return journal(database, now=NOW).finish(claim, result, current)


def audit_count(database):
    with database() as session:
        return session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action.like("openshell.behavior.%")))


def test_new_worker_reads_durable_result_without_promoting_deployment(database, ready):
    challenge, result, current = ready
    first = journal(database).prepare(challenge, current)
    assert first.state == "prepared" and first.epoch == 0
    assert journal(database).prepare(challenge, current) == first
    claim = journal(database).claim(first.verification_id, current)
    assert claim and claim.owner_token not in repr(claim)
    with database() as session:
        row = session.get(OpenShellBehaviorOperation, first.verification_id)
        assert row.owner_sha256 != claim.owner_token and len(row.owner_sha256) == 64
        assert claim.owner_token not in json.dumps(row.challenge)
    accepted = finish(database, claim, result, current)
    assert accepted.state == "accepted" and accepted.epoch == 2
    assert journal(database).read(first.verification_id) == accepted
    assert journal(database).claim(first.verification_id, current) is None
    assert audit_count(database) == 3
    with database() as session:
        deployment = session.get(Deployment, ORIGIN.deployment_id)
        assert deployment.status == "effective" and deployment.verification == {"level": "readback_verified"}


def test_concurrent_workers_only_one_receives_execution_claim(database, ready):
    challenge, _, current = ready
    journal(database).prepare(challenge, current)

    def worker(_):
        try:
            return journal(database).claim(challenge["verification_id"], current)
        except BehaviorJournalError as error:
            assert str(error) == "behavior_transition_conflict"
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        claims = list(workers.map(worker, range(2)))
    assert sum(c is not None for c in claims) == 1
    assert audit_count(database) == 2


def test_lost_collector_process_cannot_be_resumed_or_replayed(database, ready):
    challenge, _, current = ready
    journal(database).prepare(challenge, current)
    claim = journal(database).claim(challenge["verification_id"], current)
    assert claim
    # Simulate a worker dying after claim. A replacement never obtains a lease.
    assert journal(database).claim(claim.verification_id, current) is None
    late = journal(database, now=NOW + timedelta(minutes=6))
    assert late.expire(claim.verification_id).state == "unknown"
    assert late.claim(claim.verification_id, current) is None
    assert late.expire(claim.verification_id).epoch == 2
    assert audit_count(database) == 3


def test_expired_unstarted_probe_never_gets_claim(database, ready):
    challenge, _, current = ready
    journal(database).prepare(challenge, current)
    late = journal(database, now=NOW + timedelta(minutes=6))
    assert late.claim(challenge["verification_id"], current) is None
    assert late.read(challenge["verification_id"]).state == "expired"
    assert audit_count(database) == 2


def test_remaining_window_must_cover_execution_budget(database, ready):
    challenge, _, current = ready
    journal(database).prepare(challenge, current)
    late = journal(database, now=NOW.replace(minute=4, second=59))
    with pytest.raises(BehaviorJournalError, match="behavior_window_remaining_insufficient"):
        late.claim(challenge["verification_id"], current)
    assert late.read(challenge["verification_id"]).state == "prepared"
    assert audit_count(database) == 1


def test_late_result_cannot_turn_expired_run_into_acceptance(database, ready):
    challenge, result, current = ready
    journal(database).prepare(challenge, current)
    claim = journal(database).claim(challenge["verification_id"], current)
    late = journal(database, now=NOW + timedelta(minutes=6))
    assert late.finish(claim, result, current).state == "unknown"


def test_other_worker_cannot_finish_or_abandon_claim(database, ready):
    challenge, result, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    impostor = replace(claim, owner_token="0" * 64)
    for action in (lambda: finish(database, impostor, result, current), lambda: j.abandon(impostor)):
        with pytest.raises(BehaviorJournalError, match="behavior_owner_conflict"):
            action()
    assert j.read(claim.verification_id).state == "running" and audit_count(database) == 2


def test_result_consumed_once_even_when_same_worker_retries(database, ready):
    challenge, result, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    finish(database, claim, result, current)
    with pytest.raises(BehaviorJournalError, match="behavior_owner_conflict"):
        finish(database, claim, result, current)
    assert audit_count(database) == 3


def test_collector_failure_is_unknown_and_never_eligible_again(database, ready):
    challenge, _, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    assert j.abandon(claim).state == "unknown"
    assert j.claim(claim.verification_id, current) is None


def test_bad_observations_are_retained_as_rejected_not_effective(database, ready):
    challenge, result, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    result["observations"][2]["outcome"] = "dns_failure"
    fact = finish(database, claim, result, current)
    assert fact.state == "rejected" and fact.reason_code == "behavior_deny_not_observed"
    assert fact.result == result


def test_malformed_raw_error_and_credentials_are_not_stored(database, ready):
    challenge, _, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    fact = finish(database, claim, {"raw_stderr": "synthetic-secret", "api_key": "synthetic-secret"}, current)
    assert fact.state == "rejected" and fact.result is None
    with database() as session:
        row = session.get(OpenShellBehaviorOperation, claim.verification_id)
        assert row.result is None and row.result_digest is None
        for audit in session.scalars(select(AuditEvent)):
            assert "synthetic-secret" not in json.dumps(audit.summary)


def test_cross_tenant_cannot_prepare_read_or_claim(database, ready):
    challenge, _, current = ready
    journal(database).prepare(challenge, current)
    other = journal(database, tenant="another-tenant")
    with pytest.raises(BehaviorJournalError, match="behavior_scope_mismatch"):
        other.prepare(challenge, current)
    for action in (lambda: other.read(challenge["verification_id"]),
                   lambda: other.claim(challenge["verification_id"], current)):
        with pytest.raises(BehaviorJournalError, match="behavior_operation_unknown"):
            action()


def test_challenge_id_and_nonce_cannot_be_reused_for_different_operation(database, ready):
    challenge, _, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    altered = copy.deepcopy(challenge)
    altered["timeout_ms"] = 2000
    with pytest.raises(BehaviorJournalError, match="behavior_challenge_conflict"):
        j.prepare(altered, current)
    altered = copy.deepcopy(challenge)
    altered["verification_id"] = "opv-" + "f" * 32
    with pytest.raises(BehaviorJournalError, match="behavior_challenge_conflict"):
        j.prepare(altered, current)
    assert audit_count(database) == 1


def test_binding_revocation_between_claim_and_result_prevents_acceptance(database, ready):
    challenge, result, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    with database.begin() as session:
        session.get(RuntimeBinding, ORIGIN.binding_id).status = "revoked"
    with pytest.raises(BehaviorJournalError, match="behavior_parent_unavailable"):
        finish(database, claim, result, current)
    assert j.abandon(claim).state == "unknown"


@pytest.mark.parametrize("phase", ["prepared", "running", "accepted", "rejected", "unknown", "expired"])
def test_missing_audit_rolls_back_state_and_does_not_return_new_claim(database, ready, phase):
    challenge, result, current = ready
    j = journal(database)
    if phase != "prepared":
        j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current) if phase in ("accepted", "rejected", "unknown") else None

    def reject_audit(session, *_):
        if any(isinstance(row, AuditEvent) and row.action == "openshell.behavior." + phase for row in session.new):
            raise RuntimeError("synthetic audit unavailable")

    event.listen(database.class_, "before_flush", reject_audit)
    try:
        with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
            if phase == "prepared":
                j.prepare(challenge, current)
            elif phase == "running":
                j.claim(challenge["verification_id"], current)
            elif phase == "rejected":
                finish(database, claim, {}, current)
            elif phase == "unknown":
                j.abandon(claim)
            elif phase == "expired":
                journal(database, now=NOW + timedelta(minutes=6)).expire(challenge["verification_id"])
            else:
                finish(database, claim, result, current)
    finally:
        event.remove(database.class_, "before_flush", reject_audit)
    if phase == "prepared":
        with pytest.raises(BehaviorJournalError, match="behavior_operation_unknown"):
            j.read(challenge["verification_id"])
    else:
        assert j.read(challenge["verification_id"]).state == (
            "prepared" if phase in ("running", "expired") else "running"
        )


def test_observations_before_durable_claim_are_rejected(database, ready):
    challenge, result, current = ready
    j = journal(database, now=NOW)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    fact = j.finish(claim, result, current)
    assert fact.state == "rejected"
    assert fact.reason_code == "behavior_result_predates_claim"


@pytest.mark.parametrize("field,value", [("epoch", 0), ("owner_sha256", None), ("started_at", None),
                                        ("result_digest", "f" * 64)])
def test_corrupt_persistent_claim_fails_closed(database, ready, field, value):
    challenge, _, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    with database.begin() as session:
        setattr(session.get(OpenShellBehaviorOperation, claim.verification_id), field, value)
    with pytest.raises(BehaviorJournalError, match="behavior_record_invalid"):
        j.read(claim.verification_id)


@pytest.mark.parametrize("change", ["tenant", "deployment", "revision", "origin"])
def test_parent_drift_before_claim_never_issues_execution_token(database, ready, change):
    challenge, _, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    with database.begin() as session:
        if change == "tenant":
            session.get(Tenant, ORIGIN.tenant_id).status = "disabled"
        elif change == "deployment":
            session.get(Deployment, ORIGIN.deployment_id).status = "rolled_back"
        elif change == "revision":
            session.get(OpenShellOperation, ORIGIN.operation_id).applied_revision = "3"
        else:
            parent = session.get(OpenShellOperation, ORIGIN.operation_id)
            parent.origin = {**parent.origin, "target": "different"}
    with pytest.raises(BehaviorJournalError, match="behavior_parent_"):
        j.claim(challenge["verification_id"], current)
    assert j.read(challenge["verification_id"]).state == "prepared"
    assert audit_count(database) == 1


def test_cross_deployment_and_stale_epoch_cannot_consume(database, ready):
    challenge, result, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)
    with pytest.raises(BehaviorJournalError, match="behavior_owner_conflict"):
        finish(database, replace(claim, epoch=0), result, current)
    other = journal(database)
    other.deployment_id = "another-deployment"
    with pytest.raises(BehaviorJournalError, match="behavior_operation_unknown"):
        other.finish(claim, result, current)
    assert j.read(claim.verification_id).state == "running"


def test_simultaneous_finish_only_one_result_is_consumed(database, ready):
    challenge, result, current = ready
    j = journal(database)
    j.prepare(challenge, current)
    claim = j.claim(challenge["verification_id"], current)

    def consume(_):
        try:
            return finish(database, claim, result, current)
        except BehaviorJournalError as error:
            assert str(error) in ("behavior_owner_conflict", "behavior_transition_conflict")
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(consume, range(2)))
    assert sum(r is not None and r.state == "accepted" for r in results) == 1
    assert audit_count(database) == 3


def test_nonempty_migration_downgrade_preserves_evidence(database, ready):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    challenge, _, current = ready
    j = journal(database)
    original = j.prepare(challenge, current)
    path = Path(__file__).resolve().parents[2] / "migrations/versions/0031_openshell_behavior_operation.py"
    spec = importlib.util.spec_from_file_location("behavior_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with database.kw["bind"].begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="behavior evidence must be preserved"):
                migration.downgrade()
    assert j.read(original.verification_id) == original
