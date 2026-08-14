"""Edge 注册生命周期负向测试（设计文档 §31.4 验收）。

覆盖：注册码一次性/过期拒绝、secret 只返回一次、吊销 Edge 立即失能、任务环境隔离。
"""

from __future__ import annotations

from app.db import session_scope
from app.models import EdgeAgent, Environment
from app.tests.edge_helpers import edge_public_key_pem


def _register_edge(client, env_id, headers, identity, code=None):
    if code is None:
        code = client.post(
            f"/api/v1/environments/{env_id}/edge-enrollment", json={}, headers=headers
        ).json()["code"]
    return client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": code,
            "device_identity": identity,
            "public_key_pem": edge_public_key_pem(identity),
            "version": "0.1.0",
        },
    )


def test_enrollment_code_single_use(client, tenant_a, env_a):
    resp1 = _register_edge(client, env_a["id"], tenant_a, "edge-once")
    assert resp1.status_code == 200
    assert resp1.json()["device_secret"].startswith("edge-")

    # 同一注册码重放：拒绝
    code = client.post(
        f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_a
    ).json()["code"]
    ok = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": code,
            "device_identity": "edge-once-2",
            "public_key_pem": edge_public_key_pem("edge-once-2"),
            "version": "0.1.0",
        },
    )
    assert ok.status_code == 200
    replay = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": code,
            "device_identity": "edge-once-3",
            "public_key_pem": edge_public_key_pem("edge-once-3"),
            "version": "0.1.0",
        },
    )
    assert replay.status_code == 401


def test_wrong_enrollment_code_rejected(client, tenant_a, env_a):
    resp = _register_edge(client, env_a["id"], tenant_a, "edge-bad", code="enr-forged-code")
    assert resp.status_code == 401


def test_invalid_edge_public_key_rejected_without_consuming_enrollment(client, tenant_a, env_a):
    code = client.post(
        f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_a
    ).json()["code"]
    bad = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": code,
            "device_identity": "edge-invalid-key",
            "public_key_pem": "not-a-public-key",
            "version": "0.1.0",
        },
    )
    assert bad.status_code == 422
    good = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": code,
            "device_identity": "edge-valid-key",
            "public_key_pem": edge_public_key_pem("edge-valid-key"),
            "version": "0.1.0",
        },
    )
    assert good.status_code == 200


def test_heartbeat_and_revocation(client, tenant_a, env_a):
    reg = _register_edge(client, env_a["id"], tenant_a, "edge-revoke")
    secret = reg.json()["device_secret"]
    headers = {"Authorization": f"Bearer {secret}", "X-Edge-Identity": "edge-revoke"}

    hb = client.post("/edge/v1/heartbeat", json={"version": "0.2.0"}, headers=headers)
    assert hb.status_code == 200
    with session_scope() as session:
        edge = session.query(EdgeAgent).filter(EdgeAgent.device_identity == "edge-revoke").one()
        env = session.get(Environment, env_a["id"])
        assert edge.version == "0.2.0"
        assert edge.last_seen_at is not None
        assert env is not None and env.last_heartbeat_at is not None

    # 吊销：立即失效（在线校验，设计文档 §31.4）
    with session_scope() as session:
        edge = session.query(EdgeAgent).filter(EdgeAgent.device_identity == "edge-revoke").one()
        edge.revoked_at = edge.registered_at

    hb2 = client.post("/edge/v1/heartbeat", json={"version": "0.1.0"}, headers=headers)
    assert hb2.status_code == 401

    tasks = client.get("/edge/v1/tasks", headers=headers)
    assert tasks.status_code == 401


def test_wrong_secret_rejected(client, tenant_a, env_a):
    _register_edge(client, env_a["id"], tenant_a, "edge-wrongsecret")
    headers = {"Authorization": "Bearer edge-forged-secret", "X-Edge-Identity": "edge-wrongsecret"}
    assert client.post("/edge/v1/heartbeat", json={"version": "0.1.0"}, headers=headers).status_code == 401


def test_tasks_scoped_to_environment(client, tenant_a, tenant_b, env_a, env_b):
    # 给 env_a 建扫描任务；env_b 的 Edge 看不到
    created = client.post(
        "/api/v1/scans", json={"environment_id": env_a["id"], "scope": {"connector": "hermes"}}, headers=tenant_a
    ).json()
    reg_b = _register_edge(client, env_b["id"], tenant_b, "edge-env-b")
    headers_b = {"Authorization": f"Bearer {reg_b.json()['device_secret']}", "X-Edge-Identity": "edge-env-b"}
    tasks_b = client.get("/edge/v1/tasks", headers=headers_b).json()
    assert tasks_b == []

    reg_a = _register_edge(client, env_a["id"], tenant_a, "edge-env-a")
    headers_a = {"Authorization": f"Bearer {reg_a.json()['device_secret']}", "X-Edge-Identity": "edge-env-a"}
    tasks_a = client.get("/edge/v1/tasks", headers=headers_a).json()
    scan_tasks = [t for t in tasks_a if t["task_type"] == "scan"]
    assert any(task["id"] == created["task_id"] for task in scan_tasks)


def test_edge_receipt_requires_verification_evidence(client, tenant_a, env_a):
    """回执必须携带可机器校验证据（§21.1 不变量 #5 的 API 层落地）。"""
    client.post(
        "/api/v1/scans", json={"environment_id": env_a["id"], "scope": {}}, headers=tenant_a
    )
    reg = _register_edge(client, env_a["id"], tenant_a, "edge-receipt")
    headers = {"Authorization": f"Bearer {reg.json()['device_secret']}", "X-Edge-Identity": "edge-receipt"}
    task = client.get("/edge/v1/tasks", headers=headers).json()[0]
    mismatch = client.post(
        f"/edge/v1/tasks/{task['id']}/receipt",
        json={"task_id": "tsk-foreign", "status": "success"},
        headers=headers,
    )
    assert mismatch.status_code == 409
    resp = client.post(
        f"/edge/v1/tasks/{task['id']}/receipt",
        json={
            "task_id": task["id"],
            "device_identity": "edge-receipt",
            "status": "success",
            "summary": {},
            "verification": {"backend_revision": "rev_42", "snapshot_hash": "c" * 64},
        },
        headers=headers,
    )
    assert resp.status_code == 200
    replay = client.post(
        f"/edge/v1/tasks/{task['id']}/receipt",
        json={"task_id": task["id"], "device_identity": "edge-receipt", "status": "success"},
        headers=headers,
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent"] is True
    conflict = client.post(
        f"/edge/v1/tasks/{task['id']}/receipt",
        json={"task_id": task["id"], "device_identity": "edge-receipt", "status": "failed"},
        headers=headers,
    )
    assert conflict.status_code == 409
