"""Durable preview snapshots. There is deliberately no execution endpoint here."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import DeploymentBatchDraft
from app.outbox import audit
from app.routers.deployment_preview import (
    BatchDeploymentPreview,
    BatchPreviewRequest,
    PreviewRequest,
    Wire,
    _locate_batch,
)
from app.routers.deployment_preview import preview_deployment_batch as prepare_batch
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["policies"])


class DraftCreate(BatchPreviewRequest):
    schema_version: Literal["enterprise-batch-draft-create/v1"]
    request_key: UUID


class DraftOut(Wire):
    schema_version: Literal["enterprise-batch-draft/v1"] = "enterprise-batch-draft/v1"
    id: str
    preview: BatchDeploymentPreview
    created_at: datetime
    expires_at: datetime
    state: Literal["previewed", "expired"]
    submission_supported: Literal[False] = False


class DraftRevalidate(Wire):
    schema_version: Literal["enterprise-batch-draft-revalidate/v1"]
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


def _now():
    return datetime.now(UTC)


def _result(row):
    expires = row.expires_at.replace(tzinfo=UTC)
    return DraftOut(
        id=row.id, preview=row.preview, created_at=row.created_at.replace(tzinfo=UTC), expires_at=expires,
        state="expired" if _now() >= expires else "previewed",
    )


def _prior(session, identity, key, digest):
    row = session.scalar(select(DeploymentBatchDraft).where(
        DeploymentBatchDraft.tenant_id == identity.tenant_id, DeploymentBatchDraft.request_key == key,
    ))
    if row is not None and not hmac.compare_digest(row.request_digest, digest):
        raise HTTPException(409, "batch_draft_key_conflict")
    return row


@router.post("/api/v1/deployment-batch-drafts", response_model=DraftOut, status_code=201)
def create_draft(body: DraftCreate, response: Response, session: Session = Depends(get_session),
                 identity: Identity = Depends(get_identity)):
    _locate_batch(body, session, identity)
    response.headers["Cache-Control"] = "no-store"
    request = {
        "schema_version": body.schema_version, "tenant": identity.tenant_id,
        "actor": identity.actor_id, "actor_type": identity.identity_type,
        "items": [item.model_dump() for item in sorted(body.items, key=lambda item: item.binding_id)],
    }
    digest = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    key = str(body.request_key)
    prior = _prior(session, identity, key, digest)
    if prior is not None:
        response.status_code = 200
        return _result(prior)
    started = _now()
    preview = prepare_batch(
        BatchPreviewRequest(schema_version="enterprise-deployment-batch-preview-request/v1", items=body.items),
        response, session, identity,
    )
    row = DeploymentBatchDraft(
        tenant_id=identity.tenant_id, actor_id=identity.actor_id, actor_type=identity.identity_type,
        request_key=key, request_digest=digest, preview=preview.model_dump(),
        created_at=started.replace(tzinfo=None), expires_at=(started + timedelta(minutes=5)).replace(tzinfo=None),
    )
    try:
        session.add(row)
        session.flush()
        audit(session, identity.tenant_id, identity.identity_type, identity.actor_id,
              "deployment.batch_preview.create", "deployment_batch_draft", resource_id=row.id,
              summary={"preview_digest": preview.preview_digest, "item_count": len(preview.items)})
        session.commit()
    except IntegrityError:
        session.rollback()
        prior = _prior(session, identity, key, digest)
        if prior is None:
            raise HTTPException(409, "batch_draft_conflict") from None
        response.status_code = 200
        return _result(prior)
    return _result(row)


def _owned_draft(draft_id, session, identity):
    row = session.scalar(select(DeploymentBatchDraft).where(
        DeploymentBatchDraft.id == draft_id, DeploymentBatchDraft.tenant_id == identity.tenant_id,
    ))
    if row is None:
        raise HTTPException(404, "not_found")
    for permission in ("policy:read", "env:read"):
        ensure_permission(identity, permission)
    if row.actor_id != identity.actor_id or row.actor_type != identity.identity_type:
        raise HTTPException(403, "forbidden")
    return row


@router.get("/api/v1/deployment-batch-drafts/{draft_id}", response_model=DraftOut)
def read_draft(draft_id: str, response: Response, session: Session = Depends(get_session),
               identity: Identity = Depends(get_identity)):
    row = _owned_draft(draft_id, session, identity)
    response.headers["Cache-Control"] = "no-store"
    return _result(row)


@router.post("/api/v1/deployment-batch-drafts/{draft_id}/revalidate", response_model=DraftOut)
def revalidate_draft(draft_id: str, body: DraftRevalidate, response: Response,
                     session: Session = Depends(get_session), identity: Identity = Depends(get_identity)):
    row = _owned_draft(draft_id, session, identity)
    ensure_permission(identity, "policy:manage")
    stored = BatchDeploymentPreview.model_validate(row.preview)

    def check_expiry():
        if _now() >= row.expires_at.replace(tzinfo=UTC):
            raise HTTPException(409, "batch_draft_expired")

    check_expiry()
    if not hmac.compare_digest(body.preview_digest, stored.preview_digest):
        raise HTTPException(409, "batch_draft_changed")
    request = BatchPreviewRequest(
        schema_version="enterprise-deployment-batch-preview-request/v1",
        items=[PreviewRequest(schema_version="deployment-preview-request/v1", change_request_id=item.change_id,
                              environment_id=item.environment_id, binding_id=item.binding_id) for item in stored.items],
    )
    current = prepare_batch(request, response, session, identity)
    check_expiry()
    if not hmac.compare_digest(current.preview_digest, stored.preview_digest):
        raise HTTPException(409, "batch_draft_changed")
    response.headers["Cache-Control"] = "no-store"
    return _result(row)
