import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AgentAsset, AuditEvent, EdgeAgent, EdgeTask, PermissionFact, RoleSkillSelectionObservation
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


@pytest.fixture
def tenant_a(tenant_a):
    # Shared API database: isolate these task-heavy fixtures from scan quota tests.
    return {**tenant_a, "X-Dev-Tenant-Id": "tnt-role-" + uuid.uuid4().hex}


def selection(names=None):
    return {"schema_version": "enterprise-openclaw-skill-selection/v1", "source": "agent",
            "status": "declared_list", "names": ["docs"] if names is None else names}


def assert_unwritten(task_id):
    with session_scope() as session:
        task = session.get(EdgeTask, task_id)
        edge_ids = select(EdgeAgent.id).where(EdgeAgent.environment_id == task.environment_id)
        assert session.scalar(select(func.count(AgentAsset.id)).where(AgentAsset.discovery_scope.in_(edge_ids))) == 0
        assert session.scalar(select(func.count(RoleSkillSelectionObservation.id)).where(
            RoleSkillSelectionObservation.task_id == task_id,
        )) == 0
        assert task.status == "pending"


@pytest.fixture
def source(client, tenant_a):
    identity = "role-skill-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": identity}).json()["id"]
    headers, key = register_edge(client, tenant_a, env, identity)

    def prepare(value=None, connector="openclaw"):
        task_id = create_scan_task(client, tenant_a, env, connector)
        evidence = signed_evidence(key, identity, "ev-" + uuid.uuid4().hex)
        role = candidate("role", [evidence["evidence_id"]], source_type="openclaw_agent")
        role.update(candidate_id="openclaw:v2:" + "a" * 64, framework="openclaw",
                    source_locator="openclaw://agents/v2/" + "a" * 64,
                    attributes={"skill_selection": json.dumps(selection() if value is None else value)})
        return task_id, role, evidence

    def upload(task, role, evidence):
        batch = signed_batch(key, task, candidates=[role], evidence=[evidence])
        return client.post("/edge/v1/batches", headers=headers, json=batch), batch

    return prepare, upload, headers, key


def test_history_is_append_only_read_only_and_tenant_scoped(client, tenant_a, tenant_b, source):
    prepare, upload, headers, _ = source
    first = prepare()
    response, batch = upload(*first)
    assert response.status_code == 200, response.text
    replay = client.post("/edge/v1/batches", headers=headers, json=batch)
    assert replay.status_code == 200 and replay.json()["idempotent"]
    second = prepare(selection([]))
    response, _ = upload(*second)
    assert response.status_code == 200, response.text
    with session_scope() as session:
        rows = list(session.scalars(select(RoleSkillSelectionObservation).where(
            RoleSkillSelectionObservation.task_id.in_([first[0], second[0]]),
        ).order_by(RoleSkillSelectionObservation.received_at)))
        assert len(rows) == 2
        assert rows[0].selection["names"] == ["docs"] and rows[1].selection["names"] == []
        asset_id = rows[0].asset_id
        assert rows[1].asset_id == asset_id and rows[0].task_id != rows[1].task_id
        session.get(EdgeAgent, rows[0].edge_agent_id).revoked_at = rows[0].received_at
        assert session.scalar(select(func.count(PermissionFact.id)).where(PermissionFact.subject_id == asset_id)) == 0
        audits = session.scalar(select(func.count(AuditEvent.id)))
    route = f"/api/v1/agents/{asset_id}/skill-selections"
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403
    response = client.get(route, headers=tenant_a)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["relationship_status"] == "unresolved" and data["effective_permissions"] is None
    assert data["status"] == "historical_declarations"
    assert data["observations"][0]["selection"]["names"] == []
    assert data["observations"][1]["selection"]["names"] == ["docs"]
    assert data["observations"][0]["device"]["revoked"]
    assert all(row["source_evidence"] for row in data["observations"])
    assert "signature" not in response.text and "profiles/test" not in response.text
    with session_scope() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == audits


def test_default_role_remains_candidate_and_reuses_explicit_identity(client, tenant_a, source):
    prepare, upload, _, _ = source
    first = prepare({**selection(), "source": "defaults"})
    first[1]["name"] = "main"
    first[1]["attributes"]["role_identity_basis"] = "config_default"
    response, _ = upload(*first)
    assert response.status_code == 200, response.text
    with session_scope() as session:
        observation = session.scalar(select(RoleSkillSelectionObservation).where(
            RoleSkillSelectionObservation.task_id == first[0],
        ))
        asset_id = observation.asset_id
        asset = session.get(AgentAsset, asset_id)
        assert asset.status == "candidate"
        assert asset.attributes["role_identity_basis"] == "config_default"
        assert observation.selection["source"] == "defaults"
    second = prepare(selection([]))
    second[1]["attributes"]["role_identity_basis"] = "explicit_config"
    response, _ = upload(*second)
    assert response.status_code == 200, response.text
    with session_scope() as session:
        observation = session.scalar(select(RoleSkillSelectionObservation).where(
            RoleSkillSelectionObservation.task_id == second[0],
        ))
        assert observation.asset_id == asset_id
        asset = session.get(AgentAsset, asset_id)
        assert asset.status == "candidate"
        assert asset.attributes["role_identity_basis"] == "explicit_config"
        assert session.scalar(select(func.count(PermissionFact.id)).where(PermissionFact.subject_id == asset_id)) == 0
    response = client.get(f"/api/v1/agents/{asset_id}/skill-selections", headers=tenant_a)
    assert response.status_code == 200
    assert response.json()["relationship_status"] == "unresolved"
    assert response.json()["effective_permissions"] is None
    assert len(response.json()["observations"]) == 2


