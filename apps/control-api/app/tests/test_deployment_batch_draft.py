import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, DeploymentBatchDraft, EdgeTask
from app.routers import deployment_batch_draft as route
from app.tests.test_deployment_preview import setup

URL = "/api/v1/deployment-batch-drafts"


def body(client, headers, env):
    items = [setup(client, headers, env, target="draft-" + uuid.uuid4().hex)[0] for _ in range(2)]
    return {"schema_version": "enterprise-batch-draft-create/v1", "request_key": str(uuid.uuid4()), "items": items}


def counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(m)) for m in
                (DeploymentBatchDraft, AuditEvent, Deployment, EdgeTask)]


def test_draft_survives_refresh_and_replay_without_execution(client, tenant_a, env_a, monkeypatch):
    request = body(client, tenant_a, env_a)
    before = counts()
    now = datetime(2026, 9, 25, tzinfo=UTC)
    monkeypatch.setattr(route, "_now", lambda: now)
    response = client.post(URL, headers=tenant_a, json=request)
    assert response.status_code == 201, response.text
    value = response.json()
    assert value["submission_supported"] is False and value["state"] == "previewed"
    assert value["expires_at"] == "2026-09-25T00:05:00Z"
    assert [a - b for a, b in zip(counts(), before, strict=True)] == [1, 1, 0, 0]

    def unexpected(*args, **kwargs):
        pytest.fail("replay/read must not call backend preparation")

    monkeypatch.setattr(route, "prepare_batch", unexpected)
    for _ in range(2):
        replay = client.post(URL, headers=tenant_a, json={**request, "items": request["items"][::-1]})
        assert replay.status_code == 200 and replay.json() == value
        read = client.get(URL + "/" + value["id"], headers=tenant_a)
        assert read.json() == value and read.headers["cache-control"] == "no-store"
    monkeypatch.setattr(route, "_now", lambda: now + timedelta(minutes=5))
    expired = client.post(URL, headers=tenant_a, json=request)
    assert expired.status_code == 200 and expired.json()["state"] == "expired"
    assert expired.json()["expires_at"] == value["expires_at"]
    assert [a - b for a, b in zip(counts(), before, strict=True)] == [1, 1, 0, 0]


def test_draft_actor_tenant_and_request_conflicts(client, tenant_a, tenant_b, env_a):
    request = body(client, tenant_a, env_a)
    created = client.post(URL, headers=tenant_a, json=request).json()
    before = counts()
    other = {**tenant_a, "X-Dev-User-Id": "another-user"}
    assert client.post(URL, headers=other, json=request).status_code == 409
    assert client.get(URL + "/" + created["id"], headers=other).status_code == 403
    assert client.get(URL + "/" + created["id"], headers=tenant_b).status_code == 404
    assert client.post(URL, headers=tenant_b, json=request).status_code == 404
    assert client.post(URL, headers={**tenant_a, "X-Dev-Roles": "viewer"}, json=request).status_code == 403
    assert client.post(URL, headers=tenant_a, json={**request, "items": request["items"][:1]}).status_code == 409
    assert client.post(URL, headers=tenant_a, json={**request, "expires_at": "2099"}).status_code == 422
    assert client.post(URL, headers=tenant_a, json={**request, "request_key": "bad"}).status_code == 422
    assert counts() == before


def test_audit_failure_rolls_back_entire_draft(client, tenant_a, env_a, monkeypatch):
    request = body(client, tenant_a, env_a)
    before = counts()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    monkeypatch.setattr(route, "audit", fail)
    with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
        client.post(URL, headers=tenant_a, json=request)
    assert counts() == before


def test_one_unapproved_item_prevents_draft_and_audit_creation(client, tenant_a, env_a):
    request = body(client, tenant_a, env_a)
    with session_scope() as session:
        session.get(ChangeRequest, request["items"][1]["change_request_id"]).status = "pending"
    before = counts()
    result = client.post(URL, headers=tenant_a, json=request)
    assert result.status_code == 409
    assert result.json() == {"detail": "change_not_approved"}
    assert counts() == before
