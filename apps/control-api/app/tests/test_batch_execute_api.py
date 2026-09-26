from datetime import UTC, datetime, timedelta

import pytest

from app import batch_reservation
from app.db import session_scope
from app.models import ChangeRequest
from app.routers import deployment_batch_draft as drafts
from app.routers import deployment_submission as submissions
from app.tests.test_batch_reservation import counts
from app.tests.test_batch_shared_policy import shared_draft


def request(draft):
    return {"schema_version": "enterprise-batch-execute/v1",
            "preview_digest": draft["preview"]["preview_digest"], "confirm_execution": True}


def url(draft):
    return f"/api/v1/deployment-batch-drafts/{draft['id']}/execute"


def test_explicit_execute_and_expired_retry_only_read(client, tenant_a, monkeypatch):
    draft, _, _, _ = shared_draft(client, tenant_a)
    before = counts()
    result = client.post(url(draft), headers=tenant_a, json=request(draft))
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    payload = result.json()
    assert payload["schema_version"] == "enterprise-batch-execution/v1"
    assert payload["retry_executes"] is False and payload["state"] == "recorded"
    assert [item["deployment_status"] for item in payload["items"]] == ["sent", "sent"]
    assert counts()[3] - before[3] == 2
    monkeypatch.setattr(drafts, "_now", lambda: datetime.now(UTC) + timedelta(days=1))
    before = counts()
    assert client.post(url(draft), headers=tenant_a, json=request(draft)).json() == payload
    assert counts() == before


@pytest.mark.parametrize("confirmation", [None, False, 1, "true"])
def test_explicit_boolean_confirmation_required(client, tenant_a, confirmation):
    draft, _, _, _ = shared_draft(client, tenant_a)
    body = request(draft)
    if confirmation is None:
        del body["confirm_execution"]
    else:
        body["confirm_execution"] = confirmation
    before = counts()
    assert client.post(url(draft), headers=tenant_a, json=body).status_code == 422
    assert counts() == before


def test_identity_permissions_digest_and_extra_fields_cannot_override(client, tenant_a, tenant_b):
    draft, _, _, _ = shared_draft(client, tenant_a)
    before = counts()
    for headers, body, status in (
        (tenant_b, request(draft), 404),
        ({**tenant_a, "X-Dev-User-Id": "other-actor"}, request(draft), 403),
        ({**tenant_a, "X-Dev-Roles": "viewer"}, request(draft), 403),
        (tenant_a, {**request(draft), "preview_digest": "0" * 64}, 409),
        (tenant_a, {**request(draft), "tenant_id": tenant_b["X-Dev-Tenant-Id"]}, 422),
    ):
        result = client.post(url(draft), headers=headers, json=body)
        assert result.status_code == status, result.text
        assert counts() == before


@pytest.mark.parametrize("expired", [False, True])
def test_unapproved_or_expired_batch_never_executes(client, tenant_a, monkeypatch, expired):
    draft, _, _, _ = shared_draft(client, tenant_a)
    if expired:
        monkeypatch.setattr(drafts, "_now", lambda: datetime.now(UTC) + timedelta(days=1))
    else:
        with session_scope() as session:
            session.get(ChangeRequest, draft["preview"]["items"][1]["change_id"]).status = "pending"
    before = counts()
    result = client.post(url(draft), headers=tenant_a, json=request(draft))
    assert result.status_code == 409, result.text
    assert counts() == before


def test_unknown_effect_is_not_reexecuted_through_http(client, tenant_a, monkeypatch):
    draft, _, _, _ = shared_draft(client, tenant_a)
    entered = []

    def fail(*args, **kwargs):
        entered.append(True)
        raise RuntimeError("private fixture failure detail")

    monkeypatch.setattr(submissions, "execute_deployment", fail)
    result = client.post(url(draft), headers=tenant_a, json=request(draft))
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "unconfirmed"
    assert [item["deployment_status"] for item in result.json()["items"]] == ["pending", "failed"]
    before = counts()
    assert client.post(url(draft), headers=tenant_a, json=request(draft)).json() == result.json()
    assert entered == [True] and counts() == before
    assert "private fixture" not in result.text


def test_reservation_audit_failure_rolls_back_and_redacts_error(client, tenant_a, monkeypatch):
    draft, _, _, _ = shared_draft(client, tenant_a)

    def fail(*args, **kwargs):
        raise RuntimeError("private fixture audit detail")

    monkeypatch.setattr(batch_reservation, "audit", fail)
    before = counts()
    result = client.post(url(draft), headers=tenant_a, json=request(draft))
    assert result.status_code == 502
    assert "batch_execution_unconfirmed" in result.text and "private fixture" not in result.text
    assert counts() == before
