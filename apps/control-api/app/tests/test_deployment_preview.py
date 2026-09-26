"""Same preflight for preview/submit, no preview writes, stale content refusal."""

import json
import uuid
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy import func, select

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.operation_registry import PolicyOperationRegistry
from app.db import session_scope
from app.models import (
    AuditEvent,
    ChangeRequest,
    Deployment,
    DesiredPolicy,
    EdgeTask,
    Environment,
    RuntimeBinding,
    Tenant,
)
from app.tests.binding_helpers import make_binding
from app.tests.test_change_review import approver, change
from app.tests.test_openshell_policy_operations import StatefulRunner


def setup(client, headers, env, backend="fake", target=None):
    binding, asset, _ = make_binding(client, headers, env["id"], backend=backend, target=target)
    cr, policy = change(client, headers, agent_ids=[asset], enforcement_mode="block")
    assert (
        client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(headers), json={}).status_code
        == 200
    )
    return {
        "schema_version": "deployment-preview-request/v1",
        "change_request_id": cr["id"],
        "environment_id": env["id"],
        "binding_id": binding["id"],
    }, policy


def preview(client, headers, body):
    response = client.post("/api/v1/deployment-preview", headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def submit(client, headers, body, value):
    return client.post(
        "/api/v1/deployment-preview/submit",
        headers=headers,
        json={**body, "schema_version": "deployment-preview-submit/v1", "preview_digest": value["preview_digest"]},
    )


def counts():
    with session_scope() as s:
        return [s.scalar(select(func.count()).select_from(model)) for model in (Deployment, EdgeTask, AuditEvent)]


def test_fake_preview_no_writes_and_submit_independent_readback(client, tenant_a, env_a):
    body, _ = setup(client, tenant_a, env_a)
    before = counts()
    value = preview(client, tenant_a, body)
    assert counts() == before
    assert value["action"] == "development_task" and value["base_revision"] is None
    root = Path(__file__).resolve().parents[4] / "packages/contracts"
    for name, data in [
        ("deployment-preview-request", body),
        ("deployment-preview", value),
        (
            "deployment-preview-submit",
            {**body, "schema_version": "deployment-preview-submit/v1", "preview_digest": value["preview_digest"]},
        ),
    ]:
        jsonschema.Draft202012Validator(json.loads((root / f"{name}.v1.schema.json").read_text())).validate(data)
    result = submit(client, tenant_a, body, value)
    assert result.status_code == 201, result.text
    history = client.get(f"/api/v1/change-requests/{body['change_request_id']}/execution", headers=tenant_a).json()
    assert history["deployments"][0]["id"] == result.json()["id"] and history["deployments"][0]["status"] == "sent"
    with session_scope() as s:
        event = s.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == result.json()["id"], AuditEvent.action == "deployment.create"
            )
        )
        assert event.summary["preview_digest"] == value["preview_digest"]
    assert submit(client, tenant_a, body, value).status_code == 409


@pytest.mark.parametrize("field", ["policy", "binding", "environment", "approval", "actor"])
def test_changed_preview_never_creates_deployment(client, tenant_a, env_a, field):
    body, policy = setup(client, tenant_a, env_a)
    value = preview(client, tenant_a, body)
    before = counts()
    with session_scope() as s:
        if field == "policy":
            s.get(DesiredPolicy, policy["id"]).network = [
                {"endpoint": "different.example:443", "effect": "allow", "binary_paths": ["/usr/bin/curl"]}
            ]
        elif field == "binding":
            s.get(RuntimeBinding, body["binding_id"]).backend_target_id = "changed-target"
        elif field == "environment":
            old_name = s.get(Environment, body["environment_id"]).name
            s.get(Environment, body["environment_id"]).name = "renamed-" + body["binding_id"]
        elif field == "approval":
            s.get(ChangeRequest, body["change_request_id"]).status = "rejected"
        else:
            tenant_a = {**tenant_a, "X-Dev-User-Id": "other-actor"}
        s.commit()
    response = submit(client, tenant_a, body, value)
    if field == "environment":
        with session_scope() as s:
            s.get(Environment, body["environment_id"]).name = old_name
            s.commit()
    assert response.status_code == 409
    assert counts() == before


