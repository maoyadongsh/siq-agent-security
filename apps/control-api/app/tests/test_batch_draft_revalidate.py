from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.db import session_scope
from app.models import ChangeRequest, DeploymentBatchDraft, DesiredPolicy, RuntimeBinding
from app.routers import deployment_batch_draft as route
from app.tests.test_deployment_batch_draft import URL, body, counts
from app.tests.test_deployment_preview import cli_scope, setup  # noqa: F401
from app.tests.test_openshell_policy_operations import StatefulRunner


def fixture(client, headers, env, monkeypatch):
    now = datetime(2026, 9, 25, tzinfo=UTC)
    monkeypatch.setattr(route, "_now", lambda: now)
    request = body(client, headers, env)
    response = client.post(URL, headers=headers, json=request)
    assert response.status_code == 201, response.text
    draft = response.json()
    return now, request, draft


def revalidate(client, headers, draft, **extra):
    return client.post(URL + "/" + draft["id"] + "/revalidate", headers=headers, json={
        "schema_version": "enterprise-batch-draft-revalidate/v1",
        "preview_digest": draft["preview"]["preview_digest"], **extra,
    })


def test_unchanged_revalidation_is_read_only_and_does_not_extend_expiry(client, tenant_a, env_a, monkeypatch):
    now, _, draft = fixture(client, tenant_a, env_a, monkeypatch)
    before = counts()
    monkeypatch.setattr(route, "_now", lambda: now + timedelta(minutes=4))
    for _ in range(2):
        response = revalidate(client, tenant_a, draft)
        assert response.status_code == 200, response.text
        assert response.json() == draft
        assert response.headers["cache-control"] == "no-store"
    assert counts() == before


@pytest.mark.parametrize("mutation,code", [
    ("binding", "binding_revoked"), ("approval", "change_not_approved"),
    ("policy", "batch_draft_changed"),
])
def test_changed_item_refuses_whole_revalidation(client, tenant_a, env_a, monkeypatch, mutation, code):
    _, request, draft = fixture(client, tenant_a, env_a, monkeypatch)
    item = request["items"][1]
    with session_scope() as session:
        if mutation == "binding":
            session.get(RuntimeBinding, item["binding_id"]).status = "revoked"
        elif mutation == "approval":
            session.get(ChangeRequest, item["change_request_id"]).status = "pending"
        else:
            change = session.get(ChangeRequest, item["change_request_id"])
            session.get(DesiredPolicy, change.policy_id).name = "changed-preview-name"
    before = counts()
    response = revalidate(client, tenant_a, draft)
    assert response.status_code == 409 and response.json() == {"detail": code}
    with session_scope() as session:
        assert session.get(DeploymentBatchDraft, draft["id"]).preview == draft["preview"]
    assert counts() == before


def test_expiry_checked_before_and_after_slow_preflight(client, tenant_a, env_a, monkeypatch):
    now, _, draft = fixture(client, tenant_a, env_a, monkeypatch)
    before = counts()
    prepare = route.prepare_batch
    calls = []

    def slow(*args, **kwargs):
        calls.append(True)
        result = prepare(*args, **kwargs)
        monkeypatch.setattr(route, "_now", lambda: now + timedelta(minutes=5))
        return result

    monkeypatch.setattr(route, "prepare_batch", slow)
    response = revalidate(client, tenant_a, draft)
    assert response.status_code == 409 and response.json()["detail"] == "batch_draft_expired"
    response = revalidate(client, tenant_a, draft)
    assert response.status_code == 409 and response.json()["detail"] == "batch_draft_expired"
    assert calls == [True] and counts() == before


def test_identity_digest_and_strict_request_denials_do_not_probe(client, tenant_a, tenant_b, env_a, monkeypatch):
    _, _, draft = fixture(client, tenant_a, env_a, monkeypatch)
    before = counts()

    def unexpected(*args, **kwargs):
        pytest.fail("invalid confirmation must not probe targets")

    monkeypatch.setattr(route, "prepare_batch", unexpected)
    assert revalidate(client, tenant_b, draft).status_code == 404
    assert revalidate(client, {**tenant_a, "X-Dev-User-Id": "other"}, draft).status_code == 403
    assert revalidate(client, {**tenant_a, "X-Dev-Roles": "viewer"}, draft).status_code == 403
    assert revalidate(client, tenant_a, draft, preview_digest="0" * 64).status_code == 409
    assert revalidate(client, tenant_a, draft, preview_digest="invalid").status_code == 422
    assert revalidate(client, tenant_a, draft, approved=True).status_code == 422
    assert counts() == before


def test_live_revision_drift_rejects_stored_draft_without_apply(client, request, monkeypatch, tmp_path):
    from app.tests.binding_helpers import assign_target_authority

    headers, env = request.getfixturevalue("cli_scope")
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="")
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: backend)
    item, _ = setup(client, headers, env, backend="openshell-cli", target="s1")
    assign_target_authority(monkeypatch, tmp_path, item["binding_id"], backend)
    response = client.post(URL, headers=headers, json={
        "schema_version": "enterprise-batch-draft-create/v1", "request_key": str(uuid4()), "items": [item],
    })
    assert response.status_code == 201, response.text
    draft = response.json()
    before = counts()
    runner.revision += 1
    response = revalidate(client, headers, draft)
    assert response.status_code == 409 and response.json() == {"detail": "batch_draft_changed"}
    assert runner.set_calls == 0 and counts() == before
