"""Persist the execution reservation before side effects; retries only read it."""

import hashlib
import hmac
import json
from datetime import UTC
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ChangeRequest, Deployment, DeploymentSubmission, Environment, RuntimeBinding
from app.outbox import audit
from app.routers.deployment_preview import PreviewSubmit, Wire, _prepare, _snapshot
from app.routers.policies import execute_deployment
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])


class SubmissionCreate(PreviewSubmit):
    schema_version: Literal["deployment-submission-create/v1"]
    request_key: str = Field(pattern=r"^[a-f0-9-]{36}$")


class SubmissionOut(Wire):
    schema_version: Literal["deployment-submission/v1"] = "deployment-submission/v1"
    id: str = Field(min_length=1, max_length=64)
    change_id: str = Field(min_length=1, max_length=64)
    deployment_id: str = Field(min_length=1, max_length=64)
    state: Literal["unconfirmed", "recorded", "needs_attention"]
    deployment_status: Literal["pending", "sent", "effective", "failed", "rolled_back"]
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    created_at: str


def _change(session, identity, change_id):
    cr = session.scalar(
        select(ChangeRequest).where(ChangeRequest.id == change_id, ChangeRequest.tenant_id == identity.tenant_id)
    )
    if cr is None:
        raise HTTPException(404, "not_found")
    return cr


def _result(session, identity, row):
    deployment = session.scalar(
        select(Deployment).where(
            Deployment.id == row.deployment_id,
            Deployment.tenant_id == identity.tenant_id,
            Deployment.change_request_id == row.change_request_id,
        )
    )
    if deployment is None:
        raise HTTPException(409, "deployment_submission_inconsistent")
    status = deployment.status
    if status not in ("pending", "sent", "effective", "failed", "rolled_back"):
        raise HTTPException(409, "deployment_submission_inconsistent")
    return SubmissionOut(
        id=row.id,
        change_id=row.change_request_id,
        deployment_id=deployment.id,
        state="unconfirmed"
        if status == "pending"
        else "needs_attention"
        if status in ("failed", "rolled_back")
        else "recorded",
        deployment_status=status,
        preview_digest=row.preview_digest,
        created_at=row.created_at.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
    )


def _existing(session, identity, key, digest):
    row = session.scalar(
        select(DeploymentSubmission).where(
            DeploymentSubmission.tenant_id == identity.tenant_id, DeploymentSubmission.request_key == key
        )
    )
    if row is None:
        return None
    if not hmac.compare_digest(row.request_digest, digest):
        raise HTTPException(409, "deployment_submission_key_conflict")
    return _result(session, identity, row)


@router.get("/api/v1/change-requests/{change_id}/deployment-submission", response_model=SubmissionOut)
def read_submission(
    change_id: str,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    _change(session, identity, change_id)
    ensure_permission(identity, "policy:read")
    row = session.scalar(
        select(DeploymentSubmission).where(
            DeploymentSubmission.tenant_id == identity.tenant_id, DeploymentSubmission.change_request_id == change_id
        )
    )
    if row is None:
        raise HTTPException(404, "deployment_submission_not_found")
    response.headers["Cache-Control"] = "no-store"
    return _result(session, identity, row)


@router.post("/api/v1/deployment-submissions", response_model=SubmissionOut, status_code=201)
def create_submission(
    body: SubmissionCreate,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    _change(session, identity, body.change_request_id)
    for model, object_id in ((Environment, body.environment_id), (RuntimeBinding, body.binding_id)):
        if session.scalar(select(model.id).where(model.id == object_id, model.tenant_id == identity.tenant_id)) is None:
            raise HTTPException(404, "not_found")
    for permission in ("policy:read", "policy:manage", "env:read"):
        ensure_permission(identity, permission)
    response.headers["Cache-Control"] = "no-store"
    digest = hashlib.sha256(
        json.dumps(
            {
                "actor": identity.actor_id,
                "actor_type": identity.identity_type,
                "tenant": identity.tenant_id,
                "request": body.model_dump(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    prior = _existing(session, identity, body.request_key, digest)
    if prior is not None:
        response.status_code = 200
        return prior
    if (
        session.scalar(
            select(DeploymentSubmission.id).where(
                DeploymentSubmission.tenant_id == identity.tenant_id,
                DeploymentSubmission.change_request_id == body.change_request_id,
            )
        )
        is not None
    ):
        # A durable claim cannot be released. Refuse another key immediately,
        # without waiting for the running executor's change row lock.
        raise HTTPException(409, "deployment_submission_exists")
    try:
        prepared = _prepare(body, session, identity)
    except HTTPException:
        # Another request may have committed its reservation while we waited
        # for the change row lock. Read it; never execute a duplicate.
        prior = _existing(session, identity, body.request_key, digest)
        if prior is not None:
            response.status_code = 200
            return prior
        raise
    current = _snapshot(prepared, identity)
    if not hmac.compare_digest(body.preview_digest, current.preview_digest):
        raise HTTPException(409, "deployment_preview_changed")
    deployment = Deployment(
        tenant_id=identity.tenant_id,
        environment_id=prepared.environment.id,
        change_request_id=prepared.change.id,
        target=prepared.binding.backend_target_id,
        runtime_binding_id=prepared.binding.id,
        to_revision=f"policy-{prepared.policy.version}",
        status="pending",
    )
    session.add(deployment)
    try:
        session.flush()
        row = DeploymentSubmission(
            tenant_id=identity.tenant_id,
            change_request_id=prepared.change.id,
            deployment_id=deployment.id,
            request_key=body.request_key,
            request_digest=digest,
            preview_digest=current.preview_digest,
        )
        session.add(row)
        session.flush()
        audit(
            session,
            identity.tenant_id,
            identity.identity_type,
            identity.actor_id,
            "deployment.reserve",
            "deployment",
            resource_id=deployment.id,
            summary={"submission_id": row.id, "preview_digest": current.preview_digest},
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        prior = _existing(session, identity, body.request_key, digest)
        if prior is not None:
            response.status_code = 200
            return prior
        raise HTTPException(409, "deployment_submission_exists") from None
    # The committed pending row survives process loss before/during/after apply.
    # It is never expired or replayed, even when no external effect is known.
    submission_id = row.id
    session.expire_all()
    try:
        prepared = _prepare(body, session, identity, allowed_submission_id=submission_id)
        fresh = _snapshot(prepared, identity)
        if not hmac.compare_digest(fresh.preview_digest, current.preview_digest):
            raise HTTPException(409, "deployment_preview_changed")
    except HTTPException:
        # This reservation has not crossed the execution boundary yet.
        deployment.status = "failed"
        deployment.verification = {"level": "failed", "backend_mutated": False}
        audit(
            session,
            identity.tenant_id,
            identity.identity_type,
            identity.actor_id,
            "deployment.fail",
            "deployment",
            resource_id=deployment.id,
            summary={
                "submission_id": submission_id,
                "reason": "submission_recheck_refused",
                "preview_digest": current.preview_digest,
            },
        )
        session.commit()
        return _result(session, identity, row)
    except Exception:
        session.rollback()
        raise HTTPException(502, "deployment_submission_unconfirmed") from None
    try:
        execute_deployment(
            prepared, session, identity, preview_digest=current.preview_digest, reserved_deployment=deployment
        )
    except Exception:
        session.rollback()
        session.expire_all()
        # A committed failure has useful evidence; an uncommitted/unknown
        # outcome remains pending and can only be investigated through reads.
        if session.get(Deployment, deployment.id).status != "failed":
            raise HTTPException(502, "deployment_submission_unconfirmed") from None
    return _result(session, identity, row)