def test_tenant_permissions_strict_fields_and_backend_binding(client, tenant_a, tenant_b, env_a, monkeypatch):
    body, _ = setup(client, tenant_a, env_a)
    assert client.post("/api/v1/deployment-preview", headers=tenant_b, json=body).status_code == 404
    assert (
        client.post("/api/v1/deployment-preview", headers={**tenant_a, "X-Dev-Roles": "viewer"}, json=body).status_code
        == 403
    )
    assert (
        client.post("/api/v1/deployment-preview", headers=tenant_a, json={**body, "target": "injected"}).status_code
        == 422
    )
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    result = client.post("/api/v1/deployment-preview", headers=tenant_a, json=body)
    assert result.status_code == 409 and result.json()["detail"] == "binding_backend_mismatch"


@pytest.fixture
def cli_scope(client, tenant_a):
    tenant_id = "preview-" + uuid.uuid4().hex
    with session_scope() as session:
        session.add(Tenant(id=tenant_id, name="isolated preview"))
        session.commit()
    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant_id}
    response = client.post(
        "/api/v1/environments", headers=headers, json={"name": "preview environment", "mode": "enforce"}
    )
    assert response.status_code == 201
    return headers, response.json()


def test_cli_revision_recheck_and_only_confirmed_plan_applied(client, cli_scope, monkeypatch, tmp_path):
    tenant_a, env_a = cli_scope
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: backend)
    body, _ = setup(client, tenant_a, env_a, backend="openshell-cli", target="s1")
    from app.tests.binding_helpers import assign_target_authority
    assign_target_authority(monkeypatch, tmp_path, body["binding_id"], backend)
    value = preview(client, tenant_a, body)
    assert value["action"] == "dynamic_update" and value["base_revision"] == "4"
    assert runner.set_calls == 0
    runner.revision = 5
    result = submit(client, tenant_a, body, value)
    assert result.status_code == 409 and result.json()["detail"] == "deployment_preview_changed"
    assert runner.set_calls == 0
    value = preview(client, tenant_a, body)
    result = submit(client, tenant_a, body, value)
    assert result.status_code == 201 and result.json()["status"] == "effective"
    assert runner.set_calls == 1


def test_unstable_gateway_scope_cannot_be_previewed(client, cli_scope, monkeypatch):
    tenant_a, env_a = cli_scope
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    original = backend.probe
    monkeypatch.setattr(backend, "probe", lambda: replace(original(), endpoint_fingerprint=""))
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: backend)
    body, _ = setup(client, tenant_a, env_a, backend="openshell-cli", target="s1")
    result = client.post("/api/v1/deployment-preview", headers=tenant_a, json=body)
    assert result.status_code == 409 and result.json()["detail"] == "deployment_target_identity_unconfirmed"
    assert runner.set_calls == 0


@pytest.mark.parametrize("mutation", ["missing", "deleted", "tenant", "expired", "renewed"])
def test_target_authority_change_blocks_apply(client, cli_scope, monkeypatch, tmp_path, mutation):
    from app.tests.binding_helpers import assign_target_authority

    headers, environment = cli_scope
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    monkeypatch.delenv("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE", raising=False)
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: backend)
    body, _ = setup(client, headers, environment, backend="openshell-cli", target="s1")
    before = counts()
    if mutation == "missing":
        response = client.post("/api/v1/deployment-preview", headers=headers, json=body)
    else:
        path = assign_target_authority(monkeypatch, tmp_path, body["binding_id"], backend)
        value = preview(client, headers, body)
        if mutation == "deleted":
            path.unlink()
        else:
            catalog = json.loads(path.read_text())
            if mutation == "tenant":
                catalog["assignments"][0]["tenant_id"] = "another-tenant"
            elif mutation == "expired":
                catalog["issued_at"] = "2020-01-01T00:00:00Z"
                catalog["expires_at"] = "2020-01-02T00:00:00Z"
            else:
                # Still valid, but it is not the administrator document previewed.
                catalog["expires_at"] = "2099-01-01T00:00:00Z"
            path.write_text(json.dumps(catalog))
        response = submit(client, headers, body, value)
    assert response.status_code == 409, response.text
    expected = "deployment_preview_changed" if mutation == "renewed" else "deployment_target_authority_unverified"
    assert response.json()["detail"] == expected
    assert runner.set_calls == 0 and counts() == before


