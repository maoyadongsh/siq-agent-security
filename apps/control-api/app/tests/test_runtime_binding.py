"""P0-1/P0-2 安全负向测试：RuntimeBinding 强绑定与静态策略 gate。

证明旧行为被拒绝：
- 客户端自由文本 target 不再被接受（schema 422）；
- 跨租户/已吊销/环境不符/selector 未命中的绑定部署一律拒绝；
- selector 引用未知资产 id 部署时 fail-closed；
- openshell-cli 下静态策略（needs_generation）不得进入 effective。
"""

from __future__ import annotations

import uuid

import pytest

from app.db import session_scope
from app.tests.binding_helpers import make_binding, make_instance
from app.tests.test_policy_flow import _create_policy, _fake_cli_backend


@pytest.fixture(scope="session")
def tenant_b_admin():
    """租户 B 持 policy:manage 的身份（conftest 的 tenant_b 只有只读角色）。"""
    return {
        "X-Dev-Tenant-Id": "tnt-B",
        "X-Dev-User-Id": "user-b-admin",
        "X-Dev-Roles": "tenant_admin,security_admin,agent_owner",
    }


def _approved_cr(client, headers, policy_id, tenant_id):
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy_id, "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=headers,
    ).json()
    approver = {
        "X-Dev-Tenant-Id": tenant_id,
        "X-Dev-User-Id": f"approver-{uuid.uuid4().hex[:8]}",
        "X-Dev-Roles": "reviewer",
    }
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    assert resp.status_code == 200, resp.text
    return cr


def test_create_binding_happy_path_with_audit_outbox(client, tenant_a, env_a):
    asset_id, instance_id = make_instance("tnt-A", env_a["id"])
    resp = client.post(
        "/api/v1/runtime-bindings",
        json={
            "agent_instance_id": instance_id,
            "environment_id": env_a["id"],
            "backend": "openshell-cli",
            "backend_target_id": f"sbx-{uuid.uuid4().hex[:8]}",
            "attestation": {"backend_version": "v0.0.83"},
        },
        headers=tenant_a,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["asset_id"] == asset_id
    assert body["revoked_at"] is None

    # 安全相关：审计 + outbox 与状态变化同事务
    with session_scope() as session:
        from app.models import AuditEvent, OutboxEvent

        create_audit = session.query(AuditEvent).filter(
            AuditEvent.action == "binding.create", AuditEvent.resource_id == body["id"]
        ).one()
        assert create_audit.summary["backend_target_id"] == body["backend_target_id"]
        events = session.query(OutboxEvent).filter(
            OutboxEvent.event_type == "runtime_binding.created.v1"
        ).all()
        assert any(e.payload.get("resource_ref") == body["id"] for e in events)


def test_create_binding_cross_tenant_instance_404(client, tenant_a, tenant_b_admin, env_a):
    """跨租户 agent_instance 创建 binding：404 隐藏存在性（不变量 #1）。"""
    _, instance_id = make_instance("tnt-A", env_a["id"])
    env_b = client.post(
        "/api/v1/environments",
        json={"name": f"env-b-{uuid.uuid4().hex[:8]}", "mode": "enforce"},
        headers=tenant_b_admin,
    ).json()
    resp = client.post(
        "/api/v1/runtime-bindings",
        json={
            "agent_instance_id": instance_id,
            "environment_id": env_b["id"],
            "backend": "openshell-cli",
            "backend_target_id": f"sbx-{uuid.uuid4().hex[:8]}",
        },
        headers=tenant_b_admin,
    )
    assert resp.status_code == 404


def test_create_binding_cross_tenant_environment_404(client, tenant_a, tenant_b, env_a, env_b):
    """environment 跨租户同样 404。"""
    _, instance_id = make_instance("tnt-A", env_a["id"])
    resp = client.post(
        "/api/v1/runtime-bindings",
        json={
            "agent_instance_id": instance_id,
            "environment_id": env_b["id"],
            "backend": "openshell-cli",
            "backend_target_id": f"sbx-{uuid.uuid4().hex[:8]}",
        },
        headers=tenant_a,
    )
    assert resp.status_code == 404


def test_create_binding_duplicate_target_conflict(client, tenant_a, env_a):
    """同一 (tenant, backend, target) 重复登记：409。"""
    target = f"sbx-dup-{uuid.uuid4().hex[:8]}"
    make_binding(client, tenant_a, env_a["id"], target=target)
    _, instance_id = make_instance("tnt-A", env_a["id"])
    resp = client.post(
        "/api/v1/runtime-bindings",
        json={
            "agent_instance_id": instance_id,
            "environment_id": env_a["id"],
            "backend": "fake",
            "backend_target_id": target,
        },
        headers=tenant_a,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "binding_target_conflict"


def test_list_bindings_tenant_isolated(client, tenant_a, tenant_b, env_a):
    binding, _, _ = make_binding(client, tenant_a, env_a["id"])
    listed_a = client.get("/api/v1/runtime-bindings", headers=tenant_a).json()
    assert any(b["id"] == binding["id"] for b in listed_a)
    listed_b = client.get("/api/v1/runtime-bindings", headers=tenant_b).json()
    assert all(b["id"] != binding["id"] for b in listed_b)


def test_deploy_with_target_field_rejected_422(client, tenant_a, env_a):
    """旧行为拒绝：请求体携带自由文本 target 直接被 schema 拒绝（extra=forbid）。"""
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    cr = _approved_cr(client, tenant_a, policy["id"], "tnt-A")
    resp = client.post(
        "/api/v1/deployments",
        json={
            "change_request_id": cr["id"],
            "environment_id": env_a["id"],
            "binding_id": binding["id"],
            "target": "attacker-controlled-sandbox",
        },
        headers=tenant_a,
    )
    assert resp.status_code == 422


def test_deploy_cross_tenant_binding_404(client, tenant_a, tenant_b_admin, env_a):
    """跨租户 binding_id 部署：404（不区分不存在与他租户）。"""
    binding, _, _ = make_binding(client, tenant_a, env_a["id"])
    env_b = client.post(
        "/api/v1/environments",
        json={"name": f"env-bx-{uuid.uuid4().hex[:8]}", "mode": "enforce"},
        headers=tenant_b_admin,
    ).json()
    policy = _create_policy(client, tenant_b_admin)
    cr = _approved_cr(client, tenant_b_admin, policy["id"], "tnt-B")
    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_b["id"], "binding_id": binding["id"]},
        headers=tenant_b_admin,
    )
    assert resp.status_code == 404


