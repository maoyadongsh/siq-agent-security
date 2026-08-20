"""P1-5 Edge 任务原子领取（claim/lease）测试。

覆盖：
- 租约内任务对其他设备不可见（先后 fetch；条件 UPDATE 的 rowcount 语义保证
  并发下也只有一个请求能 claim 成功，SQLite 单写者串行化同理）；
- 同一设备重复 fetch 拿回自己租约内的任务且 attempt 递增（at-least-once）；
- 租约过期后其他设备可接管；
- 非持有者在租约内回执 → 409 receipt_lease_mismatch，持有者回执正常；
- 终态幂等重放语义不变（idempotent / replay_conflict 优先于租约检查）。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import session_scope
from app.models import EdgeTask, utcnow
from app.tests.edge_helpers import create_scan_task, register_edge


@pytest.fixture(scope="module")
def lease_env(client, tenant_a):
    """独立环境，避免与其他测试模块共享 env_a 的遗留任务互相干扰。"""
    resp = client.post(
        "/api/v1/environments",
        json={"name": "lease-test-env", "env_type": "host", "mode": "enforce"},
        headers=tenant_a,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_lease_excludes_other_devices(client, tenant_a, lease_env):
    task_id = create_scan_task(client, tenant_a, lease_env["id"])
    headers_a, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-a1")
    headers_b, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-b1")

    tasks_a = client.get("/edge/v1/tasks", headers=headers_a).json()
    assert any(t["id"] == task_id for t in tasks_a)
    with session_scope() as session:
        task = session.get(EdgeTask, task_id)
        assert task.lease_owner == "edge-lease-a1"
        assert task.leased_at is not None
        assert task.attempt == 1

    # 设备 B 在租约内 fetch：拿不到 A 持有的任务
    tasks_b = client.get("/edge/v1/tasks", headers=headers_b).json()
    assert all(t["id"] != task_id for t in tasks_b)


def test_same_device_refetch_renews_lease(client, tenant_a, lease_env):
    task_id = create_scan_task(client, tenant_a, lease_env["id"])
    headers_a, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-a2")

    first = client.get("/edge/v1/tasks", headers=headers_a).json()
    assert any(t["id"] == task_id for t in first)
    # 重复 fetch（重试/重启）：拿回自己租约未过期的任务，attempt 递增
    second = client.get("/edge/v1/tasks", headers=headers_a).json()
    assert any(t["id"] == task_id for t in second)
    with session_scope() as session:
        task = session.get(EdgeTask, task_id)
        assert task.lease_owner == "edge-lease-a2"
        assert task.attempt == 2


def test_lease_expiry_allows_takeover(client, tenant_a, lease_env):
    task_id = create_scan_task(client, tenant_a, lease_env["id"])
    headers_a, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-a3")
    headers_b, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-b3")

    tasks_a = client.get("/edge/v1/tasks", headers=headers_a).json()
    assert any(t["id"] == task_id for t in tasks_a)

    # 直接把 leased_at 调到过去，模拟持有者宕机、租约过期
    with session_scope() as session:
        task = session.get(EdgeTask, task_id)
        task.leased_at = utcnow() - timedelta(seconds=3600)

    tasks_b = client.get("/edge/v1/tasks", headers=headers_b).json()
    assert any(t["id"] == task_id for t in tasks_b)
    with session_scope() as session:
        task = session.get(EdgeTask, task_id)
        assert task.lease_owner == "edge-lease-b3"
        assert task.attempt == 2


def test_receipt_lease_mismatch(client, tenant_a, lease_env):
    task_id = create_scan_task(client, tenant_a, lease_env["id"])
    headers_a, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-a4")
    headers_b, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-b4")

    tasks_a = client.get("/edge/v1/tasks", headers=headers_a).json()
    assert any(t["id"] == task_id for t in tasks_a)

    # 非持有者在租约内提交回执 → 409 receipt_lease_mismatch
    resp_b = client.post(
        f"/edge/v1/tasks/{task_id}/receipt",
        json={"status": "failed", "error_code": "boom"},
        headers=headers_b,
    )
    assert resp_b.status_code == 409
    assert resp_b.json()["detail"] == "receipt_lease_mismatch"

    # 持有者回执正常
    resp_a = client.post(
        f"/edge/v1/tasks/{task_id}/receipt",
        json={"status": "failed", "error_code": "boom"},
        headers=headers_a,
    )
    assert resp_a.status_code == 200


def test_terminal_receipt_replay_semantics_unchanged(client, tenant_a, lease_env):
    task_id = create_scan_task(client, tenant_a, lease_env["id"])
    headers_a, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-a5")
    headers_b, _ = register_edge(client, tenant_a, lease_env["id"], "edge-lease-b5")

    tasks_a = client.get("/edge/v1/tasks", headers=headers_a).json()
    assert any(t["id"] == task_id for t in tasks_a)

    ok = client.post(
        f"/edge/v1/tasks/{task_id}/receipt",
        json={"status": "success"},
        headers=headers_a,
    )
    assert ok.status_code == 200
    # 同状态重放 → 幂等
    replay = client.post(
        f"/edge/v1/tasks/{task_id}/receipt",
        json={"status": "success"},
        headers=headers_a,
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent"] is True
    # 不同终态重放 → replay_conflict
    conflict = client.post(
        f"/edge/v1/tasks/{task_id}/receipt",
        json={"status": "failed"},
        headers=headers_a,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "receipt_replay_conflict"
    # 终态幂等优先于租约检查：其他设备对已达终态任务的重放仍按既有幂等语义处理
    other = client.post(
        f"/edge/v1/tasks/{task_id}/receipt",
        json={"status": "success"},
        headers=headers_b,
    )
    assert other.status_code == 200
    assert other.json()["idempotent"] is True
