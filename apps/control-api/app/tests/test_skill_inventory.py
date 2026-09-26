from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, SkillInstallation, SkillManifestObservation, utcnow
from app.tests import test_skill_upload as uploads
from app.tests.edge_helpers import register_edge

upload_case = uploads.upload_case


def installation_id(edge_id):
    with session_scope() as session:
        return session.scalar(select(SkillInstallation.id).where(SkillInstallation.edge_agent_id == edge_id))


def test_uploaded_skill_visible_without_implying_permissions(client, tenant_a, upload_case):
    _, upload, _, edge_id, _, env = upload_case
    assert upload().status_code == 200
    key = installation_id(edge_id)
    with session_scope() as session:
        before = session.scalar(select(func.count(AuditEvent.id)))
    response = client.get("/api/v1/skill-installations", headers=tenant_a, params={"environment_id": env})
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    value = response.json()
    assert value["schema_version"] == "enterprise-skill-inventory/v1"
    assert value["next_cursor"] is None and len(value["items"]) == 1
    item = value["items"][0]
    assert item["installation_id"] == key
    assert item["latest_observation"]["declared_tools"] == ["read_file"]
    assert item["latest_observation"]["name"] == "sample"
    assert item["effective_permissions"] is None
    assert item["presence"] == "observed_not_verified_current"
    assert item["relationship_status"] == "unresolved"
    detail = client.get(f"/api/v1/skill-installations/{key}", headers=tenant_a)
    assert detail.json() == item
    assert detail.headers["cache-control"] == "no-store"
    assert "signature" not in response.text and "secret" not in response.text and "/fixture/skills" not in response.text
    with session_scope() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == before


def test_skill_inventory_tenant_permissions_and_filters(client, tenant_a, tenant_b, upload_case):
    _, upload, _, edge_id, _, env = upload_case
    assert upload().status_code == 200
    route = f"/api/v1/skill-installations/{installation_id(edge_id)}"
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant_b, "X-Dev-Roles": "viewer"}).status_code == 404
    assert client.get(route, headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403
    assert client.get("/api/v1/skill-installations", headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403
    assert client.get(route).status_code in (401, 404)
    assert (
        client.get("/api/v1/skill-installations", headers=tenant_b, params={"environment_id": env}).json()["items"]
        == []
    )
    assert (
        client.get("/api/v1/skill-installations", headers=tenant_a, params={"device_id": "missing"}).json()["items"]
        == []
    )
    assert (
        len(client.get("/api/v1/skill-installations", headers=tenant_a, params={"device_id": edge_id}).json()["items"])
        == 1
    )


def test_skill_inventory_latest_revoked_and_bounded_pagination(client, tenant_a, upload_case):
    _, upload, _, edge_id, _, env = upload_case
    assert upload().status_code == 200
    key = installation_id(edge_id)
    with session_scope() as session:
        original = session.scalar(
            select(SkillManifestObservation).where(SkillManifestObservation.installation_id == key)
        )
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()
        session.add(
            SkillManifestObservation(
                tenant_id=tenant_a["X-Dev-Tenant-Id"],
                installation_id=key,
                manifest_sha256="c" * 64,
                parser_version=original.parser_version,
                parse_status="unsupported",
                name=None,
                allowed_tools_present=False,
                declared_tools=[],
                observed_at=original.observed_at + timedelta(seconds=1),
                batch_digest="d" * 64,
                batch_signature="private-signature",
            )
        )
        for index in range(3):
            session.add(
                SkillInstallation(
                    tenant_id=tenant_a["X-Dev-Tenant-Id"], edge_agent_id=edge_id, locator_sha256=f"{index:064x}"
                )
            )
    ids, items, cursor = [], [], None
    for _ in range(5):
        params = {"environment_id": env, "limit": 2}
        if cursor:
            params["cursor"] = cursor
        result = client.get("/api/v1/skill-installations", headers=tenant_a, params=params).json()
        assert len(result["items"]) <= 2
        items.extend(result["items"])
        ids.extend(row["installation_id"] for row in result["items"])
        cursor = result["next_cursor"]
        if cursor is None:
            break
    assert len(ids) == len(set(ids)) == 4 and ids == sorted(ids)
    observed = next(row for row in items if row["installation_id"] == key)
    assert observed["device"]["revoked"] is True
    assert observed["latest_observation"]["parse_status"] == "unsupported"
    assert observed["latest_observation"]["name"] is None
    assert all(row["latest_observation"] is None for row in items if row["installation_id"] != key)
    assert "private-signature" not in str(items)


def test_corrupt_foreign_device_binding_not_exposed(client, tenant_a, tenant_b, upload_case):
    _, upload, _, edge_id, _, env = upload_case
    assert upload().status_code == 200
    key = installation_id(edge_id)
    other = client.post("/api/v1/environments", headers=tenant_b, json={"name": "foreign-skill-source"}).json()["id"]
    register_edge(client, tenant_b, other, "foreign-skill-" + key)
    with session_scope() as session:
        foreign = session.scalar(select(EdgeAgent).where(EdgeAgent.environment_id == other))
        session.get(SkillInstallation, key).edge_agent_id = foreign.id
    assert client.get(f"/api/v1/skill-installations/{key}", headers=tenant_a).status_code == 404
    assert client.get(f"/api/v1/skill-installations/{key}/observations", headers=tenant_a).status_code == 404
    assert client.get(f"/api/v1/skill-installations/{key}/observations", headers=tenant_b).status_code == 404
    assert (
        client.get("/api/v1/skill-installations", headers=tenant_a, params={"environment_id": env}).json()["items"]
        == []
    )
    assert (
        client.get("/api/v1/skill-installations", headers=tenant_b, params={"environment_id": other}).json()["items"]
        == []
    )


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"cursor": "../private"}])
def test_skill_inventory_rejects_unbounded_requests(client, tenant_a, params):
    assert client.get("/api/v1/skill-installations", headers=tenant_a, params=params).status_code == 422


