import uuid

import pytest

from app.db import session_scope
from app.models import ChangeRequest, DesiredPolicy
from app.routers import deployment_preview
from app.tests.test_deployment_preview import counts, setup

ROUTE = "/api/v1/deployment-previews/batch"


def request(items):
    return {"schema_version": "enterprise-deployment-batch-preview-request/v1", "items": items}


@pytest.mark.parametrize("field", ["change_request_id", "environment_id", "binding_id", "policy"])
@pytest.mark.parametrize("role", ["tenant_admin,security_admin,agent_owner,platform_operator", "viewer"])
def test_entire_batch_located_before_permissions_or_preflight(
    client, tenant_a, tenant_b, env_a, monkeypatch, field, role
):
    first, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    second, policy = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    if field == "policy":
        with session_scope() as session:
            session.get(DesiredPolicy, policy["id"]).tenant_id = tenant_b["X-Dev-Tenant-Id"]
    else:
        second = {**second, field: "missing-object"}
    calls = []
    original = deployment_preview._prepare

    def tracked(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(deployment_preview, "_prepare", tracked)
    before = counts()
    for items in ([first, second], [second, first]):
        response = client.post(ROUTE, headers={**tenant_a, "X-Dev-Roles": role}, json=request(items))
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "not_found"}
    assert calls == []
    assert counts() == before


@pytest.mark.parametrize("field", ["change_request_id", "environment_id", "binding_id"])
def test_foreign_reference_rejected_without_preparing_any_item(
    client, tenant_a, tenant_b, env_a, env_b, monkeypatch, field
):
    first, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    second, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    # Explicit fixture creator privileges; the tested caller remains tenant A.
    foreign_creator = {**tenant_b, "X-Dev-Roles": tenant_a["X-Dev-Roles"]}
    foreign, _ = setup(client, foreign_creator, env_b, target="batch-" + uuid.uuid4().hex)
    second[field] = foreign[field]

    def unexpected(*args, **kwargs):
        pytest.fail("foreign batch must be rejected before preparing any item")

    monkeypatch.setattr(deployment_preview, "_prepare", unexpected)
    before = counts()
    for headers in (tenant_a, {**tenant_a, "X-Dev-Roles": "viewer"}):
        response = client.post(ROUTE, headers=headers, json=request([first, second]))
        assert response.status_code == 404, response.text
        assert response.json() == {"detail": "not_found"}
    denied = client.post(ROUTE, headers={**tenant_a, "X-Dev-Roles": "viewer"}, json=request([first]))
    assert denied.status_code == 403 and denied.json() == {"detail": "forbidden"}
    assert counts() == before


def test_batch_preview_sorted_bound_and_read_only(client, tenant_a, env_a):
    first, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    second, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    before = counts()
    response = client.post(ROUTE, headers=tenant_a, json=request([first, second]))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    value = response.json()
    assert value["batch_submission_supported"] is False
    assert [item["binding_id"] for item in value["items"]] == sorted([first["binding_id"], second["binding_id"]])
    assert client.post(ROUTE, headers=tenant_a, json=request([second, first])).json() == value
    other_actor = {**tenant_a, "X-Dev-User-Id": "batch-other-actor"}
    changed = client.post(ROUTE, headers=other_actor, json=request([first, second]))
    assert changed.status_code == 200
    assert changed.json()["preview_digest"] != value["preview_digest"]
    assert counts() == before


def test_batch_preview_denials_do_not_write_or_return_partial_results(client, tenant_a, tenant_b, env_a):
    first, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    second, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    before = counts()
    body = request([first, second])
    assert client.post(ROUTE, headers=tenant_b, json=body).status_code == 404
    assert client.post(ROUTE, headers={**tenant_a, "X-Dev-Roles": "viewer"}, json=body).status_code == 403
    with session_scope() as session:
        session.get(ChangeRequest, second["change_request_id"]).status = "pending"
    response = client.post(ROUTE, headers=tenant_a, json=body)
    assert response.status_code == 409 and "items" not in response.json()
    assert counts() == before


def test_batch_preview_duplicate_limits_and_overlapping_targets(client, tenant_a, env_a, monkeypatch):
    first, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    second, _ = setup(client, tenant_a, env_a, target="batch-" + uuid.uuid4().hex)
    before = counts()
    for body in (
        request([]),
        request([first] * 21),
        request([first, first]),
        request([first, {**second, "change_request_id": first["change_request_id"]}]),
        {**request([first]), "actor_id": "injected"},
    ):
        assert client.post(ROUTE, headers=tenant_a, json=body).status_code == 422
    # Database already forbids duplicate registered targets. Exercise the additional
    # aggregation guard with a projected collision, without disabling that constraint.
    original = deployment_preview._snapshot
    monkeypatch.setattr(
        deployment_preview,
        "_snapshot",
        lambda prepared, identity: original(prepared, identity).model_copy(update={"target": "same-shared-target"}),
    )
    response = client.post(ROUTE, headers=tenant_a, json=request([first, second]))
    assert response.status_code == 409
    assert response.json()["detail"] == "batch_preview_target_overlap"
    assert counts() == before
