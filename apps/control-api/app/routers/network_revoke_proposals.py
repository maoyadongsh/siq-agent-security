"""Transactional new-version proposals; no approval or runtime mutation."""

import hashlib
import hmac
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.adapters.openshell.network_change import assess_network_change
from app.adapters.openshell.policy_safety import validate_network_rules
from app.db import get_session
from app.models import ChangeRequest, DesiredPolicy, new_id
from app.network_revoke_plan import NetworkRevokePlanError, plan_network_revoke
from app.outbox import audit, emit_event
from app.routers.change_review import _section
from app.routers.deployment_preview import Wire
from app.routers.policies import _desired_from_policy, _validate_policy_static
from app.rulepack import load_rulepack
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])


class Selection(Wire):
    endpoint: str = Field(min_length=1, max_length=512)
    binary_path: str = Field(min_length=1, max_length=512)


class Proposal(Wire):
    schema_version: Literal["enterprise-network-revoke-proposal/v1"]
    baseline_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_key: UUID
    selections: list[Selection] = Field(min_length=1, max_length=256)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode()).hexdigest()


def locate(session, identity, policy_id):
    policy = session.scalar(select(DesiredPolicy).where(
        DesiredPolicy.tenant_id == identity.tenant_id, DesiredPolicy.id == policy_id,
    ).with_for_update())
    if policy is None:
        raise HTTPException(404, "not_found")
    for permission in ("policy:read", "policy:manage", "change:propose"):
        ensure_permission(identity, permission)
    return policy


def baseline(policy, identity):
    return digest({"tenant": identity.tenant_id, "actor": identity.actor_id,
                   "actor_type": identity.identity_type, "name": policy.name,
                   "policy": _desired_from_policy(policy)})


def result(cr, source):
    return {"schema_version": "enterprise-network-revoke-proposal-result/v1",
            "source_policy_id": source, "policy_id": cr.policy_id, "change_request_id": cr.id,
            "requires_independent_approval": True, "executed": False}


def existing_result(session, identity, key, request_digest, source):
    cr = session.scalar(select(ChangeRequest).where(
        ChangeRequest.tenant_id == identity.tenant_id, ChangeRequest.idempotency_key == key))
    if cr is None:
        return None
    if (cr.proposer_user_id != identity.actor_id
        or cr.impact.get("network_revoke_request_digest") != request_digest):
        raise HTTPException(409, "network_revoke_request_conflict")
    return result(cr, source)


@router.get("/api/v1/policies/{policy_id}/network-revoke-baseline")
def read_baseline(policy_id: str, response: Response, session: Session = Depends(get_session),
                  identity: Identity = Depends(get_identity)):
    policy = locate(session, identity, policy_id)
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "enterprise-network-revoke-baseline/v1", "policy_id": policy.id,
            "policy_version": policy.version, "baseline_digest": baseline(policy, identity)}


@router.get("/api/v1/policies/{policy_id}/network-revoke-options")
def read_options(policy_id: str, response: Response, session: Session = Depends(get_session),
                 identity: Identity = Depends(get_identity)):
    policy = locate(session, identity, policy_id)
    if assess_network_change(policy.network, policy.network) == "unknown":
        raise HTTPException(422, "network_revoke_baseline_unsupported")
    pairs = sorted({(rule["endpoint"], path) for rule in validate_network_rules(policy.network)
                    for path in rule["binary_paths"]})
    if len(pairs) > 256 or any(len(endpoint) > 512 or len(path) > 512 for endpoint, path in pairs):
        raise HTTPException(422, "network_revoke_options_unavailable")
    selections = [{"endpoint": endpoint, "binary_path": path} for endpoint, path in pairs]
    _, _, rules = load_rulepack()
    safe = _section("network", "network", selections, rules)
    if safe.redacted or safe.truncated:
        raise HTTPException(422, "network_revoke_options_unavailable")
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "enterprise-network-revoke-options/v1", "policy_id": policy.id,
            "policy_version": policy.version, "baseline_digest": baseline(policy, identity),
            "selections": selections, "coverage": "complete_policy_network"}


