"""跨租户负向测试（设计文档 §21.1 不变量 #1 / §31.4 验收）。

核心断言：知道对象 ID 不构成访问权；跨租户与不存在统一 404，不泄露存在性。
"""

from __future__ import annotations

from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


def _make_agent(client, headers, name, *, evidence_id=None, edge_identity=None):
    """经 Edge 上传批次创建一个候选资产（不直接写库）。"""
    env_resp = client.post("/api/v1/environments", json={"name": f"env-{name}"}, headers=headers)
    env_id = env_resp.json()["id"]
    identity = edge_identity or f"edge-{name}"
    evidence_id = evidence_id or f"ev-{name}"
    edge_headers, private_key = register_edge(client, headers, env_id, identity)
    task_id = create_scan_task(client, headers, env_id)
    evidence = signed_evidence(
        private_key,
        identity,
        evidence_id,
        content_hash="a" * 64,
        source_locator=f"profiles/{name}/config.yaml",
    )
    batch = signed_batch(
        private_key,
        task_id,
        candidates=[candidate(name, [evidence_id])],
        evidence=[evidence],
    )
    upload = client.post("/edge/v1/batches", json=batch, headers=edge_headers)
    assert upload.status_code == 200, upload.text
    assets = client.get("/api/v1/candidates", headers=headers).json()
    return next(a for a in assets if a["name"] == name)


def test_evidence_linked_to_asset_via_batch(client, tenant_a):
    """批次上传的 evidence_ids 必须落库并可通过资产证据端点查询（§10.5 关联）。"""
    agent_a = _make_agent(client, tenant_a, "agent-ev")
    evidence = client.get(f"/api/v1/agents/{agent_a['id']}/evidence", headers=tenant_a).json()
    assert len(evidence) == 1
    assert evidence[0]["source_locator"].endswith("config.yaml")


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
    edge_headers, private_key = register_edge(client, tenant_a, env_id, "edge-orphan")
    task_id = create_scan_task(client, tenant_a, env_id)
    evidence = signed_evidence(private_key, "edge-orphan", "ev-orphan", content_hash="b" * 64)
    batch = signed_batch(private_key, task_id, evidence=[evidence])
    resp = client.post("/edge/v1/batches", json=batch, headers=edge_headers)
    assert resp.status_code == 422
    assert "orphan_evidence" in resp.json()["detail"]


def test_same_external_evidence_id_is_tenant_scoped(client, tenant_a, tenant_b):
    agent_a = _make_agent(
        client,
        tenant_a,
        "shared-evidence-a",
        evidence_id="ev-shared-evidence-id",
        edge_identity="edge-shared-evidence-a",
    )
    agent_b = _make_agent(
        client,
        tenant_b,
        "shared-evidence-b",
        evidence_id="ev-shared-evidence-id",
        edge_identity="edge-shared-evidence-b",
    )
    evidence_a = client.get(f"/api/v1/agents/{agent_a['id']}/evidence", headers=tenant_a).json()
    evidence_b = client.get(f"/api/v1/agents/{agent_b['id']}/evidence", headers=tenant_b).json()
    assert evidence_a[0]["id"] == evidence_b[0]["id"] == "ev-shared-evidence-id"
    assert evidence_a[0]["observation_id"] != evidence_b[0]["observation_id"]


def test_tampered_or_unbound_evidence_batch_is_rejected(client, tenant_a):
    env = client.post("/api/v1/environments", json={"name": "env-batch-negative"}, headers=tenant_a).json()
    identity = "edge-batch-negative"
    edge_headers, private_key = register_edge(client, tenant_a, env["id"], identity)
    task_id = create_scan_task(client, tenant_a, env["id"])
    evidence = signed_evidence(private_key, identity, "ev-batch-negative")
    valid = signed_batch(
        private_key,
        task_id,
        candidates=[candidate("batch-negative", ["ev-batch-negative"])],
        evidence=[evidence],
    )

    tampered_batch = {**valid, "candidates": [{**valid["candidates"][0], "name": "tampered"}]}
    response = client.post("/edge/v1/batches", json=tampered_batch, headers=edge_headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "batch_signature_invalid"

    tampered_evidence = {**evidence, "content_hash": "f" * 64}
    resigned_batch = signed_batch(
        private_key,
        task_id,
        candidates=[candidate("batch-negative", ["ev-batch-negative"])],
        evidence=[tampered_evidence],
    )
    response = client.post("/edge/v1/batches", json=resigned_batch, headers=edge_headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "evidence_signature_invalid"

    unbound = signed_batch(
        private_key,
        "tsk-not-owned",
        candidates=[candidate("batch-negative", ["ev-batch-negative"])],
        evidence=[evidence],
    )
    response = client.post("/edge/v1/batches", json=unbound, headers=edge_headers)
    assert response.status_code == 409
    assert response.json()["detail"] == "batch_task_binding_invalid"


def test_edge_batch_declared_over_size_limit_is_rejected_before_parsing(client, tenant_a):
    env = client.post("/api/v1/environments", json={"name": "env-batch-size"}, headers=tenant_a).json()
    edge_headers, _ = register_edge(client, tenant_a, env["id"], "edge-batch-size")
    response = client.post(
        "/edge/v1/batches",
        content=b"{}",
        headers={**edge_headers, "Content-Length": str(8 * 1024 * 1024 + 1)},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "batch_too_large"
