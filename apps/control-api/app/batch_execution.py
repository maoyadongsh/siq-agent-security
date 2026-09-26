"""Execute only newly reserved items, sequentially; uncertain effects never replay."""

from datetime import UTC

from fastapi import HTTPException, Response
from sqlalchemy import select

from app.batch_reservation import reserve_batch
from app.models import Deployment
from app.outbox import audit
from app.routers import deployment_batch_draft as drafts
from app.routers import deployment_submission as submissions
from app.routers.deployment_batch_result import read_batch_reservation


def _stop_unstarted(items, session, identity, reason):
    """Only items never entered by this live invocation may be marked no-effect."""
    if not items:
        return
    try:
        for body, submission, deployment in items:
            row = session.scalar(select(Deployment).where(
                Deployment.id == deployment.id, Deployment.tenant_id == identity.tenant_id,
                Deployment.change_request_id == body.change_request_id,
            ).with_for_update().execution_options(populate_existing=True))
            if row is None or row.status != "pending":
                raise HTTPException(409, "batch_unstarted_state_changed")
            row.status = "failed"
            row.verification = {"level": "failed", "backend_mutated": False, "reason": reason}
            audit(session, identity.tenant_id, identity.identity_type, identity.actor_id,
                  "deployment.fail", "deployment", resource_id=row.id,
                  summary={"submission_id": submission.id, "reason": reason, "preview_digest": body.preview_digest})
        session.commit()
    except Exception:
        session.rollback()
        raise HTTPException(502, "batch_stop_unconfirmed") from None


def execute_batch(draft_id, body: drafts.DraftRevalidate, session, identity):
    """Internal orchestration, not a public retry/approval endpoint.

    Existing reservations yield no fresh items and therefore only a read. The
    caller owns this request's session; never reconstruct fresh items after loss.
    """
    _, fresh = reserve_batch(draft_id, body, session, identity)
    if fresh:
        draft = drafts._owned_draft(draft_id, session, identity)
        deadline = draft.expires_at.replace(tzinfo=UTC)
        for index, (request, submission, deployment) in enumerate(fresh):
            if drafts._now() >= deadline:
                _stop_unstarted(fresh[index:], session, identity, "batch_deadline_before_start")
                break
            try:
                result = submissions._execute_new_reservation(
                    request, session, identity, submission, deployment, deadline=deadline,
                )
            except Exception:
                session.rollback()
                # The current item's external effect may be unknown: never mark it no-effect.
                _stop_unstarted(fresh[index + 1:], session, identity, "batch_stopped_after_unconfirmed")
                break
            if result.state != "recorded":
                _stop_unstarted(fresh[index + 1:], session, identity, "batch_stopped_after_failure")
                break
    return read_batch_reservation(draft_id, Response(), session, identity)