@router.post("/api/v1/policies/{policy_id}/network-revoke-proposals", status_code=201)
def propose(policy_id: str, body: Proposal, response: Response, session: Session = Depends(get_session),
            identity: Identity = Depends(get_identity)):
    source = locate(session, identity, policy_id)
    response.headers["Cache-Control"] = "no-store"
    selections = sorted((item.model_dump() for item in body.selections),
                        key=lambda item: (item["endpoint"], item["binary_path"]))
    key = "nrp-" + digest([identity.tenant_id, str(body.request_key)])
    request_digest = digest([identity.tenant_id, identity.actor_id, identity.identity_type,
                             source.id, body.baseline_digest, selections])
    saved = existing_result(session, identity, key, request_digest, policy_id)
    if saved:
        return saved
    try:
        value = stage_proposal(session, identity, source, body.baseline_digest, selections, key, request_digest)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        saved = existing_result(session, identity, key, request_digest, policy_id)
        if saved:
            return saved
        raise HTTPException(409, "network_revoke_concurrent_change") from None
    except Exception:
        session.rollback()
        raise HTTPException(503, "network_revoke_proposal_unavailable") from None
    return value


def stage_proposal(session, identity, source, baseline_digest, selections, key, request_digest):
    """Stage one proposal and its evidence; the caller owns the transaction boundary."""
    if not hmac.compare_digest(baseline(source, identity), baseline_digest):
        raise HTTPException(409, "network_revoke_baseline_changed")
    try:
        planned = plan_network_revoke(_desired_from_policy(source), selections)
    except NetworkRevokePlanError as exc:
        raise HTTPException(422, str(exc)) from None
    planned.pop("policy_id")
    planned.pop("version")
    planned.pop("status")
    version = session.scalar(select(func.max(DesiredPolicy.version)).where(
        DesiredPolicy.tenant_id == identity.tenant_id, DesiredPolicy.name == source.name)) + 1
    policy = DesiredPolicy(id=new_id("pol"), tenant_id=identity.tenant_id, name=source.name,
                           version=version, status="validated", **planned)
    if _validate_policy_static(policy):
        raise HTTPException(422, "network_revoke_policy_invalid")
    cr = ChangeRequest(id=new_id("cr"), tenant_id=identity.tenant_id, policy_id=policy.id,
                       proposer_user_id=identity.actor_id, approval_policy="standard", status="proposed",
                       idempotency_key=key,
                       diff={"policy_version": version, "enforcement_mode": policy.enforcement_mode},
                       impact={"source_policy_id": source.id, "source_policy_version": source.version,
                               "proposal_actor_type": identity.identity_type,
                               "network_revoke_request_digest": request_digest})
    session.add(policy)
    session.flush()
    session.add(cr)
    for action, kind, resource in (("policy.create", "desired_policy", policy.id),
                                   ("change.request.create", "change_request", cr.id)):
        audit(session, identity.tenant_id, identity.identity_type, identity.actor_id, action, kind,
              resource_id=resource, summary={"source_policy_id": source.id, "request_digest": request_digest})
    emit_event(session, identity.tenant_id, "policy.change.requested.v1",
               {"change_request_id": cr.id, "policy_id": policy.id}, resource_ref=cr.id)
    return result(cr, source.id)


@router.get("/api/v1/policies/{policy_id}/network-revoke-proposals/{request_key}")
def recover_proposal(policy_id: str, request_key: UUID, response: Response,
                     session: Session = Depends(get_session), identity: Identity = Depends(get_identity)):
    # Locate every object and the original actor before permissions; never use the UUID as authority.
    source = session.scalar(select(DesiredPolicy.id).where(
        DesiredPolicy.tenant_id == identity.tenant_id, DesiredPolicy.id == policy_id))
    key = "nrp-" + digest([identity.tenant_id, str(request_key)])
    cr = session.scalar(select(ChangeRequest).where(
        ChangeRequest.tenant_id == identity.tenant_id, ChangeRequest.idempotency_key == key,
        ChangeRequest.proposer_user_id == identity.actor_id))
    if (source is None or cr is None or not isinstance(cr.impact, dict)
        or cr.impact.get("source_policy_id") != policy_id
        or cr.impact.get("proposal_actor_type") != identity.identity_type):
        raise HTTPException(404, "not_found")
    child = session.scalar(select(DesiredPolicy.id).where(
        DesiredPolicy.tenant_id == identity.tenant_id, DesiredPolicy.id == cr.policy_id))
    if child is None:
        raise HTTPException(404, "not_found")
    for permission in ("policy:read", "policy:manage", "change:propose"):
        ensure_permission(identity, permission)
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "enterprise-network-revoke-recovery/v1", "source_policy_id": policy_id,
            "policy_id": cr.policy_id, "change_request_id": cr.id, "change_status": cr.status,
            "lookup_executed": False}
