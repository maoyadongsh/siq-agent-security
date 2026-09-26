import uuid
from datetime import timedelta

from sqlalchemy import select, update

from app.db import session_scope
from app.models import EdgeAgent, EdgeTask, utcnow
from app.tests.edge_helpers import register_edge, signed_batch, signed_evidence


def test_target_bound_claim_receipt_and_batch(client, tenant_a, tenant_b):
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": "target-" + uuid.uuid4().hex}).json()[
        "id"
    ]
    identity = "target-" + uuid.uuid4().hex
    target, _ = register_edge(client, tenant_a, env, identity)
    other_id = "other-" + uuid.uuid4().hex
    other, other_key = register_edge(client, tenant_a, env, other_id)
    try:
        request = {"environment_id": env, "connector": "hermes", "scope": {}, "target_device_identity": identity}
        assert client.post("/api/v1/scans", headers=tenant_b, json=request).status_code == 404
        assert (
            client.post(
                "/api/v1/scans", headers=tenant_a, json={**request, "target_device_identity": "missing-device"}
            ).status_code
            == 404
        )
        created = client.post("/api/v1/scans", headers=tenant_a, json=request)
        assert created.status_code == 200
        task_id = created.json()["task_id"]
        assert client.get("/edge/v1/tasks", headers=other).json() == []
        received = client.get("/edge/v1/tasks", headers=target).json()
        assert received[0]["id"] == task_id
        assert received[0]["payload"]["target_device_identity"] == identity
        with session_scope() as session:
            session.get(EdgeTask, task_id).leased_at = utcnow() - timedelta(days=1)
        assert client.get("/edge/v1/tasks", headers=other).json() == []
        receipt = {"status": "failed", "error_code": "fixture"}
        response = client.post(f"/edge/v1/tasks/{task_id}/receipt", headers=other, json=receipt)
        assert response.status_code == 409 and response.json()["detail"] == "receipt_task_device_mismatch"
        batch = signed_batch(other_key, task_id, evidence=[signed_evidence(other_key, other_id, "target-fixture")])
        response = client.post("/edge/v1/batches", headers=other, json=batch)
        assert response.status_code == 409 and response.json()["detail"] == "batch_task_device_mismatch"
        assert client.post(f"/edge/v1/tasks/{task_id}/receipt", headers=target, json=receipt).status_code == 200
        assert client.post(f"/edge/v1/tasks/{task_id}/receipt", headers=other, json=receipt).status_code == 409
        with session_scope() as session:
            session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity)).revoked_at = utcnow()
        assert client.post("/api/v1/scans", headers=tenant_a, json=request).status_code == 409
    finally:
        with session_scope() as session:
            session.execute(update(EdgeTask).where(EdgeTask.environment_id == env).values(status="expired"))
