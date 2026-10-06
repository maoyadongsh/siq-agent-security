"""Renew only the original request owner; join synchronous writes on cancellation."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from sqlmodel import select

from services import qwen38_request_http as http, qwen38_runtime_lease as lease
from services.runtime_startup_guard import run_guarded_startup

logger = logging.getLogger(__name__)


def _renew(context, cancelled, deadline, expected_run_id=None):
    stage = "authority_precheck"
    started = time.monotonic()

    def rejected(reason):
        # Fixed categories only; never log exception text or binding contents.
        logger.warning("qwen_request_lease_renewal_rejected stage=%s elapsed_ms=%d",
                       reason, int((time.monotonic() - started) * 1000))
        return False

    try:
        context.check()
        stage = "binding_type"
        binding = context.execution_binding
        if not isinstance(binding, lease.ExecutionLeaseBinding):
            return rejected(stage)
        stage = "database_binding"
        with context.session_factory() as session:
            row = session.exec(select(lease.coordination.ActiveRunLease).where(
                lease.coordination.ActiveRunLease.id == binding.row_id).with_for_update()).first()
            if (row is None or not lease.is_current(session, binding)
                    or (expected_run_id is not None and row.run_id != expected_run_id)
                    or cancelled.is_set() or time.monotonic() >= deadline):
                return rejected(stage)
            stage = "database_renewal"
            if not lease.coordination.renew_active_run_sync(session, profile=binding.profile,
                    session_id=binding.session_id, run_id=row.run_id, owner_id=binding.owner_id):
                return rejected(stage)
        stage = "authority_postcheck"
        context.check()
        if cancelled.is_set() or time.monotonic() >= deadline:
            return rejected("cancelled_or_deadline")
        return True
    except Exception:
        # Neither driver errors nor identity responses enter the task result.
        return rejected(stage)


async def _joined(operation):
    """Join a bounded synchronous operation before allowing cleanup to race it."""
    cancelled = threading.Event()
    worker = asyncio.create_task(asyncio.to_thread(operation, cancelled, time.monotonic() + 10))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancelled.set()
        # A timeout must not leave a database write running after containment.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled.set()
        worker.result()
        raise


async def renew(context, *, expected_run_id=None):
    if not isinstance(context, http.RequestHTTPBinding):
        return False
    def operation(cancelled, deadline):
        if expected_run_id is None:
            return _renew(context, cancelled, deadline)
        return _renew(context, cancelled, deadline, expected_run_id)
    return await _joined(operation)


async def run(context, operation, *, interval=30, on_renewed=None):
    """Guard a complete operation; the caller retains and cleans its run handle."""
    if not isinstance(context, http.RequestHTTPBinding):
        raise ValueError("qwen_request_heartbeat_binding_invalid")

    async def heartbeat():
        valid = await renew(context)
        if valid and on_renewed is not None:
            on_renewed()
        return valid

    return await run_guarded_startup(operation, heartbeat, interval=interval, check_timeout=10)
