"""策略/变更/部署流程测试（设计文档 §14/§19.3）。

覆盖：职责分离（提出者不能自批）、幂等键、未批准不能部署、回滚、enforcement_mode 校验。
"""

from __future__ import annotations

import uuid

from app.db import session_scope
from app.tests.binding_helpers import make_binding
from app.tests.edge_helpers import edge_public_key_pem


def _create_policy(client, headers, name=None, enforcement_mode="audit_only", agent_ids=None):
    name = name or f"policy-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/v1/policies",
        json={
            "name": name,
            "selector": {"agent_ids": agent_ids or ["agt_1"]},
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
    assert resp.status_code == 422
    assert "extra_forbidden" in resp.text


def test_secret_reference_is_accepted_without_plaintext(client, tenant_a):
    resp = client.post(
        "/api/v1/policies",
        json={
            "name": f"secret-ref-{uuid.uuid4().hex[:8]}",
            "selector": {"agent_ids": ["agt_1"]},
            "secrets": [{"ref": "vault://agents/provider", "purpose": "model access", "injection": "gateway"}],
        },
        headers=tenant_a,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "validated"


def test_segregation_of_duties(client, tenant_a):
    policy = _create_policy(client, tenant_a, enforcement_mode="block")
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
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    # 未批准部署：拒绝
    resp = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert resp.status_code == 409

    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert dep.status_code == 201, dep.text
    assert dep.json()["status"] == "sent"
    assert dep.json()["target"] == binding["backend_target_id"]  # target 由绑定服务端解析
    assert dep.json()["runtime_binding_id"] == binding["id"]

    # 回滚
    rollback = client.post(f"/api/v1/deployments/{dep.json()['id']}/rollback", json={}, headers=tenant_a)
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "rolled_back"


def test_policy_cross_tenant_404(client, tenant_a, tenant_b):
    policy = _create_policy(client, tenant_a)
    resp = client.post(f"/api/v1/policies/{policy['id']}/validate", json={}, headers=tenant_b)
    assert resp.status_code == 404


def _approved_deployment(client, tenant_a, env_a):
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
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
            "public_key_pem": edge_public_key_pem(identity),
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
        assert d.status == "failed"
        assert d.verification is None


def test_edge_publish_policy_receipt_constant_fail_closed(client, tenant_a, env_a):
    """常量语义：Phase 4 回执验证器落地前，publish_policy 成功回执一律 failed + edge_publish_unsupported。"""
    dep = _approved_deployment(client, tenant_a, env_a)
    headers = _edge_headers(client, tenant_a, env_a, "edge-const-1")
    tasks = client.get("/edge/v1/tasks", headers=headers).json()
    task = next(
        t for t in tasks if t["task_type"] == "publish_policy" and t["payload"].get("deployment_id") == dep["id"]
    )
    resp = client.post(
        f"/edge/v1/tasks/{task['id']}/receipt",
        json={
            "status": "success",
            "summary": {"applied": True},
            "verification": {"backend_revision": "rev_9", "snapshot_hash": "e" * 64},
        },
        headers=headers,
    )
    assert resp.status_code == 200
    with session_scope() as session:
        from app.models import Deployment, OutboxEvent

        d = session.query(Deployment).filter(Deployment.id == dep["id"]).one()
        assert d.status == "failed"
        assert (d.receipt or {}).get("status") == "success"  # 回执保留原始状态
        failed_events = [
            e
            for e in session.query(OutboxEvent)
            .filter(OutboxEvent.event_type == "policy.deployment.failed.v1")
            .all()
            if e.payload.get("resource_ref") == dep["id"]
        ]
        assert failed_events, "失败事件必须已发出"
        assert failed_events[-1].payload["payload"]["reason"] == "edge_publish_unsupported"


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
    target = f"siq-as-live-{uuid.uuid4().hex[:8]}"
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"], backend="openshell-cli", target=target)
    policy = _create_policy(client, tenant_a, enforcement_mode="block", agent_ids=[asset_id])
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)

    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert dep.status_code == 201, dep.text
    body = dep.json()
    assert body["status"] == "effective"  # 真实 policy set + 读回验证通过
    assert body["verification"]["allow_checks"]
    assert body["verification"]["deny_checks"]
    assert fake.applied, "policy set 必须真实发生"
    assert fake.applied[0][2] == target


def test_deployment_openshell_apply_failure_fails_closed(client, tenant_a, env_a, monkeypatch):
    """网关拒绝（如静态段不一致）→ 502 + deployment failed，绝不伪装 effective。"""
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    _fake_cli_backend(monkeypatch, apply_error="Error: filesystem include_workdir cannot be changed on a live sandbox")
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"], backend="openshell-cli")
    policy = _create_policy(client, tenant_a, enforcement_mode="block", agent_ids=[asset_id])
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)

    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert dep.status_code == 502
    with session_scope() as session:
        from app.models import AuditEvent, Deployment

        d = session.query(Deployment).filter(Deployment.change_request_id == cr["id"]).one()
        assert d.status == "failed"
        assert (d.receipt or {}).get("error_code") == "AdapterError"
        assert len((d.receipt or {}).get("error_digest", "")) == 64
        assert "include_workdir" not in str(d.receipt)
        failure_audit = session.query(AuditEvent).filter(
            AuditEvent.action == "deployment.fail",
            AuditEvent.resource_id == d.id,
        ).one()
        assert "include_workdir" not in str(failure_audit.summary)
        assert failure_audit.summary["error_digest"] == d.receipt["error_digest"]


