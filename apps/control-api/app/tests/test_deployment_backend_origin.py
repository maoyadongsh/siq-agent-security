"""Backend reconfiguration must never turn an external rollback into a bookkeeping success."""

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, RuntimeBinding
from app.tests.test_policy_flow import _sent_deployment_with_fake_backend


@pytest.mark.parametrize(
    "original,configured", [("openshell-cli", "fake"), ("fake", "none"), ("fake", "openshell-cli")]
)
@pytest.mark.parametrize("legacy", [False, True])
def test_rollback_uses_original_backend_without_mutating_on_config_switch(
    client,
    tenant_a,
    env_a,
    monkeypatch,
    original,
    configured,
    legacy,
):
    binding, _, change, deployment = _sent_deployment_with_fake_backend(client, tenant_a, env_a)
    # Synthetic history, not an assertion of actual external OpenShell execution.
    with session_scope() as session:
        row = session.get(Deployment, deployment["id"])
        row.execution_backend = None if legacy else original
        row.status = "effective"
        session.get(ChangeRequest, change["id"]).status = "effective"
        session.get(RuntimeBinding, binding["id"]).backend = original
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", configured)
    response = client.post(f"/api/v1/deployments/{deployment['id']}/rollback", headers=tenant_a, json={})
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "deployment_backend_changed"
    with session_scope() as session:
        assert session.get(Deployment, deployment["id"]).status == "effective"
        assert session.get(ChangeRequest, change["id"]).status == "effective"
        assert (
            session.scalar(
                select(AuditEvent).where(
                    AuditEvent.resource_id == deployment["id"],
                    AuditEvent.action == "deployment.rollback",
                )
            )
            is None
        )


def test_new_deployment_records_backend_and_rejects_client_override(client, tenant_a, tenant_b, env_a):
    _, _, _, deployment = _sent_deployment_with_fake_backend(client, tenant_a, env_a)
    with session_scope() as session:
        assert session.get(Deployment, deployment["id"]).execution_backend == "fake"
    denied = client.post(f"/api/v1/deployments/{deployment['id']}/rollback", headers=tenant_b, json={})
    assert denied.status_code == 404
    override = client.post(
        "/api/v1/deployments",
        headers=tenant_a,
        json={
            "change_request_id": "synthetic",
            "environment_id": env_a["id"],
            "binding_id": "synthetic",
            "execution_backend": "fake",
        },
    )
    assert override.status_code == 422


def test_legacy_unknown_origin_does_not_guess_current_backend(client, tenant_a, env_a):
    _, _, _, deployment = _sent_deployment_with_fake_backend(client, tenant_a, env_a)
    with session_scope() as session:
        row = session.get(Deployment, deployment["id"])
        row.execution_backend = None
        row.runtime_binding_id = None
    response = client.post(f"/api/v1/deployments/{deployment['id']}/rollback", headers=tenant_a, json={})
    assert response.status_code == 409
    assert response.json()["detail"] == "deployment_backend_unknown"
