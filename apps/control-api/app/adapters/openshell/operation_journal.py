"""Durable private operation facts. Callers still enforce live authorization."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.openshell.sealed_snapshot import SnapshotCipher, SnapshotOrigin
from app.models import Deployment, OpenShellOperation, utcnow
from app.outbox import audit


class JournalError(Exception):
    """Fixed categories; never backend output or sensitive snapshots."""


@dataclass(frozen=True)
class OperationFact:
    origin: SnapshotOrigin
    state: str
    epoch: int
    policy: dict[str, Any] = field(repr=False)
    applied_revision: str | None = None
    applied_digest: str | None = None
    restored_revision: str | None = None
    restored_digest: str | None = None


class OperationJournal:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        cipher: SnapshotCipher,
        origin: SnapshotOrigin,
        *,
        actor_type: str,
        actor_id: str,
    ):
        origin.validate()
        if not actor_type or not actor_id:
            raise JournalError("operation_actor_required")
        self._sessions = sessions
        self._cipher = cipher
        self.origin = origin
        self._actor_type = actor_type
        self._actor_id = actor_id

    def _query(self):
        return select(OpenShellOperation).where(
            OpenShellOperation.id == self.origin.operation_id,
            OpenShellOperation.tenant_id == self.origin.tenant_id,
            OpenShellOperation.deployment_id == self.origin.deployment_id,
        )

    def _fact(self, row: OpenShellOperation) -> OperationFact:
        if row.origin != asdict(self.origin):
            raise JournalError("operation_origin_conflict")
        return OperationFact(
            origin=self.origin,
            state=row.state,
            epoch=row.epoch,
            policy=self._cipher.open(self.origin, row.sealed_snapshot),
            applied_revision=row.applied_revision,
            applied_digest=row.applied_digest,
            restored_revision=row.restored_revision,
            restored_digest=row.restored_digest,
        )

    def _audit(self, session: Session, state: str, epoch: int) -> None:
        audit(
            session,
            self.origin.tenant_id,
            self._actor_type,
            self._actor_id,
            "openshell.operation." + state,
            "deployment",
            resource_id=self.origin.deployment_id,
            summary={"operation_id": self.origin.operation_id, "epoch": epoch},
        )

    def prepare(self, policy: dict[str, Any]) -> OperationFact:
        sealed = self._cipher.seal(self.origin, policy)
        with self._sessions.begin() as session:
            existing = session.scalar(self._query())
            if existing is not None:
                return self._fact(existing)
            deployment = session.scalar(
                select(Deployment).where(
                    Deployment.id == self.origin.deployment_id,
                    Deployment.tenant_id == self.origin.tenant_id,
                )
            )
            if deployment is None:
                raise JournalError("operation_deployment_unavailable")
            if (
                deployment.environment_id != self.origin.environment_id
                or deployment.runtime_binding_id != self.origin.binding_id
                or deployment.execution_backend != self.origin.backend
                or deployment.target != self.origin.target
                or deployment.status != "pending"
            ):
                raise JournalError("operation_deployment_conflict")
            row = OpenShellOperation(
                id=self.origin.operation_id,
                tenant_id=self.origin.tenant_id,
                deployment_id=self.origin.deployment_id,
                origin=asdict(self.origin),
                sealed_snapshot=sealed,
                state="prepared",
                epoch=0,
            )
            session.add(row)
            self._audit(session, "prepared", 0)
            session.flush()
            return self._fact(row)

    def read(self) -> OperationFact:
        with self._sessions() as session:
            row = session.scalar(self._query())
            if row is None:
                raise JournalError("operation_unknown")
            return self._fact(row)

    def transition(
        self,
        *,
        expected_state: str,
        expected_epoch: int,
        state: str,
        revision: str | None = None,
        digest: str | None = None,
    ) -> OperationFact:
        allowed = {
            ("prepared", "applying"),
            ("prepared", "applied"),
            ("applying", "applied"),
            ("applying", "unknown"),
            ("applied", "rollback_pending"),
            ("rollback_pending", "rolled_back"),
            ("rollback_pending", "unknown"),
        }
        if (expected_state, state) not in allowed or type(expected_epoch) is not int or expected_epoch < 0:
            raise JournalError("operation_transition_invalid")
        values: dict[str, Any] = {"state": state, "epoch": expected_epoch + 1, "updated_at": utcnow()}
        if state in {"applied", "rolled_back"}:
            if not isinstance(revision, str) or not re.fullmatch(r"[1-9][0-9]{0,31}", revision):
                raise JournalError("operation_revision_invalid")
            wanted = self.origin.expected_digest if state == "applied" else self.origin.base_digest
            if digest != wanted:
                raise JournalError("operation_digest_mismatch")
            if expected_state == "prepared" and (
                digest != self.origin.base_digest or revision != self.origin.base_revision
            ):
                raise JournalError("operation_noop_mismatch")
            prefix = "applied" if state == "applied" else "restored"
            values.update({prefix + "_revision": revision, prefix + "_digest": digest})
        elif revision is not None or digest is not None:
            raise JournalError("operation_transition_invalid")
        with self._sessions.begin() as session:
            row = session.scalar(self._query())
            if row is None:
                raise JournalError("operation_unknown")
            self._fact(row)  # Authenticate recovery material before changing any state.
            changed = session.execute(
                update(OpenShellOperation)
                .where(
                    OpenShellOperation.id == self.origin.operation_id,
                    OpenShellOperation.tenant_id == self.origin.tenant_id,
                    OpenShellOperation.deployment_id == self.origin.deployment_id,
                    OpenShellOperation.state == expected_state,
                    OpenShellOperation.epoch == expected_epoch,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise JournalError("operation_transition_conflict")
            self._audit(session, state, expected_epoch + 1)
            session.flush()
            session.refresh(row)
            return self._fact(row)
