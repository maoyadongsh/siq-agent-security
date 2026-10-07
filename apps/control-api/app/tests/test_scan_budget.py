"""Actual denial, isolation, reclamation and no-partial-effect scan regressions."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AgentAsset, AuditEvent, Finding, OutboxEvent
from app.rate_limit import SlidingWindowLimiter
from app.scan_body_limit import ScanBodyLimit
from app.scan_budget import ScanBudget
from app.tests.binding_helpers import make_instance


def test_actor_tenant_and_expiry_are_atomic():
    now = [0]
    budget = ScanBudget(actor_limit=1, tenant_limit=2, clock=lambda: now[0])
    with budget.acquire("A", "alice"):
        pass
    with pytest.raises(HTTPException) as e:
        with budget.acquire("A", "alice"):
            pytest.fail("actor quota bypassed")
    assert e.value.detail == "threat_scan_actor_rate_limited"
    assert e.value.headers["Retry-After"] == "60"
    with budget.acquire("A", "bob"):
        pass
    with pytest.raises(HTTPException) as e:
        with budget.acquire("A", "charlie"):
            pytest.fail("tenant quota bypassed by another actor")
    assert e.value.detail == "threat_scan_tenant_rate_limited"
    with budget.acquire("B", "alice"):
        pass
    now[0] = 60
    with budget.acquire("A", "alice"):
        pass
    assert budget.snapshot()["keys"] == 2


def test_full_budget_does_not_evict_live_keys_or_charge_partial_admission():
    now = [0]
    budget = ScanBudget(max_keys=2, actor_limit=1, clock=lambda: now[0])
    with budget.acquire("A", "alice"):
        pass
    with pytest.raises(HTTPException) as e:
        with budget.acquire("B", "bob"):
            pass
    assert e.value.detail == "threat_scan_budget_capacity"
    with pytest.raises(HTTPException) as e:
        with budget.acquire("A", "alice"):
            pass
    assert e.value.detail == "threat_scan_actor_rate_limited"
    assert budget.snapshot()["keys"] == 2
    now[0] = 61
    with budget.acquire("B", "bob"):
        pass


def test_parallel_slot_and_exception_release_without_consuming_denied_quota():
    entered, release = Event(), Event()
    budget = ScanBudget(concurrency=1, actor_limit=1)

    def hold():
        with budget.acquire("A", "alice"):
            entered.set()
            assert release.wait(5)
            raise ValueError("synthetic failure")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(hold)
        try:
            assert entered.wait(5)
            with pytest.raises(HTTPException) as e:
                with budget.acquire("B", "bob"):
                    pass
            assert e.value.detail == "threat_scan_busy"
        finally:
            release.set()
        with pytest.raises(ValueError):
            future.result(timeout=5)
    with budget.acquire("B", "bob"):
        pass
    assert budget.snapshot()["active"] == 0


def test_registration_key_capacity_recovers_without_eviction():
    now = [0]
    limiter = SlidingWindowLimiter(limit=1, window_seconds=10, max_keys=2, clock=lambda: now[0])
    assert limiter.allow("a")[0] and limiter.allow("b")[0]
    for i in range(20):
        assert not limiter.allow(f"flood-{i}")[0]
    assert not limiter.allow("a")[0]
    assert len(limiter._hits) == 2
    now[0] = 10
    assert limiter.allow("c")[0]
    assert len(limiter._hits) == 1


@pytest.mark.parametrize("chunks,status", [([b"1234", b"5678"], 204), ([b"1234", b"56789"], 413)])
def test_body_is_bounded_before_parser_despite_content_length(chunks, status):
    messages = [{"type": "http.request", "body": chunk, "more_body": i < len(chunks)-1}
                for i, chunk in enumerate(chunks)]
    sent, parsed = [], []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        parsed.append((await receive())["body"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    asyncio.run(ScanBodyLimit(app, max_bytes=8)({
        "type": "http", "method": "POST", "path": "/api/v1/assets/x/threat-scan",
        "headers": [(b"content-length", b"1")],
    }, receive, send))
    assert sent[0]["status"] == status
    assert parsed == ([b"12345678"] if status == 204 else [])


def test_denied_scan_never_analyzes_or_mutates(client, tenant_a, tenant_b, env_a, monkeypatch):
    from app.routers import threat
    budget = ScanBudget(actor_limit=1)
    monkeypatch.setattr(threat, "get_scan_budget", lambda: budget, raising=False)
    asset_id, _ = make_instance(tenant_a["X-Dev-Tenant-Id"], env_a["id"])
    path = f"/api/v1/assets/{asset_id}/threat-scan"
    assert client.post(path, headers=tenant_b, json={"content": "hello"}).status_code == 404
    assert budget.snapshot()["keys"] == 0
    assert client.post(path, headers=tenant_a, json={"content": "echo hello"}).status_code == 200

    def count_state():
        with session_scope() as session:
            return (session.scalar(select(func.count()).select_from(Finding)),
                    session.scalar(select(func.count()).select_from(AuditEvent)),
                    session.scalar(select(func.count()).select_from(OutboxEvent)),
                    session.get(AgentAsset, asset_id).artifact_digest)

    before = count_state()
    analyze, calls = threat.analyze, []

    def observed_analyze(*args, **kwargs):
        calls.append(True)
        return analyze(*args, **kwargs)

    monkeypatch.setattr(threat, "analyze", observed_analyze)
    response = client.post(path, headers=tenant_a, json={"content": "echo hello"})
    assert response.status_code == 429
    assert calls == []
    assert int(response.headers["Retry-After"]) > 0
    assert count_state() == before


@pytest.mark.parametrize("name,value", [
    ("SIQ_AS_THREAT_SCAN_ACTOR_LIMIT", "0"),
    ("SIQ_AS_THREAT_SCAN_TENANT_LIMIT", "1001"),
    ("SIQ_AS_THREAT_SCAN_CONCURRENCY", "17"),
    ("SIQ_AS_THREAT_SCAN_CONCURRENCY", "synthetic-private-value"),
])
def test_invalid_budget_configuration_is_rejected_without_value_echo(monkeypatch, name, value):
    from app.config import load_settings
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError) as e:
        load_settings()
    assert name in str(e.value)
    assert "synthetic-private-value" not in str(e.value)
