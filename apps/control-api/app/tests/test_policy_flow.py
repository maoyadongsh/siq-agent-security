"""策略/变更/部署流程测试（设计文档 §14/§19.3）。

覆盖：职责分离（提出者不能自批）、幂等键、未批准不能部署、回滚、enforcement_mode 校验。
"""

from __future__ import annotations

import uuid

from app.db import session_scope


def _create_policy(client, headers, name=None, enforcement_mode="audit_only"):
    name = name or f"policy-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/policies",
        json={
            "name": name,
            "selector": {"agent_ids": ["agt_1"]},
            "network": [
                {
                "endpoint": "api.example.com:443",
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


def _approved_deployment(client, tenant_a, env_a):
    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "target": "hermes:legal"},
        headers=tenant_a,
    ).json()
    return dep


def _edge_headers(client, tenant_a, env_a, identity):
    enr = client.post(
        f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_a
    ).json()
    reg = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enr["code"],
            "device_identity": identity,
            "public_key_pem": "PEM",
            "version": "0.1.0",
        },
    ).json()
    return {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": identity}


def test_deployment_requires_verification_evidence(client, tenant_a, env_a):
    """不变量 #5：无验证证据的回执不得标记 effective（fail-closed）。"""
    dep = _approved_deployment(client, tenant_a, env_a)
    headers = _edge_headers(client, tenant_a, env_a, "edge-verify-1")
    tasks = client.get("/edge/v1/tasks", headers=headers).json()
    task = next(
        t for t in tasks if t["task_type"] == "publish_policy" and t["payload"].get("deployment_id") == dep["id"]
    )

    resp = client.post(
        f"/edge/v1/tasks/{task['id']}/receipt",
        json={"status": "success", "summary": {"applied": True}, "verification": {}},
        headers=headers,
    )
    assert resp.status_code == 200
    with session_scope() as session:
        from app.models import Deployment

        d = session.query(Deployment).filter(Deployment.id == dep["id"]).one()
        assert d.status == "failed"  # 无验证证据 → 不得 effective


def test_deployment_effective_with_verification(client, tenant_a, env_a):
    dep = _approved_deployment(client, tenant_a, env_a)
    headers = _edge_headers(client, tenant_a, env_a, "edge-verify-2")
    tasks = client.get("/edge/v1/tasks", headers=headers).json()
    task = next(
        t for t in tasks if t["task_type"] == "publish_policy" and t["payload"].get("deployment_id") == dep["id"]
    )
    resp = client.post(
        f"/edge/v1/tasks/{task['id']}/receipt",
        json={
            "status": "success",
            "summary": {"applied": True},
            "verification": {"backend_revision": "rev_42", "snapshot_hash": "e" * 64},
        },
        headers=headers,
    )
    assert resp.status_code == 200
    with session_scope() as session:
        from app.models import Deployment

        d = session.query(Deployment).filter(Deployment.id == dep["id"]).one()
        assert d.status == "effective"
        assert d.verification["backend_revision"] == "rev_42"


def test_deployment_compiles_with_fake_backend(client, tenant_a, env_a, monkeypatch):
    """SIQ_AS_ENFORCEMENT_BACKEND=fake：部署任务携带编译制品 + unsupported 显式列表（§14.1）。"""
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "fake")
    dep = _approved_deployment(client, tenant_a, env_a)
    headers = _edge_headers(client, tenant_a, env_a, "edge-compile-1")
    tasks = client.get("/edge/v1/tasks", headers=headers).json()
    task = next(
        t for t in tasks if t["task_type"] == "publish_policy" and t["payload"].get("deployment_id") == dep["id"]
    )
    compiled = task["payload"]["compiled"]
    assert compiled["backend"] == "openshell"
    assert compiled["artifact_hash"]
    # 默认策略含 network（v0.0.83 无动态更新）→ needs_generation + 显式 unsupported
    assert compiled["needs_generation"] is True
    assert "network.dynamic_update" in compiled["unsupported_by_backend"]


def _fake_cli_backend(monkeypatch, *, revision="1", apply_error=None):
    """真实闭环测试夹具：审批→编译→plan→apply→verify 全链路的可控 CLI 后端。"""
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.tests.test_openshell_cli_backend import GATEWAY_INFO, REAL_POLICY_GET_FULL

    class FakeCli(OpenShellCliBackend):
        def __init__(self):
            super().__init__(runner=self._r, env_script="/nonexistent")
            self.applied = []
            self.active_rev = 1

        def _r(self, args):
            if tuple(args[:2]) == ("gateway", "info"):
                return 0, GATEWAY_INFO, ""
            if tuple(args[:2]) == ("policy", "get") and "--full" in args:
                # 有状态：set 后回读必须反映新 revision 与新网络规则（真实网关语义）
                import yaml as _yaml

                body = _yaml.safe_load(REAL_POLICY_GET_FULL.split("---", 1)[1])
                if self.active_rev >= 2:
                    body["network_policies"] = {
                        "siq_as_rule_0": {
                            "name": "siq-as-rule-0",
                            "endpoints": [{"host": "api.example.com", "port": 443}],
                            "binaries": [{"path": "/usr/bin/curl"}],
                        }
                    }
                meta = f"Version:      1\nHash:         h\nStatus:       Loaded\nActive:       {self.active_rev}\n---\n"
                return 0, meta + _yaml.safe_dump(body, sort_keys=False), ""
            if tuple(args[:2]) == ("policy", "set"):
                if apply_error:
                    return 1, apply_error, ""
                self.applied.append(args)
                self.active_rev += 1
                return 0, f"✓ Policy version {self.active_rev} submitted (hash: 5385cd2cf66f)\n", ""
            return 1, "", f"unexpected: {args}"

    fake = FakeCli()
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: fake)
    return fake


