from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app import batch_reservation as service
from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, DeploymentBatchReservation, DeploymentSubmission, EdgeTask
from app.routers import deployment_batch_draft as drafts
from app.security import ROLE_PERMISSIONS, Identity
from app.tests.test_deployment_batch_draft import URL, body


def setup(client, headers, env):
    request = body(client, headers, env)
    result = client.post(URL, headers=headers, json=request)
    assert result.status_code == 201, result.text
    draft = result.json()
    roles = frozenset(headers["X-Dev-Roles"].split(","))
    identity = Identity("user", headers["X-Dev-User-Id"], headers["X-Dev-Tenant-Id"], roles,
                        frozenset().union(*(ROLE_PERMISSIONS[role] for role in roles)))
    confirmation = drafts.DraftRevalidate(schema_version="enterprise-batch-draft-revalidate/v1",
                                         preview_digest=draft["preview"]["preview_digest"])
    return request, draft, identity, confirmation


def counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model)) for model in
                (DeploymentBatchReservation, DeploymentSubmission, Deployment, EdgeTask, AuditEvent)]


def reserve(draft, identity, confirmation):
    with session_scope() as session:
        batch, fresh = service.reserve_batch(draft["id"], confirmation, session, identity)
        return batch.id, [(body.model_dump(), row.id, deployment.id) for body, row, deployment in fresh]


def test_atomic_claim_and_existing_claim_never_return_fresh_execution_items(client, tenant_a, env_a, monkeypatch):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    before = counts()
    batch_id, fresh = reserve(draft, identity, confirmation)
    assert len(fresh) == 2
    assert [a - b for a, b in zip(counts(), before, strict=True)] == [1, 2, 2, 0, 3]
    with session_scope() as session:
        batch = session.get(DeploymentBatchReservation, batch_id)
        assert batch.submission_ids == [row_id for _, row_id, _ in fresh]
        for request, row_id, deployment_id in fresh:
            assert session.get(Deployment, deployment_id).status == "pending"
            saved = session.get(DeploymentSubmission, row_id)
            assert saved.request_digest == service.submission_request_digest(
                service.SubmissionCreate(**request), identity
            )
    monkeypatch.setattr(drafts, "_now", lambda: datetime.now(UTC) + timedelta(days=1))
    before = counts()
    assert reserve(draft, identity, confirmation) == (batch_id, [])
    assert counts() == before


@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_any_audit_failure_rolls_back_all_items(client, tenant_a, env_a, monkeypatch, fail_at):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    original = service.audit
    calls = []

    def failing(*args, **kwargs):
        calls.append(True)
        if len(calls) == fail_at:
            raise RuntimeError("synthetic audit failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "audit", failing)
    before = counts()
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        reserve(draft, identity, confirmation)
    assert counts() == before


def test_deadline_rechecked_before_committing_claims(client, tenant_a, env_a, monkeypatch):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    original = service.audit

    def expire(*args, **kwargs):
        result = original(*args, **kwargs)
        monkeypatch.setattr(drafts, "_now", lambda: datetime.now(UTC) + timedelta(days=1))
        return result

    monkeypatch.setattr(service, "audit", expire)
    before = counts()
    with pytest.raises(HTTPException) as error:
        reserve(draft, identity, confirmation)
    assert error.value.detail == "batch_draft_expired" and counts() == before


def test_authority_and_unapproved_item_fail_without_claims(client, tenant_a, tenant_b, env_a):
    request, draft, identity, confirmation = setup(client, tenant_a, env_a)
    before = counts()
    for other, code in (
        (replace(identity, tenant_id=tenant_b["X-Dev-Tenant-Id"]), 404),
        (replace(identity, actor_id="another"), 403),
        (replace(identity, permissions=frozenset()), 403),
    ):
        with pytest.raises(HTTPException) as error:
            reserve(draft, other, confirmation)
        assert error.value.status_code == code
    with session_scope() as session:
        session.get(ChangeRequest, request["items"][1]["change_request_id"]).status = "pending"
    with pytest.raises(HTTPException) as error:
        reserve(draft, identity, confirmation)
    assert error.value.detail == "change_not_approved"
    assert counts() == before
