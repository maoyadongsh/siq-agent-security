import hashlib
import uuid

from sqlalchemy import select, update

from app.db import session_scope
from app.models import AgentAsset, EdgeAgent, EdgeTask, Finding
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


def test_threat_scan_cannot_borrow_other_device_same_external_evidence(client, tenant_a):
    name = "threat-device-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": name}).json()["id"]
    contents = ["safe synthetic content one", "safe synthetic content two"]
    assets = []
    try:
        for i, content in enumerate(contents):
            identity = name + str(i)
            headers, key = register_edge(client, tenant_a, env, identity)
            task_id = create_scan_task(client, tenant_a, env)
            ev = signed_evidence(key, identity, name, content_hash=hashlib.sha256(content.encode()).hexdigest())
            cand = {**candidate(name, [name]), "artifact_digest": "0" * 64}
            body = signed_batch(key, task_id, candidates=[cand], evidence=[ev])
            assert client.post("/edge/v1/batches", headers=headers, json=body).status_code == 200
            with session_scope() as session:
                edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
                assets.append(session.scalar(select(AgentAsset.id).where(AgentAsset.discovery_scope == edge.id)))
        route = f"/api/v1/assets/{assets[0]}/threat-scan"
        result = client.post(route, headers=tenant_a, json={"content": contents[1], "evidence_ids": [name]})
        assert result.status_code == 422
        assert result.json()["detail"].startswith("content_not_bound")
        result = client.post(
            route, headers=tenant_a, json={"content": contents[0], "evidence_ids": [name + "-unrelated"]}
        )
        assert result.status_code == 422 and result.json()["detail"] == "evidence_not_bound_to_asset"
        with session_scope() as session:
            assert session.get(AgentAsset, assets[0]).artifact_digest == "0" * 64
            assert session.scalar(select(Finding.id).where(Finding.asset_id == assets[0])) is None
        result = client.post(route, headers=tenant_a, json={"content": contents[0], "evidence_ids": [name]})
        assert result.status_code == 200
    finally:
        with session_scope() as session:
            session.execute(update(EdgeTask).where(EdgeTask.environment_id == env).values(status="expired"))
