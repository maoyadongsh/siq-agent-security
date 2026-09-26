import pytest
from sqlalchemy import select

from app import discovery_scheduler
from app.db import session_scope
from app.models import DiscoveryScheduleRecord, EdgeTask
from app.tests.test_discovery_schedule_confirmation import PATH, confirmation  # noqa: F401
from app.tests.test_discovery_schedule_management import counts, management  # noqa: F401
from app.tests.test_discovery_scheduler import confirmed  # noqa: F401
from app.tests.test_initial_scan import catalog, initial_context  # noqa: F401

TICK = "/edge/v1/discovery-schedules/tick"


def tick_body(body):
    return {"schema_version": "edge-discovery-schedule-tick/v1",
            "schedule_id": body["schedule_id"], "intent_digest": body["intent_digest"]}


def test_device_reads_exact_intent_without_confirmation_or_writes(client, tenant_a, request):
    headers, signed, _ = request.getfixturevalue("confirmation")
    path = "/edge/v1/discovery-schedules/" + signed["schedule_id"]
    before = counts()
    result = client.get(path, headers=headers)
    assert result.status_code == 200 and result.headers["cache-control"] == "no-store"
    body = result.json()
    assert set(body) == {"schema_version", "intent", "intent_digest", "status", "revision"}
    assert body["schema_version"] == "edge-discovery-schedule-intent/v1"
    assert body["intent"]["device_identity"] == headers["X-Edge-Identity"]
    assert body["intent_digest"] == signed["intent_digest"]
    assert body["status"] == "pending_confirmation" and body["revision"] == 0
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, signed["schedule_id"])
        assert body["intent"] == row.intent
    assert client.get(path, headers=tenant_a).status_code == 401
    assert client.get("/edge/v1/discovery-schedules/eds-" + "f" * 32, headers=headers).status_code == 404
    assert counts() == before
    with session_scope() as session:
        session.get(DiscoveryScheduleRecord, signed["schedule_id"]).intent_digest = "f" * 64
    assert client.get(path, headers=headers).status_code == 409
    with session_scope() as session:
        session.get(DiscoveryScheduleRecord, signed["schedule_id"]).tenant_id = "other-fixture-tenant"
    assert client.get(path, headers=headers).status_code == 404
    assert counts() == before


def test_confirm_then_poll_replay_claim_and_revoke(client, tenant_a, request):
    headers, signed, management_path = request.getfixturevalue("confirmation")
    body = tick_body(signed)
    before = counts()
    pending = client.post(TICK, headers=headers, json=body)
    assert pending.status_code == 200 and pending.json()["task_ids"] == []
    assert counts() == before
    assert client.post(PATH, headers=headers, json=signed).status_code == 200
    result = client.post(TICK, headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    ids = result.json()["task_ids"]
    assert ids
    after = counts()
    assert client.post(TICK, headers=headers, json=body).json() == result.json()
    assert counts() == after
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, body["schedule_id"])
        assert row.reserved_runs == 1 and row.revision == 2
        for task in session.scalars(select(EdgeTask).where(EdgeTask.id.in_(ids))):
            assert task.payload["target_device_identity"] == headers["X-Edge-Identity"]
            assert task.signature and task.task_type in {"scan", "skill_scan"}
    claimed = client.get("/edge/v1/tasks", headers=headers)
    assert claimed.status_code == 200
    assert set(ids) <= {task["id"] for task in claimed.json()}
    assert client.post(management_path + "/" + body["schedule_id"] + "/revoke",
                       headers=tenant_a, json={"expected_revision": 2}).status_code == 200
    after = counts()
    stopped = client.post(TICK, headers=headers, json=body)
    assert stopped.json()["status"] == "revoked" and stopped.json()["task_ids"] == []
    assert counts() == after


def test_tick_rejects_identity_digest_scope_and_payload_overrides(client, tenant_a, request):
    headers, signed, _ = request.getfixturevalue("confirmation")
    body = tick_body(signed)
    before = counts()
    assert client.post(TICK, headers=tenant_a, json=body).status_code == 401
    assert client.post(TICK, headers=headers, json={**body, "intent_digest": "f" * 64}).status_code == 409
    assert client.post(TICK, headers=headers,
                       json={**body, "schedule_id": "eds-" + "f" * 32}).status_code == 404
    assert client.post(TICK, headers=headers, json={**body, "now": "2030-01-01T00:00:00Z"}).status_code == 422
    # Valid ID belonging to this device, but no longer in its verified tenant scope.
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, body["schedule_id"])
        row.tenant_id = "other-fixture-tenant"
    assert client.post(TICK, headers=headers, json=body).status_code == 404
    assert counts() == before


def test_tick_audit_failure_rolls_back_entire_round(client, request, monkeypatch):
    headers, signed, _ = request.getfixturevalue("confirmation")
    assert client.post(PATH, headers=headers, json=signed).status_code == 200
    before = counts()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit unavailable")

    monkeypatch.setattr(discovery_scheduler, "audit", fail)
    with pytest.raises(RuntimeError, match="synthetic audit unavailable"):
        client.post(TICK, headers=headers, json=tick_body(signed))
    assert counts() == before
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, signed["schedule_id"])
        assert row.reserved_runs == 0 and row.revision == 1
