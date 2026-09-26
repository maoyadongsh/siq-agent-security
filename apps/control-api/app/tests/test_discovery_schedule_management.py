import copy
import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.discovery_scheduler import digest
from app.models import AuditEvent, DiscoveryScheduleRecord, DiscoveryScheduleRun, EdgeAgent, EdgeTask, utcnow
from app.tests.test_discovery_scheduler import confirmed  # noqa: F401
from app.tests.test_initial_scan import catalog, initial_context  # noqa: F401


@pytest.fixture
def management(request):
    context = request.getfixturevalue("confirmed")
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, context["schedule_id"])
        intent = {**row.intent, "schedule_id": "eds-" + uuid.uuid4().hex}
        return (f"/api/v1/environments/{row.environment_id}/discovery-schedules",
                {"intent": intent, "installation_plan": row.installation_plan})


def counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model))
                for model in (DiscoveryScheduleRecord, EdgeTask, DiscoveryScheduleRun, AuditEvent)]


def test_create_is_pending_and_replay_never_dispatches(client, tenant_a, management):
    path, body = management
    before = counts()
    created = client.post(path, headers=tenant_a, json=body)
    assert created.status_code == 200
    assert created.headers["cache-control"] == "no-store"
    assert created.json()["status"] == "pending_confirmation"
    assert counts() == [before[0] + 1, before[1], before[2], before[3] + 1]
    after = counts()
    assert client.post(path, headers=tenant_a, json=body).json() == created.json()
    assert counts() == after
    changed = copy.deepcopy(body)
    changed["intent"]["max_runs"] += 1
    assert client.post(path, headers=tenant_a, json=changed).status_code == 409
    assert counts() == after


def test_create_permissions_scope_and_no_client_status_override(client, tenant_a, tenant_b, management):
    path, body = management
    before = counts()
    assert client.post(path, headers=tenant_b, json=body).status_code == 404
    assert client.post(path, headers={**tenant_a, "X-Dev-Roles": "viewer"}, json=body).status_code == 403
    assert client.post(path, headers=tenant_a, json={**body, "status": "active"}).status_code == 422
    assert counts() == before


@pytest.mark.parametrize("fault", ["forged_plan", "digest", "revoked", "missing_device"])
def test_unverified_or_invalid_binding_never_creates(client, tenant_a, management, fault):
    path, original = management
    body = copy.deepcopy(original)
    expected = "discovery_schedule_invalid_binding"
    if fault == "forged_plan":
        body["installation_plan"]["plan_id"] = "eip-" + "f" * 32
        body["intent"]["installation_plan_sha256"] = digest(body["installation_plan"])
        expected = "discovery_install_plan_unverified"
    elif fault == "digest":
        body["intent"]["installation_plan_sha256"] = "f" * 64
    elif fault == "revoked":
        with session_scope() as session:
            edge = session.scalar(select(EdgeAgent).where(
                EdgeAgent.device_identity == body["intent"]["device_identity"]))
            edge.revoked_at = utcnow()
    else:
        body["intent"]["device_identity"] = "missing-device"
        expected = "not_found"
    before = counts()
    response = client.post(path, headers=tenant_a, json=body)
    assert response.status_code == (404 if fault == "missing_device" else 409)
    assert response.json()["detail"] == expected
    assert counts() == before


def test_revoke_cas_idempotence_and_no_task_changes(client, tenant_a, tenant_b, management):
    path, body = management
    assert client.post(path, headers=tenant_a, json=body).status_code == 200
    path += "/" + body["intent"]["schedule_id"] + "/revoke"
    before = counts()
    assert client.post(path, headers=tenant_b, json={"expected_revision": 0}).status_code == 404
    assert client.post(path, headers={**tenant_a, "X-Dev-Roles": "viewer"},
                       json={"expected_revision": 0}).status_code == 403
    assert client.post(path, headers=tenant_a, json={"expected_revision": 1}).status_code == 409
    assert client.post(path, headers=tenant_a, json={"expected_revision": True}).status_code == 422
    assert counts() == before
    result = client.post(path, headers=tenant_a, json={"expected_revision": 0})
    assert result.status_code == 200 and result.json()["status"] == "revoked"
    assert result.json()["revision"] == 1
    assert counts() == [*before[:3], before[3] + 1]
    assert client.post(path, headers=tenant_a, json={"expected_revision": 0}).json() == result.json()
    assert counts() == [*before[:3], before[3] + 1]


@pytest.mark.parametrize("operation", ["create", "revoke"])
def test_management_audit_failure_rolls_back(client, tenant_a, management, monkeypatch, operation):
    path, body = management
    if operation == "revoke":
        assert client.post(path, headers=tenant_a, json=body).status_code == 200
        path += "/" + body["intent"]["schedule_id"] + "/revoke"
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr("app.routers.discovery_schedules.audit", fail)
    before = counts()
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        client.post(path, headers=tenant_a, json=body if operation == "create" else {"expected_revision": 0})
    assert counts() == before
    if operation == "revoke":
        with session_scope() as session:
            row = session.get(DiscoveryScheduleRecord, body["intent"]["schedule_id"])
            assert row.status == "pending_confirmation" and row.revision == 0


# --- GET read-only management list (CL-02-SCHEDULE-MANAGEMENT); POST tests above are unchanged ---
from app.models import OutboxEvent  # noqa: E402


def list_counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model))
                for model in (DiscoveryScheduleRecord, EdgeTask, DiscoveryScheduleRun, AuditEvent, OutboxEvent)]


def _create(client, tenant_a, management, count):
    path, body = management
    ids = []
    for _ in range(count):
        created = copy.deepcopy(body)
        created["intent"]["schedule_id"] = "eds-" + uuid.uuid4().hex
        assert client.post(path, headers=tenant_a, json=created).status_code == 200
        ids.append(created["intent"]["schedule_id"])
    return path, ids


