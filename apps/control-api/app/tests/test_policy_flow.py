"""策略/变更/部署流程测试（设计文档 §14/§19.3）。

覆盖：职责分离（提出者不能自批）、幂等键、未批准不能部署、回滚、enforcement_mode 校验。
"""

from __future__ import annotations

import uuid


def _create_policy(client, headers, name=None, enforcement_mode="audit_only"):
    name = name or f"policy-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/policies",
        json={
            "name": name,
            "selector": {"agent_ids": ["agt_1"]},
            "network": [
                {
                "endpoint": "api.example.com:443/orders/**",
                "effect": "allow",
                "methods": ["GET"],
                "purpose": "order-read",
            }
            ],
            "enforcement_mode": enforcement_mode,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_policy_static_validation(client, tenant_a):
    bad = client.post(
        "/api/v1/policies",
        json={"name": "bad", "selector": {}, "enforcement_mode": "block"},
        headers=tenant_a,
    )
    assert bad.status_code == 201  # 创建成功但状态为 draft 且错误显式
    assert bad.json()["status"] == "draft"
    assert "selector.agent_ids" in str(bad.json()["unsupported_by_backend"])


def test_secret_must_be_reference_not_plaintext(client, tenant_a):
    resp = client.post(
        "/api/v1/policies",
        json={
            "name": "secret-policy",
            "selector": {"agent_ids": ["agt_1"]},
            "secrets": [{"value": "sk-plaintext-should-not-be-here"}],
        },
        headers=tenant_a,
    )
    assert resp.status_code == 201
    assert "secrets[]" in str(resp.json()["unsupported_by_backend"])


def test_segregation_of_duties(client, tenant_a):
    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    # 同一人提出并批准：拒绝（§19.3 职责分离）
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=tenant_a)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "segregation_of_duties"

    # 换批准者（reviewer 角色）：通过
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    resp2 = client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    assert resp2.status_code == 200
    assert resp2.json()["approver_user_id"] == "user-approver"


def test_idempotency_key(client, tenant_a):
    policy = _create_policy(client, tenant_a)
    key = f"ik-{uuid.uuid4().hex}"
    first = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": key},
        headers=tenant_a,
    )
    second = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": key},
        headers=tenant_a,
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_deployment_requires_approval(client, tenant_a, env_a):
    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    # 未批准部署：拒绝
    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "target": "hermes:legal"},
        headers=tenant_a,
    )
    assert resp.status_code == 409

    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "target": "hermes:legal"},
        headers=tenant_a,
    )
    assert dep.status_code == 201, dep.text
    assert dep.json()["status"] == "sent"

    # 回滚
    rollback = client.post(f"/api/v1/deployments/{dep.json()['id']}/rollback", json={}, headers=tenant_a)
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "rolled_back"


def test_policy_cross_tenant_404(client, tenant_a, tenant_b):
    policy = _create_policy(client, tenant_a)
    resp = client.post(f"/api/v1/policies/{policy['id']}/validate", json={}, headers=tenant_b)
    assert resp.status_code == 404
