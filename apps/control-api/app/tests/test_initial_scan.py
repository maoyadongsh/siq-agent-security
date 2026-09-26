import copy
import uuid

import pytest
from sqlalchemy import func, select, update

from app.db import session_scope
from app.models import EdgeInitialScan, EdgeTask
from app.tests import test_install_plan_issuer as issuer
from app.tests.edge_helpers import register_edge

catalog = issuer.catalog


@pytest.fixture
def initial_context(client, tenant_a, catalog):
    identity = "initial-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": identity}).json()["id"]
    plan = client.post(f"/api/v1/environments/{env}/install-plans", headers=tenant_a, json=issuer.request()).json()
    headers, _ = register_edge(client, tenant_a, env, identity)
    capabilities = {
        "inventory_schema": "enterprise-installed-capabilities/v1",
        "protocol_version": "connector-protocol.v1",
        "connectors": [c["id"] for c in plan["connectors"]],
        "connector_versions": {c["id"]: c["version"] for c in plan["connectors"]},
        "data_categories": [],
    }
    assert (
        client.post(
            "/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": capabilities}
        ).status_code
        == 200
    )
    yield env, headers, plan
    with session_scope() as session:
        session.execute(update(EdgeTask).where(EdgeTask.environment_id == env).values(status="expired"))


def send(client, headers, plan):
    return client.post(
        "/edge/v1/initial-scan", headers=headers, json={"schema_version": "edge-initial-scan/v1", "plan": plan}
    )


def test_initial_exact_scope_target_and_replay(client, initial_context):
    env, headers, plan = initial_context
    response = send(client, headers, plan)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["replay"] is False
    again = send(client, headers, plan).json()
    assert again["replay"] is True and again["task_ids"] == result["task_ids"]
    with session_scope() as session:
        tasks = session.scalars(select(EdgeTask).where(EdgeTask.environment_id == env)).all()
        assert len(tasks) == len(plan["connectors"])
        assert tasks[0].payload["scope"] == plan["connectors"][0]["scope"]
        assert tasks[0].payload["target_device_identity"] == headers["X-Edge-Identity"]
        assert tasks[0].signature
    changed = copy.deepcopy(plan)
    changed["connectors"][0]["scope"]["include"] = ["SOUL.md"]
    assert send(client, headers, changed).status_code == 409


@pytest.mark.parametrize("fault", ["scope", "tenant", "environment", "capabilities", "no_audit", "expired"])
def test_initial_scan_rejects_without_tasks(client, initial_context, fault, monkeypatch):
    env, headers, plan = initial_context
    changed = copy.deepcopy(plan)
    if fault == "scope":
        changed["connectors"][0]["scope"]["include"] = ["SOUL.md"]
    elif fault in {"tenant", "environment"}:
        changed[fault + "_id"] = "other"
    elif fault == "capabilities":
        caps = {
            "inventory_schema": "enterprise-installed-capabilities/v1",
            "protocol_version": "connector-protocol.v1",
            "connectors": [],
            "connector_versions": {},
            "data_categories": [],
        }
        assert (
            client.post(
                "/edge/v1/heartbeat", headers=headers, json={"version": "0.1.0", "capabilities": caps}
            ).status_code
            == 200
        )
    elif fault == "no_audit":
        changed["plan_id"] = "eip-" + "f" * 32
    else:

        def expired(self):
            raise ValueError("expired")

        monkeypatch.setattr("app.install_plan.EnterpriseInstallPlan.require_current", expired)
    response = send(client, headers, changed)
    assert response.status_code == (404 if fault in {"tenant", "environment"} else 409)
    with session_scope() as session:
        assert session.scalar(select(func.count(EdgeTask.id)).where(EdgeTask.environment_id == env)) == 0


def test_initial_audit_failure_rolls_back(client, initial_context, monkeypatch):
    env, headers, plan = initial_context
    with session_scope() as session:
        before = session.scalar(select(func.count(EdgeInitialScan.edge_agent_id)))

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("app.routers.initial_scan.audit", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        send(client, headers, plan)
    with session_scope() as session:
        assert session.scalar(select(func.count(EdgeTask.id)).where(EdgeTask.environment_id == env)) == 0
        assert session.scalar(select(func.count(EdgeInitialScan.edge_agent_id))) == before
