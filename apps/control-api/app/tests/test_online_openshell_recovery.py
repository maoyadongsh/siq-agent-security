import uuid

import pytest
from sqlalchemy import select

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.db import session_scope
from app.models import Deployment, OpenShellOperation
from app.routers import policies
from app.tests.binding_helpers import assign_target_authority
from app.tests.test_deployment_submission import post, preview, read, setup
from app.tests.test_openshell_policy_operations import StatefulRunner


def prepared(client, tenant_a, env_a, monkeypatch, tmp_path):
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()

    def run(args):
        if args[:2] == ["policy", "get"]:
            args = [*args[:2], "s1", *args[3:]]
        return runner(args)

    # Fresh adapter on every route simulates loss of the process registry;
    # the independent stateful runner represents the external backend.
    monkeypatch.setattr(policies, "OpenShellCliBackend", lambda: OpenShellCliBackend(runner=run, env_script=""))
    body, _ = setup(client, tenant_a, env_a, backend="openshell-cli")
    assign_target_authority(monkeypatch, tmp_path, body["binding_id"], policies.OpenShellCliBackend())
    value = preview(client, tenant_a, body)
    request = {**body, "schema_version": "deployment-submission-create/v1",
               "request_key": str(uuid.uuid4()), "preview_digest": value["preview_digest"]}
    return runner, request


def deployed(client, tenant_a, request):
    response = post(client, tenant_a, request)
    assert response.status_code == 201 and response.json()["state"] == "recorded", response.text
    return response.json()["deployment_id"]


def test_missing_recovery_key_prevents_api_external_effect(client, tenant_a, env_a, monkeypatch, tmp_path):
    runner, request = prepared(client, tenant_a, env_a, monkeypatch, tmp_path)
    monkeypatch.delenv("SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE")
    response = post(client, tenant_a, request)
    assert response.status_code == 201 and response.json()["state"] == "needs_attention", response.text
    assert runner.set_calls == 0


def test_adapter_success_without_committed_operation_cannot_become_effective(
    client, tenant_a, env_a, monkeypatch, tmp_path,
):
    from app.adapters.openshell.contracts import DeploymentReceipt, VerificationReport

    runner, request = prepared(client, tenant_a, env_a, monkeypatch, tmp_path)
    original_factory = policies.OpenShellCliBackend

    def unbound_adapter():
        adapter = original_factory()
        adapter.apply_dynamic = lambda target, plan, expected_revision: DeploymentReceipt(
            backend_revision="9", operation_id="opo-uncommitted", target=target,
            base_revision=expected_revision, base_policy_digest=plan.base_policy_digest,
            applied_policy_digest="b" * 64, result="applied",
        )
        adapter.verify = lambda *args: VerificationReport(passed=True, level="readback_verified")
        return adapter

    monkeypatch.setattr(policies, "OpenShellCliBackend", unbound_adapter)
    response = post(client, tenant_a, request)
    assert response.status_code == 201 and response.json()["state"] == "needs_attention", response.text
    assert runner.set_calls == 0


@pytest.mark.parametrize("fault", ["missing", "tampered", "key_unavailable"])
def test_invalid_or_missing_durable_material_never_uses_memory_fallback(
    client, tenant_a, env_a, monkeypatch, tmp_path, fault,
):
    runner, request = prepared(client, tenant_a, env_a, monkeypatch, tmp_path)
    deployment_id = deployed(client, tenant_a, request)
    if fault == "key_unavailable":
        monkeypatch.delenv("SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE")
    else:
        with session_scope() as session:
            row = session.scalar(select(OpenShellOperation).where(OpenShellOperation.deployment_id == deployment_id))
            if fault == "missing":
                session.delete(row)  # Isolated synthetic history with no persisted legacy material.
            else:
                row.sealed_snapshot = {**row.sealed_snapshot, "ciphertext": "tampered"}
    response = client.post(f"/api/v1/deployments/{deployment_id}/rollback", headers=tenant_a, json={})
    assert response.status_code == 502, response.text
    assert runner.set_calls == 1
    with session_scope() as session:
        assert session.get(Deployment, deployment_id).status == "effective"


def test_rollback_final_audit_failure_can_recover_without_second_external_write(
    client, tenant_a, env_a, monkeypatch, tmp_path,
):
    runner, request = prepared(client, tenant_a, env_a, monkeypatch, tmp_path)
    deployment_id = deployed(client, tenant_a, request)
    original = policies.audit

    def fail_final(*args, **kwargs):
        if args[4] == "deployment.rollback":
            raise RuntimeError("synthetic final audit failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(policies, "audit", fail_final)
    url = f"/api/v1/deployments/{deployment_id}/rollback"
    with pytest.raises(RuntimeError, match="synthetic final audit failure"):
        client.post(url, headers=tenant_a, json={})
    assert runner.set_calls == 2
    recovery = client.get(f"/api/v1/deployments/{deployment_id}/recovery", headers=tenant_a)
    assert recovery.json()["state"] == "rolled_back"
    with session_scope() as session:
        assert session.get(Deployment, deployment_id).status == "effective"
    monkeypatch.setattr(policies, "audit", original)
    response = client.post(url, headers=tenant_a, json={})
    assert response.status_code == 200 and response.json()["status"] == "rolled_back", response.text
    assert runner.set_calls == 2
    assert read(client, tenant_a, request).json()["deployment_status"] == "rolled_back"
