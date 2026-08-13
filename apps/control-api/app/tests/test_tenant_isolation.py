"""跨租户负向测试（设计文档 §21.1 不变量 #1 / §31.4 验收）。

核心断言：知道对象 ID 不构成访问权；跨租户与不存在统一 404，不泄露存在性。
"""

from __future__ import annotations


def _make_agent(client, headers, name):
    """经 Edge 上传批次创建一个候选资产（不直接写库）。"""
    env_resp = client.post("/api/v1/environments", json={"name": f"env-{name}"}, headers=headers)
    env_id = env_resp.json()["id"]
    # 注册 Edge
    enr = client.post(f"/api/v1/environments/{env_id}/edge-enrollment", json={}, headers=headers).json()
    reg = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enr["code"],
            "device_identity": f"edge-{name}",
            "public_key_pem": "PEM-PLACEHOLDER",
            "version": "0.1.0",
        },
    )
    edge_secret = reg.json()["device_secret"]
    edge_headers = {"Authorization": f"Bearer {edge_secret}", "X-Edge-Identity": f"edge-{name}"}
    batch = {
        "candidates": [
            {
                "candidate_id": f"hermes:{name}",
                "source_type": "hermes_profile",
                "source_locator": f"hermes://profiles/{name}",
                "discovered_at": "2026-08-13T12:00:00Z",
                "name": name,
                "framework": "hermes",
                "evidence_ids": [f"ev-{name}"],
            }
        ],
        "evidence": [
            {
                "evidence_id": f"ev-{name}",
                "source_type": "manifest",
                "source_locator": f"profiles/{name}/config.yaml",
                "observed_at": "2026-08-13T12:00:00Z",
                "collector_id": f"edge-{name}",
                "connector_version": "0.1.0",
                "content_hash": "a" * 64,
                "redaction_profile": "siq.redaction.v1",
                "classification": "internal",
                "signature": "sig",
            }
        ],
    }
    upload = client.post("/edge/v1/batches", json=batch, headers=edge_headers)
    assert upload.status_code == 200, upload.text
    assets = client.get("/api/v1/candidates", headers=headers).json()
    return next(a for a in assets if a["name"] == name)


def test_cross_tenant_candidate_list_invisible(client, tenant_a, tenant_b):
    agent_a = _make_agent(client, tenant_a, "agent-a")
    assets_b = client.get("/api/v1/candidates", headers=tenant_b).json()
    assert all(a["id"] != agent_a["id"] for a in assets_b)


def test_cross_tenant_agent_id_guessing_404(client, tenant_a, tenant_b):
    agent_a = _make_agent(client, tenant_a, "agent-a2")
    # B 用 A 的资产 ID 深链访问：必须 404 且不可见
    resp = client.get(f"/api/v1/agents/{agent_a['id']}", headers=tenant_b)
    assert resp.status_code == 404
    # 任意猜测 ID 同样 404（不区分"不存在"与"无权"）
    resp2 = client.get("/api/v1/agents/agt_nonexistent", headers=tenant_b)
    assert resp2.status_code == 404


def test_cross_tenant_environment_404(client, tenant_a, tenant_b, env_a):
    resp = client.post(
        f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_b
    )
    assert resp.status_code == 404


def test_tenant_derived_not_client_supplied(client, tenant_b, env_b):
    """环境创建永远落到身份派生的租户；env_b 属于 tnt-B。"""
    resp = client.get("/api/v1/environments", headers=tenant_b)
    assert resp.status_code == 200
    assert all(env["tenant_id"] == "tnt-B" for env in resp.json())


def test_cross_tenant_audit_invisible(client, tenant_a, tenant_b):
    _make_agent(client, tenant_a, "agent-a3")
    events_b = client.get("/api/v1/audit-events", headers=tenant_b).json()
    # B 的审计里不得出现 A 的操作
    assert not any(e["actor_id"] == "user-a" for e in events_b)


def test_orphan_evidence_rejected(client, tenant_a):
    """Connector 合同：每批 evidence 必须被 candidate 引用，孤儿证据拒绝（§10.2 硬性要求）。"""
    env_resp = client.post("/api/v1/environments", json={"name": "env-orphan"}, headers=tenant_a)
    env_id = env_resp.json()["id"]
    enr = client.post(f"/api/v1/environments/{env_id}/edge-enrollment", json={}, headers=tenant_a).json()
    reg = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enr["code"],
            "device_identity": "edge-orphan",
            "public_key_pem": "PEM",
            "version": "0.1.0",
        },
    )
    edge_headers = {"Authorization": f"Bearer {reg.json()['device_secret']}", "X-Edge-Identity": "edge-orphan"}
    batch = {
        "candidates": [],
        "evidence": [
            {
                "evidence_id": "ev-orphan",
                "source_type": "manifest",
                "source_locator": "x",
                "observed_at": "2026-08-13T12:00:00Z",
                "collector_id": "edge-orphan",
                "connector_version": "0.1.0",
                "content_hash": "b" * 64,
                "signature": "sig",
            }
        ],
    }
    resp = client.post("/edge/v1/batches", json=batch, headers=edge_headers)
    assert resp.status_code == 422
    assert "orphan_evidence" in resp.json()["detail"]
