"""Explicit confirmation for the existing independently approved batch executor."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, StrictBool
from sqlalchemy.orm import Session

from app.batch_execution import execute_batch
from app.db import get_session
from app.routers.deployment_batch_draft import DraftRevalidate
from app.routers.deployment_preview import Wire
from app.routers.deployment_submission import SubmissionOut
from app.security import Identity, get_identity

router = APIRouter(tags=["policies"])


class BatchExecute(Wire):
    schema_version: Literal["enterprise-batch-execute/v1"]
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_execution: StrictBool


class BatchExecutionOut(Wire):
    schema_version: Literal["enterprise-batch-execution/v1"] = "enterprise-batch-execution/v1"
    reservation_id: str
    draft_id: str
    state: Literal["unconfirmed", "recorded", "needs_attention"]
    items: list[SubmissionOut]
    retry_executes: Literal[False] = False


@router.post("/api/v1/deployment-batch-drafts/{draft_id}/execute", response_model=BatchExecutionOut)
def submit_batch(draft_id: str, body: BatchExecute, response: Response,
                 session: Session = Depends(get_session), identity: Identity = Depends(get_identity)):
    response.headers["Cache-Control"] = "no-store"
    if not body.confirm_execution:
        raise HTTPException(422, "batch_execution_confirmation_required")
    try:
        result = execute_batch(draft_id, DraftRevalidate(
            schema_version="enterprise-batch-draft-revalidate/v1", preview_digest=body.preview_digest,
        ), session, identity)
    except HTTPException:
        raise
    except Exception:
        session.rollback()
        raise HTTPException(502, "batch_execution_unconfirmed") from None
    return BatchExecutionOut(reservation_id=result.id, draft_id=result.draft_id,
                             state=result.state, items=result.items)
