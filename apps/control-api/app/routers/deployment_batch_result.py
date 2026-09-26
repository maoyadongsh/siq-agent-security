"""Read durable batch dispositions without interpreting pending as safe to retry."""

import hmac
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Deployment, DeploymentBatchReservation, DeploymentSubmission
from app.routers.deployment_batch_draft import _owned_draft
from app.routers.deployment_preview import BatchDeploymentPreview, Wire
from app.routers.deployment_submission import SubmissionCreate, SubmissionOut, _result, submission_request_digest
from app.security import Identity, get_identity

router = APIRouter(tags=["policies"])


class BatchReservationOut(Wire):
    schema_version: Literal["enterprise-batch-reservation/v1"] = "enterprise-batch-reservation/v1"
    id: str
    draft_id: str
    state: Literal["unconfirmed", "recorded", "needs_attention"]
    items: list[SubmissionOut]
    execution_supported: Literal[False] = False


def _validate(model, value):
    try:
        return model.model_validate(value)
    except ValidationError:
        raise HTTPException(409, "batch_reservation_inconsistent") from None


def _same_digest(value, expected):
    return isinstance(value, str) and len(value) == 64 and value.isascii() and hmac.compare_digest(value, expected)


@router.get("/api/v1/deployment-batch-drafts/{draft_id}/reservation", response_model=BatchReservationOut)
def read_batch_reservation(draft_id: str, response: Response, session: Session = Depends(get_session),
                           identity: Identity = Depends(get_identity)):
    draft = _owned_draft(draft_id, session, identity)
    batch = session.scalar(select(DeploymentBatchReservation).where(
        DeploymentBatchReservation.tenant_id == identity.tenant_id,
        DeploymentBatchReservation.draft_id == draft_id,
    ))
    if batch is None:
        raise HTTPException(404, "batch_reservation_not_found")
    stored = _validate(BatchDeploymentPreview, draft.preview)
    ids = batch.submission_ids
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 20 or len(ids) != len(stored.items)
            or any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids)):
        raise HTTPException(409, "batch_reservation_inconsistent")
    results = []
    for submission_id, item in zip(ids, stored.items, strict=True):
        submission = session.scalar(select(DeploymentSubmission).where(
            DeploymentSubmission.id == submission_id, DeploymentSubmission.tenant_id == identity.tenant_id,
        ))
        if submission is None or submission.change_request_id != item.change_id:
            raise HTTPException(409, "batch_reservation_inconsistent")
        deployment = session.scalar(select(Deployment).where(
            Deployment.id == submission.deployment_id, Deployment.tenant_id == identity.tenant_id,
            Deployment.change_request_id == item.change_id, Deployment.environment_id == item.environment_id,
            Deployment.runtime_binding_id == item.binding_id, Deployment.target == item.target,
        ))
        expected = _validate(SubmissionCreate, {
            "schema_version": "deployment-submission-create/v1", "request_key": submission.request_key,
            "change_request_id": item.change_id, "environment_id": item.environment_id, "binding_id": item.binding_id,
            "preview_digest": item.preview_digest,
        })
        if (deployment is None or not _same_digest(submission.preview_digest, item.preview_digest)
                or not _same_digest(submission.request_digest, submission_request_digest(expected, identity))):
            raise HTTPException(409, "batch_reservation_inconsistent")
        results.append(_result(session, identity, submission))
    # Unknown takes precedence: a known failure does not erase another item's uncertainty.
    states = {item.state for item in results}
    state = (
        "unconfirmed" if "unconfirmed" in states else "needs_attention" if "needs_attention" in states else "recorded"
    )
    response.headers["Cache-Control"] = "no-store"
    return BatchReservationOut(id=batch.id, draft_id=draft_id, state=state, items=results)
