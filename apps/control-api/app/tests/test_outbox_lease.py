"""DEV12-B：Outbox 领取租约与 CAS 确认。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete

from app.db import session_scope
from app.models import OutboxEvent, new_id, utcnow
from app.outbox_lease import (
    claim_outbox_batch,
    confirm_outbox_published,
    nack_outbox_publish,
)


@pytest.fixture(autouse=True)
def clean_outbox_events():
    """Keep lease tests independent from events created by earlier modules."""
    with session_scope() as session:
        session.execute(delete(OutboxEvent))
    yield
    with session_scope() as session:
        session.execute(delete(OutboxEvent))


def _seed_event(session, *, event_id: str | None = None) -> str:
    eid = event_id or new_id("out")
    session.add(
        OutboxEvent(
            id=eid,
            tenant_id="tnt-A",
            event_type="test.outbox.v1",
            payload={"event_id": f"evt_{eid}", "event_type": "test.outbox.v1", "payload": {}},
            occurred_at=utcnow(),
        )
    )
    session.commit()
    return eid


def test_two_workers_claim_disjoint(client):
    _ = client
    with session_scope() as session:
        a = _seed_event(session)
        b = _seed_event(session)

    with session_scope() as s1:
        claimed1 = claim_outbox_batch(s1, worker_id="w1", limit=10)
    with session_scope() as s2:
        claimed2 = claim_outbox_batch(s2, worker_id="w2", limit=10)

    ids1 = {c.id for c in claimed1}
    ids2 = {c.id for c in claimed2}
    assert ids1.isdisjoint(ids2)
    assert {a, b} <= (ids1 | ids2)


def test_confirm_requires_matching_lease(client):
    _ = client
    with session_scope() as session:
        eid = _seed_event(session)
    with session_scope() as session:
        claimed = claim_outbox_batch(session, worker_id="w-confirm", limit=10)
    item = next(c for c in claimed if c.id == eid)
    with session_scope() as session:
        assert (
            confirm_outbox_published(
                session, event_id=eid, worker_id="other-worker", lease_revision=item.lease_revision
            )
            is False
        )
    with session_scope() as session:
        assert (
            confirm_outbox_published(
                session, event_id=eid, worker_id="w-confirm", lease_revision=item.lease_revision
            )
            is True
        )
        row = session.get(OutboxEvent, eid)
        assert row.published_at is not None
        assert row.lease_owner is None


def test_expired_lease_can_be_reclaimed(client, monkeypatch):
    _ = client
    monkeypatch.setenv("SIQ_AS_OUTBOX_LEASE_SECONDS", "5")
    with session_scope() as session:
        eid = _seed_event(session)
    with session_scope() as session:
        claim_outbox_batch(session, worker_id="w-stale", limit=10)
    with session_scope() as session:
        row = session.get(OutboxEvent, eid)
        row.leased_at = utcnow() - timedelta(seconds=60)
        session.commit()
    with session_scope() as session:
        claimed = claim_outbox_batch(session, worker_id="w-takeover", limit=10)
    assert any(c.id == eid and c.worker_id == "w-takeover" for c in claimed)


def test_nack_sets_backoff_then_dead_letter(client, monkeypatch):
    _ = client
    monkeypatch.setenv("SIQ_AS_OUTBOX_MAX_ATTEMPTS", "2")
    with session_scope() as session:
        eid = _seed_event(session)
    with session_scope() as session:
        claimed = claim_outbox_batch(session, worker_id="w-nack", limit=10)
    item = next(c for c in claimed if c.id == eid)
    with session_scope() as session:
        nack_outbox_publish(
            session,
            event_id=eid,
            worker_id="w-nack",
            lease_revision=item.lease_revision,
            attempt=1,
        )
        row = session.get(OutboxEvent, eid)
        assert row.published_at is None
        assert row.next_attempt_at is not None
        assert row.lease_owner is None
        # 退避期内不可再领
        row.next_attempt_at = utcnow() + timedelta(hours=1)
        session.commit()
    with session_scope() as session:
        assert claim_outbox_batch(session, worker_id="w-nack2", limit=10) == []
    with session_scope() as session:
        row = session.get(OutboxEvent, eid)
        row.next_attempt_at = utcnow() - timedelta(seconds=1)
        session.commit()
    with session_scope() as session:
        claimed2 = claim_outbox_batch(session, worker_id="w-nack2", limit=10)
    item2 = next(c for c in claimed2 if c.id == eid)
    with session_scope() as session:
        nack_outbox_publish(
            session,
            event_id=eid,
            worker_id="w-nack2",
            lease_revision=item2.lease_revision,
            attempt=2,
        )
        row = session.get(OutboxEvent, eid)
        assert row.dead_lettered_at is not None
