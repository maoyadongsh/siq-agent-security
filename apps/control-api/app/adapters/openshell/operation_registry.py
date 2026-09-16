"""Bounded process-local binding for OpenShell apply/rollback operations."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass

from app.adapters.openshell.contracts import PolicySnapshot


@dataclass(frozen=True)
class PolicyOperation:
    operation_id: str
    target: str
    base: PolicySnapshot
    applied_revision: str
    applied_digest: str
    no_op: bool


class PolicyOperationRegistry:
    """Private, bounded registry shared by backend instances in one process."""

    def __init__(self, limit: int = 256):
        if limit < 1:
            raise ValueError("operation registry limit must be positive")
        self._limit = limit
        self._lock = threading.Lock()
        self._records: OrderedDict[str, PolicyOperation] = OrderedDict()
        self._target_locks = tuple(threading.RLock() for _ in range(64))

    def target_lock(self, target: str) -> threading.RLock:
        digest = hashlib.sha256(target.encode("utf-8")).digest()
        return self._target_locks[digest[0] % len(self._target_locks)]

    def remember(self, operation: PolicyOperation) -> None:
        with self._lock:
            while len(self._records) >= self._limit:
                self._records.popitem(last=False)
            self._records[operation.operation_id] = operation

    def get(self, operation_id: str) -> PolicyOperation | None:
        with self._lock:
            return self._records.get(operation_id)

    def consume(self, operation_id: str) -> None:
        with self._lock:
            self._records.pop(operation_id, None)


PROCESS_POLICY_OPERATIONS = PolicyOperationRegistry()
