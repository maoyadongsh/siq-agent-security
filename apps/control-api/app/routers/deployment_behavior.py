"""Authenticated fixed-template collection and bounded, side-effect-free history."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.adapters.openshell.behavior_coordinator import BehaviorCoordinator
from app.adapters.openshell.behavior_journal import BehaviorFact, BehaviorJournal, BehaviorJournalError, behavior_fact
from app.adapters.openshell.behavior_profiles import load_behavior_profiles
from app.adapters.openshell.behavior_protocol import Digest, ProbeID, Timestamp, Token, Wire, _time
from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.recovery_keys import load_recovery_cipher
from app.adapters.openshell.sealed_snapshot import SnapshotError
from app.adapters.openshell.target_mutex import TargetLockError
from app.behavior_authority import BehaviorAuthority
from app.db import get_engine, get_session, get_session_factory
from app.list_meta import apply_list_meta, take_page
from app.models import Deployment, OpenShellBehaviorOperation
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])


class BehaviorStart(Wire):
    schema_version: Literal["deployment-behavior-start/v1"]
    verification_id: ProbeID
    profile_id: Token


class BehaviorStartV2(Wire):
    schema_version: Literal["deployment-behavior-start/v2"]
    verification_id: ProbeID
    profile_id: Token
    profile_sha256: Digest


class BehaviorScope(Wire):
    target: Token
    policy_revision: Token
    policy_digest: Digest
    transport: Literal["direct_tcp", "http_connect"]
    endpoint: Annotated[str, Field(max_length=21)]
    allow_path: Annotated[str, Field(max_length=512)]
    deny_path: Annotated[str, Field(max_length=512)]
    attempts: Annotated[int, Field(ge=3, le=10)]


class BehaviorOut(Wire):
    schema_version: Literal["deployment-behavior-operation/v1"] = "deployment-behavior-operation/v1"
    verification_id: ProbeID
    deployment_id: Token
    profile_id: Token | None
    state: Literal["prepared", "running", "accepted", "rejected", "unknown", "expired"]
    reason_code: Annotated[str | None, Field(max_length=80)]
    issued_at: Timestamp
    expires_at: Timestamp
    observed_at: Timestamp | None
    time_window: Literal["within", "expired"]
    current_enforcement_verified: Literal[False] = False
    observation_count: Annotated[int, Field(ge=0, le=40)]
    scope: BehaviorScope


def _deployment(session, identity, deployment_id):
    row = session.scalar(select(Deployment).where(Deployment.id == deployment_id,
                                                 Deployment.tenant_id == identity.tenant_id))
    if row is None:
        raise HTTPException(404, "not_found")
    return row


def _journal(identity, deployment_id):
    return BehaviorJournal(get_session_factory(), load_recovery_cipher(), tenant_id=identity.tenant_id,
                           deployment_id=deployment_id, actor_type=identity.identity_type, actor_id=identity.actor_id)


def _output(fact: BehaviorFact) -> BehaviorOut:
    c, r = fact.challenge, fact.result
    return BehaviorOut(verification_id=fact.verification_id, deployment_id=c["binding"]["deployment_id"],
        profile_id=fact.profile_id, state=fact.state, reason_code=fact.reason_code,
        issued_at=c["issued_at"], expires_at=c["expires_at"], observed_at=r["finished_at"] if r else None,
        time_window="within" if datetime.now(UTC) < _time(c["expires_at"]) else "expired",
        observation_count=len(r["observations"]) if r else 0,
        scope=BehaviorScope(target=c["binding"]["target"], policy_revision=c["binding"]["policy_revision"],
            policy_digest=c["binding"]["policy_digest"], transport=c.get("transport", {}).get("mode", "direct_tcp"),
            endpoint=f"{c['receiver_ipv4']}:{c['receiver_port']}", allow_path=c["allow_path"], deny_path=c["deny_path"],
            attempts=c["attempts"]))


@router.get("/api/v1/deployments/{deployment_id}/behavior-verifications", response_model=list[BehaviorOut])
def list_behavior(
    deployment_id: str, response: Response, limit: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    _deployment(session, identity, deployment_id)
    ensure_permission(identity, "policy:read")
    response.headers["Cache-Control"] = "no-store"
    rows = list(session.scalars(select(OpenShellBehaviorOperation).where(
        OpenShellBehaviorOperation.tenant_id == identity.tenant_id,
        OpenShellBehaviorOperation.deployment_id == deployment_id,
    ).order_by(OpenShellBehaviorOperation.created_at.desc(), OpenShellBehaviorOperation.id).limit(limit + 1)))
    rows, truncated = take_page(rows, limit=limit)
    apply_list_meta(response, limit=limit, returned=len(rows), truncated=truncated)
    if not rows:
        return []
    try:
        return [_output(behavior_fact(row, identity.tenant_id, deployment_id)) for row in rows]
    except (BehaviorJournalError, SnapshotError, ValueError, TypeError):
        raise HTTPException(503, "behavior_history_unavailable") from None


@router.get("/api/v1/deployments/{deployment_id}/behavior-verifications/{verification_id}", response_model=BehaviorOut)
def read_behavior(
    deployment_id: str, verification_id: str, response: Response,
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    _deployment(session, identity, deployment_id)
    row = session.scalar(select(OpenShellBehaviorOperation).where(
        OpenShellBehaviorOperation.id == verification_id, OpenShellBehaviorOperation.tenant_id == identity.tenant_id,
        OpenShellBehaviorOperation.deployment_id == deployment_id))
    if row is None:
        raise HTTPException(404, "not_found")
    ensure_permission(identity, "policy:read")
    response.headers["Cache-Control"] = "no-store"
    try:
        return _output(behavior_fact(row, identity.tenant_id, deployment_id))
    except (BehaviorJournalError, SnapshotError, ValueError, TypeError):
        raise HTTPException(503, "behavior_history_unavailable") from None


@router.post("/api/v1/deployments/{deployment_id}/behavior-verifications", response_model=BehaviorOut)
def start_behavior(
    deployment_id: str, body: BehaviorStart | BehaviorStartV2, request: Request, response: Response,
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    deployment = _deployment(session, identity, deployment_id)
    for permission in ("policy:manage", "policy:read"):
        ensure_permission(identity, permission)
    response.headers["Cache-Control"] = "no-store"
    try:
        row = session.scalar(select(OpenShellBehaviorOperation).where(
            OpenShellBehaviorOperation.id == body.verification_id,
            OpenShellBehaviorOperation.tenant_id == identity.tenant_id,
            OpenShellBehaviorOperation.deployment_id == deployment_id))
        if row is not None:
            fact = behavior_fact(row, identity.tenant_id, deployment_id)
            if (fact.profile_id != body.profile_id or
                isinstance(body, BehaviorStartV2) and fact.profile_sha256 != body.profile_sha256):
                raise HTTPException(409, "behavior_request_conflict")
            return _output(fact)  # Historical acknowledgment; no runtime or profile access.
        if (deployment.status != "effective" or deployment.execution_backend != "openshell-cli"
            or os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none") != "openshell-cli"):
            raise HTTPException(409, "behavior_deployment_unavailable")
        session.rollback()  # Release request reads before private journal transactions.
        journal = _journal(identity, deployment_id)
        adapter = OpenShellCliBackend()
        authority = BehaviorAuthority(request, identity, get_session_factory(), adapter)
        coordinator = BehaviorCoordinator(journal, get_engine(), adapter,
            authorize=authority.authorize, before_accept=authority.before_accept)
        return _output(coordinator.run(body.profile_id, body.verification_id,
            expected_profile_sha256=body.profile_sha256 if isinstance(body, BehaviorStartV2) else None))
    except HTTPException:
        raise
    except TargetLockError:
        raise HTTPException(409, "behavior_target_busy") from None
    except (BehaviorJournalError, AdapterError):
        raise HTTPException(409, "behavior_collection_refused") from None
    except (SnapshotError, SQLAlchemyError, ValueError, TypeError):
        raise HTTPException(503, "behavior_collection_unavailable") from None


class BehaviorAssess(Wire):
    schema_version: Literal['deployment-behavior-assess/v1']
    verification_id: ProbeID


class BehaviorAssessmentOut(Wire):
    schema_version: Literal['deployment-behavior-assessment/v1'] = 'deployment-behavior-assessment/v1'
    deployment_id: Token
    verification_id: ProbeID
    evaluated_at: Timestamp
    valid_until: Timestamp | None
    state: Literal['verified', 'not_accepted', 'expired', 'changed', 'unavailable']
    level: Literal['enforcement_verified', 'unverified']
    current_enforcement_verified: bool
    reason_code: Annotated[str, Field(max_length=80)]
    scope: BehaviorScope


@router.post('/api/v1/deployments/{deployment_id}/behavior-assessment', response_model=BehaviorAssessmentOut)
def assess_behavior(
    deployment_id: str, body: BehaviorAssess, request: Request, response: Response,
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    _deployment(session, identity, deployment_id)
    row = session.scalar(select(OpenShellBehaviorOperation).where(
        OpenShellBehaviorOperation.id == body.verification_id,
        OpenShellBehaviorOperation.tenant_id == identity.tenant_id,
        OpenShellBehaviorOperation.deployment_id == deployment_id))
    if row is None:
        raise HTTPException(404, 'not_found')
    ensure_permission(identity, 'policy:read')
    response.headers['Cache-Control'] = 'no-store'
    try:
        fact = behavior_fact(row, identity.tenant_id, deployment_id)
        historical = _output(fact)
    except (BehaviorJournalError, ValueError, TypeError):
        raise HTTPException(503, 'behavior_history_unavailable') from None
    checked_at = datetime.now(UTC)
    accepted, reason = False, 'behavior_operation_not_accepted'
    if fact.state == 'accepted':
        if checked_at >= _time(fact.challenge['expires_at']):
            reason = 'behavior_evidence_expired'
        elif fact.profile_id is None:
            reason = 'behavior_profile_reference_missing'
        else:
            session.rollback()
            try:
                journal = _journal(identity, deployment_id)
                adapter = OpenShellCliBackend()
                authority = BehaviorAuthority(request, identity, get_session_factory(), adapter,
                                              permissions=('policy:read',))
                coordinator = BehaviorCoordinator(journal, get_engine(), adapter,
                    authorize=authority.authorize, before_accept=authority.before_accept)
                accepted, reason, checked_at = coordinator.assess(body.verification_id)
            except (TargetLockError, BehaviorJournalError, AdapterError, SnapshotError,
                    SQLAlchemyError, ValueError, TypeError, RuntimeError):
                reason = 'behavior_current_state_unavailable'
    if accepted and datetime.now(UTC) >= _time(fact.challenge['expires_at']):
        accepted, reason = False, 'behavior_evidence_expired'
    if accepted:
        state = 'verified'
    elif reason in ('behavior_evidence_expired', 'behavior_challenge_expired', 'behavior_time_invalid'):
        state = 'expired'
    elif reason in ('behavior_operation_not_accepted', 'behavior_profile_reference_missing'):
        state = 'not_accepted'
    elif reason == 'behavior_current_state_unavailable':
        state = 'unavailable'
    else:
        state = 'changed'
    return BehaviorAssessmentOut(deployment_id=deployment_id, verification_id=body.verification_id,
        evaluated_at=checked_at.isoformat().replace('+00:00', 'Z'),
        valid_until=fact.challenge['expires_at'] if accepted else None, state=state,
        level='enforcement_verified' if accepted else 'unverified', current_enforcement_verified=accepted,
        reason_code=reason, scope=historical.scope)


class BehaviorProfileOut(Wire):
    profile_id: Token
    profile_sha256: Digest
    issued_at: Timestamp
    expires_at: Timestamp
    timeout_ms: Annotated[int, Field(ge=100, le=10000)]
    scope: BehaviorScope


class BehaviorProfilesOut(Wire):
    schema_version: Literal['deployment-behavior-profiles/v1'] = 'deployment-behavior-profiles/v1'
    deployment_id: Token
    profiles: Annotated[list[BehaviorProfileOut], Field(max_length=32)]


@router.get('/api/v1/deployments/{deployment_id}/behavior-profiles', response_model=BehaviorProfilesOut)
def behavior_profiles(
    deployment_id: str, response: Response,
    session: Session = Depends(get_session), identity: Identity = Depends(get_identity),
):
    deployment = _deployment(session, identity, deployment_id)
    ensure_permission(identity, 'policy:read')
    response.headers['Cache-Control'] = 'no-store'
    if deployment.execution_backend != 'openshell-cli' or deployment.status != 'effective':
        return BehaviorProfilesOut(deployment_id=deployment_id, profiles=[])
    try:
        profiles = load_behavior_profiles()
    except AdapterError:
        raise HTTPException(503, 'behavior_profiles_unavailable') from None
    items = []
    for approved in profiles:
        p = approved.profile
        if (p.binding.tenant_id, p.binding.deployment_id) != (identity.tenant_id, deployment_id):
            continue
        items.append(BehaviorProfileOut(profile_id=p.profile_id, profile_sha256=approved.file_sha256,
            issued_at=p.issued_at, expires_at=p.expires_at, timeout_ms=p.timeout_ms,
            scope=BehaviorScope(target=p.binding.target, policy_revision=p.binding.policy_revision,
                policy_digest=p.binding.policy_digest, transport=p.transport.mode,
                endpoint=f'{p.receiver_ipv4}:{p.receiver_port}', allow_path=p.allow_path, deny_path=p.deny_path,
                attempts=p.attempts)))
    return BehaviorProfilesOut(deployment_id=deployment_id, profiles=items)
