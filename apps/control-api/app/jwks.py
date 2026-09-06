"""JWKS 拉取与生命周期（DEV08）。

- 用 time.monotonic 管理 TTL（默认 60s，可配置边界内）
- unknown_kid 触发有频率限制的单飞刷新
- TTL 过期且拉取失败 → fail-closed，不无限信任陈旧密钥集
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

FetchFn = Callable[[str], dict[str, Any]]
ClockFn = Callable[[], float]

DEFAULT_TTL_SECONDS = 60.0
MIN_TTL_SECONDS = 5.0
MAX_TTL_SECONDS = 300.0
# 随机/未知 kid 强制刷新的最小间隔，防止放大上游请求
UNKNOWN_KID_REFRESH_MIN_INTERVAL = 5.0


def clamp_jwks_ttl(seconds: float) -> float:
    if seconds < MIN_TTL_SECONDS or seconds > MAX_TTL_SECONDS:
        raise ValueError(
            f"SIQ_AS_JWKS_TTL_SECONDS 必须在 [{MIN_TTL_SECONDS}, {MAX_TTL_SECONDS}] 内，收到 {seconds}"
        )
    return float(seconds)


def default_fetch_jwks(url: str) -> dict[str, Any]:
    resp = httpx.get(url, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise ValueError("jwks_invalid_shape")
    if len(data["keys"]) == 0:
        raise ValueError("jwks_empty")
    return data


@dataclass
class JWKSCache:
    """进程内 JWKS 缓存：TTL + 单飞刷新 + unknown_kid 有界刷新。"""

    url: str
    ttl_seconds: float = DEFAULT_TTL_SECONDS
    fetch: FetchFn = field(default=default_fetch_jwks)
    clock: ClockFn = field(default=time.monotonic)
    unknown_kid_min_interval: float = UNKNOWN_KID_REFRESH_MIN_INTERVAL

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _keys: dict[str, Any] | None = field(default=None, init=False, repr=False)
    _fetched_at: float = field(default=0.0, init=False, repr=False)
    _refreshing: bool = field(default=False, init=False, repr=False)
    _last_unknown_refresh_at: float | None = field(default=None, init=False, repr=False)
    _cond: threading.Condition = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.ttl_seconds = clamp_jwks_ttl(self.ttl_seconds)
        object.__setattr__(self, "_cond", threading.Condition(self._lock))

    def get(self, *, force_refresh: bool = False) -> dict[str, Any]:
        with self._cond:
            now = self.clock()
            fresh = (
                self._keys is not None
                and not force_refresh
                and (now - self._fetched_at) < self.ttl_seconds
            )
            if fresh:
                assert self._keys is not None
                return self._keys

            while self._refreshing:
                self._cond.wait(timeout=10.0)
                now = self.clock()
                if (
                    self._keys is not None
                    and not force_refresh
                    and (now - self._fetched_at) < self.ttl_seconds
                ):
                    return self._keys
                if not self._refreshing:
                    break

            # 单飞：本调用者负责拉取
            self._refreshing = True

        try:
            data = self.fetch(self.url)
        except Exception:
            with self._cond:
                self._refreshing = False
                self._cond.notify_all()
            # fail-closed：过期或从未成功时不得回退陈旧集
            raise
        else:
            with self._cond:
                self._keys = data
                self._fetched_at = self.clock()
                self._refreshing = False
                self._cond.notify_all()
                return data

    def get_for_kid(self, kid: str | None) -> dict[str, Any]:
        """返回含目标 kid 的 JWKS；未知 kid 时在频率限制内强制刷新一次。"""
        data = self.get()
        if _find_jwk(data, kid) is not None:
            return data

        with self._lock:
            now = self.clock()
            last = self._last_unknown_refresh_at
            allow = last is None or (now - last) >= self.unknown_kid_min_interval
            if allow:
                self._last_unknown_refresh_at = now

        if allow:
            data = self.get(force_refresh=True)
        return data


def _find_jwk(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    if kid is None:
        return None
    for jwk in jwks.get("keys") or []:
        if isinstance(jwk, dict) and jwk.get("kid") == kid:
            return jwk
    return None


find_jwk = _find_jwk