def test_deploy_revoked_binding_409(client, tenant_a, env_a):
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    cr = _approved_cr(client, tenant_a, policy["id"], "tnt-A")

    revoke = client.post(f"/api/v1/runtime-bindings/{binding['id']}/revoke", json={}, headers=tenant_a)
    assert revoke.status_code == 200
    assert revoke.json()["status"] == "revoked"
    assert revoke.json()["revoked_at"] is not None

    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "binding_revoked"

    # 吊销同事务审计 + outbox
    with session_scope() as session:
        from app.models import AuditEvent, OutboxEvent

        session.query(AuditEvent).filter(
            AuditEvent.action == "binding.revoke", AuditEvent.resource_id == binding["id"]
        ).one()
        events = session.query(OutboxEvent).filter(
            OutboxEvent.event_type == "runtime_binding.revoked.v1"
        ).all()
        assert any(e.payload.get("resource_ref") == binding["id"] for e in events)


def test_revoke_cross_tenant_binding_404(client, tenant_a, tenant_b_admin, env_a):
    binding, _, _ = make_binding(client, tenant_a, env_a["id"])
    resp = client.post(f"/api/v1/runtime-bindings/{binding['id']}/revoke", json={}, headers=tenant_b_admin)
    assert resp.status_code == 404


def test_deploy_binding_environment_mismatch_409(client, tenant_a, env_a):
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    other_env = client.post(
        "/api/v1/environments",
        json={"name": f"env-a2-{uuid.uuid4().hex[:8]}", "mode": "enforce"},
        headers=tenant_a,
    ).json()
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    cr = _approved_cr(client, tenant_a, policy["id"], "tnt-A")
    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": other_env["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "binding_environment_mismatch"


def test_deploy_binding_not_in_policy_selector_409(client, tenant_a, env_a):
    """策略选资产 A、binding 绑资产 B：部署拒绝（selector 与运行时强绑定）。"""
    binding, _, _ = make_binding(client, tenant_a, env_a["id"])
    other_asset_id, _ = make_instance("tnt-A", env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[other_asset_id])
    cr = _approved_cr(client, tenant_a, policy["id"], "tnt-A")
    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "binding_not_in_policy_selector"


def test_deploy_selector_unknown_agent_id_fail_closed_409(client, tenant_a, env_a):
    """selector 引用不存在的资产 id：部署 fail-closed（防止拼写漂移导致策略落空）。"""
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id, "agt_nonexistent"])
    cr = _approved_cr(client, tenant_a, policy["id"], "tnt-A")
    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert resp.status_code == 409
    assert resp.json()["detail"] == "selector_unknown_agent_id"


def test_deploy_selector_matches_instance_id(client, tenant_a, env_a):
    """selector.agent_ids 允许填实例 id：命中该实例的 binding 可部署。"""
    binding, _, instance_id = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[instance_id])
    cr = _approved_cr(client, tenant_a, policy["id"], "tnt-A")
    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["runtime_binding_id"] == binding["id"]


def test_static_policy_openshell_cli_rejected_422(client, tenant_a, env_a, monkeypatch):
    """P0-2：静态策略（filesystem → needs_generation）在 generation 路径修复前不得部署。

    拒绝时不创建 Deployment 行、不改变 CR 状态（编译 gate 先于任何 flush）。
    """
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    _fake_cli_backend(monkeypatch)
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"], backend="openshell-cli")

    name = f"static-policy-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/policies",
        json={
            "name": name,
            "selector": {"agent_ids": [asset_id]},
            "filesystem": {"read_only": ["/etc"]},
            "network": [{"endpoint": "api.example.com:443", "effect": "allow"}],
            "enforcement_mode": "block",
        },
        headers=tenant_a,
    )
    assert resp.status_code == 201, resp.text
    policy = resp.json()
    cr = _approved_cr(client, tenant_a, policy["id"], "tnt-A")

    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert dep.status_code == 422
    assert dep.json()["detail"] == "static_generation_unavailable"
    with session_scope() as session:
        from app.models import ChangeRequest, Deployment

        assert session.query(Deployment).filter(Deployment.change_request_id == cr["id"]).count() == 0
        row = session.query(ChangeRequest).filter(ChangeRequest.id == cr["id"]).one()
        assert row.status == "approved"  # CR 状态不被副作用改变
