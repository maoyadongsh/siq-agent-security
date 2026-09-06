"""DEV11-E：注册限速（业务键，非源 IP）。"""

from __future__ import annotations

import pytest

from app.rate_limit import (
    SlidingWindowLimiter,
    registration_rejected_total,
    reset_registration_limiters_for_tests,
)
from app.tests.edge_helpers import edge_public_key_pem


@pytest.fixture(autouse=True)
def _reset_registration_limiters():
    reset_registration_limiters_for_tests()
    yield
    reset_registration_limiters_for_tests()


def test_sliding_window_limiter_unit():
    clock = {"t": 0.0}

    def now():
        return clock["t"]

    lim = SlidingWindowLimiter(limit=2, window_seconds=10.0, clock=now)
    assert lim.allow("k")[0] is True
    assert lim.allow("k")[0] is True
    ok, retry = lim.allow("k")
    assert ok is False and retry >= 1
    assert lim.rejected_total == 1
    clock["t"] = 11.0
    assert lim.allow("k")[0] is True


def test_register_rate_limited_by_device_identity(client, tenant_a, env_a, monkeypatch):
    monkeypatch.setenv("SIQ_AS_REGISTER_RATE_LIMIT", "3")
    monkeypatch.setenv("SIQ_AS_REGISTER_RATE_WINDOW_SECONDS", "60")
    reset_registration_limiters_for_tests()

    identity = "edge-rate-limit-id"
    # 故意用无效码：仍计入限速，证明限速在验码之前
    before = registration_rejected_total()
    statuses = []
    for i in range(5):
        resp = client.post(
            "/edge/v1/register",
            json={
                "enrollment_code": f"enr-forged-rate-{i}",
                "device_identity": identity,
                "public_key_pem": edge_public_key_pem(identity),
                "version": "0.1.0",
            },
        )
        statuses.append(resp.status_code)
    assert statuses[:3] == [401, 401, 401]
    assert statuses[3] == 429
    assert statuses[4] == 429
    limited = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": "enr-forged-rate-x",
            "device_identity": identity,
            "public_key_pem": edge_public_key_pem(identity),
            "version": "0.1.0",
        },
    )
    assert limited.status_code == 429
    assert limited.json()["detail"] == "registration_rate_limited"
    assert limited.headers.get("Retry-After") is not None
    assert int(limited.headers["Retry-After"]) >= 1
    assert registration_rejected_total() > before

    # 不同身份不受牵连（同 NAT 场景：不按 IP）
    other = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": "enr-forged-other",
            "device_identity": "edge-rate-other-ok",
            "public_key_pem": edge_public_key_pem("edge-rate-other-ok"),
            "version": "0.1.0",
        },
    )
    assert other.status_code == 401


def test_enrollment_create_rate_limited(client, tenant_a, env_a, monkeypatch):
    monkeypatch.setenv("SIQ_AS_ENROLLMENT_CREATE_RATE_LIMIT", "2")
    monkeypatch.setenv("SIQ_AS_REGISTER_RATE_WINDOW_SECONDS", "60")
    reset_registration_limiters_for_tests()

    url = f"/api/v1/environments/{env_a['id']}/edge-enrollment"
    assert client.post(url, json={}, headers=tenant_a).status_code == 200
    assert client.post(url, json={}, headers=tenant_a).status_code == 200
    third = client.post(url, json={}, headers=tenant_a)
    assert third.status_code == 429
    assert third.json()["detail"] == "enrollment_create_rate_limited"
    assert third.headers.get("Retry-After") is not None