def test_project_tls_context_change_rejects_preview_without_apply(client, cli_scope, monkeypatch, tmp_path):
    headers, environment = cli_scope
    monkeypatch.setenv('SIQ_AS_ENFORCEMENT_BACKEND', 'openshell-cli')
    monkeypatch.setenv('SIQ_AS_OPENSHELL_CLI_BIN', '/fixture/openshell')
    monkeypatch.setenv('SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT', 'https://127.0.0.1:17671')
    monkeypatch.setenv('XDG_STATE_HOME', '/fixture/project-a/state')
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script='')
    monkeypatch.setattr('app.routers.policies.OpenShellCliBackend', lambda: backend)
    body, _ = setup(client, headers, environment, backend='openshell-cli', target='s1')
    from app.tests.binding_helpers import assign_target_authority
    assign_target_authority(monkeypatch, tmp_path, body["binding_id"], backend)
    value = preview(client, headers, body)
    before = counts()
    # Identical endpoint/version/target cannot authorize another TLS context.
    monkeypatch.setenv('XDG_STATE_HOME', '/fixture/project-b/state')
    response = submit(client, headers, body, value)
    assert response.status_code == 409
    assert response.json()['detail'] == 'deployment_target_authority_unverified'
    assert runner.set_calls == 0 and counts() == before


def test_authority_changed_after_prepare_cannot_execute(client, cli_scope, monkeypatch, tmp_path):
    from app.routers import policies
    from app.tests.binding_helpers import assign_target_authority

    headers, environment = cli_scope
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr(policies, "OpenShellCliBackend", lambda: backend)
    body, _ = setup(client, headers, environment, backend="openshell-cli", target="s1")
    path = assign_target_authority(monkeypatch, tmp_path, body["binding_id"], backend)
    original = policies.prepare_deployment

    def prepare_then_change(*args, **kwargs):
        prepared = original(*args, **kwargs)
        catalog = json.loads(path.read_text())
        catalog["expires_at"] = "2099-01-01T00:00:00Z"
        path.write_text(json.dumps(catalog))
        return prepared

    monkeypatch.setattr(policies, "prepare_deployment", prepare_then_change)
    before = counts()
    response = client.post(
        "/api/v1/deployments", headers=headers,
        json={key: value for key, value in body.items() if key != "schema_version"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "deployment_target_authority_changed"
    assert runner.set_calls == 0 and counts() == before


def test_rollback_requires_current_target_authority(client, cli_scope, monkeypatch, tmp_path):
    from app.tests.binding_helpers import assign_target_authority

    headers, environment = cli_scope
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: backend)
    body, _ = setup(client, headers, environment, backend="openshell-cli", target="s1")
    path = assign_target_authority(monkeypatch, tmp_path, body["binding_id"], backend)
    result = submit(client, headers, body, preview(client, headers, body))
    assert result.status_code == 201, result.text
    deployment_id = result.json()["id"]
    with session_scope() as session:
        receipt = session.get(Deployment, deployment_id).receipt
        assert receipt["target_authority"]["assignment_id"] == "fixture-assignment"
        assert len(receipt["endpoint_fingerprint"]) == len(receipt["gateway_name_sha256"]) == 64
    path.unlink()
    before = runner.set_calls
    response = client.post(f"/api/v1/deployments/{deployment_id}/rollback", headers=headers, json={})
    assert response.status_code != 200
    assert runner.set_calls == before