def test_deployment_openshell_cli_closed_loop(client, tenant_a, env_a, monkeypatch):
    """#2 闭环：审批 → 编译 → 真实 policy set → 读回验证 → effective（不变量 #5）。"""
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    fake = _fake_cli_backend(monkeypatch)
    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)

    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "target": "siq-as-live"},
        headers=tenant_a,
    )
    assert dep.status_code == 201, dep.text
    body = dep.json()
    assert body["status"] == "effective"  # 真实 policy set + 读回验证通过
    assert body["verification"]["allow_checks"]
    assert body["verification"]["deny_checks"]
    assert fake.applied, "policy set 必须真实发生"
    assert fake.applied[0][2] == "siq-as-live"


def test_deployment_openshell_apply_failure_fails_closed(client, tenant_a, env_a, monkeypatch):
    """网关拒绝（如静态段不一致）→ 502 + deployment failed，绝不伪装 effective。"""
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    _fake_cli_backend(monkeypatch, apply_error="Error: filesystem include_workdir cannot be changed on a live sandbox")
    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)

    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "target": "siq-as-live"},
        headers=tenant_a,
    )
    assert dep.status_code == 502
    with session_scope() as session:
        from app.models import Deployment

        d = session.query(Deployment).filter(Deployment.change_request_id == cr["id"]).one()
        assert d.status == "failed"
        assert "include_workdir" in (d.receipt or {}).get("error", "")


def test_list_endpoints_tenant_isolated(client, tenant_a, tenant_b):
    """策略/变更/部署列表：租户隔离 + 可见性。"""
    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()

    policies_a = client.get("/api/v1/policies", headers=tenant_a).json()
    crs_a = client.get("/api/v1/change-requests", headers=tenant_a).json()
    assert any(p["id"] == policy["id"] for p in policies_a)
    assert any(c["id"] == cr["id"] for c in crs_a)

    policies_b = client.get("/api/v1/policies", headers=tenant_b).json()
    crs_b = client.get("/api/v1/change-requests", headers=tenant_b).json()
    assert all(p["id"] != policy["id"] for p in policies_b)
    assert all(c["id"] != cr["id"] for c in crs_b)


def test_rollback_invokes_real_backend(client, tenant_a, env_a, monkeypatch):
    """§14.4：openshell-cli 模式下回滚调用真实后端（--rev 回读 + policy set）。"""
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.contracts import (
        BackendCapabilities,
        DeploymentReceipt,
        PolicySnapshot,
        RollbackReceipt,
        VerificationReport,
    )

    class FakeCli(OpenShellCliBackend):
        def __init__(self):
            super().__init__(runner=lambda a: (1, "", "unused"), env_script="/n")
            self.rollbacks: list[str] = []

        def probe(self):
            return BackendCapabilities(
                backend="openshell", schema_version="v1", dynamic_network_update=True
            )

        def read_effective_policy(self, target):
            return PolicySnapshot(target=target, revision="1", network=[])

        def plan_change(self, target, compiled):
            from app.adapters.openshell.contracts import ChangePlan

            return ChangePlan(
                target=target, kind="dynamic", expected_revision="1", artifact_hash=compiled.artifact_hash
            )

        def apply_dynamic(self, target, plan, expected_revision):
            return DeploymentReceipt(backend_revision="2", evidence={"snapshot_hash": "h"})

        def verify(self, target, checks, receipt):
            return VerificationReport(
                passed=True,
                allow_checks=[{"endpoint": e, "result": "allow"} for e in checks.get("expect_allow", [])],
                deny_checks=[{"endpoint": e, "result": "deny"} for e in checks.get("expect_deny", [])],
            )

        def rollback(self, target, receipt):
            self.rollbacks.append(target)
            return RollbackReceipt(restored_revision="1", evidence={"ok": True})

    fake = FakeCli()
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: fake)

    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "target": "s-rollback"},
        headers=tenant_a,
    ).json()
    assert dep["status"] == "effective", dep

    resp = client.post(f"/api/v1/deployments/{dep['id']}/rollback", json={}, headers=tenant_a)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "rolled_back"
    assert body["verification"]["rollback"]["restored_revision"] == "1"
    assert fake.rollbacks == ["s-rollback"]
