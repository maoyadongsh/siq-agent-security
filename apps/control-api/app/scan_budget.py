"""Bounded process-local scan admission; no content, tenant IDs or credentials retained."""
from __future__ import annotations

import hashlib
import logging
import math
import threading
import time
from collections import Counter, deque
from contextlib import contextmanager

from fastapi import HTTPException

logger = logging.getLogger("siq-agent-security.scan-budget")

class ScanBudget:
    def __init__(self, *, actor_limit=20, tenant_limit=60, concurrency=2,
                 window_seconds=60, max_keys=4096, clock=time.monotonic):
        if min(actor_limit, tenant_limit, concurrency, window_seconds, max_keys) < 1:
            raise ValueError("scan budget must be positive")
        self.actor_limit = actor_limit
        self.tenant_limit = tenant_limit
        self.concurrency = concurrency
        self.window = window_seconds
        self.max_keys = max_keys
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._active = 0
        self._rejected = Counter()

    def _reject(self, reason, retry):
        self._rejected[reason] += 1
        count = self._rejected[reason]
        # Log exponentially spaced aggregate counts, never attacker input.
        if count & (count - 1) == 0:
            logger.warning("threat_scan_rejected category=%s process_count=%d", reason, count)
        raise HTTPException(status_code=429, detail="threat_scan_" + reason,
                            headers={"Retry-After": str(max(1, math.ceil(retry)))})

    def _enter(self, tenant, actor):
        # Length-prefixing prevents separator collisions in caller-controlled IDs.
        tenant_hash = hashlib.sha256(tenant.encode()).hexdigest()
        actor_hash = hashlib.sha256((str(len(tenant)) + ":" + tenant + actor).encode()).hexdigest()
        keys = (("tenant", tenant_hash), ("actor", actor_hash))
        limits = (self.tenant_limit, self.actor_limit)
        with self._lock:
            now = self.clock()
            cutoff = now - self.window
            # Bounded sweep; stale keys disappear even when callers never return.
            for key in list(self._hits):
                queue = self._hits[key]
                while queue and queue[0] <= cutoff:
                    queue.popleft()
                if not queue:
                    del self._hits[key]
            for key, limit in zip(keys, limits, strict=True):
                queue = self._hits.get(key)
                if queue and len(queue) >= limit:
                    self._reject(key[0] + "_rate_limited", queue[0] + self.window - now)
            if self._active >= self.concurrency:
                self._reject("busy", 1)
            if len(self._hits) + sum(key not in self._hits for key in keys) > self.max_keys:
                self._reject("budget_capacity", self.window)
            for key in keys:
                self._hits.setdefault(key, deque()).append(now)
            self._active += 1

    @contextmanager
    def acquire(self, tenant, actor):
        self._enter(tenant, actor)
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1

    def snapshot(self):
        with self._lock:
            return {"scope": "process", "active": self._active,
                    "keys": len(self._hits), "rejected": dict(self._rejected)}


_budget: ScanBudget | None = None
_budget_lock = threading.Lock()


def get_scan_budget():
    global _budget
    with _budget_lock:
        if _budget is None:
            from app.config import load_settings
            settings = load_settings()
            _budget = ScanBudget(actor_limit=settings.threat_scan_actor_limit,
                                tenant_limit=settings.threat_scan_tenant_limit,
                                concurrency=settings.threat_scan_concurrency)
        return _budget