def test_list_endpoints_tenant_isolated(client, tenant_a, tenant_b):
    """策略/变更/部署列表：租户隔离 + 可见性。"""
    policy = _create_policy(client, tenant_a, enforcement_mode="block")
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

    target = f"s-rollback-{uuid.uuid4().hex[:8]}"
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"], backend="openshell-cli", target=target)
    policy = _create_policy(client, tenant_a, enforcement_mode="block", agent_ids=[asset_id])
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": policy["id"], "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    ).json()
    assert dep["status"] == "effective", dep

    resp = client.post(f"/api/v1/deployments/{dep['id']}/rollback", json={}, headers=tenant_a)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "rolled_back"
    assert body["verification"]["rollback"]["restored_revision"] == "1"
    assert fake.rollbacks == [target]


def test_enforcement_mode_downgrade_requires_high_risk(client, tenant_a):
    """§14.2 修订：enforcement_mode 只允许升级；降级审批必须 high_risk 变更单。"""
    v1 = _create_policy(client, tenant_a, enforcement_mode="block")  # v1 = block
    with session_scope() as session:
        from app.models import DesiredPolicy

        v2 = DesiredPolicy(
            tenant_id="tnt-A",
            name=v1["name"],
            selector={"agent_ids": ["a"]},
            enforcement_mode="warn",  # v2 降级
            version=2,
            status="validated",
        )
        session.add(v2)
        session.commit()
        v2_id = v2.id

    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-approver", "X-Dev-Roles": "reviewer"}
    cr = client.post(
        "/api/v1/change-requests",
        json={"policy_id": v2_id, "idempotency_key": f"ik-{uuid.uuid4().hex}"},
        headers=tenant_a,
    ).json()
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    assert resp.status_code == 409
    assert "enforcement_downgrade_requires_high_risk" in resp.json()["detail"]

    # high_risk 变更单可以批准降级
    cr2 = client.post(
        "/api/v1/change-requests",
        json={
            "policy_id": v2_id,
            "idempotency_key": f"ik-{uuid.uuid4().hex}",
            "approval_policy": "high_risk",
        },
        headers=tenant_a,
    ).json()
    resp2 = client.post(f"/api/v1/change-requests/{cr2['id']}/approve", json={}, headers=approver)
    assert resp2.status_code == 200


def test_break_glass_requires_dedicated_permission(client, tenant_a):
    """§19.2：发起 break_glass 需独立权限点 change:break_glass；普通 proposer 自选 break_glass 直接 403。"""
    policy = _create_policy(client, tenant_a)
    proposer = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-plain-proposer", "X-Dev-Roles": "agent_owner"}
    resp = client.post(
        "/api/v1/change-requests",
        json={
            "policy_id": policy["id"],
            "idempotency_key": f"ik-{uuid.uuid4().hex}",
            "approval_policy": "break_glass",
        },
        headers=proposer,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "forbidden"


def test_break_glass_sod_applies_same_person_rejected(client, tenant_a):
    """§19.3 修订：break_glass 不豁免 SoD；同一人 propose+approve 仍被 409 拒绝。"""
    policy = _create_policy(client, tenant_a)
    cr = client.post(
        "/api/v1/change-requests",
        json={
            "policy_id": policy["id"],
            "idempotency_key": f"ik-{uuid.uuid4().hex}",
            "approval_policy": "break_glass",
        },
        headers=tenant_a,
    ).json()
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=tenant_a)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "segregation_of_duties"


def test_break_glass_cross_person_emergency_approval(client, tenant_a, env_a):
    """§19.3：持 change:break_glass 的提出者 + 跨人批准 → emergency_applied 并可部署。"""
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    cr = client.post(
        "/api/v1/change-requests",
        json={
            "policy_id": policy["id"],
            "idempotency_key": f"ik-{uuid.uuid4().hex}",
            "approval_policy": "break_glass",
        },
        headers=tenant_a,
    ).json()
    # 跨人批准（另一用户，change:approve）：放行进入紧急通道
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-bg-approver", "X-Dev-Roles": "security_admin"}
    resp = client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    assert resp.status_code == 200
    assert resp.json()["status"] == "emergency_applied"

    # emergency_applied 允许部署
    dep = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert dep.status_code == 201


def test_break_glass_review_due_after_deployment_status_change(client, tenant_a, env_a):
    """worker：紧急变更部署后状态已改变，到期仍必须转事后复核。"""
    from datetime import timedelta

    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    policy = _create_policy(client, tenant_a, agent_ids=[asset_id])
    cr = client.post(
        "/api/v1/change-requests",
        json={
            "policy_id": policy["id"],
            "idempotency_key": f"ik-{uuid.uuid4().hex}",
            "approval_policy": "break_glass",
        },
        headers=tenant_a,
    ).json()
    approver = {"X-Dev-Tenant-Id": "tnt-A", "X-Dev-User-Id": "user-bg-approver", "X-Dev-Roles": "security_admin"}
    client.post(f"/api/v1/change-requests/{cr['id']}/approve", json={}, headers=approver)
    deployed = client.post(
        "/api/v1/deployments",
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
        headers=tenant_a,
    )
    assert deployed.status_code == 201
    with session_scope() as session:
        from app.models import ChangeRequest

        row = session.query(ChangeRequest).filter(ChangeRequest.id == cr["id"]).one()
        assert row.status != "emergency_applied"
        row.created_at = row.created_at - timedelta(hours=25)  # 超过默认 24h TTL
        session.commit()
    from app.worker import once

    once()
    with session_scope() as session:
        from app.models import ChangeRequest

        row = session.query(ChangeRequest).filter(ChangeRequest.id == cr["id"]).one()
        assert row.status == "post_review_due"
