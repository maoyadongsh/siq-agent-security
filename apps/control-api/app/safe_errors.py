"""Stable, non-sensitive error references for persistence and API boundaries."""

from __future__ import annotations

import hashlib


def error_reference(exc: BaseException) -> dict[str, str]:
    """Return an error class and digest without persisting the raw message."""
    return {
        "error_code": type(exc).__name__[:64],
        "error_digest": hashlib.sha256(str(exc).encode("utf-8", errors="replace")).hexdigest(),
    }
