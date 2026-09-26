import uuid

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AgentAsset, AgentInstance, AuditEvent, Deployment, OutboxEvent, RuntimeBinding
from app.tests.binding_helpers import make_binding, make_instance
from app.tests.test_policy_flow import _create_policy
from app.tests.test_runtime_binding import _approved_cr


def payload(instance, environment):
    return {"agent_instance_id": instance, "environment_id": environment, "backend": "fake",
            "backend_target_id": "identity-fixture-" + uuid.uuid4().hex}


def test_registration_locates_before_permission(client, tenant_a, env_a, env_b):
    _, instance = make_instance("tnt-A", env_a["id"])
    viewer = {**tenant_a, "X-Dev-Roles": "viewer"}
    assert client.post("/api/v1/runtime-bindings", headers=viewer,
                       json=payload("missing-instance", env_a["id"])).status_code == 404
    assert client.post("/api/v1/runtime-bindings", headers=viewer,
                       json=payload(instance, env_b["id"])).status_code == 404
    assert client.post("/api/v1/runtime-bindings", headers=viewer,
                       json=payload(instance, env_a["id"])).status_code == 403


def test_explicit_instance_creation_has_real_audit_and_event_ids(client, tenant_a, env_a):
    asset_id, _ = make_instance("tnt-A", env_a["id"])
    response = client.post(f"/api/v1/assets/{asset_id}/instances", headers=tenant_a,
                           json={"environment_id": env_a["id"], "runtime": "openclaw"})
    assert response.status_code == 201, response.text
    instance_id = response.json()["id"]
    with session_scope() as session:
        assert session.scalar(select(AuditEvent.id).where(
            AuditEvent.resource_id == instance_id, AuditEvent.action == "agent.instance.create",
        )) is not None
        event = session.scalar(select(OutboxEvent).where(
            OutboxEvent.payload["resource_ref"].as_string() == instance_id,
        ))
        assert event is not None and event.payload["payload"]["agent_instance_id"] == instance_id


@pytest.mark.parametrize("unknown", [True, False])
def test_registration_cannot_relocate_or_invent_environment(client, tenant_a, env_a, unknown):
    _, instance_id = make_instance("tnt-A", env_a["id"])
    other = client.post("/api/v1/environments", headers=tenant_a,
                        json={"name": "identity-env-" + uuid.uuid4().hex}).json()["id"]
    if unknown:
        with session_scope() as session:
            session.get(AgentInstance, instance_id).environment_id = None
    body = payload(instance_id, other)
    response = client.post("/api/v1/runtime-bindings", headers=tenant_a, json=body)
    expected = "binding_instance_environment_unverified" if unknown else "binding_instance_environment_mismatch"
    assert response.status_code == 409 and response.json()["detail"] == expected
    with session_scope() as session:
        assert session.scalar(select(RuntimeBinding.id).where(
            RuntimeBinding.backend_target_id == body["backend_target_id"],
        )) is None
        assert session.get(AgentInstance, instance_id).environment_id == (None if unknown else env_a["id"])


@pytest.mark.parametrize("drift", ["environment", "unknown_environment", "asset", "instance_tenant", "asset_tenant"])
def test_deployment_revalidates_binding_source_before_adapter(client, tenant_a, env_a, env_b, monkeypatch, drift):
    from app.routers import policies

    binding, asset_id, instance_id = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    change = _approved_cr(client, tenant_a, policy["id"], "tnt-A")
    with session_scope() as session:
        instance = session.get(AgentInstance, instance_id)
        if drift == "environment":
            instance.environment_id = env_b["id"]
        elif drift == "unknown_environment":
            instance.environment_id = None
        elif drift == "asset":
            other = AgentAsset(tenant_id="tnt-A", name="different role")
            session.add(other)
            session.flush()
            instance.asset_id = other.id
        elif drift == "instance_tenant":
            instance.tenant_id = "tnt-B"
        else:
            session.get(AgentAsset, asset_id).tenant_id = "tnt-B"

    def never(*args, **kwargs):
        pytest.fail("adapter reached after identity drift")

    monkeypatch.setattr(policies, "_compile_for_enforcement", never)
    body = {"change_request_id": change["id"], "environment_id": env_a["id"], "binding_id": binding["id"]}
    response = client.post("/api/v1/deployments", headers=tenant_a, json=body)
    assert response.status_code == 409 and response.json()["detail"] == "binding_source_identity_changed"
    with session_scope() as session:
        assert session.scalar(select(Deployment.id).where(Deployment.change_request_id == change["id"])) is None
