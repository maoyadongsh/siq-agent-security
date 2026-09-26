from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AgentAsset, AgentInstance, AuditEvent, OutboxEvent, PermissionFact


@pytest.fixture
def candidates(tenant_a):
    with session_scope() as session:
        assets = [
            AgentAsset(
                tenant_id=tenant_a["X-Dev-Tenant-Id"],
                name=f"bulk-{index}",
                framework="hermes",
                status="candidate",
                role="existing-role",
            )
            for index in range(2)
        ]
        session.add_all(assets)
        session.flush()
        return [{"asset_id": row.id, "expected_updated_at": row.updated_at.isoformat()} for row in assets]


def send(client, tenant, items):
    return client.post(
        "/api/v1/candidates/bulk-confirm",
        headers=tenant,
        json={
            "schema_version": "enterprise-candidate-bulk-confirm/v1",
            "items": items,
        },
    )


def assert_untouched(items):
    ids = [item["asset_id"] for item in items]
    with session_scope() as session:
        assert all(
            row.status == "candidate" for row in session.scalars(select(AgentAsset).where(AgentAsset.id.in_(ids)))
        )
        assert session.scalar(select(AgentInstance.id).where(AgentInstance.asset_id.in_(ids))) is None
        assert session.scalar(select(AuditEvent.id).where(AuditEvent.resource_id.in_(ids))) is None
        assert (
            session.scalar(
                select(OutboxEvent.id).where(
                    OutboxEvent.payload["payload"]["agent_asset_id"].as_string().in_(ids),
                )
            )
            is None
        )


def test_bulk_confirmation_preserves_order_audit_and_not_permissions(client, tenant_a, candidates):
    items = list(reversed(candidates))
    result = send(client, tenant_a, items)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    body = result.json()
    assert body["schema_version"] == "enterprise-candidate-bulk-confirm-result/v1"
    assert [row["id"] for row in body["items"]] == [item["asset_id"] for item in items]
    assert all(row["status"] == "confirmed" and row["role"] == "existing-role" for row in body["items"])
    ids = [item["asset_id"] for item in items]
    with session_scope() as session:
        instances = session.scalars(select(AgentInstance).where(AgentInstance.asset_id.in_(ids))).all()
        assert len(instances) == 2 and all(row.status == "observed" for row in instances)
        assert (
            len(
                session.scalars(
                    select(AuditEvent).where(
                        AuditEvent.resource_id.in_(ids),
                        AuditEvent.action == "agent.confirm",
                    )
                ).all()
            )
            == 2
        )
        assert (
            len(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.payload["payload"]["agent_asset_id"].as_string().in_(ids),
                    )
                ).all()
            )
            == 2
        )
        assert session.scalar(select(PermissionFact.id).where(PermissionFact.subject_id.in_(ids))) is None
    assert send(client, tenant_a, items).status_code == 409
    assert client.post(f"/api/v1/candidates/{ids[0]}/confirm", headers=tenant_a, json={}).status_code == 409


@pytest.mark.parametrize("fault", ["foreign", "missing", "viewer", "stale", "duplicate", "empty", "too_many"])
def test_bulk_confirmation_denial_is_atomic(client, tenant_a, tenant_b, candidates, fault):
    items = [dict(item) for item in candidates]
    headers = tenant_a
    expected = 422
    if fault == "foreign":
        headers, expected = {**tenant_b, "X-Dev-Roles": "viewer"}, 404
    elif fault == "missing":
        items.append({**items[0], "asset_id": "missing"})
        expected = 404
    elif fault == "viewer":
        headers, expected = {**tenant_a, "X-Dev-Roles": "viewer"}, 403
    elif fault == "stale":
        items[-1]["expected_updated_at"] = "2000-01-01T00:00:00Z"
        expected = 409
    elif fault == "duplicate":
        items.append(items[0])
    elif fault == "empty":
        items = []
    else:
        items *= 26
    assert send(client, headers, items).status_code == expected
    assert_untouched(candidates)


def test_second_audit_failure_rolls_back_entire_bulk(client, tenant_a, candidates, monkeypatch):
    from app.routers import inventory

    original = inventory.audit
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("audit unavailable")
        return original(*args, **kwargs)

    monkeypatch.setattr(inventory, "audit", fail_second)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        send(client, tenant_a, candidates)
    assert calls == 2
    assert_untouched(candidates)


def test_stale_loaded_candidate_cannot_bypass_conditional_update(client, tenant_a, candidates, monkeypatch):
    from app.routers import inventory

    original = inventory._confirm_candidate_in_transaction

    def changed_after_read(session, identity, asset, body):
        # Simulate a stale in-memory object after the database row changed.
        old = asset.updated_at
        session.execute(
            inventory.update(AgentAsset)
            .where(AgentAsset.id == asset.id)
            .values(
                updated_at=old + timedelta(seconds=1),
            )
            .execution_options(synchronize_session=False)
        )
        return original(session, identity, asset, body)

    monkeypatch.setattr(inventory, "_confirm_candidate_in_transaction", changed_after_read)
    assert send(client, tenant_a, candidates).status_code == 409
    assert_untouched(candidates)