@pytest.mark.parametrize("value", [
    {**selection(), "names": ["docs", "docs"]},
    {**selection(), "names": ["z", "a"]},
    {**selection(), "names": ["sk-synthetic-secret-1234567890"]},
    {**selection(), "names": ["a"] * 65},
    {**selection(), "names": ["a" * 129]},
    {**selection(), "extra": "private-fixture"},
    {**selection(), "status": "unconfigured"},
    {**selection(), "source": "none"},
    {**selection(), "status": "unsupported"},
])
def test_invalid_selection_rejects_whole_batch_without_echo(client, source, value):
    prepare, upload, _, _ = source
    task, role, evidence = prepare(value)
    response, _ = upload(task, role, evidence)
    assert response.status_code == 422 and response.json()["detail"] == "role_skill_selection_invalid"
    assert "private-fixture" not in response.text and "sk-synthetic" not in response.text
    assert_unwritten(task)


@pytest.mark.parametrize("fault", [
    "framework", "identity", "connector", "duplicate_json", "duplicate_location", "duplicate_evidence",
    "excess_refs", "duplicate_refs",
])
def test_false_or_ambiguous_origin_denied(client, source, fault):
    prepare, _, headers, key = source
    task, role, evidence = prepare(connector="hermes" if fault == "connector" else "openclaw")
    roles, evidence_rows = [role], [evidence]
    if fault == "framework":
        role["framework"] = "hermes"
    elif fault == "identity":
        role["candidate_id"] = "openclaw:v2:" + "b" * 64
    elif fault == "duplicate_json":
        role["attributes"]["skill_selection"] = json.dumps(selection())[:-1] + ',"names":[]}'
    elif fault == "duplicate_location":
        roles.append({**role, "candidate_id": "different"})
    elif fault == "duplicate_evidence":
        evidence_rows.append(evidence)
    elif fault == "excess_refs":
        role["evidence_ids"] *= 65
    elif fault == "duplicate_refs":
        role["evidence_ids"] *= 2
    batch = signed_batch(key, task, candidates=roles, evidence=evidence_rows)
    assert client.post("/edge/v1/batches", headers=headers, json=batch).status_code == 422
    assert_unwritten(task)


def test_legacy_attribute_not_backfilled(client, tenant_a):
    with session_scope() as session:
        asset = AgentAsset(tenant_id=tenant_a["X-Dev-Tenant-Id"], name="legacy",
                           attributes={"skill_selection": json.dumps(selection())})
        session.add(asset)
        session.flush()
        asset_id = asset.id
    response = client.get(f"/api/v1/agents/{asset_id}/skill-selections", headers=tenant_a)
    assert response.json()["status"] == "no_recorded_declaration"
    assert response.json()["observations"] == []


def test_audit_failure_rolls_back_declaration(client, source, monkeypatch):
    from app.routers import inventory

    prepare, upload, _, _ = source
    task, role, evidence = prepare()

    def fail(*args, **kwargs):
        raise RuntimeError("fixture audit unavailable")

    monkeypatch.setattr(inventory, "audit", fail)
    with pytest.raises(RuntimeError, match="fixture audit unavailable"):
        upload(task, role, evidence)
    assert_unwritten(task)


def test_projection_bounded_and_corrupted_foreign_device_hidden(client, tenant_a, tenant_b, source):
    prepare, upload, _, _ = source
    prepared = prepare()
    response, _ = upload(*prepared)
    assert response.status_code == 200
    foreign_env = client.post("/api/v1/environments", headers=tenant_b,
                              json={"name": "foreign-role-" + uuid.uuid4().hex}).json()["id"]
    foreign_identity = "foreign-role-" + uuid.uuid4().hex
    register_edge(client, tenant_b, foreign_env, foreign_identity)
    with session_scope() as session:
        # Scope lookup by this fixture's task, not shared test database counts.
        task_id = prepared[0]
        original = session.scalar(select(RoleSkillSelectionObservation).where(
            RoleSkillSelectionObservation.task_id == task_id,
        ))
        asset_id = original.asset_id
        task = session.get(EdgeTask, task_id)
        foreign_edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == foreign_identity))
        for index in range(101):
            synthetic_task = EdgeTask(
                environment_id=task.environment_id, task_type="scan", payload={}, status="uploaded",
                expires_at=task.expires_at,
            )
            session.add(synthetic_task)
            session.flush()
            session.add(RoleSkillSelectionObservation(
                tenant_id=original.tenant_id, asset_id=asset_id,
                edge_agent_id=foreign_edge.id if index == 100 else original.edge_agent_id,
                task_id=synthetic_task.id, batch_digest="b" * 64, selection=selection(["fixture"]),
                source_evidence=[], observed_at=original.observed_at,
                received_at=original.received_at + timedelta(seconds=index + 1),
            ))
    response = client.get(f"/api/v1/agents/{asset_id}/skill-selections", headers=tenant_a)
    data = response.json()
    assert data["observations_truncated"] and len(data["observations"]) == 100
    assert all(row["selection"]["names"] == ["fixture"] for row in data["observations"])
    assert foreign_edge.id not in response.text
