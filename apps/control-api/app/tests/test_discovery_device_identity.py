import uuid

from sqlalchemy import select, update

from app.db import session_scope
from app.models import AgentAsset, EdgeAgent, EdgeTask, Evidence
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


def test_same_locator_and_evidence_across_devices_do_not_merge(client, tenant_a, tenant_b):
    name = "device-scope-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": name}).json()["id"]
    try:
        assets = []
        for i in range(2):
            identity = name + str(i)
            headers, key = register_edge(client, tenant_a, env, identity)
            for _ in range(2):
                task_id = create_scan_task(client, tenant_a, env)
                ev = signed_evidence(key, identity, name, content_hash="a" * 64)
                batch = signed_batch(key, task_id, candidates=[candidate("same-profile", [name])], evidence=[ev])
                response = client.post("/edge/v1/batches", headers=headers, json=batch)
                assert response.status_code == 200, response.text
            with session_scope() as session:
                edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
                rows = session.scalars(select(AgentAsset).where(AgentAsset.discovery_scope == edge.id)).all()
                assert len(rows) == 1
                assets.append(rows[0].id)
            evidence = client.get(f"/api/v1/agents/{assets[-1]}/evidence", headers=tenant_a)
            assert evidence.status_code == 200
            assert len(evidence.json()) == 1
            assert evidence.json()[0]["collector_id"] == identity
            origin = client.get(f"/api/v1/agents/{assets[-1]}/discovery-origin", headers=tenant_a)
            assert origin.status_code == 200 and origin.headers["cache-control"] == "no-store"
            assert origin.json()["status"] == "device_bound"
            assert origin.json()["device"]["identity"] == identity
            assert origin.json()["environment"]["id"] == env
            assert len(origin.json()["observations"]) == 1
            assert origin.json()["observations"][0]["evidence_id"] == name
            assert "secret" not in origin.text
            assert client.get(f"/api/v1/agents/{assets[-1]}/evidence", headers=tenant_b).status_code == 404
        assert assets[0] != assets[1]
        with session_scope() as session:
            observations = session.scalars(select(Evidence).where(Evidence.environment_id == env)).all()
            assert len(observations) == 2
    finally:
        with session_scope() as session:
            session.execute(update(EdgeTask).where(EdgeTask.environment_id == env).values(status="expired"))
