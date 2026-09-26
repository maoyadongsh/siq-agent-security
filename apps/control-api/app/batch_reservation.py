"""Reserve all items atomically, with no external apply and no replay authority."""

import hmac
from datetime import UTC
from uuid import uuid4

from fastapi import HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Deployment, DeploymentBatchReservation, DeploymentSubmission
from app.outbox import audit
from app.routers import deployment_batch_draft as drafts
from app.routers.deployment_preview import BatchDeploymentPreview, BatchPreviewRequest, PreviewRequest
from app.routers.deployment_submission import SubmissionCreate, submission_request_digest
from app.security import ensure_permission


def _existing(session, identity, draft_id):
    return session.scalar(select(DeploymentBatchReservation).where(
        DeploymentBatchReservation.tenant_id == identity.tenant_id,
        DeploymentBatchReservation.draft_id == draft_id,
    ))


def reserve_batch(draft_id, body: drafts.DraftRevalidate, session, identity):
    """Return (batch, fresh_items); fresh_items is always empty for a prior claim.

    This owns the commit boundary. Never call with unrelated pending DB changes.
    Each new tuple is (SubmissionCreate, DeploymentSubmission, Deployment), usable
    only by the current request's future executor, never reconstructed on retry.
    """
    draft = drafts._owned_draft(draft_id, session, identity)
    ensure_permission(identity, "policy:manage")
    stored = BatchDeploymentPreview.model_validate(draft.preview)
    if not hmac.compare_digest(body.preview_digest, stored.preview_digest):
        raise HTTPException(409, "batch_draft_changed")
    prior = _existing(session, identity, draft_id)
    if prior is not None:
        return prior, []
    expires = draft.expires_at.replace(tzinfo=UTC)

    def check_expiry():
        if drafts._now() >= expires:
            raise HTTPException(409, "batch_draft_expired")

    request = BatchPreviewRequest(
        schema_version="enterprise-deployment-batch-preview-request/v1",
        items=[PreviewRequest(schema_version="deployment-preview-request/v1", change_request_id=item.change_id,
                              environment_id=item.environment_id, binding_id=item.binding_id) for item in stored.items],
    )
    fresh = []
    try:
        check_expiry()
        current = drafts.prepare_batch(request, Response(), session, identity)
        check_expiry()
        if not hmac.compare_digest(current.preview_digest, stored.preview_digest):
            raise HTTPException(409, "batch_draft_changed")
        for item in current.items:
            submission_body = SubmissionCreate(
                schema_version="deployment-submission-create/v1", request_key=str(uuid4()),
                change_request_id=item.change_id, environment_id=item.environment_id,
                binding_id=item.binding_id, preview_digest=item.preview_digest,
            )
            deployment = Deployment(
                tenant_id=identity.tenant_id, environment_id=item.environment_id, change_request_id=item.change_id,
                target=item.target, runtime_binding_id=item.binding_id, to_revision=f"policy-{item.policy_version}",
                status="pending",
            )
            session.add(deployment)
            session.flush()
            submission = DeploymentSubmission(
                tenant_id=identity.tenant_id, change_request_id=item.change_id, deployment_id=deployment.id,
                request_key=submission_body.request_key,
                request_digest=submission_request_digest(submission_body, identity), preview_digest=item.preview_digest,
            )
            session.add(submission)
            session.flush()
            audit(session, identity.tenant_id, identity.identity_type, identity.actor_id,
                  "deployment.reserve", "deployment", resource_id=deployment.id,
                  summary={"submission_id": submission.id, "preview_digest": item.preview_digest})
            fresh.append((submission_body, submission, deployment))
        batch = DeploymentBatchReservation(
            tenant_id=identity.tenant_id, draft_id=draft_id, submission_ids=[row.id for _, row, _ in fresh],
        )
        session.add(batch)
        session.flush()
        audit(session, identity.tenant_id, identity.identity_type, identity.actor_id,
              "deployment.batch_reserve", "deployment_batch_reservation", resource_id=batch.id,
              summary={"draft_id": draft_id, "preview_digest": stored.preview_digest, "item_count": len(fresh)})
        check_expiry()
        session.commit()
    except (IntegrityError, HTTPException) as exc:
        session.rollback()
        prior = _existing(session, identity, draft_id)
        if prior is not None:
            return prior, []
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(409, "batch_reservation_conflict") from None
    except Exception:
        session.rollback()
        raise
    return batch, fresh
