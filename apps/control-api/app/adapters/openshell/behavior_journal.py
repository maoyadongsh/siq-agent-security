"""Atomic probe coordination; no network calls or deployment-grade promotion.

The coordinator must perform live user/approval/operator authorization and hold
the cooperating target mutex. This journal separately checks the persistent
deployment/binding/apply origin; it never trusts a caller's claimed run state.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.openshell.behavior_protocol import (
    BehaviorChallenge,
    challenge_digest,
    parse_behavior_challenge,
    parse_behavior_result,
    validate_behavior_challenge,
    validate_behavior_result,
)
from app.adapters.openshell.sealed_snapshot import SnapshotCipher, SnapshotError, SnapshotOrigin
from app.models import Deployment, OpenShellBehaviorOperation, OpenShellOperation, RuntimeBinding, Tenant
from app.outbox import audit

_TRANSITIONS = {"prepared": {"running", "expired"}, "running": {"accepted", "rejected", "unknown"}}
_EPOCHS = {"prepared": 0, "running": 1, "expired": 1, "accepted": 2, "rejected": 2, "unknown": 2}


class BehaviorJournalError(Exception):
    """Fixed categories only; callers must also suppress database transport errors."""


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _digest(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class BehaviorFact:
    verification_id: str
    state: str
    epoch: int
    reason_code: str | None
    challenge: dict = field(repr=False)
    result: dict | None = field(repr=False)
    profile_id: str | None = None
    profile_sha256: str | None = None


@dataclass(frozen=True)
class BehaviorClaim:
    verification_id: str
    epoch: int
    owner_token: str = field(repr=False)
    challenge: dict = field(repr=False)


def _profile_reference(profile_id, profile_sha256):
    if profile_id is None and profile_sha256 is None:
        return
    if (not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", profile_id)
        or not isinstance(profile_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", profile_sha256)):
        raise BehaviorJournalError("behavior_profile_reference_invalid")


def behavior_fact(row: OpenShellBehaviorOperation, tenant_id: str, deployment_id: str) -> BehaviorFact:
    _profile_reference(row.profile_id, row.profile_sha256)
    try:
        challenge = parse_behavior_challenge(row.challenge)
    except (ValidationError, ValueError, TypeError):
        raise BehaviorJournalError("behavior_record_invalid") from None
    if (challenge_digest(challenge) != row.challenge_digest or challenge.verification_id != row.id
        or challenge.binding.tenant_id != tenant_id or row.tenant_id != tenant_id
        or challenge.binding.deployment_id != deployment_id or row.deployment_id != deployment_id
        or challenge.binding.operation_id != row.operation_id
        or hashlib.sha256(challenge.nonce.encode()).hexdigest() != row.nonce_sha256
        or _time(challenge.expires_at).replace(tzinfo=None) != row.expires_at
        or type(row.epoch) is not int or row.epoch != _EPOCHS.get(row.state)):
        raise BehaviorJournalError("behavior_record_invalid")
    ran = row.state in ("running", "accepted", "rejected", "unknown")
    if ran:
        if (not isinstance(row.owner_sha256, str) or len(row.owner_sha256) != 64
            or any(c not in "0123456789abcdef" for c in row.owner_sha256)
            or not isinstance(row.started_at, datetime)
            or not _time(challenge.issued_at).replace(tzinfo=None) <= row.started_at < row.expires_at):
            raise BehaviorJournalError("behavior_record_invalid")
    elif row.owner_sha256 is not None or row.started_at is not None:
        raise BehaviorJournalError("behavior_record_invalid")
    if ((row.state == "accepted" and row.result is None)
        or (row.state not in ("accepted", "rejected") and row.result is not None)):
        raise BehaviorJournalError("behavior_record_invalid")
    if row.result is not None:
        try:
            result = parse_behavior_result(row.result).model_dump(mode="json")
        except (ValidationError, ValueError, TypeError):
            raise BehaviorJournalError("behavior_record_invalid") from None
        if _digest(result) != row.result_digest:
            raise BehaviorJournalError("behavior_record_invalid")
    elif row.result_digest is not None:
        raise BehaviorJournalError("behavior_record_invalid")
    return BehaviorFact(row.id, row.state, row.epoch, row.reason_code,
                        copy.deepcopy(row.challenge), copy.deepcopy(row.result), row.profile_id, row.profile_sha256)


class BehaviorJournal:
    def __init__(
        self, sessions: sessionmaker[Session], cipher: SnapshotCipher, *, tenant_id: str,
        deployment_id: str, actor_type: str, actor_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if any(not isinstance(v, str) or not v or len(v) > 128
               for v in (tenant_id, deployment_id, actor_type, actor_id)):
            raise BehaviorJournalError("behavior_scope_invalid")
        self.sessions, self.cipher = sessions, cipher
        self.tenant_id, self.deployment_id = tenant_id, deployment_id
        self.actor_type, self.actor_id, self.clock = actor_type, actor_id, clock

    def _now(self) -> datetime:
        now = self.clock()
        if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
            raise BehaviorJournalError("behavior_clock_invalid")
        return now

    def _query(self, verification_id: str):
        return select(OpenShellBehaviorOperation).where(
            OpenShellBehaviorOperation.id == verification_id,
            OpenShellBehaviorOperation.tenant_id == self.tenant_id,
            OpenShellBehaviorOperation.deployment_id == self.deployment_id,
        )

    def _load(self, session: Session, verification_id: str) -> OpenShellBehaviorOperation:
        row = session.scalar(self._query(verification_id).with_for_update())
        if row is None:
            raise BehaviorJournalError("behavior_operation_unknown")
        self._fact(row)
        return row

    def _fact(self, row: OpenShellBehaviorOperation) -> BehaviorFact:
        return behavior_fact(row, self.tenant_id, self.deployment_id)

    def _live_parent(self, session: Session, challenge: BehaviorChallenge) -> None:
        binding = challenge.binding
        if binding.tenant_id != self.tenant_id or binding.deployment_id != self.deployment_id:
            raise BehaviorJournalError("behavior_scope_mismatch")
        tenant = session.scalar(select(Tenant).where(Tenant.id == self.tenant_id).with_for_update())
        deployment = session.scalar(select(Deployment).where(
            Deployment.id == self.deployment_id, Deployment.tenant_id == self.tenant_id,
        ).with_for_update())
        runtime = session.scalar(select(RuntimeBinding).where(
            RuntimeBinding.id == binding.binding_id, RuntimeBinding.tenant_id == self.tenant_id,
        ).with_for_update())
        parent = session.scalar(select(OpenShellOperation).where(
            OpenShellOperation.id == binding.operation_id, OpenShellOperation.tenant_id == self.tenant_id,
            OpenShellOperation.deployment_id == self.deployment_id,
        ).with_for_update())
        if (tenant is None or tenant.status != "active" or deployment is None or runtime is None or parent is None
            or deployment.status != "effective" or deployment.execution_backend != "openshell-cli"
            or deployment.runtime_binding_id != binding.binding_id
            or deployment.environment_id != binding.environment_id or deployment.target != binding.target
            or runtime.status != "active" or runtime.revoked_at is not None or runtime.backend != "openshell-cli"
            or runtime.environment_id != binding.environment_id or runtime.backend_target_id != binding.target
            or parent.state != "applied" or parent.applied_revision != binding.policy_revision
            or parent.applied_digest != binding.policy_digest):
            raise BehaviorJournalError("behavior_parent_unavailable")
        receipt = deployment.receipt or {}
        expected_receipt = {"operation_id": binding.operation_id, "target": binding.target,
                            "backend_revision": binding.policy_revision, "applied_policy_digest": binding.policy_digest,
                            "endpoint_fingerprint": binding.gateway_fingerprint}
        if any(receipt.get(key) != value for key, value in expected_receipt.items()):
            raise BehaviorJournalError("behavior_parent_mismatch")
        try:
            origin = SnapshotOrigin(**parent.origin)
            self.cipher.open(origin, parent.sealed_snapshot)
        except (SnapshotError, ValueError, TypeError):
            raise BehaviorJournalError("behavior_parent_mismatch") from None
        expected_origin = {"operation_id": binding.operation_id, "tenant_id": binding.tenant_id,
                           "environment_id": binding.environment_id, "binding_id": binding.binding_id,
                           "deployment_id": binding.deployment_id, "target": binding.target,
                           "gateway_fingerprint": binding.gateway_fingerprint, "expected_digest": binding.policy_digest,
                           "backend": "openshell-cli"}
        if any(getattr(origin, key) != value for key, value in expected_origin.items()):
            raise BehaviorJournalError("behavior_parent_mismatch")

    def _audit(self, session: Session, row: OpenShellBehaviorOperation) -> None:
        audit(session, self.tenant_id, self.actor_type, self.actor_id, "openshell.behavior." + row.state,
              "deployment", resource_id=self.deployment_id,
              summary={"verification_id": row.id, "operation_id": row.operation_id, "epoch": row.epoch,
                       "challenge_sha256": row.challenge_digest, "result_sha256": row.result_digest,
                       "reason_code": row.reason_code,
                       **({"profile_id": row.profile_id, "profile_sha256": row.profile_sha256}
                          if row.profile_id is not None else {})})

    def _transition(self, session: Session, row: OpenShellBehaviorOperation, state: str, **values) -> BehaviorFact:
        if state not in _TRANSITIONS.get(row.state, set()):
            raise BehaviorJournalError("behavior_transition_invalid")
        values.update(state=state, epoch=row.epoch + 1, updated_at=self._now().replace(tzinfo=None))
        changed = session.execute(update(OpenShellBehaviorOperation).where(
            OpenShellBehaviorOperation.id == row.id, OpenShellBehaviorOperation.tenant_id == self.tenant_id,
            OpenShellBehaviorOperation.deployment_id == self.deployment_id,
            OpenShellBehaviorOperation.state == row.state, OpenShellBehaviorOperation.epoch == row.epoch,
        ).values(**values).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            raise BehaviorJournalError("behavior_transition_conflict")
        session.refresh(row)
        self._audit(session, row)
        session.flush()
        return self._fact(row)

    def prepare(
        self, challenge: dict, current_readback: dict, *,
        profile_id: str | None = None, profile_sha256: str | None = None,
    ) -> BehaviorFact:
        _profile_reference(profile_id, profile_sha256)
        try:
            expected = parse_behavior_challenge(challenge)
        except (ValidationError, ValueError, TypeError):
            raise BehaviorJournalError("behavior_schema_invalid") from None
        if expected.binding.tenant_id != self.tenant_id or expected.binding.deployment_id != self.deployment_id:
            raise BehaviorJournalError("behavior_scope_mismatch")
        digest = challenge_digest(expected)
        try:
            with self.sessions.begin() as session:
                existing = session.scalar(self._query(expected.verification_id).with_for_update())
                if existing is not None:
                    if (existing.challenge_digest != digest
                        or (existing.profile_id, existing.profile_sha256) != (profile_id, profile_sha256)):
                        raise BehaviorJournalError("behavior_challenge_conflict")
                    return self._fact(existing)
                valid, reason = validate_behavior_challenge(challenge, current_readback, now=self._now())
                if not valid:
                    raise BehaviorJournalError(reason)
                self._live_parent(session, expected)
                row = OpenShellBehaviorOperation(
                    id=expected.verification_id, tenant_id=self.tenant_id, deployment_id=self.deployment_id,
                    operation_id=expected.binding.operation_id, challenge=expected.model_dump(mode="json"),
                    challenge_digest=digest, nonce_sha256=hashlib.sha256(expected.nonce.encode()).hexdigest(),
                    profile_id=profile_id, profile_sha256=profile_sha256,
                    state="prepared", epoch=0, expires_at=_time(expected.expires_at).replace(tzinfo=None),
                )
                session.add(row)
                session.flush()
                self._audit(session, row)
                return self._fact(row)
        except IntegrityError:
            with self.sessions() as session:
                existing = session.scalar(self._query(expected.verification_id))
                if (existing is not None and existing.challenge_digest == digest
                    and (existing.profile_id, existing.profile_sha256) == (profile_id, profile_sha256)):
                    return self._fact(existing)
            raise BehaviorJournalError("behavior_challenge_conflict") from None

    def read(self, verification_id: str) -> BehaviorFact:
        with self.sessions() as session:
            return self._fact(self._load(session, verification_id))

    def claim(self, verification_id: str, current_readback: dict) -> BehaviorClaim | None:
        with self.sessions.begin() as session:
            row = self._load(session, verification_id)
            if row.state != "prepared":
                return None
            if self._now().replace(tzinfo=None) >= row.expires_at:
                self._transition(session, row, "expired", reason_code="behavior_deadline_expired")
                return None
            valid, reason = validate_behavior_challenge(row.challenge, current_readback, now=self._now())
            if not valid:
                raise BehaviorJournalError(reason)
            self._live_parent(session, parse_behavior_challenge(row.challenge))
            token = secrets.token_hex(32)
            fact = self._transition(session, row, "running", owner_sha256=hashlib.sha256(token.encode()).hexdigest(),
                                    started_at=self._now().replace(tzinfo=None))
            return BehaviorClaim(fact.verification_id, fact.epoch, token, fact.challenge)

    def _owned(self, row: OpenShellBehaviorOperation, claim: BehaviorClaim) -> None:
        if (not isinstance(claim, BehaviorClaim) or not isinstance(claim.owner_token, str)
            or len(claim.owner_token) != 64 or row.state != "running" or row.epoch != claim.epoch
            or not row.owner_sha256 or not hmac.compare_digest(
                row.owner_sha256, hashlib.sha256(claim.owner_token.encode()).hexdigest())):
            raise BehaviorJournalError("behavior_owner_conflict")

    def finish(
        self, claim: BehaviorClaim, result: dict, current_readback: dict,
        *, before_accept: Callable[[Session], None] | None = None,
    ) -> BehaviorFact:
        if not isinstance(claim, BehaviorClaim):
            raise BehaviorJournalError("behavior_owner_conflict")
        with self.sessions.begin() as session:
            row = self._load(session, claim.verification_id)
            self._owned(row, claim)
            now = self._now()
            if now.replace(tzinfo=None) >= row.expires_at:
                return self._transition(session, row, "unknown", reason_code="behavior_deadline_expired")
            self._live_parent(session, parse_behavior_challenge(row.challenge))
            accepted, reason = validate_behavior_result(
                result, row.challenge, current_readback, now=now, run_state=row.state,
            )
            try:
                saved = parse_behavior_result(result).model_dump(mode="json")
            except (ValidationError, ValueError, TypeError):
                saved = None  # Never persist arbitrary error output, keys or a client success claim.
            if accepted and _time(saved["started_at"]).replace(tzinfo=None) < row.started_at:
                accepted, reason = False, "behavior_result_predates_claim"
            if accepted and before_accept is not None:
                # Database-only live authorization; no probe IO while rows are locked.
                before_accept(session)
            if accepted and self._now().replace(tzinfo=None) >= row.expires_at:
                return self._transition(session, row, "unknown", reason_code="behavior_deadline_expired")
            return self._transition(session, row, "accepted" if accepted else "rejected", reason_code=reason,
                                    result=saved, result_digest=_digest(saved) if saved is not None else None)

    def abandon(self, claim: BehaviorClaim) -> BehaviorFact:
        if not isinstance(claim, BehaviorClaim):
            raise BehaviorJournalError("behavior_owner_conflict")
        with self.sessions.begin() as session:
            row = self._load(session, claim.verification_id)
            self._owned(row, claim)
            return self._transition(session, row, "unknown", reason_code="behavior_collector_unconfirmed")

    def expire(self, verification_id: str) -> BehaviorFact:
        with self.sessions.begin() as session:
            row = self._load(session, verification_id)
            if row.state not in ("prepared", "running") or self._now().replace(tzinfo=None) < row.expires_at:
                return self._fact(row)
            return self._transition(session, row, "unknown" if row.state == "running" else "expired",
                                    reason_code="behavior_deadline_expired")