def test_skill_history_pagination_ties_and_redaction(client, tenant_a, upload_case):
    _, upload, _, edge_id, _, _ = upload_case
    assert upload().status_code == 200
    key = installation_id(edge_id)
    route = f"/api/v1/skill-installations/{key}/observations"
    with session_scope() as session:
        original = session.scalar(
            select(SkillManifestObservation).where(SkillManifestObservation.installation_id == key)
        )
        for index in range(4):
            session.add(
                SkillManifestObservation(
                    id=f"smo_history_{index}",
                    tenant_id=tenant_a["X-Dev-Tenant-Id"],
                    installation_id=key,
                    manifest_sha256=f"{index:064x}",
                    parser_version=original.parser_version,
                    parse_status="unsupported",
                    name=None,
                    allowed_tools_present=False,
                    declared_tools=[],
                    observed_at=original.observed_at + timedelta(seconds=index // 2 + 1),
                    batch_digest=f"{index:064x}",
                    batch_signature="private-history-signature",
                )
            )
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()
        original_id = original.id
        before = session.scalar(select(func.count(AuditEvent.id)))
    ids, cursor = [], None
    for _ in range(4):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = client.get(route, headers=tenant_a, params=params)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["schema_version"] == "enterprise-skill-history/v1"
        assert body["installation_id"] == key and len(body["items"]) <= 2
        for item in body["items"]:
            assert set(item) == {
                "observation_id",
                "manifest_sha256",
                "parser_version",
                "parse_status",
                "name",
                "allowed_tools_present",
                "declared_tools",
                "observed_at",
                "batch_digest",
            }
        assert "private-history-signature" not in response.text
        ids.extend(item["observation_id"] for item in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert ids == ["smo_history_3", "smo_history_2", "smo_history_1", "smo_history_0", original_id]
    with session_scope() as session:
        assert session.scalar(select(func.count(AuditEvent.id))) == before


def test_skill_history_access_and_cursor_scope(client, tenant_a, tenant_b, upload_case):
    _, upload, _, edge_id, _, _ = upload_case
    assert upload().status_code == 200
    key = installation_id(edge_id)
    route = f"/api/v1/skill-installations/{key}/observations"
    assert client.get(route, headers=tenant_b).status_code == 404
    assert client.get(route, headers={**tenant_b, "X-Dev-Roles": "viewer"}).status_code == 404
    assert client.get(route, headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403
    assert client.get(route).status_code in (401, 404)
    observation_id = client.get(route, headers=tenant_a).json()["items"][0]["observation_id"]
    with session_scope() as session:
        other = SkillInstallation(tenant_id=tenant_a["X-Dev-Tenant-Id"], edge_agent_id=edge_id, locator_sha256="f" * 64)
        session.add(other)
        session.flush()
        other_id = other.id
    other_route = f"/api/v1/skill-installations/{other_id}/observations"
    assert client.get(other_route, headers=tenant_a).json()["items"] == []
    assert client.get(other_route, headers=tenant_a, params={"cursor": observation_id}).status_code == 404
    assert client.get(route, headers=tenant_a, params={"cursor": "smo_missing"}).status_code == 404
    for params in ({"limit": 0}, {"limit": 201}, {"cursor": "../private"}):
        assert client.get(route, headers=tenant_a, params=params).status_code == 422
