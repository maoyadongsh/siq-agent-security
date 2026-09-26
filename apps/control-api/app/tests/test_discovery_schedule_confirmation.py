import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, DiscoveryScheduleRecord
from app.routers.discovery_schedule_confirmation import ConfirmSchedule
from app.tests.edge_helpers import edge_private_key
from app.tests.test_discovery_schedule_management import counts, management  # noqa: F401
from app.tests.test_discovery_scheduler import confirmed  # noqa: F401
from app.tests.test_initial_scan import catalog, initial_context  # noqa: F401

PATH = "/edge/v1/discovery-schedules/confirm"


def signed(body, identity):
    value = {**body, "signature": "0" * 128}
    value["signature"] = edge_private_key(identity).sign(ConfirmSchedule.model_validate(value).signed_bytes()).hex()
    return value


@pytest.fixture
def confirmation(request, client, tenant_a):
    path, create = request.getfixturevalue("management")
    _, headers, _ = request.getfixturevalue("initial_context")
    response = client.post(path, headers=tenant_a, json=create)
    assert response.status_code == 200
    body = {"schema_version": "edge-discovery-schedule-confirm/v1",
            "schedule_id": create["intent"]["schedule_id"], "device_identity": headers["X-Edge-Identity"],
            "environment_id": create["installation_plan"]["environment_id"],
            "control_plane_origin": create["installation_plan"]["control_plane_origin"],
            "intent_digest": response.json()["intent_digest"],
            "installation_plan_sha256": create["intent"]["installation_plan_sha256"],
            "expected_revision": 0, "confirmed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "user_confirmed": True}
    return headers, signed(body, headers["X-Edge-Identity"]), path


def test_signed_confirmation_replay_and_revoke_cannot_reactivate(client, tenant_a, confirmation):
    headers, body, path = confirmation
    before = counts()
    result = client.post(PATH, headers=headers, json=body)
    assert result.status_code == 200 and result.json()["status"] == "active"
    assert result.headers["cache-control"] == "no-store"
    assert counts() == [*before[:3], before[3] + 1]  # No tasks or rounds.
    assert client.post(PATH, headers=headers, json=body).json() == result.json()
    assert counts() == [*before[:3], before[3] + 1]
    revoked = client.post(path + "/" + body["schedule_id"] + "/revoke", headers=tenant_a,
                          json={"expected_revision": 1})
    assert revoked.status_code == 200
    assert client.post(PATH, headers=headers, json=body).status_code == 409
    with session_scope() as session:
        assert session.get(DiscoveryScheduleRecord, body["schedule_id"]).status == "revoked"


@pytest.mark.parametrize("fault", ["signature", "wrong_key", "origin", "digest", "revision", "stale", "future"])
def test_confirmation_binding_denials(client, confirmation, fault):
    headers, original, _ = confirmation
    body = copy.deepcopy(original)
    if fault == "signature":
        body["signature"] = "0" * 128
    elif fault == "wrong_key":
        body = signed(body, "other-synthetic-device")
    else:
        if fault == "origin":
            body["control_plane_origin"] = "https://other.example.test"
        elif fault == "digest":
            body["intent_digest"] = "f" * 64
        elif fault == "revision":
            body["expected_revision"] = 1
        else:
            delta = timedelta(minutes=-6 if fault == "stale" else 6)
            body["confirmed_at"] = (datetime.now(UTC) + delta).isoformat().replace("+00:00", "Z")
        body = signed(body, headers["X-Edge-Identity"])
    before = counts()
    result = client.post(PATH, headers=headers, json=body)
    assert result.status_code == (401 if fault in {"signature", "wrong_key"} else 409)
    assert counts() == before


@pytest.mark.parametrize("value", [False, 1, "true"])
def test_confirmation_boolean_cannot_be_coerced(client, confirmation, value):
    headers, body, _ = confirmation
    before = counts()
    assert client.post(PATH, headers=headers, json={**body, "user_confirmed": value}).status_code == 422
    assert counts() == before


def test_confirmation_requires_device_credential_and_audit_atomicity(client, tenant_a, confirmation, monkeypatch):
    headers, body, _ = confirmation
    before = counts()
    assert client.post(PATH, headers=tenant_a, json=body).status_code == 401
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic confirmation audit failure")
    monkeypatch.setattr("app.routers.discovery_schedule_confirmation.audit", fail)
    with pytest.raises(RuntimeError, match="synthetic confirmation audit failure"):
        client.post(PATH, headers=headers, json=body)
    assert counts() == before
    with session_scope() as session:
        row = session.scalar(select(DiscoveryScheduleRecord).where(DiscoveryScheduleRecord.id == body["schedule_id"]))
        assert row.status == "pending_confirmation" and row.revision == 0


@pytest.mark.parametrize("fault", ["projection", "create_source", "install_source"])
def test_confirmation_rechecks_stored_integrity_and_source(client, confirmation, fault):
    headers, body, _ = confirmation
    with session_scope() as session:
        row = session.get(DiscoveryScheduleRecord, body["schedule_id"])
        if fault == "projection":
            row.max_runs += 1
        else:
            action = "scan.schedule.create" if fault == "create_source" else "install.plan.create"
            resource = row.id if fault == "create_source" else row.environment_id
            event = session.scalar(select(AuditEvent).where(
                AuditEvent.resource_id == resource, AuditEvent.action == action))
            assert event is not None
            event.decision = "deny"
    before = counts()
    result = client.post(PATH, headers=headers, json=body)
    assert result.status_code == 409
    assert result.json()["detail"] == ("discovery_confirmation_integrity_failed" if fault == "projection"
                                      else "discovery_confirmation_source_unverified")
    assert counts() == before
