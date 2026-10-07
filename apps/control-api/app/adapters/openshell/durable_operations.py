"""Enterprise CLI registry: durable facts with cooperating-writer exclusion."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.openshell.contracts import AdapterError, PolicySnapshot, RollbackReceipt
from app.adapters.openshell.operation_journal import JournalError, OperationJournal
from app.adapters.openshell.operation_registry import PolicyOperation
from app.adapters.openshell.policy_safety import gateway_network_to_rules, static_policy_digest
from app.adapters.openshell.sealed_snapshot import SnapshotCipher, SnapshotError, SnapshotOrigin
from app.adapters.openshell.target_mutex import TargetLockError, target_mutex
from app.models import OpenShellOperation


@dataclass(frozen=True)
class OperationContext:
    tenant_id: str
    environment_id: str
    binding_id: str
    deployment_id: str
    target: str
    gateway_fingerprint: str
    gateway_name_sha256: str


class DurablePolicyOperations:
    def __init__(
        self, sessions: sessionmaker[Session], engine: Engine, cipher: SnapshotCipher,
        context: OperationContext, *, actor_type: str, actor_id: str,
        before_apply: Callable[[], None] | None = None,
    ):
        self._sessions = sessions
        self._engine = engine
        self._cipher = cipher
        self.context = context
        self._actor_type = actor_type
        self._actor_id = actor_id
        self._before_apply = before_apply
        self._active_operation_id: str | None = None

    def _make_journal(self, origin: SnapshotOrigin) -> OperationJournal:
        if any(getattr(origin, key) != value for key, value in asdict(self.context).items()):
            raise JournalError("operation_origin_conflict")
        return OperationJournal(self._sessions, self._cipher, origin,
                                actor_type=self._actor_type, actor_id=self._actor_id)

    def _journal(self, operation_id: str) -> OperationJournal:
        with self._sessions() as session:
            row = session.scalar(select(OpenShellOperation).where(
                OpenShellOperation.id == operation_id,
                OpenShellOperation.tenant_id == self.context.tenant_id,
                OpenShellOperation.deployment_id == self.context.deployment_id,
            ))
            if row is None:
                raise JournalError("operation_unknown")
            try:
                origin = SnapshotOrigin(**row.origin)
            except (TypeError, ValueError):
                raise JournalError("operation_origin_conflict") from None
            if origin.operation_id != operation_id:
                raise JournalError("operation_origin_conflict")
        return self._make_journal(origin)

    def _mark_unknown(self) -> None:
        if not self._active_operation_id:
            return
        try:
            journal = self._journal(self._active_operation_id)
            fact = journal.read()
            if fact.state in {"applying", "rollback_pending"}:
                journal.transition(expected_state=fact.state, expected_epoch=fact.epoch, state="unknown")
        except Exception:
            # A down database cannot be repaired here; the durable in-flight
            # marker remains, and no automatic write replay is allowed.
            pass

    @contextmanager
    def target_lock(self, target: str):
        if target != self.context.target:
            raise AdapterError("openshell_recovery_target_mismatch")
        try:
            with target_mutex(self._engine, self.context.gateway_fingerprint, target):
                try:
                    yield
                except Exception:
                    self._mark_unknown()
                    raise
        except (JournalError, SnapshotError, TargetLockError, SQLAlchemyError, ValueError, TypeError):
            raise AdapterError("openshell_recovery_unavailable") from None

    def prepare(self, operation: PolicyOperation) -> None:
        if operation.target != self.context.target:
            raise JournalError("operation_origin_conflict")
        origin = SnapshotOrigin(
            **asdict(self.context), operation_id=operation.operation_id, backend="openshell-cli",
            base_revision=operation.base.revision, base_digest=operation.base.policy_digest,
            expected_digest=operation.applied_digest,
        )
        journal = self._make_journal(origin)
        if journal.prepare(operation.base.policy).state != "prepared":
            raise JournalError("operation_replay_refused")
        self._active_operation_id = operation.operation_id

    def before_write(self, operation_id: str) -> None:
        if self._before_apply is not None:
            self._before_apply()
        journal = self._journal(operation_id)
        fact = journal.read()
        journal.transition(expected_state="prepared", expected_epoch=fact.epoch, state="applying")

    def remember(self, operation: PolicyOperation) -> None:
        journal = self._journal(operation.operation_id)
        fact = journal.read()
        if (operation.target != self.context.target or operation.base.revision != fact.origin.base_revision
            or operation.base.policy_digest != fact.origin.base_digest):
            raise JournalError("operation_origin_conflict")
        if operation.no_op and self._before_apply is not None:
            self._before_apply()
        journal.transition(
            expected_state="prepared" if operation.no_op else "applying", expected_epoch=fact.epoch,
            state="applied", revision=operation.applied_revision, digest=operation.applied_digest,
        )

    def get(self, operation_id: str) -> PolicyOperation:
        journal = self._journal(operation_id)
        fact = journal.read()
        if fact.state not in {"applied", "rolled_back"}:
            raise AdapterError("openshell_recovery_outcome_unconfirmed")
        if not fact.applied_revision or not fact.applied_digest:
            raise JournalError("operation_applied_metadata_missing")
        self._active_operation_id = operation_id
        policy = fact.policy
        base = PolicySnapshot(
            target=self.context.target, revision=fact.origin.base_revision, policy=policy,
            policy_digest=fact.origin.base_digest, static_digest=static_policy_digest(policy),
            filesystem=policy.get("filesystem_policy") or {}, process=policy.get("process") or {},
            network=gateway_network_to_rules(policy.get("network_policies")),
        )
        return PolicyOperation(operation_id, self.context.target, base, fact.applied_revision,
                               fact.applied_digest, fact.origin.expected_digest == fact.origin.base_digest)

    def before_rollback(self, operation_id: str) -> None:
        journal = self._journal(operation_id)
        fact = journal.read()
        journal.transition(expected_state="applied", expected_epoch=fact.epoch, state="rollback_pending")

    def complete_rollback(self, operation_id: str, revision: str, digest: str) -> None:
        journal = self._journal(operation_id)
        fact = journal.read()
        journal.transition(expected_state="rollback_pending", expected_epoch=fact.epoch,
                           state="rolled_back", revision=revision, digest=digest)

    def restored(self, operation_id: str) -> RollbackReceipt | None:
        fact = self._journal(operation_id).read()
        if fact.state != "rolled_back":
            return None
        if not fact.restored_revision or not fact.restored_digest:
            raise JournalError("operation_restored_metadata_missing")
        return RollbackReceipt(
            restored_revision=fact.restored_revision, restored_digest=fact.restored_digest,
            result="no_op" if fact.origin.expected_digest == fact.origin.base_digest else "restored",
            evidence={"operation_id": operation_id, "replayed": True},
        )

    def recovery_hint(self) -> dict:
        if self._active_operation_id is None:
            return {}
        try:
            fact = self._journal(self._active_operation_id).read()
            state = fact.state
        except Exception:
            state = "unavailable"
        return {"operation_id": self._active_operation_id, "recovery_state": state}
