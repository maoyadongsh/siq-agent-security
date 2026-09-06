"""JWKS TTL / 单飞 / unknown_kid 有界刷新（DEV08-A）。"""

from __future__ import annotations

import threading
import time

import pytest

from app.jwks import JWKSCache, clamp_jwks_ttl, find_jwk


def test_clamp_jwks_ttl_bounds():
    assert clamp_jwks_ttl(60) == 60.0
    with pytest.raises(ValueError):
        clamp_jwks_ttl(1)
    with pytest.raises(ValueError):
        clamp_jwks_ttl(999)


def test_ttl_expiry_refetches_with_monotonic_clock():
    calls: list[str] = []
    clock = {"t": 1000.0}

    def fetch(url: str) -> dict:
        calls.append(url)
        return {"keys": [{"kid": f"k{len(calls)}", "kty": "RSA"}]}

    cache = JWKSCache(url="https://iam.test/jwks", ttl_seconds=60.0, fetch=fetch, clock=lambda: clock["t"])
    first = cache.get()
    assert first["keys"][0]["kid"] == "k1"
    assert len(calls) == 1

    clock["t"] += 30
    assert cache.get()["keys"][0]["kid"] == "k1"
    assert len(calls) == 1

    clock["t"] += 40  # past TTL
    second = cache.get()
    assert second["keys"][0]["kid"] == "k2"
    assert len(calls) == 2


def test_fetch_failure_after_expiry_is_fail_closed():
    clock = {"t": 0.0}
    state = {"ok": True}

    def fetch(_url: str) -> dict:
        if not state["ok"]:
            raise RuntimeError("jwks_down")
        return {"keys": [{"kid": "old", "kty": "RSA"}]}

    cache = JWKSCache(url="https://iam.test/jwks", ttl_seconds=10.0, fetch=fetch, clock=lambda: clock["t"])
    assert cache.get()["keys"][0]["kid"] == "old"
    clock["t"] += 11
    state["ok"] = False
    with pytest.raises(RuntimeError, match="jwks_down"):
        cache.get()


def test_unknown_kid_triggers_bounded_refresh():
    clock = {"t": 0.0}
    docs = [
        {"keys": [{"kid": "a", "kty": "RSA"}]},
        {"keys": [{"kid": "a", "kty": "RSA"}, {"kid": "b", "kty": "RSA"}]},
        {"keys": [{"kid": "a", "kty": "RSA"}, {"kid": "b", "kty": "RSA"}, {"kid": "c", "kty": "RSA"}]},
    ]
    calls = {"n": 0}

    def fetch(_url: str) -> dict:
        idx = min(calls["n"], len(docs) - 1)
        calls["n"] += 1
        return docs[idx]

    cache = JWKSCache(
        url="https://iam.test/jwks",
        ttl_seconds=60.0,
        fetch=fetch,
        clock=lambda: clock["t"],
        unknown_kid_min_interval=5.0,
    )
    # Initial miss forces fetch via get_for_kid
    jwks = cache.get_for_kid("b")
    assert find_jwk(jwks, "b") is not None
    assert calls["n"] == 2  # cold get + force refresh

    # Immediate unknown kid must NOT refresh again (rate limit)
    before = calls["n"]
    jwks = cache.get_for_kid("missing")
    assert find_jwk(jwks, "missing") is None
    assert calls["n"] == before

    clock["t"] += 5.0
    jwks = cache.get_for_kid("c")
    assert find_jwk(jwks, "c") is not None
    assert calls["n"] == before + 1


def test_concurrent_refresh_is_single_flight():
    barrier = threading.Barrier(4)
    calls = {"n": 0}
    lock = threading.Lock()

    def fetch(_url: str) -> dict:
        with lock:
            calls["n"] += 1
        time.sleep(0.05)
        return {"keys": [{"kid": "only", "kty": "RSA"}]}

    cache = JWKSCache(url="https://iam.test/jwks", ttl_seconds=60.0, fetch=fetch)
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            barrier.wait()
            assert find_jwk(cache.get(), "only") is not None
        except BaseException as exc:  # noqa: BLE001 — collect for assert
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert calls["n"] == 1
