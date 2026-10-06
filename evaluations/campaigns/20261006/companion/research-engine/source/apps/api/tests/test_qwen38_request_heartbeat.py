import asyncio
import threading
import time
from datetime import timedelta

import pytest
from services.runtime_startup_guard import StartupLeaseLost
from sqlmodel import Session
from tests.test_qwen38_runtime_lease import owned as _owned

from services import qwen38_request_heartbeat as heartbeat

owned = _owned


@pytest.fixture
def context(owned, monkeypatch):
    monkeypatch.setattr(heartbeat.http.RequestHTTPBinding, "check", lambda self: 321)
    return heartbeat.http.RequestHTTPBinding(None, lambda: Session(owned.engine), owned.authorized, owned.binding)


def test_renew_keeps_original_binding_and_exact_120_second_window(owned, context, monkeypatch):
    now = owned.now + timedelta(seconds=30)
    monkeypatch.setattr(heartbeat.lease.coordination, "utcnow_naive", lambda: now)
    assert heartbeat._renew(context, threading.Event(), time.monotonic() + 10)
    with context.session_factory() as session:
        row = session.get(heartbeat.lease.coordination.ActiveRunLease, owned.row.id)
        assert row.updated_at == now and row.lease_until == now + timedelta(seconds=120)
        assert heartbeat.lease.is_current(session, owned.binding)
        assert row.run_id == owned.row.run_id


@pytest.mark.parametrize("fault", ["expired", "owner", "generation", "tenant", "cancelled", "deadline", "revoked"])
def test_rejected_heartbeat_cannot_extend_lease(owned, context, monkeypatch, fault):
    def check(self):
        if fault == "revoked":
            raise RuntimeError("synthetic private authority details")
        return 321
    monkeypatch.setattr(heartbeat.http.RequestHTTPBinding, "check", check)
    cancelled = threading.Event()
    if fault == "cancelled":
        cancelled.set()
    with context.session_factory() as session:
        row = session.get(heartbeat.lease.coordination.ActiveRunLease, owned.row.id)
        if fault == "owner":
            row.owner_id = "recovery-owner"
        if fault == "generation":
            row.pool_owner_generation += 1
        if fault == "tenant":
            row.pool_tenant_id = "other"
        if fault == "expired":
            row.lease_until = owned.now
        session.add(row)
        session.commit()
        before = (row.updated_at, row.lease_until)
    assert heartbeat._renew(context, cancelled, time.monotonic() + (-1 if fault == "deadline" else 10)) is False
    with context.session_factory() as session:
        row = session.get(heartbeat.lease.coordination.ActiveRunLease, owned.row.id)
        assert (row.updated_at, row.lease_until) == before


def test_takeover_during_precheck_is_rejected_under_row_lock(owned, context, monkeypatch):
    def check(self):
        with context.session_factory() as session:
            row = session.get(heartbeat.lease.coordination.ActiveRunLease, owned.row.id)
            row.pool_owner_generation += 1
            session.add(row)
            session.commit()
        return 321
    monkeypatch.setattr(heartbeat.http.RequestHTTPBinding, "check", check)
    assert not heartbeat._renew(context, threading.Event(), time.monotonic() + 10)


def test_rejected_heartbeat_records_only_fixed_category(context, monkeypatch, caplog):
    def fail(self):
        raise RuntimeError("synthetic-secret-token-and-private-company-data")
    monkeypatch.setattr(heartbeat.http.RequestHTTPBinding, "check", fail)
    assert heartbeat._renew(context, threading.Event(), time.monotonic() + 10) is False
    assert "stage=authority_precheck" in caplog.text
    assert "synthetic-secret" not in caplog.text
    assert "private-company" not in caplog.text


@pytest.mark.asyncio
async def test_cancellation_joins_worker_and_prevents_late_write(owned, context, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = heartbeat._renew
    def worker(*args):
        entered.set()
        assert release.wait(3)
        try:
            return original(*args)
        finally:
            finished.set()
    monkeypatch.setattr(heartbeat, "_renew", worker)
    task = asyncio.create_task(heartbeat.renew(context))
    await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(.01)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    with context.session_factory() as session:
        row = session.get(heartbeat.lease.coordination.ActiveRunLease, owned.row.id)
        assert row.updated_at == owned.now and row.lease_until == owned.row.lease_until


@pytest.mark.asyncio
async def test_loss_joins_model_operation_and_never_accepts_late_success(context, monkeypatch):
    count = 0
    joined = []
    async def renew(_):
        nonlocal count
        count += 1
        return count < 3
    async def operation(checkpoint):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            joined.append(True)
            return "untrusted-late-success"
    monkeypatch.setattr(heartbeat, "renew", renew)
    with pytest.raises(StartupLeaseLost):
        await heartbeat.run(context, operation, interval=.01)
    assert joined == [True]
