"""进程内滑动窗口限速（DEV11-E / M-P5d）。

键为业务标识（device_identity / enrollment_code / tenant:env），
刻意不按源 IP，避免同 NAT 合法设备互伤。
多副本需外部协调；本切片不宣称跨进程一致。
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, *, limit: int, window_seconds: float, clock=time.monotonic):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self.rejected_total = 0

    def allow(self, key: str) -> tuple[bool, int]:
        """返回 (allowed, retry_after_seconds)。拒绝时递增 rejected_total。"""
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= self.limit:
                self.rejected_total += 1
                retry = max(1, int(self.window_seconds - (now - q[0])) + 1)
                return False, retry
            q.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self.rejected_total = 0


_register_limiter: SlidingWindowLimiter | None = None
_enrollment_create_limiter: SlidingWindowLimiter | None = None


def reset_registration_limiters_for_tests() -> None:
    global _register_limiter, _enrollment_create_limiter
    _register_limiter = None
    _enrollment_create_limiter = None


def _register_limiter_instance() -> SlidingWindowLimiter:
    global _register_limiter
    if _register_limiter is None:
        from app.config import load_settings

        s = load_settings()
        _register_limiter = SlidingWindowLimiter(
            limit=s.register_rate_limit,
            window_seconds=float(s.register_rate_window_seconds),
        )
    return _register_limiter


def _enrollment_create_limiter_instance() -> SlidingWindowLimiter:
    global _enrollment_create_limiter
    if _enrollment_create_limiter is None:
        from app.config import load_settings

        s = load_settings()
        _enrollment_create_limiter = SlidingWindowLimiter(
            limit=s.enrollment_create_rate_limit,
            window_seconds=float(s.register_rate_window_seconds),
        )
    return _enrollment_create_limiter


def check_register_rate(*, device_identity: str, enrollment_code: str) -> tuple[bool, int]:
    """注册：按身份与注册码分别计数（任一超限即拒绝）。"""
    limiter = _register_limiter_instance()
    ok_id, retry_id = limiter.allow(f"id:{device_identity}")
    if not ok_id:
        return False, retry_id
    # 注册码明文不入键；用截断哈希降低日志泄露面
    import hashlib

    code_key = hashlib.sha256(enrollment_code.encode("utf-8")).hexdigest()[:32]
    ok_code, retry_code = limiter.allow(f"code:{code_key}")
    if not ok_code:
        return False, retry_code
    return True, 0


def check_enrollment_create_rate(*, tenant_id: str, environment_id: str) -> tuple[bool, int]:
    limiter = _enrollment_create_limiter_instance()
    return limiter.allow(f"enroll:{tenant_id}:{environment_id}")


def registration_rejected_total() -> int:
    total = 0
    if _register_limiter is not None:
        total += _register_limiter.rejected_total
    if _enrollment_create_limiter is not None:
        total += _enrollment_create_limiter.rejected_total
    return total