def test_list_pagination_cursor_and_empty_page(client, tenant_a, management):
    path, ids = _create(client, tenant_a, management, 3)
    environment_id = path.split("/")[4]
    full = client.get(path, headers=tenant_a, params={"limit": 100})
    assert full.status_code == 200 and full.headers["cache-control"] == "no-store"
    body = full.json()
    assert body["schema_version"] == "enterprise-discovery-schedule-management/v1"
    assert body["environment_id"] == environment_id
    assert body["evaluated_at"].endswith("Z")
    all_ids = [item["schedule_id"] for item in body["items"]]
    assert all_ids == sorted(all_ids) and set(ids) <= set(all_ids)
    collected = []
    cursor = None
    for _ in range(50):
        page = client.get(path, headers=tenant_a, params={"limit": 2, **({"cursor": cursor} if cursor else {})})
        assert page.status_code == 200
        page_body = page.json()
        page_ids = [item["schedule_id"] for item in page_body["items"]]
        assert page_ids == sorted(page_ids) and len(page_ids) <= 2
        collected.extend(page_ids)
        assert page_body["next_cursor"] == (page_ids[-1] if page_body["next_cursor"] is not None else None)
        if page_body["next_cursor"] is None:
            break
        assert page_body["next_cursor"] == page_ids[-1]
        cursor = page_body["next_cursor"]
    else:
        pytest.fail("pagination did not terminate")
    assert collected == all_ids
    empty_env = client.post("/api/v1/environments", headers=tenant_a,
                            json={"name": "schedule-empty-" + uuid.uuid4().hex[:8], "env_type": "host"}).json()
    empty = client.get(f"/api/v1/environments/{empty_env['id']}/discovery-schedules", headers=tenant_a)
    assert empty.status_code == 200 and empty.json()["items"] == [] and empty.json()["next_cursor"] is None


def test_list_cross_tenant_and_missing_environment_404(client, tenant_a, tenant_b, management):
    path, _ = _create(client, tenant_a, management, 1)
    assert client.get(path, headers=tenant_b).status_code == 404
    assert client.get("/api/v1/environments/env-missing/discovery-schedules", headers=tenant_a).status_code == 404


def test_list_requires_env_read_permission(client, tenant_a, management):
    path, _ = _create(client, tenant_a, management, 1)
    assert client.get(path, headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403


@pytest.mark.parametrize("params", [
    {"cursor": "not-a-cursor"}, {"cursor": "eds-" + "A" * 32}, {"cursor": "eds-" + "g" * 32},
    {"cursor": "eds-" + "a" * 31}, {"limit": 0}, {"limit": 101},
])
def test_list_cursor_and_limit_validation_422(client, tenant_a, management, params):
    path, _ = _create(client, tenant_a, management, 1)
    assert client.get(path, headers=tenant_a, params=params).status_code == 422


def test_list_can_revoke_permission_combinations(client, tenant_a, management):
    path, _ = _create(client, tenant_a, management, 1)
    assert client.get(path, headers=tenant_a).json()["can_revoke"] is True
    assert client.get(path, headers={**tenant_a, "X-Dev-Roles": "security_admin"}).json()["can_revoke"] is False
    assert client.get(path, headers={**tenant_a, "X-Dev-Roles": "tenant_admin"}).json()["can_revoke"] is False
    assert client.get(path, headers={**tenant_a, "X-Dev-Roles": "platform_operator"}).json()["can_revoke"] is True


def test_list_projection_whitelist_no_sensitive_fields(client, tenant_a, management):
    path, ids = _create(client, tenant_a, management, 1)
    body = client.get(path, headers=tenant_a).json()
    assert set(body) == {"schema_version", "environment_id", "evaluated_at", "can_revoke", "items", "next_cursor"}
    item = next(row for row in body["items"] if row["schedule_id"] == ids[0])
    assert set(item) == {"schedule_id", "edge_agent_id", "status", "revision", "starts_at", "expires_at",
                         "interval_seconds", "max_runs", "reserved_runs", "last_reserved_slot", "created_at"}
    assert item["status"] == "pending_confirmation" and item["revision"] == 0
    assert item["reserved_runs"] == 0 and item["last_reserved_slot"] is None
    assert item["interval_seconds"] == 900 and item["max_runs"] == 4
    for key in ("starts_at", "expires_at", "created_at"):
        assert item[key].endswith("Z") and "T" in item[key]
    raw = repr(body)
    for leaked in ("installation_plan", "intent_digest", "device_identity", "purpose", "signature", "tnt-"):
        assert leaked not in raw


def test_list_changes_no_state(client, tenant_a, management):
    path, ids = _create(client, tenant_a, management, 2)
    before = list_counts()
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, ids[0])
        baseline = (row.status, row.revision, row.reserved_runs)
    page = client.get(path, headers=tenant_a, params={"limit": 1})
    assert page.status_code == 200
    if page.json()["next_cursor"] is not None:
        assert client.get(path, headers=tenant_a,
                          params={"limit": 1, "cursor": page.json()["next_cursor"]}).status_code == 200
    assert list_counts() == before
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, ids[0])
        assert (row.status, row.revision, row.reserved_runs) == baseline


def test_list_reflects_revoke_via_existing_post(client, tenant_a, management):
    path, ids = _create(client, tenant_a, management, 1)
    assert client.post(f"{path}/{ids[0]}/revoke", headers=tenant_a, json={"expected_revision": 0}).status_code == 200
    items = client.get(path, headers=tenant_a).json()["items"]
    row = next(item for item in items if item["schedule_id"] == ids[0])
    assert row["status"] == "revoked" and row["revision"] == 1
