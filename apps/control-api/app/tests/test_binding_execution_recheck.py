"""Execute-boundary binding recheck: drift after prepare rejects stale prepared results.

CL-04-BINDING-EXECUTION-RECHECK: the checks in prepare_deployment and the side
effects in execute_deployment read the binding through the request session's ORM
identity map. A committed change between those two points was invisible, so a
revoked or re-pointed binding could still drive apply_dynamic / publish_policy.

Every mutation below commits through an independent session (session_scope on a
separate connection), never by editing the in-memory prepared objects, so the
tests prove the database read at the execution boundary observes the drift.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    AgentAsset,
    AgentInstance,
    AuditEvent,
    Deployment,
    DeploymentSubmission,
    EdgeTask,
    OutboxEvent,
    RuntimeBinding,
)
from app.tests.binding_helpers import assign_target_authority, make_binding
from app.tests.test_change_review import approver, change


def _setup(client, headers, env, backend="fake", target=None):
    binding, asset, instance = make_binding(client, headers, env["id"], backend=backend, target=target)
    cr, _ = change(client, headers, agent_ids=[asset], enforcement_mode="block")
    approved = client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(headers), json={})
    assert approved.status_code == 200, approved.text
    return binding, asset, instance, cr


def _deploy(client, headers, binding, cr, env):
    return client.post(
        "/api/v1/deployments",
        headers=headers,
        json={"change_request_id": cr["id"], "environment_id": env["id"], "binding_id": binding["id"]},
    )


def _counts():
    with session_scope() as session:
        return [
            session.scalar(select(func.count()).select_from(model))
            for model in (Deployment, EdgeTask, AuditEvent, OutboxEvent)
        ]


def _revoke(binding_id):
    with session_scope() as session:
        session.get(RuntimeBinding, binding_id).status = "revoked"


def _drift_after_prepare(monkeypatch, namespace, mutate):
    original = namespace.prepare_deployment
    captured = {}

    def prepare_then_drift(*args, **kwargs):
        prepared = original(*args, **kwargs)
        captured["prepared"] = prepared
        mutate()
        return prepared

    monkeypatch.setattr(namespace, "prepare_deployment", prepare_then_drift)
    return captured


def _openshell_scope(client, tenant_a, monkeypatch, tmp_path):
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.operation_registry import PolicyOperationRegistry
    from app.models import Tenant
    from app.routers import policies
    from app.tests.test_openshell_policy_operations import StatefulRunner

    # StatefulRunner only answers for sandbox "s1"; a fresh tenant per test keeps
    # the (tenant, backend, target) uniqueness constraint satisfied across tests.
    tenant_id = "recheck-" + uuid.uuid4().hex
    with session_scope() as session:
        session.add(Tenant(id=tenant_id, name="isolated recheck"))
        session.commit()
    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant_id}
    created = client.post("/api/v1/environments", headers=headers, json={"name": "recheck env", "mode": "enforce"})
    assert created.status_code == 201, created.text
    env = created.json()
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr(policies, "OpenShellCliBackend", lambda: backend)
    binding, _, _, cr = _setup(client, headers, env, backend="openshell-cli", target="s1")
    assign_target_authority(monkeypatch, tmp_path, binding["id"], backend)
    return headers, env, binding, cr, runner, backend


def test_unchanged_prepared_deployment_still_executes_fake(client, tenant_a, env_a, monkeypatch):
    from app.routers import policies

    binding, _, _, cr = _setup(client, tenant_a, env_a)
    _drift_after_prepare(monkeypatch, policies, lambda: None)
    response = _deploy(client, tenant_a, binding, cr, env_a)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "sent"


def test_binding_revoked_after_prepare_is_rejected_before_fake_task(client, tenant_a, env_a, monkeypatch):
    from app.routers import policies

    binding, _, _, cr = _setup(client, tenant_a, env_a)
    captured = _drift_after_prepare(monkeypatch, policies, lambda: _revoke(binding["id"]))
    before = _counts()
    response = _deploy(client, tenant_a, binding, cr, env_a)
    assert _counts() == before  # no deployment row, no publish_policy task, no success audit/outbox
    # The request session's identity map still serves the pre-drift object ...
    assert captured["prepared"].binding.status == "active"
    # ... while an independent read shows the committed revocation.
    with session_scope() as session:
        assert session.get(RuntimeBinding, binding["id"]).status == "revoked"
    assert response.status_code == 409 and response.json()["detail"] == "binding_revoked"


@pytest.mark.parametrize(
    "field", ["backend_target_id", "environment_id", "asset_id", "agent_instance_id", "backend", "tenant"]
)
def test_binding_reference_drift_after_prepare_is_rejected(client, tenant_a, env_a, env_b, monkeypatch, field):
    from app.routers import policies

    binding, _, _, cr = _setup(client, tenant_a, env_a)

    def drift():
        with session_scope() as session:
            row = session.get(RuntimeBinding, binding["id"])
            if field == "backend_target_id":
                row.backend_target_id = f"sandbox-{uuid.uuid4().hex[:8]}"
            elif field == "environment_id":
                row.environment_id = env_b["id"]
            elif field == "asset_id":
                asset = AgentAsset(tenant_id="tnt-A", name="drift asset", status="confirmed")
                session.add(asset)
                session.flush()
                row.asset_id = asset.id
            elif field == "agent_instance_id":
                asset = AgentAsset(tenant_id="tnt-A", name="drift asset", status="confirmed")
                session.add(asset)
                session.flush()
                instance = AgentInstance(
                    tenant_id="tnt-A", asset_id=asset.id, environment_id=env_a["id"], runtime="hermes"
                )
                session.add(instance)
                session.flush()
                row.agent_instance_id = instance.id
            elif field == "backend":
                row.backend = "openshell-cli"
            else:
                row.tenant_id = "tnt-B"

    _drift_after_prepare(monkeypatch, policies, drift)
    before = _counts()
    response = _deploy(client, tenant_a, binding, cr, env_a)
    assert response.status_code == 409 and response.json()["detail"] == "binding_source_identity_changed"
    assert _counts() == before


@pytest.mark.parametrize("drift", ["environment", "unknown_environment", "asset", "instance_tenant", "asset_tenant"])
def test_instance_source_drift_after_prepare_is_rejected(client, tenant_a, env_a, env_b, monkeypatch, drift):
    from app.routers import policies

    binding, asset_id, instance_id, cr = _setup(client, tenant_a, env_a)

    def mutate():
        with session_scope() as session:
            instance = session.get(AgentInstance, instance_id)
            if drift == "environment":
                instance.environment_id = env_b["id"]
            elif drift == "unknown_environment":
                instance.environment_id = None
            elif drift == "asset":
                other = AgentAsset(tenant_id="tnt-A", name="different role", status="confirmed")
                session.add(other)
                session.flush()
                instance.asset_id = other.id
            elif drift == "instance_tenant":
                instance.tenant_id = "tnt-B"
            else:
                session.get(AgentAsset, asset_id).tenant_id = "tnt-B"

    _drift_after_prepare(monkeypatch, policies, mutate)
    before = _counts()
    response = _deploy(client, tenant_a, binding, cr, env_a)
    assert response.status_code == 409 and response.json()["detail"] == "binding_source_identity_changed"
    assert _counts() == before


def test_unchanged_prepared_deployment_still_executes_openshell(client, tenant_a, monkeypatch, tmp_path):
    from app.routers import policies

    headers, env, binding, cr, runner, _ = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    _drift_after_prepare(monkeypatch, policies, lambda: None)
    response = _deploy(client, headers, binding, cr, env)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "effective" and runner.set_calls == 1


def test_binding_revoked_after_prepare_is_rejected_before_apply(client, tenant_a, monkeypatch, tmp_path):
    from app.routers import policies

    headers, env, binding, cr, runner, _ = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    _drift_after_prepare(monkeypatch, policies, lambda: _revoke(binding["id"]))
    before = _counts()
    response = _deploy(client, headers, binding, cr, env)
    assert runner.set_calls == 0  # apply_dynamic must not run with a revoked binding
    assert _counts() == before
    assert response.status_code == 409 and response.json()["detail"] == "binding_revoked"


def test_binding_revoked_during_execute_probe_is_rejected_before_apply(client, tenant_a, monkeypatch, tmp_path):
    headers, env, binding, cr, runner, backend = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    original_probe = backend.probe
    probes = []

    def probe_then_revoke():
        probes.append(1)
        caps = original_probe()
        if len(probes) == 2:
            # The drift lands while the last read-only probe runs. A recheck only
            # at the execute entry would already have passed; the recheck must sit
            # after that probe and before apply_dynamic.
            _revoke(binding["id"])
        return caps

    monkeypatch.setattr(backend, "probe", probe_then_revoke)
    before = _counts()
    response = _deploy(client, headers, binding, cr, env)
    assert len(probes) == 2  # prepare-time probe + execute-time recheck probe
    assert runner.set_calls == 0  # apply_dynamic must not run after drift seen post-probe
    assert _counts() == before
    assert response.status_code == 409 and response.json()["detail"] == "binding_revoked"


def test_binding_revoked_after_preview_prepare_is_rejected_on_submit(client, tenant_a, env_a, monkeypatch):
    from app.routers import deployment_preview

    binding, _, _, cr = _setup(client, tenant_a, env_a)
    body = {
        "schema_version": "deployment-preview-request/v1",
        "change_request_id": cr["id"],
        "environment_id": env_a["id"],
        "binding_id": binding["id"],
    }
    value = client.post("/api/v1/deployment-preview", headers=tenant_a, json=body)
    assert value.status_code == 200, value.text
    # The preview digest still matches: it is computed from the same stale ORM
    # state, so only the persisted-state recheck can reject this submit.
    _drift_after_prepare(monkeypatch, deployment_preview, lambda: _revoke(binding["id"]))
    before = _counts()
    submit_body = {
        **body,
        "schema_version": "deployment-preview-submit/v1",
        "preview_digest": value.json()["preview_digest"],
    }
    response = client.post("/api/v1/deployment-preview/submit", headers=tenant_a, json=submit_body)
    assert response.status_code == 409 and response.json()["detail"] == "binding_revoked"
    assert _counts() == before


def test_reserved_submission_drift_refuses_without_releasing_reservation(client, tenant_a, env_a, monkeypatch):
    from app.routers import deployment_submission
    from app.tests.test_deployment_preview import preview

    binding, _, _, cr = _setup(client, tenant_a, env_a)
    body = {
        "schema_version": "deployment-preview-request/v1",
        "change_request_id": cr["id"],
        "environment_id": env_a["id"],
        "binding_id": binding["id"],
    }
    request = {
        **body,
        "schema_version": "deployment-submission-create/v1",
        "request_key": str(uuid.uuid4()),
        "preview_digest": preview(client, tenant_a, body)["preview_digest"],
    }
    original_execute = deployment_submission.execute_deployment
    calls = []

    def revoke_then_execute(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            # The re-prepare inside _execute_new_reservation already passed; the
            # revocation commits after it and before any execution side effect.
            _revoke(binding["id"])
        return original_execute(*args, **kwargs)

    monkeypatch.setattr(deployment_submission, "execute_deployment", revoke_then_execute)
    task_count = _counts()[1]
    response = client.post("/api/v1/deployment-submissions", headers=tenant_a, json=request)
    # Existing callers conservatively surface a pre-effect refusal as unknown;
    # the reservation contract is unchanged by the recheck.
    assert response.status_code == 502 and response.json()["detail"] == "deployment_submission_unconfirmed"
    assert calls == [1]
    with session_scope() as session:
        row = session.scalar(select(DeploymentSubmission).where(DeploymentSubmission.change_request_id == cr["id"]))
        assert row is not None  # the durable reservation is not released
        deployment = session.get(Deployment, row.deployment_id)
        assert deployment.status == "pending"  # never marked effective or failed
        actions = session.scalars(select(AuditEvent.action).where(AuditEvent.resource_id == deployment.id)).all()
        assert sorted(actions) == ["deployment.reserve"]
    assert _counts()[1] == task_count  # no publish_policy task
    replay = client.post("/api/v1/deployment-submissions", headers=tenant_a, json=request)
    assert replay.status_code == 200
    assert replay.json()["state"] == "unconfirmed" and replay.json()["deployment_status"] == "pending"
    assert calls == [1]  # replays only read; they never re-enter execution


def test_batch_item_drift_refuses_and_stops_later_items_without_effects(client, tenant_a, env_a, monkeypatch):
    from app import batch_execution
    from app.routers import deployment_submission
    from app.tests.test_batch_reservation import setup as batch_setup

    _, draft, identity, confirmation = batch_setup(client, tenant_a, env_a)
    original_execute = deployment_submission.execute_deployment
    calls = []

    def revoke_then_execute(prepared, *args, **kwargs):
        calls.append(prepared.binding.id)
        if len(calls) == 1:
            _revoke(prepared.binding.id)
        return original_execute(prepared, *args, **kwargs)

    monkeypatch.setattr(deployment_submission, "execute_deployment", revoke_then_execute)
    with session_scope() as session:
        before_tasks = session.scalar(select(func.count()).select_from(EdgeTask))
        result = batch_execution.execute_batch(draft["id"], confirmation, session, identity).model_dump()
        after_tasks = session.scalar(select(func.count()).select_from(EdgeTask))
    assert result["state"] == "unconfirmed"
    assert [item["deployment_status"] for item in result["items"]] == ["pending", "failed"]
    assert len(calls) == 1  # the drifted item refused; the second item never entered execution
    assert after_tasks == before_tasks
    with session_scope() as session:
        skipped = session.get(Deployment, result["items"][1]["deployment_id"])
        assert skipped.verification["backend_mutated"] is False
        assert session.get(Deployment, result["items"][0]["deployment_id"]).verification is None
        replay = batch_execution.execute_batch(draft["id"], confirmation, session, identity).model_dump()
    assert replay == result and len(calls) == 1  # existing reservations only read
