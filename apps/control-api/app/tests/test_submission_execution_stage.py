"""Batch reuse boundary: only fresh, committed reservations enter execution."""

import uuid

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, Deployment, DeploymentSubmission
from app.routers import deployment_submission as route
from app.tests.test_deployment_submission import counts, post, prepared, read


@pytest.mark.parametrize("interrupt", [False, True])
def test_new_execution_stage_requires_committed_claim_and_is_never_reentered(
    client, tenant_a, env_a, monkeypatch, interrupt
):
    body = prepared(client, tenant_a, env_a)
    calls = []
    original = route._execute_new_reservation

    def stage(request, session, identity, row, deployment):
        # A separate transaction can see both claim and audit before any effect.
        with session_scope() as other:
            saved = other.get(DeploymentSubmission, row.id)
            assert saved is not None and saved.preview_digest == body["preview_digest"]
            assert other.get(Deployment, deployment.id).status == "pending"
            event = other.scalar(select(AuditEvent).where(
                AuditEvent.resource_id == deployment.id, AuditEvent.action == "deployment.reserve",
            ))
            assert event is not None and event.summary["submission_id"] == row.id
        calls.append(row.id)
        if interrupt:
            raise RuntimeError("synthetic process loss before execution stage")
        return original(request, session, identity, row, deployment)

    monkeypatch.setattr(route, "_execute_new_reservation", stage)
    if interrupt:
        with pytest.raises(RuntimeError, match="synthetic process loss"):
            post(client, tenant_a, body)
        expected_state = "unconfirmed"
    else:
        assert post(client, tenant_a, body).status_code == 201
        expected_state = "recorded"
    before = counts()
    for _ in range(2):
        response = post(client, tenant_a, body)
        assert response.status_code == 200 and response.json()["state"] == expected_state
        assert read(client, tenant_a, body).json() == response.json()
    assert post(client, tenant_a, {**body, "request_key": str(uuid.uuid4())}).status_code == 409
    assert len(calls) == 1 and counts() == before
