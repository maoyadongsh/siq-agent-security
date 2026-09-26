import hashlib

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AgentAsset, AgentInstance, AuditEvent, OutboxEvent
from app.tests import test_candidate_bulk_confirm as confirmation

candidates = confirmation.candidates


def send(client, tenant, items, **extra):
    return client.post(
        "/api/v1/candidates/bulk-dismiss",
        headers=tenant,
        json={
            "schema_version": "enterprise-candidate-bulk-dismiss/v1",
            "items": items,
            "reason_code": "out_of_scope",
            **extra,
        },
    )


def test_bulk_dismiss_retains_assets_no_instances_and_private_audit(client, tenant_a, candidates):
    items = list(reversed(candidates))
    response = send(client, tenant_a, items)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["schema_version"] == "enterprise-candidate-bulk-dismiss-result/v1"
    assert [row["id"] for row in result["items"]] == [item["asset_id"] for item in items]
    assert all(row["status"] == "dismissed" for row in result["items"])
    ids = [item["asset_id"] for item in items]
    with session_scope() as session:
        assets = session.scalars(select(AgentAsset).where(AgentAsset.id.in_(ids))).all()
        assert len(assets) == 2
        assert all(row.dismissed_reason == "不属于本次管理范围" and row.dismissed_expires_at is None for row in assets)
        assert session.scalar(select(AgentInstance.id).where(AgentInstance.asset_id.in_(ids))) is None
        events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.payload["payload"]["agent_asset_id"].as_string().in_(ids),
            )
        ).all()
        assert len(events) == 2 and all(row.event_type == "agent.asset.dismissed.v1" for row in events)
        audits = session.scalars(select(AuditEvent).where(AuditEvent.resource_id.in_(ids))).all()
        assert len(audits) == 2 and all(row.action == "agent.dismiss" for row in audits)
        assert all(
            row.summary == {"reason_sha256": hashlib.sha256("不属于本次管理范围".encode()).hexdigest()}
            for row in audits
        )
    assert send(client, tenant_a, items).status_code == 409
    assert confirmation.send(client, tenant_a, items).status_code == 409


@pytest.mark.parametrize(
    "fault", ["foreign", "viewer", "missing", "stale", "duplicate", "empty", "oversize", "reason", "extra"]
)
def test_bulk_dismiss_denial_has_no_partial_changes(client, tenant_a, tenant_b, candidates, fault):
    items = [dict(row) for row in candidates]
    headers, expected, extra = tenant_a, 422, {}
    if fault == "foreign":
        headers, expected = {**tenant_b, "X-Dev-Roles": "viewer"}, 404
    elif fault == "viewer":
        headers, expected = {**tenant_a, "X-Dev-Roles": "viewer"}, 403
    elif fault == "missing":
        items[-1]["asset_id"] = "missing"
        expected = 404
    elif fault == "stale":
        items[-1]["expected_updated_at"] = "2000-01-01T00:00:00Z"
        expected = 409
    elif fault == "duplicate":
        items.append(items[0])
    elif fault == "empty":
        items = []
    elif fault == "oversize":
        items *= 26
    elif fault == "reason":
        extra = {"reason_code": "private free text"}
    else:
        extra = {"reason": "private free text"}
    assert send(client, headers, items, **extra).status_code == expected
    confirmation.assert_untouched(candidates)


@pytest.mark.parametrize("failure", ["audit", "emit_event"])
def test_bulk_dismiss_second_effect_failure_rolls_back(client, tenant_a, candidates, monkeypatch, failure):
    from app.routers import inventory

    original = getattr(inventory, failure)
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("transaction effect unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(inventory, failure, fail_second)
    with pytest.raises(RuntimeError, match="transaction effect unavailable"):
        send(client, tenant_a, candidates)
    assert calls == 2
    confirmation.assert_untouched(candidates)


def test_single_dismiss_audit_no_raw_reason_and_blocks_confirm(client, tenant_a, candidates):
    asset_id = candidates[0]["asset_id"]
    reason = "private synthetic note"
    assert (
        client.post(f"/api/v1/candidates/{asset_id}/dismiss", headers=tenant_a, json={"reason": reason}).status_code
        == 200
    )
    assert client.post(f"/api/v1/candidates/{asset_id}/confirm", headers=tenant_a, json={}).status_code == 409
    with session_scope() as session:
        event = session.scalar(select(AuditEvent).where(AuditEvent.resource_id == asset_id))
        assert reason not in str(event.summary)
        assert event.summary["reason_sha256"] == hashlib.sha256(reason.encode()).hexdigest()
