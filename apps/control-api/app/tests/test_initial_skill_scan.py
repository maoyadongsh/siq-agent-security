import json
import uuid

import pytest
from sqlalchemy import select, update

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, EdgeInitialScan, EdgeTask, OutboxEvent
from app.signing import build_task_envelope, public_key_base64, verify_task_signature
from app.tests import test_install_plan_issuer as issuer
from app.tests.edge_helpers import register_edge
from app.tests.test_skill_capability_claim import skill_capabilities

catalog = issuer.catalog


@pytest.fixture
def skill_initial_context(client, tenant_a, catalog, request):
    value = json.loads(catalog.read_text())
    connector = value["releases"][0]["connectors"][0]
    connector["id"] = "directory"
    connector["scope"] = {"roots": ["/fixture/skills"], "include": ["AGENTS.md", "SKILL.md"]}
    if getattr(request, "param", False):
        connector["scope"]["include"] = ["SKILL.md"]
    catalog.write_text(json.dumps(value))
    identity = "initial-skills-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": identity}).json()["id"]
    response = client.post(
        f"/api/v1/environments/{env}/install-plans",
        headers=tenant_a,
        json={**issuer.request(), "connectors": ["directory"]},
    )
    assert response.status_code == 200
    plan = response.json()
    headers, _ = register_edge(client, tenant_a, env, identity)
    caps = skill_capabilities()
    caps["connector_versions"]["directory"] = plan["connectors"][0]["version"]
    assert (
        client.post(
            "/edge/v1/heartbeat",
            headers=headers,
            json={
                "version": "0.1.0",
                "capabilities": caps,
            },
        ).status_code
        == 200
    )
    yield env, headers, plan
    with session_scope() as session:
        session.execute(update(EdgeTask).where(EdgeTask.environment_id == env).values(status="expired"))


def send(client, headers, plan, version="v2"):
    return client.post(
        "/edge/v1/initial-scan",
        headers=headers,
        json={
            "schema_version": "edge-initial-scan/" + version,
            "plan": plan,
        },
    )


def test_initial_skill_signed_scope_and_replay(client, skill_initial_context):
    env, headers, plan = skill_initial_context
    response = send(client, headers, plan)
    assert response.status_code == 200
    assert response.json()["schema_version"] == "edge-initial-scan-result/v2"
    assert len(response.json()["task_ids"]) == 2
    again = send(client, headers, plan)
    assert again.json() == {**response.json(), "replay": True}
    with session_scope() as session:
        tasks = session.scalars(select(EdgeTask).where(EdgeTask.environment_id == env)).all()
        assert len(tasks) == 2
        assert {row.task_type for row in tasks} == {"scan", "skill_scan"}
        ordinary = next(row for row in tasks if row.task_type == "scan")
        assert ordinary.payload["scope"]["include"] == ["AGENTS.md"]
        row = next(row for row in tasks if row.task_type == "skill_scan")
        assert row.payload == {
            "connector": "directory",
            "inventory_kind": "skills",
            "target_device_identity": headers["X-Edge-Identity"],
            "scope": {"roots": ["/fixture/skills"], "include": ["SKILL.md"]},
        }
        for row in tasks:
            envelope = build_task_envelope(row.id, row.task_type, env, row.payload, row.expires_at.isoformat())
            assert verify_task_signature(public_key_base64(), envelope, row.signature)
        events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.payload["payload"]["environment_id"].as_string() == env,
                OutboxEvent.event_type.in_(("scan.created.v1", "skill.scan.created.v1")),
            )
        ).all()
        assert len(events) == 2
        assert {event.event_type for event in events} == {"scan.created.v1", "skill.scan.created.v1"}
        audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.resource_id == env,
                AuditEvent.action == "scan.initial.create",
            )
        ).all()
        assert len(audits) == 1 and audits[0].summary["task_count"] == 2


@pytest.mark.parametrize("fault", ["capability", "quota", "audit", "tampered_scope"])
def test_initial_skill_atomic_denial(client, skill_initial_context, fault, monkeypatch):
    env, headers, plan = skill_initial_context
    if fault == "capability":
        caps = skill_capabilities()
        caps["connector_versions"]["directory"] = plan["connectors"][0]["version"]
        caps["connector_task_types"] = {"directory": ["scan"]}
        assert (
            client.post(
                "/edge/v1/heartbeat",
                headers=headers,
                json={
                    "version": "0.1.0",
                    "capabilities": caps,
                },
            ).status_code
            == 200
        )
    elif fault == "quota":
        monkeypatch.setenv("SIQ_AS_SCAN_QUOTA_PER_TENANT", "1")
    elif fault == "tampered_scope":
        plan["connectors"][0]["scope"]["roots"] = ["/fixture/other"]
    else:

        def fail(*args, **kwargs):
            raise RuntimeError("audit unavailable")

        monkeypatch.setattr("app.routers.initial_scan.audit", fail)
    if fault == "audit":
        with pytest.raises(RuntimeError, match="audit unavailable"):
            send(client, headers, plan)
    else:
        assert send(client, headers, plan).status_code == (429 if fault == "quota" else 409)
    with session_scope() as session:
        assert session.scalar(select(EdgeTask.id).where(EdgeTask.environment_id == env)) is None
        assert (
            session.scalar(
                select(EdgeInitialScan)
                .join(
                    EdgeAgent,
                    EdgeAgent.id == EdgeInitialScan.edge_agent_id,
                )
                .where(EdgeAgent.environment_id == env)
            )
            is None
        )
        assert (
            session.scalar(
                select(OutboxEvent).where(
                    OutboxEvent.payload["payload"]["environment_id"].as_string() == env,
                    OutboxEvent.event_type.in_(("scan.created.v1", "skill.scan.created.v1")),
                )
            )
            is None
        )


def test_legacy_initial_record_is_not_rewritten_as_skill_scan(client, skill_initial_context):
    env, headers, plan = skill_initial_context
    original = send(client, headers, plan, "v1")
    assert original.status_code == 200
    assert send(client, headers, plan).json() == {"detail": "initial_scan_version_conflict"}
    with session_scope() as session:
        tasks = session.scalars(select(EdgeTask).where(EdgeTask.environment_id == env)).all()
        assert len(tasks) == 1 and tasks[0].task_type == "scan"
        record = session.scalar(select(EdgeInitialScan).where(EdgeInitialScan.task_ids == original.json()["task_ids"]))
        assert record is not None


@pytest.mark.parametrize("skill_initial_context", [True], indirect=True)
@pytest.mark.parametrize("legacy_first", [False, True])
def test_skill_only_scope_never_becomes_agent_candidate_task(client, skill_initial_context, legacy_first):
    env, headers, plan = skill_initial_context
    if legacy_first:
        assert send(client, headers, plan, "v1").status_code == 200
    result = send(client, headers, plan)
    assert result.status_code == (409 if legacy_first else 200)
    with session_scope() as session:
        tasks = session.scalars(select(EdgeTask).where(EdgeTask.environment_id == env)).all()
        assert len(tasks) == 1
        assert tasks[0].task_type == ("scan" if legacy_first else "skill_scan")
