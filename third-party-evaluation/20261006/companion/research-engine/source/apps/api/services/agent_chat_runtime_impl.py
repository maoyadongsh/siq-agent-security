import asyncio
import hashlib
import importlib
import json
import logging
import os
import re
import sys
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from database import DATABASE_URL, async_engine
from fastapi import Request
from models import ChatMessage, ChatSessionMemory
from siq_financial_tools import calculator as financial_calculator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from scripts.openshell import governed_model_route
from services import (
    agent_memory_analytics,
    agent_memory_service,
    agent_runtime_answer_audit,
    agent_runtime_attachments,
    agent_runtime_catalog,
    agent_runtime_citations,
    agent_runtime_context,
    agent_runtime_dedupe,
    agent_runtime_diagnostics,
    agent_runtime_display,
    agent_runtime_fallback_contexts,
    agent_runtime_financial_claim_verifier,
    agent_runtime_financial_evidence,
    agent_runtime_financial_format,
    agent_runtime_financial_guard,
    agent_runtime_financial_provenance,
    agent_runtime_financial_sources,
    agent_runtime_financial_trace,
    agent_runtime_history,
    agent_runtime_host_scope,
    agent_runtime_market_facts,
    agent_runtime_memory,
    agent_runtime_message_identity,
    agent_runtime_parse_only,
    agent_runtime_postgres_fallback,
    agent_runtime_preflight,
    agent_runtime_progress,
    agent_runtime_sec_dimensions,
    agent_runtime_statement_context,
    agent_runtime_task_ids,
    agent_runtime_wiki_context,
    confidential_auxiliary_models,
    openshell_data_scope,
    openshell_pool_adapter,
    openshell_scope_lifecycle,
    primary_market_agent_runtime,
    qwen38_request_api,
    qwen38_request_selector,
    siq_security_export,
)
from services.agent_runtime_fallback_contexts import (
    _markdown_table_cell,
    _postgres_row_md_line,
    _postgres_row_metric_name,
    _postgres_row_payload,
    _postgres_row_pdf_page,
    _postgres_row_table_index,
    _postgres_row_unit,
    _postgres_row_value,
)
from services.agent_runtime_guardrail_text import strip_guardrail_diagnostics
from services.agent_runtime_loop_guard import (
    CONSECUTIVE_TOOL_ERROR_LIMIT,
    IDLE_TIMEOUT_MESSAGE,
    LEGACY_HISTORY_LOOP_SANITIZED_PREFIX as LEGACY_HISTORY_LOOP_SANITIZED_PREFIX,
    ORPHANED_RUN_MESSAGE,
    OUTPUT_LOOP_STOP_MESSAGE,
    REPEATED_TOOL_CALL_LIMIT,
    REPEATED_TOOL_CALL_STOP_MESSAGE,
    RUN_CANCELLED_MESSAGE,
    RUN_FAILED_MESSAGE,
    STOPPED_MESSAGE,
    TIMEOUT_MESSAGE,
    TOOL_FAILURE_STOP_MESSAGE,
    ExternalToolLoopStreamFilter,
    _assistant_reply_for_display,
    _detect_output_loop,
    _detect_stream_output_loop,
    _failed_run_reply_for_history,
    _is_loop_polluted_assistant_message,
    _sanitize_assistant_history_reply,
)
from services.agent_runtime_streaming import (
    ACTIVE_RUNS,
    ActiveRunState,
    _active_key,
    _append_completed_active_run,
    _append_progress_event,
    _append_reasoning_active_run,
    _append_state_event,
    _append_user_stopped_active_run,
    _clear_active_run,
    _extract_progress_from_text,
    _progress_payload,
    _progress_signature as _streaming_progress_signature,
    _runtime_profile,
    get_active_run_snapshot as _streaming_get_active_run_snapshot,
    has_active_run,
    project_tool_completed,
    project_tool_started,
    stop_active_run as _streaming_stop_active_run,
    stream_active_run_events as _streaming_stream_active_run_events,
    stream_idle_timeout as _streaming_stream_idle_timeout,
)
from services.agent_runtime_tool_output import normalize_tool_output as _normalize_tool_output
from services.hermes_client import (
    HermesProfile,
    HermesRunRoute,
    HermesRunStatus,
    HermesRuntimeSelectionError,
    RunTerminalAccumulator,
    RunTerminalError,
    RunTerminalResult,
    collect_run_result,
    create_run,
    discard_run_terminal_result,
    get_run_status,
    normalize_runtime_target,
    pop_run_terminal_result,
    resolve_requested_run_route,
    route_session_id,
    stop_run,
    stream_run,
)
from services.path_config import (
    ASSISTANT_WIKI_ROOT as CONFIG_ASSISTANT_WIKI_ROOT,
    BACKEND_DATA_ROOT,
    FINANCIAL_CALCULATOR_SCRIPT,
    FINANCIAL_RECONCILIATION_VALIDATOR_SCRIPT,
    HERMES_HOST_SHARED_SCRIPTS_ROOT,
    HERMES_PROFILE_ROOTS,
    HERMES_PROFILES_ROOT,
    HERMES_SHARED_SCRIPTS_ROOT,
    PDF_OUTPUT_ROOT_CANDIDATES,
    PDF_RESULT_ROOT_CANDIDATES,
    PROJECT_ROOT,
    WIKI_ROOT as CONFIG_WIKI_ROOT,
    WIKI_ROOT_CANDIDATES,
)
from services.runtime_coordination import (
    attach_active_run_pool_lease,
    bind_active_run,
    claim_active_run,
    lease_seconds,
    release_active_run,
    renew_active_run,
    runtime_owner_id,
)
from services.runtime_startup_guard import run_guarded_startup

AnswerAuditCallback = Callable[[dict[str, Any]], None]
logger = logging.getLogger(__name__)

_RUNTIME_OWNER_ID = runtime_owner_id()
_ACTIVE_RUN_CONFLICT_MESSAGE = "当前会话已有请求正在处理，请等待当前结果完成后再试。"
_ACTIVE_RUN_AUTHORITY_LOST_MESSAGE = "[失败] 任务执行权限或运行状态已变化，无法确认完整结果。请先核对已产生的文件或操作记录。"
_ORPHAN_RECONCILIATION_TASKS: set[asyncio.Task[None]] = set()


@dataclass(frozen=True)
class DurableProvisionalClaim:
    profile: HermesProfile
    session_id: str
    provisional_run_id: str
    owner_id: str


async def _claim_durable_active_run(profile: HermesProfile, session_id: str, run_id: str, owner_id: str) -> bool:
    """Claim the durable lease without holding it during Hermes/Milvus I/O."""
    try:
        async with AsyncSession(async_engine) as coordination_session:
            return await claim_active_run(
                coordination_session,
                profile=profile,
                session_id=session_id,
                run_id=run_id,
                owner_id=owner_id,
            )
    except Exception:
        # Local preflight callers retain their historical fallback. Actual run
        # creation still requires a DB-backed startup renewal before dispatch.
        if DATABASE_URL.startswith("postgresql") or os.getenv("SIQ_REQUIRE_DURABLE_RUNTIME_COORDINATION", "0") == "1":
            raise
        logger.warning("local durable claim unavailable; startup verification required")
        return True


async def _acquire_durable_provisional_claim(
    profile: HermesProfile,
    session_id: str,
) -> DurableProvisionalClaim | None:
    owner_id = _RUNTIME_OWNER_ID
    provisional_run_id = f"claim-{uuid.uuid4().hex}"
    if not await _claim_durable_active_run(profile, session_id, provisional_run_id, owner_id):
        return None
    return DurableProvisionalClaim(
        profile=profile,
        session_id=session_id,
        provisional_run_id=provisional_run_id,
        owner_id=owner_id,
    )


async def _retain_terminal_business_result(state: ActiveRunState, *, status: str) -> bool:
    from dataclasses import replace

    from services.business_run_result_store import persist

    try:
        return await asyncio.wait_for(persist(replace(state, status=status)), timeout=10)
    except Exception:
        # Persistence failure must not prevent containment. Do not log output,
        # scope, or DB errors, or claim a durable result on failure.
        logger.warning("business_result_retention_failed")
        return False


async def _release_durable_active_run(state: ActiveRunState, *, status: str) -> None:
    if state.lease_heartbeat_task and not state.lease_heartbeat_task.done():
        state.lease_heartbeat_task.cancel()
        await asyncio.gather(state.lease_heartbeat_task, return_exceptions=True)
    if qwen38_request_api.handles(state.run_route):
        # Preserve an already quiescent, final reply before deleting its runtime
        # or marking the execution complete. The store rejects unknown writers;
        # only the finalizer may establish containment in that case.
        retained = await _retain_terminal_business_result(state, status=status)
        released = await qwen38_request_api.finish(state.run_route, profile=state.profile,
            session_id=state.session_id, owner_id=state.owner_id, run_ids=(state.run_id,), status=status)
        if released:
            state.runtime_terminal_confirmed = state.runtime_children_terminal_confirmed = True
            if not retained:
                await _retain_terminal_business_result(state, status=status)
        return
    terminal_confirmed = (
        state.runtime_terminal_confirmed
        and state.runtime_children_terminal_confirmed
    )
    if qwen38_request_api.handles(state.run_route) or (state.run_route is not None and state.run_route.pool_lease_id):
        pool_released = await _release_pool_route(
            state.run_route,
            session_id=state.session_id,
            terminal_confirmed=terminal_confirmed,
        )
        # Keep the DB row recoverable whenever the writer has not been proven
        # quiescent or its exact pool release did not commit.
        if not terminal_confirmed or not pool_released:
            if (not qwen38_request_api.handles(state.run_route)
                    and state.owner_id and state.runtime_children_terminal_confirmed):
                _schedule_orphan_reconciliation(state, status=status)
            return
    if state.owner_id:
        try:
            await _release_durable_lease(
                state.profile,
                state.session_id,
                state.run_id,
                state.owner_id,
                status=status,
            )
        except Exception:
            if DATABASE_URL.startswith("postgresql") or os.getenv("SIQ_REQUIRE_DURABLE_RUNTIME_COORDINATION", "0") == "1":
                logger.exception("failed to release durable active-run lease")
            else:
                logger.debug("local durable active-run release unavailable", exc_info=True)
            return
    await _retain_terminal_business_result(state, status=status)


def _schedule_orphan_reconciliation(state: ActiveRunState, *, status: str) -> None:
    task = asyncio.create_task(_reconcile_orphaned_main_run(state, status=status))
    _ORPHAN_RECONCILIATION_TASKS.add(task)
    task.add_done_callback(_ORPHAN_RECONCILIATION_TASKS.discard)


async def _reconcile_orphaned_main_run(state: ActiveRunState, *, status: str) -> None:
    if qwen38_request_api.handles(state.run_route):
        # Request cleanup must not renew execution or enter legacy pool recovery.
        await qwen38_request_api.release(state.run_route, session_id=state.session_id)
        return
    interval = float(_env_int("SIQ_OPENSHELL_ORPHAN_RECONCILE_SECONDS", 2, minimum=1, maximum=60))
    pool_terminal_released = False
    while True:
        if not await _renew_durable_active_run(state):
            return
        if pool_terminal_released:
            try:
                if await _release_durable_lease(
                    state.profile,
                    state.session_id,
                    state.run_id,
                    state.owner_id or "",
                    status=status,
                ):
                    return
            except Exception:
                logger.exception("failed to finalize reconciled OpenShell lease")
            await asyncio.sleep(interval)
            continue
        try:
            runtime_status = await _get_routed_run_status(
                state.run_id,
                profile=state.profile,
                route=state.run_route,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(interval)
            continue
        if runtime_status.write_quiesced:
            pool_terminal_released = await _release_pool_route(
                state.run_route,
                session_id=state.session_id,
                terminal_confirmed=True,
            )
        await asyncio.sleep(interval)


async def _release_durable_lease(profile: HermesProfile, session_id: str, run_id: str, owner_id: str, *, status: str) -> bool:
    async with AsyncSession(async_engine) as coordination_session:
        return await release_active_run(
            coordination_session,
            profile=profile,
            session_id=session_id,
            run_id=run_id,
            owner_id=owner_id,
            status=status,
        )


async def _bind_durable_active_run(
    profile: HermesProfile,
    session_id: str,
    provisional_run_id: str,
    run_id: str,
    owner_id: str,
) -> bool:
    try:
        async with AsyncSession(async_engine) as coordination_session:
            return await bind_active_run(
                coordination_session,
                profile=profile,
                session_id=session_id,
                provisional_run_id=provisional_run_id,
                run_id=run_id,
                owner_id=owner_id,
            )
    except Exception:
        if DATABASE_URL.startswith("postgresql") or os.getenv("SIQ_REQUIRE_DURABLE_RUNTIME_COORDINATION", "0") == "1":
            raise
        else:
            logger.debug("local durable active-run bind unavailable", exc_info=True)
            return True


async def _attach_durable_pool_lease(
    claim: DurableProvisionalClaim,
    route: HermesRunRoute | None,
) -> bool:
    if qwen38_request_api.handles(route):
        return await qwen38_request_api.current(route, profile=claim.profile,
            session_id=claim.session_id, owner_id=claim.owner_id, run_id=claim.provisional_run_id)
    if route is None or route.pool_binding is None or not route.pool_lease_id:
        return True
    if (
        not route.pool_owner_generation
        or not route.pool_binding.scope_id
        or not route.canary_run_id
    ):
        return False
    try:
        async with AsyncSession(async_engine) as coordination_session:
            return await attach_active_run_pool_lease(
                coordination_session,
                profile=claim.profile,
                session_id=claim.session_id,
                provisional_run_id=claim.provisional_run_id,
                owner_id=claim.owner_id,
                pool_lease_id=route.pool_lease_id,
                pool_scope_id=route.pool_binding.scope_id,
                pool_binding_run_id=route.canary_run_id,
                pool_owner_generation=route.pool_owner_generation,
                pool_tenant_id=route.pool_tenant_id,
                pool_user_id=route.pool_user_id,
            )
    except Exception:
        if DATABASE_URL.startswith("postgresql") or os.getenv(
            "SIQ_REQUIRE_DURABLE_RUNTIME_COORDINATION", "0"
        ) == "1":
            raise
        logger.debug("local durable pool-lease attach unavailable", exc_info=True)
        return True


async def _renew_durable_active_run(state: ActiveRunState) -> bool:
    if qwen38_request_api.handles(state.run_route):
        return await qwen38_request_api.renew(state.run_route, profile=state.profile,
            session_id=state.session_id, owner_id=state.owner_id, run_id=state.run_id)
    try:
        async with AsyncSession(async_engine) as coordination_session:
            return await renew_active_run(
                coordination_session,
                profile=state.profile,
                session_id=state.session_id,
                run_id=state.run_id,
                owner_id=state.owner_id or "",
            )
    except Exception:
        if DATABASE_URL.startswith("postgresql") or os.getenv("SIQ_REQUIRE_DURABLE_RUNTIME_COORDINATION", "0") == "1":
            logger.exception("failed to renew durable active-run lease")
            return False
        return True


async def _renew_durable_provisional_claim(claim: DurableProvisionalClaim) -> bool:
    """Startup must not revive an expired claim or fall back to in-memory ownership."""
    try:
        async with AsyncSession(async_engine) as coordination_session:
            return await renew_active_run(
                coordination_session,
                profile=claim.profile,
                session_id=claim.session_id,
                run_id=claim.provisional_run_id,
                owner_id=claim.owner_id,
                require_unexpired=True,
            )
    except Exception:
        logger.warning("durable startup lease renewal failed")
        return False


async def _active_run_lease_heartbeat(state: ActiveRunState) -> None:
    interval = max(10, lease_seconds() // 3)
    if state.run_route is not None and state.run_route.pool_lease_id:
        interval = min(interval, 60)
    if qwen38_request_api.handles(state.run_route):
        interval = 30
    active_statuses = {"running", "postprocessing"}
    try:
        while state.status in active_statuses and not state.stop_requested:
            await asyncio.sleep(interval)
            if state.status not in active_statuses or state.stop_requested:
                return
            durable_ok = await _renew_durable_active_run(state)
            pool_ok = await _heartbeat_pool_route(
                state.run_route,
                session_id=state.session_id,
            )
            if not durable_ok or not pool_ok:
                state.stop_requested = True
                state.error = "active_run_lease_lost"
                try:
                    state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
                        state.run_id,
                        profile=state.profile,
                        route=state.run_route,
                    )
                except Exception:
                    logger.debug("failed to stop Hermes run after lease loss", exc_info=True)
                return
    except asyncio.CancelledError:
        return


FINANCIAL_CALCULATOR_PATH = FINANCIAL_CALCULATOR_SCRIPT
FINANCIAL_RECONCILIATION_VALIDATOR_PATH = FINANCIAL_RECONCILIATION_VALIDATOR_SCRIPT
FINANCIAL_CALCULATOR_PATH_TEXT = str(FINANCIAL_CALCULATOR_PATH)
FINANCIAL_RECONCILIATION_VALIDATOR_PATH_TEXT = str(FINANCIAL_RECONCILIATION_VALIDATOR_PATH)
def _load_financial_calculator_module() -> Any:
    return financial_calculator


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_int_any(names: tuple[str, ...], default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = next((os.getenv(name) for name in names if os.getenv(name) is not None), None)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_bool_any(names: tuple[str, ...], default: bool = True) -> bool:
    raw = next((os.getenv(name) for name in names if os.getenv(name) is not None), None)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_path_list(names: str | tuple[str, ...], defaults: tuple[Path, ...]) -> tuple[Path, ...]:
    if isinstance(names, str):
        names = (names,)
    raw = next((os.getenv(name) for name in names if os.getenv(name)), None)
    values = re.split(rf"[{re.escape(os.pathsep)},]", raw) if raw else [str(item) for item in defaults]
    output: list[Path] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        if not value:
            continue
        path = Path(value).expanduser()
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        output.append(path)
    return tuple(output)


HISTORY_LIMIT = _env_int_any(("SIQ_CHAT_HISTORY_LIMIT", "SIQ_CHAT_HISTORY_LIMIT"), 24, minimum=4, maximum=120)
LOCAL_MEMORY_ENABLED = _env_bool_any(("SIQ_LOCAL_MEMORY_ENABLED", "SIQ_LOCAL_MEMORY_ENABLED"), True)
LOCAL_MEMORY_ENABLED_PROFILES = {
    item.strip()
    for item in (
        os.getenv("SIQ_LOCAL_MEMORY_PROFILES")
        or (
            "siq_assistant,siq_analysis,siq_factchecker,siq_tracking,siq_legal,"
            "siq_ic_master_coordinator,siq_ic_chairman,siq_ic_strategist,"
            "siq_ic_sector_expert,siq_ic_finance_auditor,siq_ic_legal_scanner,"
            "siq_ic_risk_controller"
        )
    ).split(",")
    if item.strip()
}
LOCAL_MEMORY_RECENT_LIMIT = _env_int_any(("SIQ_LOCAL_MEMORY_RECENT_LIMIT", "SIQ_LOCAL_MEMORY_RECENT_LIMIT"), HISTORY_LIMIT, minimum=4, maximum=160)
LOCAL_MEMORY_MAX_CHARS = _env_int_any(("SIQ_LOCAL_MEMORY_MAX_CHARS", "SIQ_LOCAL_MEMORY_MAX_CHARS"), 5000, minimum=800, maximum=20000)
LOCAL_MEMORY_MAX_BULLETS = _env_int_any(("SIQ_LOCAL_MEMORY_MAX_BULLETS", "SIQ_LOCAL_MEMORY_MAX_BULLETS"), 18, minimum=4, maximum=80)
LOCAL_MEMORY_SNIPPET_CHARS = _env_int_any(("SIQ_LOCAL_MEMORY_SNIPPET_CHARS", "SIQ_LOCAL_MEMORY_SNIPPET_CHARS"), 360, minimum=120, maximum=1200)
PROFILE_SESSION_PREFIXES: dict[str, str] = {
    "siq_assistant": "siq-assistant",
    "siq_analysis": "siq-analysis",
    "siq_factchecker": "siq-factchecker",
    "siq_tracking": "siq-tracking",
    "siq_legal": "siq-legal",
}
CHAT_UPLOAD_ROOT = BACKEND_DATA_ROOT / "chat_uploads"
CHAT_PDF_PARSE_ROOT = CHAT_UPLOAD_ROOT / "pdf_parses"
CHAT_PDF_ATTACHMENT_WAIT_TIMEOUT_SECONDS = _env_int(
    os.getenv("SIQ_CHAT_PDF_ATTACHMENT_WAIT_TIMEOUT_SECONDS") and "SIQ_CHAT_PDF_ATTACHMENT_WAIT_TIMEOUT_SECONDS" or "SIQ_CHAT_PDF_ATTACHMENT_WAIT_TIMEOUT_SECONDS",
    150,
    minimum=0,
    maximum=600,
)
CHAT_PDF_ATTACHMENT_WAIT_POLL_SECONDS = _env_int(
    os.getenv("SIQ_CHAT_PDF_ATTACHMENT_WAIT_POLL_SECONDS") and "SIQ_CHAT_PDF_ATTACHMENT_WAIT_POLL_SECONDS" or "SIQ_CHAT_PDF_ATTACHMENT_WAIT_POLL_SECONDS",
    3,
    minimum=1,
    maximum=30,
)
_CHAT_MESSAGE_ATTACHMENTS_COLUMN_READY = False
ATTACHMENT_FOLLOWUP_RE = re.compile(
    r"(继续|前面|刚才|上[一个轮条张份次]|这张|那张|这份|那份|图片|照片|附件|手写|ocr|OCR)",
    re.IGNORECASE,
)
IMAGE_MODEL_BASE_URL = (
    os.getenv("SIQ_IMAGE_MODEL_BASE_URL")
    or os.getenv("SIQ_IMAGE_MODEL_URL")
    or os.getenv("SIQ_IMAGE_MODEL_BASE_URL")
    or os.getenv("SIQ_IMAGE_MODEL_URL")
    or "http://127.0.0.1:8007/v1"
).rstrip("/")
IMAGE_MODEL_NAME = (os.getenv("SIQ_IMAGE_MODEL") or os.getenv("SIQ_IMAGE_MODEL", "")).strip()
IMAGE_MODEL_ENABLED = _env_bool_any(("SIQ_IMAGE_MODEL_ENABLED", "SIQ_IMAGE_MODEL_ENABLED"), True)
IMAGE_MODEL_TIMEOUT_SECONDS = _env_int_any(("SIQ_IMAGE_MODEL_TIMEOUT_SECONDS", "SIQ_IMAGE_MODEL_TIMEOUT_SECONDS"), 90, minimum=5, maximum=600)
MAX_DOCUMENT_CONTEXT_CHARS = 16000
STREAM_TIMEOUT_SECONDS = 1800
READ_TIMEOUT_SECONDS = 1800
ASSISTANT_STREAM_IDLE_TIMEOUT_SECONDS = _env_int(
    os.getenv("SIQ_ASSISTANT_STREAM_IDLE_TIMEOUT_SECONDS") and "SIQ_ASSISTANT_STREAM_IDLE_TIMEOUT_SECONDS" or "SIQ_ASSISTANT_STREAM_IDLE_TIMEOUT_SECONDS",
    900,
    minimum=30,
    maximum=1800,
)
SPECIALIST_STREAM_IDLE_TIMEOUT_SECONDS = _env_int(
    os.getenv("SIQ_SPECIALIST_STREAM_IDLE_TIMEOUT_SECONDS") and "SIQ_SPECIALIST_STREAM_IDLE_TIMEOUT_SECONDS" or "SIQ_SPECIALIST_STREAM_IDLE_TIMEOUT_SECONDS",
    600,
    minimum=120,
    maximum=1800,
)
STREAM_EVENT_HEARTBEAT_SECONDS = _env_int(
    os.getenv("SIQ_STREAM_EVENT_HEARTBEAT_SECONDS") and "SIQ_STREAM_EVENT_HEARTBEAT_SECONDS" or "SIQ_STREAM_EVENT_HEARTBEAT_SECONDS",
    8,
    minimum=5,
    maximum=120,
)
ANALYSIS_IDEMPOTENCY_WINDOW_SECONDS = 300
ANALYSIS_DUPLICATE_MESSAGE = (
    "[已完成] 检测到这是刚刚处理过的同一条分析请求，系统没有再次创建后台 run。"
    "请查看上一条回复或已生成的报告；如需强制重建，请明确说明“强制重建”。"
)
RECENT_DUPLICATE_MESSAGE = (
    "[已处理] 检测到这是刚刚处理过的同一条请求，系统没有再次创建后台 run。"
    "请查看上一条回复；如需重新执行，请换一种明确的新指令。"
)
ANALYSIS_COMPLETED_MESSAGE = (
    "[已完成] 检测到当前公司年度分析报告已经通过验收，系统没有重复创建后台 run。"
    "如需覆盖重建，请明确说明“强制重建/覆盖重建”。"
)
_IMAGE_MODEL_NAME_CACHE: str | None = None
CONTEXT_HEADER = (
    "以下是本会话的默认上下文，只用于用户没有明确指定公司、证券代码、报告或主题时补全指代。"
    "如果用户问题或会话历史里指定了其他公司/代码/报告/行业/主题，或明显是在问通用问题，必须优先按用户问题和会话历史回答，不要强行套用默认公司。"
)
CHAT_OUTPUT_CONTRACT = (
    "回答格式要求：\n"
    "- 除非用户明确要求一段式回复，问答默认优先使用 Markdown 列表、紧凑小表格或短分节展示，不要整段纯文字堆叠。\n"
    "- 默认先给可读简版：除非用户明确要求“详细/完整/展开/生成报告”，普通问答控制在约 800-1500 中文字，优先列关键结论和关键数据，不要展开成长报告。\n"
    "- 默认报告期口径：当前已入库 Wiki 财报必须以实时 catalog/company.json 的 `primary_report_id` 为准；用户明确指定年报/季报、截止日、年份或 `report_id` 时必须匹配 company.json.reports 或 _meta/report_catalog.json，不要在默认回答、功能介绍或提问示例中写死任何年份。\n"
    "- Wiki 财报检索必须遵循 `data/wiki/_meta/AGENT_GUIDE.md` 和 `financial_source_routing_contract.md`：先按问题类型路由；主表数值、账面价值/净额、利润、现金流、资产负债等先查 `metrics/reports/<report_id>/three_statements.json`、`validation.json` 和 `evidence/evidence_index.json`，附注明细/构成/原值/减值准备再查 `semantic/document_links.json`、`semantic/note_links.json` 或 `note_detail_lookup.py`；`report.md` 全文和 `document_full.json` 只用于上下文、补页码/补表格或冲突交叉验证，不能替代主表事实源。\n"
    "- 财报问答建议结构：先给 `## 结论` 列表，再给 `## 依据/数据` 列表或表格，最后保留 `## 引用来源`。\n"
    "- 财报事实问答中，正文出现的主要数值、比例、金额、员工数、销量、市占率或派生指标，必须在唯一的 `## 引用来源` 中逐项映射到 PDF 页、表格/文本块和来源链接，不要另起 `主要数据溯源补充`、`主要数据引用来源` 等重复章节。\n"
    f"- 人均、每股、同比、增长率、占比、CAGR、外币折人民币和金额单位归一等派生计算，必须使用 `{FINANCIAL_CALCULATOR_PATH_TEXT}` 或后端确定性脚本校验；不要心算后直接输出。\n"
    "- 图片识别、按钮文本、键盘符号、单位和普通指标名一律使用普通文本；不要用 `$...$` 包裹。仅在用户明确要求公式或 LaTeX 时才输出 LaTeX 分隔符。\n"
    "- 涉及数据表证据时，引用行必须保留 `table_index` 或表格来源链接，便于前端展示可打开表格入口。\n"
    "- `## 引用来源` 内的 `source_type/file/task_id/pdf_page/table_index/md_line` 字段必须保持机器可解析，不要改写成散文。\n"
)
FINANCIAL_CALCULATION_RUNTIME_CONTRACT = (
    "财务派生计算硬约束：\n"
    f"- 人均、每股、同比、增长率、占比、CAGR、外币折人民币和金额单位归一，必须使用 `{FINANCIAL_CALCULATOR_PATH_TEXT}` 或后端同源函数；工具调用应使用单条、完整的 `--format json` 命令，后端会从当前 Hermes 回执生成并校验新版 `siq_financial_calculation_trace_v1` JSON envelope。最终回答保留简洁的 `## 计算器校验` / `## 勾稽校验` 摘要即可，不要手写或重复整段 JSON。\n"
    f"- 计算器是子命令 CLI，只允许 `normalize|per-capita|ratio|yoy|cagr`。金额单位必须与来源一致，不能依赖默认 `元`。同比示例：`python3 {FINANCIAL_CALCULATOR_PATH_TEXT} --format json yoy --current 34256859 --current-unit '人民币千元' --previous 29581014 --previous-unit '人民币千元' --currency CNY`；占比示例：`python3 {FINANCIAL_CALCULATOR_PATH_TEXT} --format json ratio --numerator 23435302 --numerator-unit '人民币千元' --denominator 34813270 --denominator-unit '人民币千元' --currency CNY`；单位归一示例：`python3 {FINANCIAL_CALCULATOR_PATH_TEXT} --format json normalize --value 34256859 --unit '人民币千元' --currency CNY`。不存在 `--operation`、`growth` 或 `proportion` 参数。\n"
    f"- 商誉、坏账准备、存货跌价准备、资产减值准备等涉及原值/准备/净额的口径，必须使用 `{FINANCIAL_RECONCILIATION_VALIDATOR_PATH_TEXT}` 或后端同源函数勾稽；后端内部保存 `siq_financial_reconciliation_trace_v1` JSON envelope（含 gross/allowance/net 三项输入与 evidence_id），可见回答只展示简要勾稽结论。商誉主表值是账面净额，不得把附注账面原值当成主表余额。\n"
    f"- 勾稽脚本同样使用子命令；商誉示例：`python3 {FINANCIAL_RECONCILIATION_VALIDATOR_PATH_TEXT} --format json goodwill --company '<公司名>' --report-id '<report_id>'`。不得把原值、准备、净额作为无子命令的位置参数。\n"
    "- 若命令返回 argparse `usage:` / `invalid choice` / `unrecognized arguments`，说明调用语法错误：不得原样重试；应按该次 usage 选择有效子命令和参数。若上下文已有结构化事实，则停止调用工具并只返回已验证事实，不输出未经校验的派生结论。\n"
    "- 中国上市公司商誉口径必须区分账面原值、减值准备余额、账面价值、当期减值损失和准备变动；若附注写明“本年/本期计入当期损益”或减值准备由 `-`/0 增加为正数，不能表述为“本期未新增减值”。\n"
    "- 上期值为 0 或负数时，普通同比/增长率默认 `not_applicable`，应描述扭亏/亏损扩大/亏损收窄和绝对变动，不能硬写普通增长百分比。\n"
    "- `(1,016)`、`（1,016）` 这类括号金额按负数处理；`HKD`、`HK$` 是港元币种，不是 `K=千` 单位。\n"
    "- `fx_required`、`division_by_zero`、`not_applicable` 是受控业务状态，不等于工具失败；必须解释状态和缺口，不能改写成确定数值。\n"
    "- 若输入中存在 `## 后端确定性财务结果包`，该结果包优先级高于模型心算和工具摘要。"
    "所有金额换算、变动额及其项目归属只能逐字采用结果包，并标注 `[calc:...]`；"
    "禁止自行补零、移动小数点、把万元/百万元写成亿元，或把某一被投资单位的变动归给另一单位。\n"
)
GENERAL_ASSISTANT_CONTEXT = (
    "当前用户是在询问智能体自身简介、能力范围、使用方式或提问示例。"
    "这是 profile 元信息请求，不是公司分析、公司跟踪或 Wiki 公司目录查询任务。"
    "回答必须遵循当前 Hermes profile 自身的角色设定，围绕当前智能体的职责、能力、边界、适合提问方式和输出形式；"
    "不要把页面默认公司、会话默认公司、本地记忆里的公司、历史 session 示例或测试样例当作当前工作集。"
    "除非用户在本条消息中明确指定公司，否则不要声称当前工作集/默认分析对象/默认跟踪对象是某家公司。"
    "不要套用其他智能体身份，特别是不要把所有角色都写成全局财报问答助手。"
    "若需要举公司示例，优先使用当前 profile 可访问的实时 Wiki catalog；无法读取时使用“某个已入库公司”。"
    "默认财报口径必须以实时 catalog/company.json 的 primary_report_id 说明，不要写死任何年份或 report_id。"
)
MEMORY_MANAGEMENT_CONTEXT = (
    "当前用户正在查询自己的会话历史、提问统计或个人长期记忆。"
    "这不是公司研究或财报事实问题。"
    "如上下文含有 <user-history-analytics>，必须直接依据其中的确定性统计回答；"
    "不得调用 pg_query.py、不得访问市场事实库、不得以 profile 文档替代用户历史，也不得编造 PDF 或财报引用。"
    "如统计块明确为空或不完整，必须如实说明其范围和限制。"
    "如上下文只含 <memory-context>，其中仅能作为已授权长期记忆使用，且当前用户问题优先。"
)
NOTE_DETAIL_SCRIPT_DIR = HERMES_SHARED_SCRIPTS_ROOT
STATEMENT_QUERY_TERMS = (
    "营业收入",
    "营收",
    "营业成本",
    "营业利润",
    "利润总额",
    "净利润",
    "归母净利润",
    "扣非归母",
    "扣非净利润",
    "每股收益",
    "净资产收益率",
    "现金流",
    "现金流量表",
    "经营活动现金",
    "投资活动现金",
    "筹资活动现金",
    "资产负债表",
    "资产负债",
    "资产构成",
    "资产结构",
    "负债结构",
    "负债与权益",
    "负债权益",
    "所有者权益",
    "股东权益",
    "偿债",
    "总资产",
    "资产总额",
    "总负债",
    "净资产",
    "利润表",
    "损益表",
    "revenue",
    "sales",
    "cost of sales",
    "operating income",
    "operating profit",
    "net income",
    "net profit",
    "earnings per share",
    "cash flow",
    "operating cash flow",
    "investing cash flow",
    "financing cash flow",
    "balance sheet",
    "statement of financial position",
    "total assets",
    "total liabilities",
    "shareholders equity",
    "stockholders equity",
    "income statement",
    "profit and loss",
)
NOTE_DETAIL_QUERY_TERMS = (
    "明细",
    "构成",
    "分布",
    "组成",
    "附注",
    "详情",
    "减值",
    "准备",
    "账龄",
    "前五名",
    "资产组",
    "可收回",
    "变动",
)
NOTE_DETAIL_EXCLUDE_TERMS = (
    "生成报告",
    "分析报告",
    "完整报告",
    "重建报告",
    "覆盖重建",
    "强制重建",
)
NOTE_DETAIL_DIRECT_TERMS = (
    "是什么",
    "查询",
    "查一下",
    "给我",
    "给我一下",
    "看一下",
    "有哪些",
    "列出",
    "展示",
    "显示",
    "明细",
    "构成",
    "分布",
    "组成",
    "详情",
    "附注",
    "账龄",
    "前五名",
)
NOTE_DETAIL_ANALYSIS_TERMS = (
    "分析",
    "评价",
    "判断",
    "影响",
    "风险",
    "原因",
    "趋势",
    "对比",
    "预测",
    "建议",
    "异常",
    "合理",
    "解释",
    "为什么",
    "怎么看",
)
FINANCIAL_NOTE_METRIC_TERMS = (
    "商誉",
    "应收账款",
    "其他应收款",
    "预付款项",
    "存货",
    "合同资产",
    "固定资产",
    "在建工程",
    "无形资产",
    "开发支出",
    "长期股权投资",
    "投资性房地产",
    "递延所得税资产",
    "短期借款",
    "长期借款",
    "应付账款",
    "合同负债",
    "预计负债",
    "营业收入",
    "营业成本",
    "销售费用",
    "管理费用",
    "研发费用",
    "财务费用",
    "资产减值损失",
    "信用减值损失",
)
FINANCIAL_EVIDENCE_ACTION_TERMS = (
    *NOTE_DETAIL_QUERY_TERMS,
    *NOTE_DETAIL_ANALYSIS_TERMS,
    "多少",
    "金额",
    "余额",
    "账面价值",
    "账面余额",
    "原值",
    "计提",
    "转回",
    "转销",
    "处置",
    "同比",
    "变化",
    "占比",
    "数据",
    "情况",
)
GOODWILL_MAIN_STATEMENT_TERMS = (
    "账面价值",
    "账面净值",
    "净额",
    "主表",
    "资产负债表",
    "报表项目",
    "合并报表",
    "余额",
)
RUNTIME_STATUS_PREFIXES = ("[已停止]", "[失败]", "[已取消]", "[错误]")
PROTOCOL_EOF_MESSAGE = "[失败] Hermes 事件流在返回终态前已结束，请重试本次请求。"
TRANSPORT_FAILURE_MESSAGE = "[失败] 任务执行连接中断，无法确认完整结果。请先核对已产生的文件或操作记录。"
STATEMENT_DIRECT_TERMS = (
    "是什么",
    "有哪些",
    "列出",
    "展示",
    "显示",
    "核心数据",
    "数据",
    "摘要",
    "情况",
    "多少",
    "概览",
    "构成",
    "结构",
    "明细",
)
GENERAL_ASSISTANT_REQUEST_TERMS = (
    "智能体简介",
    "自我介绍",
    "你是谁",
    "你能做什么",
    "能解决哪些",
    "能力范围",
    "典型场景",
    "工作方式",
    "提问示例",
    "输出边界",
    "最佳使用方式",
    "注意事项",
    "可追溯链接",
    "如何使用",
    "怎么使用",
    "怎么提问",
    "如何提问",
    "适合用户怎样提问",
)
GENERAL_ASSISTANT_SUBJECT_TERMS = (
    "你",
    "智能体",
    "助手",
    "问答助手",
    "agent",
    "siq",
)
HUMAN_CAPITAL_QUERY_TERMS = (
    "人才结构",
    "人才构成",
    "人员结构",
    "人员构成",
    "员工结构",
    "员工构成",
    "员工情况",
    "专业构成",
    "教育程度",
    "学历结构",
    "人力结构",
    "人力资源结构",
)
HUMAN_EFFICIENCY_QUERY_TERMS = (
    "人效",
    "人均营收",
    "人均收入",
    "人均产出",
    "人均创收",
    "人均利润",
    "人均成本",
    "人均人力成本",
    "人力成本",
    "人员成本",
    "人员费用",
    "员工效率",
    "劳动效率",
    "员工生产率",
    "员工人数",
    "平均员工",
)
HUMAN_CAPITAL_TABLE_TERMS = (
    "母公司在职员工的数量",
    "主要子公司在职员工的数量",
    "在职员工的数量合计",
    "专业构成",
    "教育程度",
)
CORE_KEY_METRIC_TERMS = (
    "营业收入",
    "营收",
    "收入",
    "毛利",
    "毛利率",
    "净利率",
    "利润总额",
    "净利润",
    "归母净利润",
    "扣非归母",
    "扣非净利润",
    "研发投入",
    "研发费用",
    "销售费用",
    "管理费用",
    "财务费用",
    "经营现金流",
    "经营活动现金流量净额",
    "现金流量净额",
    "基本每股收益",
    "稀释每股收益",
    "每股收益",
    "eps",
    "roe",
    "净资产收益率",
    "加权平均净资产收益率",
    "总资产",
    "总负债",
    "净资产",
    "资产负债率",
    "每股净资产",
    "revenue",
    "sales",
    "gross profit",
    "gross margin",
    "operating income",
    "operating profit",
    "net income",
    "net profit",
    "operating cash flow",
    "earnings per share",
    "total assets",
    "total liabilities",
    "total equity",
)
CORE_KEY_METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "营业收入": ("operating_revenue", "营业收入", "营收", "收入", "revenue", "sales"),
    "利润总额": ("total_profit", "利润总额"),
    "净利润": ("net_profit", "净利润", "net income", "net profit"),
    "归母净利润": ("parent_net_profit", "归属于上市公司股东的净利润", "归属于本行股东的净利润", "归母净利润"),
    "扣非归母净利润": (
        "deducted_parent_net_profit",
        "归属于上市公司股东的扣除非经常性损益的净利润",
        "扣除非经常性损益后归属于本行股东的净利润",
        "扣非归母净利润",
        "扣非净利润",
        "扣非归母",
    ),
    "经营活动现金流量净额": (
        "operating_cash_flow_net",
        "经营活动产生的现金流量净额",
        "经营现金流",
        "经营活动现金流量净额",
        "经营活动现金流",
        "operating cash flow",
    ),
    "基本每股收益": ("basic_eps", "基本每股收益", "每股收益", "eps", "earnings per share"),
    "稀释每股收益": ("diluted_eps", "稀释每股收益"),
    "扣非基本每股收益": ("deducted_basic_eps", "扣除非经常性损益后的基本每股收益", "扣非基本每股收益"),
    "加权平均净资产收益率": ("weighted_avg_roe", "加权平均净资产收益率", "净资产收益率", "roe"),
    "扣非加权平均净资产收益率": (
        "deducted_weighted_avg_roe",
        "扣除非经常性损益后的加权平均净资产收益率",
        "扣非加权平均净资产收益率",
    ),
    "总资产": ("total_assets", "总资产", "资产总额", "资产合计", "资产总计", "total assets"),
    "总负债": ("total_liabilities", "总负债", "total liabilities"),
    "商誉": ("goodwill", "商誉"),
    "归属于母公司股东权益": (
        "equity_attributable_parent",
        "total_equity",
        "shareholders equity",
        "stockholders equity",
        "归属于上市公司股东的净资产",
        "归属于本行股东权益",
        "净资产",
    ),
    "每股净资产": ("parent_nav_per_share", "每股净资产"),
}
THREE_STATEMENT_CORE_KEYS: dict[str, tuple[str, ...]] = {
    "income_statement": (
        "operating_revenue",
        "total_operating_revenue",
        "operating_cost",
        "gross_profit",
        "operating_profit",
        "total_profit",
        "net_profit",
        "parent_net_profit",
    ),
    "cash_flow_statement": (
        "operating_cash_inflow_total",
        "operating_cash_outflow_total",
        "operating_cash_flow_net",
        "investing_cash_flow_net",
        "financing_cash_flow_net",
        "cash_and_cash_equivalents_net_increase",
        "ending_cash_and_cash_equivalents",
    ),
    "balance_sheet": (
        "current_assets",
        "non_current_assets",
        "total_assets",
        "current_liabilities",
        "non_current_liabilities",
        "total_liabilities",
        "goodwill",
        "equity_attributable_parent",
        "total_equity",
        "total_liabilities_and_equity",
    ),
}
THREE_STATEMENT_CORE_NAME_TERMS: dict[str, tuple[str, ...]] = {
    "income_statement": (
        "营业收入",
        "营业总收入",
        "营业成本",
        "营业利润",
        "利润总额",
        "净利润",
        "归属于母公司",
        "归属于本行股东",
    ),
    "cash_flow_statement": (
        "经营活动现金流入小计",
        "经营活动现金流出小计",
        "经营活动产生的现金流量净额",
        "投资活动产生",
        "投资活动使用",
        "筹资活动产生",
        "筹资活动使用",
        "现金及现金等价物净增加额",
        "期末现金及现金等价物余额",
    ),
    "balance_sheet": (
        "流动资产合计",
        "非流动资产合计",
        "资产总计",
        "资产合计",
        "流动负债合计",
        "非流动负债合计",
        "负债合计",
        "商誉",
        "归属于母公司股东权益",
        "归属于本行股东权益",
        "所有者权益合计",
        "股东权益合计",
        "负债和股东权益总计",
        "负债和所有者权益总计",
    ),
}
THREE_STATEMENT_LABELS = {
    "income_statement": "利润表",
    "cash_flow_statement": "现金流量表",
    "balance_sheet": "资产负债表",
}
HERMES_PROFILE_DIRS: dict[HermesProfile, Path] = {
    "siq_assistant": HERMES_PROFILE_ROOTS["siq_assistant"],
    "siq_analysis": HERMES_PROFILE_ROOTS["siq_analysis"],
    "siq_factchecker": HERMES_PROFILE_ROOTS["siq_factchecker"],
    "siq_tracking": HERMES_PROFILE_ROOTS["siq_tracking"],
    "siq_legal": HERMES_PROFILE_ROOTS["siq_legal"],
    "siq_ic_master_coordinator": HERMES_PROFILE_ROOTS["siq_ic_master_coordinator"],
    "siq_ic_chairman": HERMES_PROFILE_ROOTS["siq_ic_chairman"],
    "siq_ic_strategist": HERMES_PROFILE_ROOTS["siq_ic_strategist"],
    "siq_ic_sector_expert": HERMES_PROFILE_ROOTS["siq_ic_sector_expert"],
    "siq_ic_finance_auditor": HERMES_PROFILE_ROOTS["siq_ic_finance_auditor"],
    "siq_ic_legal_scanner": HERMES_PROFILE_ROOTS["siq_ic_legal_scanner"],
    "siq_ic_risk_controller": HERMES_PROFILE_ROOTS["siq_ic_risk_controller"],
}
HERMES_LIVE_PROFILE_ALIASES: dict[str, str] = {
    "siq_assistant": "finsight_assistant",
    "siq_analysis": "finsight_analysis",
    "siq_factchecker": "finsight_factchecker",
    "siq_tracking": "finsight_tracking",
    "siq_legal": "finsight_legal",
}
DEFAULT_WIKI_ROOT = str(CONFIG_WIKI_ROOT)
PROJECT_WIKI_ROOT = CONFIG_WIKI_ROOT
ASSISTANT_WIKI_ROOT = CONFIG_ASSISTANT_WIKI_ROOT
PRIMARY_MARKET_DEALS_ROOT = CONFIG_WIKI_ROOT / "deals"
WIKI_FALLBACK_ROOTS: tuple[Path, ...] = tuple(
    dict.fromkeys(
        path
        for path in (
            *WIKI_ROOT_CANDIDATES,
            Path.home() / "wiki",
        )
        if (path / "companies").exists()
    )
)
os.environ.setdefault("SIQ_WIKI_ROOT", str(PROJECT_WIKI_ROOT))
os.environ.setdefault("SIQ_WIKI_ROOT", str(PROJECT_WIKI_ROOT))
os.environ.setdefault(
    "SIQ_DEFAULT_SOURCE_TYPE",
    "wiki_metrics",
)
os.environ.setdefault("SIQ_DEFAULT_SOURCE_TYPE", os.environ.get("SIQ_DEFAULT_SOURCE_TYPE", "wiki_metrics"))
os.environ.setdefault("SIQ_ASSISTANT_DEFAULT_SOURCE_TYPE", "wiki_metrics")
os.environ.setdefault("SIQ_ASSISTANT_DEFAULT_SOURCE_TYPE", os.environ.get("SIQ_ASSISTANT_DEFAULT_SOURCE_TYPE", "wiki_metrics"))
_CURRENT_PROFILE: ContextVar[HermesProfile | None] = ContextVar("siq_current_profile", default=None)


class _ProfileWikiRoot:
    def _path(self) -> Path:
        profile = _CURRENT_PROFILE.get()
        if profile == "siq_assistant":
            return ASSISTANT_WIKI_ROOT
        if primary_market_agent_runtime.is_primary_market_ic_profile(profile):
            return PRIMARY_MARKET_DEALS_ROOT
        return PROJECT_WIKI_ROOT

    def __fspath__(self) -> str:
        return os.fspath(self._path())

    def __str__(self) -> str:
        return str(self._path())

    def __repr__(self) -> str:
        return repr(self._path())

    def __truediv__(self, key: str) -> Path:
        return self._path() / key

    def resolve(self) -> Path:
        return self._path().resolve()

    def expanduser(self) -> Path:
        return self._path().expanduser()


WIKI_ROOT = _ProfileWikiRoot()


def _current_default_source_type() -> str:
    profile = _CURRENT_PROFILE.get()
    if profile == "siq_assistant":
        return os.environ.get("SIQ_ASSISTANT_DEFAULT_SOURCE_TYPE") or os.environ.get("SIQ_ASSISTANT_DEFAULT_SOURCE_TYPE", "wiki_metrics")
    return os.environ.get("SIQ_DEFAULT_SOURCE_TYPE") or os.environ.get("SIQ_DEFAULT_SOURCE_TYPE", "wiki_metrics")


def _current_source_type(kind: str) -> str:
    default_source_type = _current_default_source_type()
    prefix = default_source_type.split("_", 1)[0] if default_source_type.startswith("wiki_") else "wiki"
    return f"{prefix}_{kind}"


def _configure_wiki_module(module: Any | None) -> Any | None:
    if module is None:
        return None
    try:
        module.WIKI_BASE = WIKI_ROOT._path()
    except Exception:
        pass
    try:
        module.DEFAULT_SOURCE_TYPE = _current_default_source_type()
    except Exception:
        pass
    return module


@contextmanager
def _profile_wiki_context(profile: HermesProfile):
    token = _CURRENT_PROFILE.set(profile)
    try:
        yield
    finally:
        _CURRENT_PROFILE.reset(token)
PDF2MD_RESULTS_ROOTS = _env_path_list(
    ("SIQ_PDF2MD_RESULTS_DIRS", "SIQ_PDF2MD_RESULTS_DIRS"),
    PDF_RESULT_ROOT_CANDIDATES,
)
PDF2MD_OUTPUT_ROOTS = _env_path_list(
    ("SIQ_PDF2MD_OUTPUT_DIRS", "SIQ_PDF2MD_OUTPUT_DIRS"),
    PDF_OUTPUT_ROOT_CANDIDATES,
)
PDF2MD_PARSE_ONLY_CONTEXT_LIMIT = _env_int_any(("SIQ_PDF2MD_PARSE_ONLY_CONTEXT_LIMIT", "SIQ_PDF2MD_PARSE_ONLY_CONTEXT_LIMIT"), 3, minimum=1, maximum=8)
TASK_ID_FIELD_RE = agent_runtime_task_ids.TASK_ID_FIELD_RE
API_TASK_ID_RE = agent_runtime_task_ids.API_TASK_ID_RE
POSTGRES_FALLBACK_ROW_LIMIT = int(os.environ.get("SIQ_PG_FALLBACK_ROW_LIMIT") or os.environ.get("SIQ_PG_FALLBACK_ROW_LIMIT", "20"))
COMPANY_ALIAS_OVERRIDES: dict[str, tuple[str, ...]] = {
    "BASF-BASF": ("巴斯夫", "巴斯夫集团", "BASF Group"),
    "GENBASF-BASF": ("巴斯夫", "巴斯夫集团", "BASF Group"),
    # Common Chinese aliases are not always present in SEC company names.
    # Keep them keyed by stable catalog company_id so market resolution can
    # bind the query before evidence lookup.
    "US:0000320193": ("苹果", "苹果公司", "Apple", "Apple Inc."),
    "US:0001018724": ("亚马逊", "亚马逊公司", "Amazon", "Amazon.com"),
    "US:0001045810": ("英伟达", "英伟达公司", "NVIDIA", "Nvidia"),
    "KR:005930": ("三星电子", "三星", "Samsung Electronics", "삼성전자"),
    "JP:7203": ("丰田", "丰田汽车", "Toyota", "Toyota Motor", "トヨタ", "トヨタ自動車"),
}
POSTGRES_FALLBACK_TERMS = (
    *STATEMENT_QUERY_TERMS,
    *CORE_KEY_METRIC_TERMS,
    "财务",
    "业绩",
    "表现",
    "基本面",
    "经营情况",
    "主要数据",
    "核心数据",
    "指标",
    "金额",
    "余额",
    "同比",
    "变化",
    "占比",
    "比例",
    "率",
)
PRIMARY_DATA_EVIDENCE_MARKERS = (
    "## 主要数据溯源",
    "## 主要数据溯源补充",
    "## 财务指标溯源补充",
    "## 指标级引用来源",
)
AUTO_EVIDENCE_SECTION_TITLES = {
    "主要数据溯源",
    "主要数据溯源补充",
    "财务指标溯源补充",
    "主要数据引用来源",
    "指标级引用来源",
    "PostgreSQL 引用",
}
PRIMARY_DATA_SUPPLEMENT_MAX_ROWS = _env_int("SIQ_PRIMARY_DATA_SUPPLEMENT_MAX_ROWS", 28, minimum=6, maximum=80)
REPORT_FULLTEXT_FALLBACK_TERMS = (
    *POSTGRES_FALLBACK_TERMS,
    *FINANCIAL_NOTE_METRIC_TERMS,
    *HUMAN_CAPITAL_QUERY_TERMS,
    *HUMAN_EFFICIENCY_QUERY_TERMS,
    "年报",
    "年度报告",
    "报告",
    "全文",
    "原文",
    "披露",
    "说明",
    "业务",
    "经营",
    "市场",
    "市场占有率",
    "占有率",
    "销量",
    "销售",
    "新能源",
    "出口",
    "海外",
    "研发投入",
    "研发",
    "员工",
    "客户",
    "供应商",
    "订单",
    "产能",
    "产量",
    "分红",
    "股东",
    "前十名",
    "治理",
    "处罚",
    "诉讼",
    "担保",
    "质押",
    "商誉",
    "商譽",
    "goodwill",
    "のれん",
    "영업권",
)
REPORT_FULLTEXT_GENERIC_TERMS = {
    "年报",
    "年度报告",
    "报告",
    "全文",
    "原文",
    "披露",
    "说明",
    "业务",
    "经营",
    "数据",
    "情况",
    "分析",
    "财务",
    "业绩",
    "表现",
    "基本面",
    "主要数据",
    "核心数据",
}
REPORT_ANNUAL_TERMS = ("年报", "年度报告", "年度报", "annual", "2025年报", "2025年度")
REPORT_QUARTERLY_TERMS = ("季报", "季度报告", "一季报", "三季报", "半年报", "半年度报告", "quarter", "quarterly", "2025q")
REPORT_FULLTEXT_MAX_SNIPPETS = _env_int("SIQ_REPORT_FULLTEXT_MAX_SNIPPETS", 6, minimum=1, maximum=20)
REPORT_FULLTEXT_SNIPPET_CHARS = _env_int("SIQ_REPORT_FULLTEXT_SNIPPET_CHARS", 900, minimum=240, maximum=2200)
PROFILE_LABELS: dict[HermesProfile, str] = {
    "siq_assistant": "通用助手",
    "siq_analysis": "智能分析助手",
    "siq_factchecker": "事实核查助手",
    "siq_tracking": "跟踪助手",
    "siq_legal": "法务助手",
    "siq_ic_master_coordinator": "投委会总协调员",
    "siq_ic_chairman": "投委会主席",
    "siq_ic_strategist": "战略委员",
    "siq_ic_sector_expert": "行业专家",
    "siq_ic_finance_auditor": "财务审计委员",
    "siq_ic_legal_scanner": "法务合规委员",
    "siq_ic_risk_controller": "风险管理委员",
}
DIAGNOSTIC_MAX_AGE_SECONDS = 30 * 60
FORCE_REBUILD_TERMS = ("强制重建", "覆盖重建", "强制重新生成", "重新计算", "--force")
ANALYSIS_REPORT_TERMS = (
    "分析报告",
    "年度分析",
    "年报分析",
    "财务诊断报告",
    "年度报告",
    "完整报告",
    "html",
    "markdown",
    ".html",
    ".md",
)
ANALYSIS_GENERATION_TERMS = (
    "生成",
    "重新生成",
    "重生成",
    "重建",
    "覆盖",
    "创建",
    "新建",
    "撰写",
    "编写",
    "写一份",
    "做一份",
    "出一份",
    "跑",
    "跑一遍",
    "执行",
    "启动",
    "开始",
    "续跑",
    "恢复",
    "渲染",
)
ANALYSIS_STATUS_TERMS = (
    "完成了吗",
    "完成了么",
    "是否完成",
    "生成了吗",
    "生成了么",
    "报告路径",
    "验收结果",
    "验收了吗",
    "进度",
)
WIKI_CATALOG_COUNT_TERMS = agent_runtime_catalog.WIKI_CATALOG_COUNT_TERMS
WIKI_CATALOG_LIST_TERMS = agent_runtime_catalog.WIKI_CATALOG_LIST_TERMS
WIKI_CATALOG_SUBJECT_TERMS = agent_runtime_catalog.WIKI_CATALOG_SUBJECT_TERMS

ChatRequestEnvelope = agent_runtime_preflight.ChatRequestEnvelope
ChatRunPreflightContext = agent_runtime_preflight.ChatRunPreflightContext


SESSION_DEFAULT_CONTEXTS: dict[tuple[HermesProfile, str], str] = {}
RECENT_COMPLETED_RUNS = agent_runtime_dedupe.RECENT_COMPLETED_RUNS


def _read_json_file(path: Path) -> Any | None:
    agent_runtime_host_scope.require_path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_task_id_like(value: Any) -> bool:
    return agent_runtime_task_ids.is_task_id_like(value)


def _pdf2md_task_result_dir(task_id: str) -> Path | None:
    return agent_runtime_task_ids.pdf2md_task_result_dir(task_id, roots=PDF2MD_RESULTS_ROOTS)


def _pdf2md_task_output_dir(task_id: str) -> Path | None:
    return agent_runtime_task_ids.pdf2md_task_output_dir(task_id, roots=PDF2MD_OUTPUT_ROOTS)


def _file_contains_bytes(path: Path, needle: bytes) -> bool:
    return agent_runtime_task_ids.file_contains_bytes(path, needle)


def _company_wiki_contains_task_id(company_dir: Path, task_id: str) -> bool:
    return agent_runtime_task_ids.company_wiki_contains_task_id(company_dir, task_id)


def _wiki_task_id_exists(task_id: str, message: str = "", context: Any | None = None) -> bool:
    return agent_runtime_task_ids.wiki_task_id_exists(
        task_id,
        message,
        context,
        wiki_root=WIKI_ROOT,
        resolve_company_dirs=_resolve_company_dirs,
    )


def _task_id_exists(task_id: str, message: str = "", context: Any | None = None) -> bool:
    return agent_runtime_task_ids.task_id_exists(
        task_id,
        message,
        context,
        pdf2md_result_roots=PDF2MD_RESULTS_ROOTS,
        pdf2md_output_roots=PDF2MD_OUTPUT_ROOTS,
        wiki_root=WIKI_ROOT,
        resolve_company_dirs=_resolve_company_dirs,
    )


def _extract_task_ids_from_text(text: str | None) -> list[str]:
    return agent_runtime_task_ids.extract_task_ids_from_text(text)


def _invalid_task_ids_in_reply(message: str, context: Any | None, reply: str) -> list[str]:
    invalid = agent_runtime_task_ids.invalid_task_ids_in_reply(
        message,
        context,
        reply,
        pdf2md_result_roots=PDF2MD_RESULTS_ROOTS,
        pdf2md_output_roots=PDF2MD_OUTPUT_ROOTS,
        wiki_root=WIKI_ROOT,
        resolve_company_dirs=_resolve_company_dirs,
    )
    invalid_set = set(invalid)
    for task_id in _extract_task_ids_from_text(reply):
        if task_id in invalid_set:
            continue
        if not _task_id_matches_research_context(task_id, message, context):
            invalid.append(task_id)
            invalid_set.add(task_id)
    return invalid


def _infer_stock_code_from_text(text: str) -> str:
    return agent_runtime_parse_only.infer_stock_code_from_text(text)


def _infer_company_name_from_filename(filename: str) -> str:
    return agent_runtime_parse_only.infer_company_name_from_filename(filename)


def _pdf2md_task_info_from_dir(result_dir: Path) -> dict[str, Any] | None:
    task_id = result_dir.name
    if not _is_task_id_like(task_id):
        return None
    info: dict[str, Any] = {
        "task_id": task_id,
        "result_dir": result_dir,
    }
    for file_name in ("artifact_manifest.json", "financial_data.json", "quality_report.json", "result_payload_summary.json"):
        payload = _read_json_file(result_dir / file_name)
        if not isinstance(payload, dict):
            continue
        for key in ("filename", "result_file", "file_name", "original_filename"):
            value = payload.get(key)
            if value and not info.get("filename"):
                info["filename"] = str(value)
        if file_name == "artifact_manifest.json":
            core = payload.get("core") if isinstance(payload.get("core"), dict) else {}
            info["ready"] = bool(core.get("ready") or core.get("status") == "ready")
            artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), dict) else {}
            if artifacts:
                info["artifacts"] = artifacts
    filename = str(info.get("filename") or "")
    info["stock_code"] = _infer_stock_code_from_text(filename)
    info["company_name"] = _infer_company_name_from_filename(filename)

    result_md = result_dir / "result.md"
    if result_md.is_file():
        info["result_md"] = result_md
    for name in (
        "result_complete.md",
        "document_full.json",
        "content_list_enhanced.json",
        "content_list.json",
        "table_index.json",
        "financial_data.json",
    ):
        path = result_dir / name
        if path.exists():
            info[name.replace(".", "_")] = path
    if not any(key in info for key in ("result_md", "document_full_json", "content_list_json", "financial_data_json")):
        return None
    return info


def _iter_pdf2md_task_infos() -> list[dict[str, Any]]:
    infos: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in PDF2MD_RESULTS_ROOTS:
        try:
            children = sorted(root.iterdir(), key=lambda path: path.stat().st_mtime, reverse=True)
        except Exception:
            continue
        for child in children:
            if not child.is_dir() or child.name in seen:
                continue
            seen.add(child.name)
            info = _pdf2md_task_info_from_dir(child)
            if info:
                infos.append(info)
    return infos


def _pdf2md_task_aliases(info: dict[str, Any]) -> list[str]:
    return agent_runtime_parse_only.pdf2md_task_aliases(info)


def _pdf2md_info_matches_message(info: dict[str, Any], message: str, context: Any | None = None) -> bool:
    return agent_runtime_parse_only.pdf2md_info_matches_message(
        info,
        message,
        context,
        normalize_text=_normalize_financial_text,
        context_company_hint=_context_company_hint,
    )


def _task_id_matches_research_context(task_id: str, message: str, context: Any | None = None) -> bool:
    """Reject foreign PDF tasks only for the US SEC/XBRL research path."""

    identity = agent_runtime_context.research_identity(context)
    if str(identity.get("market") or "").strip().upper() != "US":
        return True
    company_dirs = list(_resolve_company_dirs(message, context, limit=6))
    if any(_company_wiki_contains_task_id(company_dir, task_id) for company_dir in company_dirs):
        return True
    result_dir = _pdf2md_task_result_dir(task_id)
    if result_dir is None:
        return False
    info = _pdf2md_task_info_from_dir(result_dir)
    return bool(info and _pdf2md_info_matches_message(info, message, context))


def _wiki_company_exists_for_pdf2md_info(info: dict[str, Any]) -> bool:
    stock_code = str(info.get("stock_code") or "").strip()
    if stock_code:
        try:
            if any((WIKI_ROOT / "companies").glob(f"{stock_code}-*")):
                return True
        except Exception:
            pass
    catalog = _read_json_file(WIKI_ROOT / "_meta" / "company_catalog.json")
    companies = catalog.get("companies") if isinstance(catalog, dict) else None
    if not isinstance(companies, list):
        return False
    aliases = {_normalize_financial_text(alias) for alias in _pdf2md_task_aliases(info) if alias}
    aliases.discard("")
    for company in companies:
        if not isinstance(company, dict):
            continue
        company_aliases = {
            _normalize_financial_text(value)
            for value in (
                company.get("company_id"),
                company.get("stock_code"),
                company.get("company_short_name"),
                company.get("company_full_name"),
                *((company.get("aliases") or []) if isinstance(company.get("aliases"), list) else []),
            )
            if value
        }
        if aliases & company_aliases:
            return True
    return False


def _pdf2md_parse_only_matches(message: str, context: Any | None = None, *, limit: int | None = None) -> list[dict[str, Any]]:
    return agent_runtime_parse_only._pdf2md_parse_only_matches(
        message,
        context,
        limit=limit,
        iter_pdf2md_task_infos=_iter_pdf2md_task_infos,
        pdf2md_info_matches_message=_pdf2md_info_matches_message,
        wiki_company_exists_for_pdf2md_info=_wiki_company_exists_for_pdf2md_info,
        is_general_assistant_request=_is_general_assistant_request,
        is_memory_management_request=agent_memory_analytics.is_memory_management_query,
        resolve_company_dir=_resolve_company_dir,
    )


def _should_consider_pdf2md_parse_only_context(message: str, context: Any | None = None) -> bool:
    return agent_runtime_parse_only._should_consider_pdf2md_parse_only_context(
        message,
        context,
        pdf2md_parse_only_matches=_pdf2md_parse_only_matches,
        is_general_assistant_request=_is_general_assistant_request,
        is_memory_management_request=agent_memory_analytics.is_memory_management_query,
        resolve_company_dir=_resolve_company_dir,
        report_fulltext_fallback_terms=REPORT_FULLTEXT_FALLBACK_TERMS,
        context_company_hint=_context_company_hint,
    )


def build_pdf2md_parse_only_context(message: str, context: Any | None = None) -> str | None:
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    return agent_runtime_parse_only.build_pdf2md_parse_only_context(
        message,
        context,
        pdf2md_parse_only_matches=_pdf2md_parse_only_matches,
        parse_only_context_limit=PDF2MD_PARSE_ONLY_CONTEXT_LIMIT,
    )


def _is_wiki_catalog_query(message: str) -> bool:
    return agent_runtime_catalog.is_wiki_catalog_query(
        message,
        is_general_assistant_request=_is_general_assistant_request,
        count_terms=WIKI_CATALOG_COUNT_TERMS,
        list_terms=WIKI_CATALOG_LIST_TERMS,
        subject_terms=WIKI_CATALOG_SUBJECT_TERMS,
    )


def _wiki_catalog_path() -> Path:
    return agent_runtime_catalog.wiki_catalog_path(wiki_root=WIKI_ROOT)


def _load_wiki_catalog_companies() -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    return agent_runtime_catalog.load_wiki_catalog_companies(
        wiki_root=WIKI_ROOT,
        read_json_file=_read_json_file,
    )


def _format_catalog_company_line(index: int, company: dict[str, Any]) -> str:
    return agent_runtime_catalog.format_catalog_company_line(index, company)


def build_wiki_catalog_reply(message: str) -> str | None:
    return agent_runtime_catalog.build_wiki_catalog_reply(
        message,
        wiki_root=WIKI_ROOT,
        is_general_assistant_request=_is_general_assistant_request,
        read_json_file=_read_json_file,
        count_terms=WIKI_CATALOG_COUNT_TERMS,
        list_terms=WIKI_CATALOG_LIST_TERMS,
        subject_terms=WIKI_CATALOG_SUBJECT_TERMS,
    )


def _latest_hermes_session(profile: HermesProfile) -> Path | None:
    return agent_runtime_diagnostics.latest_hermes_session(
        profile,
        profile_dirs=HERMES_PROFILE_DIRS,
        runtime_profile=_runtime_profile,
    )


def _profile_diagnostic_context(profile: HermesProfile, session_file: Path | None = None) -> dict[str, Any]:
    return agent_runtime_diagnostics.profile_diagnostic_context(
        profile,
        session_file,
        runtime_profile=_runtime_profile,
        profile_labels=PROFILE_LABELS,
    )


def _session_age_seconds(path: Path) -> float:
    return agent_runtime_diagnostics.session_age_seconds(path)


def _is_recent_diagnostic_session(path: Path) -> bool:
    return agent_runtime_diagnostics.is_recent_diagnostic_session(
        path,
        max_age_seconds=DIAGNOSTIC_MAX_AGE_SECONDS,
    )


def _recent_hermes_sessions(profile: HermesProfile, *, limit: int = 20) -> list[Path]:
    return agent_runtime_diagnostics.recent_hermes_sessions(
        profile,
        profile_dirs=HERMES_PROFILE_DIRS,
        runtime_profile=_runtime_profile,
        limit=limit,
    )


def _hash_text(text: str) -> str:
    return agent_runtime_dedupe._hash_text(text)


def _progress_signature(payload: dict[str, Any]) -> str:
    return _streaming_progress_signature(payload)


def normalize_plain_inline_latex(content: str | None) -> str:
    return agent_runtime_citations.normalize_plain_inline_latex(content)


def _force_rebuild_requested(message: str) -> bool:
    return agent_runtime_context.force_rebuild_requested(message, FORCE_REBUILD_TERMS)


def _analysis_completed_guard_applies(message: str) -> bool:
    return agent_runtime_context.analysis_completed_guard_applies(
        message,
        status_terms=ANALYSIS_STATUS_TERMS,
        report_terms=ANALYSIS_REPORT_TERMS,
        generation_terms=ANALYSIS_GENERATION_TERMS,
    )


def _should_use_analysis_completion_guard(message: str) -> bool:
    return agent_runtime_context.should_use_analysis_completion_guard(
        message,
        force_rebuild_terms=FORCE_REBUILD_TERMS,
        status_terms=ANALYSIS_STATUS_TERMS,
        report_terms=ANALYSIS_REPORT_TERMS,
        generation_terms=ANALYSIS_GENERATION_TERMS,
    )


def _dedupe_hash(message: str, context: Any | None) -> str:
    return agent_runtime_dedupe._dedupe_hash(message, context)


def _sync_attachment_owner_config() -> None:
    agent_runtime_attachments.CHAT_UPLOAD_ROOT = CHAT_UPLOAD_ROOT
    agent_runtime_attachments.CHAT_PDF_PARSE_ROOT = CHAT_PDF_PARSE_ROOT
    agent_runtime_attachments.CHAT_PDF_ATTACHMENT_WAIT_TIMEOUT_SECONDS = CHAT_PDF_ATTACHMENT_WAIT_TIMEOUT_SECONDS
    agent_runtime_attachments.CHAT_PDF_ATTACHMENT_WAIT_POLL_SECONDS = CHAT_PDF_ATTACHMENT_WAIT_POLL_SECONDS
    agent_runtime_attachments.ATTACHMENT_FOLLOWUP_RE = ATTACHMENT_FOLLOWUP_RE
    agent_runtime_attachments.IMAGE_MODEL_BASE_URL = IMAGE_MODEL_BASE_URL
    agent_runtime_attachments.IMAGE_MODEL_NAME = IMAGE_MODEL_NAME
    agent_runtime_attachments.IMAGE_MODEL_ENABLED = IMAGE_MODEL_ENABLED
    agent_runtime_attachments.IMAGE_MODEL_TIMEOUT_SECONDS = IMAGE_MODEL_TIMEOUT_SECONDS
    agent_runtime_attachments.MAX_DOCUMENT_CONTEXT_CHARS = MAX_DOCUMENT_CONTEXT_CHARS
    agent_runtime_attachments._IMAGE_MODEL_NAME_CACHE = _IMAGE_MODEL_NAME_CACHE


def _pull_attachment_owner_state() -> None:
    global _CHAT_MESSAGE_ATTACHMENTS_COLUMN_READY, _IMAGE_MODEL_NAME_CACHE
    _CHAT_MESSAGE_ATTACHMENTS_COLUMN_READY = agent_runtime_attachments._CHAT_MESSAGE_ATTACHMENTS_COLUMN_READY
    _IMAGE_MODEL_NAME_CACHE = agent_runtime_attachments._IMAGE_MODEL_NAME_CACHE


def _attachment_dicts(attachments: Any | None) -> list[dict[str, Any]]:
    return agent_runtime_attachments._attachment_dicts(attachments)


def _image_attachment_dicts(attachments: Any | None) -> list[dict[str, Any]]:
    return agent_runtime_attachments._image_attachment_dicts(attachments)


def _document_attachment_dicts(attachments: Any | None) -> list[dict[str, Any]]:
    return agent_runtime_attachments._document_attachment_dicts(attachments)


def _should_reuse_recent_attachments(message: str) -> bool:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._should_reuse_recent_attachments(message)


def _attachment_reference_context(attachments: Any | None) -> str:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._attachment_reference_context(attachments)


def _dedupe_hash_with_attachments(message: str, context: Any | None, attachments: Any | None) -> str:
    base_hash = agent_runtime_dedupe._dedupe_hash_with_attachments(message, context, attachments)
    return agent_runtime_financial_provenance.financial_llm_cache_key(
        base_hash,
        message=message,
        context=context,
        attachments=attachments,
    )


def _image_attachment_data_url(item: dict[str, Any]) -> str | None:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._image_attachment_data_url(item)


async def _resolve_image_model_name() -> str | None:
    _sync_attachment_owner_config()
    try:
        return await agent_runtime_attachments._resolve_image_model_name()
    finally:
        _pull_attachment_owner_state()


def _extract_openai_message_text(payload: dict[str, Any]) -> str:
    return agent_runtime_attachments._extract_openai_message_text(payload)


async def _analyze_single_image_with_primary_model(
    client: httpx.AsyncClient,
    *,
    model: str,
    message: str,
    item: dict[str, Any],
    index: int,
    total: int,
) -> str:
    _sync_attachment_owner_config()
    try:
        return await agent_runtime_attachments._analyze_single_image_with_primary_model(
            client,
            model=model,
            message=message,
            item=item,
            index=index,
            total=total,
        )
    finally:
        _pull_attachment_owner_state()


async def analyze_images_with_primary_model(
    message: str,
    attachments: Any | None,
) -> tuple[str, bool]:
    _sync_attachment_owner_config()
    try:
        return await agent_runtime_attachments.analyze_images_with_primary_model(message, attachments)
    finally:
        _pull_attachment_owner_state()


def _safe_chat_path(raw_path: str, *, must_be_file: bool = True) -> Path | None:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._safe_chat_path(raw_path, must_be_file=must_be_file)


def _safe_uploaded_path(item: dict[str, Any]) -> Path | None:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._safe_uploaded_path(item)


def _attachment_metadata(item: dict[str, Any]) -> dict[str, Any]:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._attachment_metadata(item)


def _pdf_attachment_parse_dirs(attachments: Any | None) -> list[Path]:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._pdf_attachment_parse_dirs(attachments)


def _pdf_parse_is_terminal(metadata: dict[str, Any]) -> bool:
    return agent_runtime_attachments._pdf_parse_is_terminal(metadata)


async def wait_for_pdf_attachment_parses(
    attachments: Any | None,
    *,
    timeout_seconds: int = CHAT_PDF_ATTACHMENT_WAIT_TIMEOUT_SECONDS,
    poll_seconds: int = CHAT_PDF_ATTACHMENT_WAIT_POLL_SECONDS,
) -> list[dict[str, Any]]:
    _sync_attachment_owner_config()
    try:
        return await agent_runtime_attachments.wait_for_pdf_attachment_parses(
            attachments,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
    finally:
        _pull_attachment_owner_state()


def _attachments_with_fresh_metadata(attachments: Any | None) -> list[dict[str, Any]]:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._attachments_with_fresh_metadata(attachments)


async def _ensure_chatmessage_attachments_column(async_session: AsyncSession) -> None:
    _sync_attachment_owner_config()
    try:
        await agent_runtime_attachments._ensure_chatmessage_attachments_column(async_session)
    finally:
        _pull_attachment_owner_state()


def _read_text_file(path: Path) -> str:
    return agent_runtime_attachments._read_text_file(path)


def _read_docx_text(path: Path) -> str:
    return agent_runtime_attachments._read_docx_text(path)


def _read_pdf_text_with_pdftotext(path: Path) -> str:
    return agent_runtime_attachments._read_pdf_text_with_pdftotext(path)


def _document_text_preview(item: dict[str, Any]) -> str:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._document_text_preview(item)


def _truncate_document_text(text: str, limit: int = MAX_DOCUMENT_CONTEXT_CHARS) -> str:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._truncate_document_text(text, limit)


def _document_attachment_context(attachments: Any | None) -> str:
    _sync_attachment_owner_config()
    return agent_runtime_attachments._document_attachment_context(attachments)


def _display_message_with_attachments(message: str, attachments: Any | None) -> str:
    return agent_runtime_attachments._display_message_with_attachments(message, attachments)


def _recent_duplicate_reply(profile: HermesProfile, session_id: str, message_hash: str) -> str | None:
    return agent_runtime_dedupe.recent_duplicate_reply(
        profile,
        session_id,
        message_hash,
        active_key=_active_key,
        idempotency_window_seconds=ANALYSIS_IDEMPOTENCY_WINDOW_SECONDS,
        duplicate_message=RECENT_DUPLICATE_MESSAGE,
        analysis_duplicate_message=ANALYSIS_DUPLICATE_MESSAGE,
    )


def _forget_recent_completed_run(profile: HermesProfile, session_id: str, message_hash: str | None = None) -> None:
    agent_runtime_dedupe.forget_recent_completed_run(
        profile,
        session_id,
        message_hash,
        active_key=_active_key,
    )


def _remember_completed_run(profile: HermesProfile, session_id: str, message_hash: str | None, reply: str) -> None:
    agent_runtime_dedupe.remember_completed_run(
        profile,
        session_id,
        message_hash,
        reply,
        active_key=_active_key,
    )


def normalize_evidence_trace_for_display(content: str | None) -> str:
    return agent_runtime_citations.normalize_evidence_trace_for_display(content)

def _diagnose_latest_hermes_session(profile: HermesProfile) -> dict[str, Any] | None:
    return agent_runtime_diagnostics.diagnose_latest_hermes_session(
        profile,
        profile_dirs=HERMES_PROFILE_DIRS,
        profile_labels=PROFILE_LABELS,
        wiki_root=WIKI_ROOT,
        runtime_profile=_runtime_profile,
        normalize_tool_output=_normalize_tool_output,
        detect_output_loop=_detect_output_loop,
        hash_text=_hash_text,
        max_age_seconds=DIAGNOSTIC_MAX_AGE_SECONDS,
    )


def _latest_successful_analysis_recovery() -> dict[str, Any] | None:
    return agent_runtime_diagnostics.latest_successful_analysis_recovery(
        wiki_root=WIKI_ROOT,
        profile_labels=PROFILE_LABELS,
    )


def _trim_tool_preview(value: Any, limit: int = 280) -> str:
    return agent_runtime_progress.trim_tool_preview(value, limit=limit)


def _is_file_search_tool_invocation(tool: str | None, preview: str | None = None) -> bool:
    return agent_runtime_progress.is_file_search_tool_invocation(
        tool,
        preview,
        project_wiki_root=PROJECT_WIKI_ROOT,
        wiki_root=WIKI_ROOT,
    )


def _display_tool_label(tool: str | None, preview: str | None = None) -> str:
    return agent_runtime_progress.display_tool_label(
        tool,
        preview,
        project_wiki_root=PROJECT_WIKI_ROOT,
        wiki_root=WIKI_ROOT,
    )


def get_active_run_snapshot(profile: HermesProfile, session_id: str) -> dict[str, Any]:
    return _streaming_get_active_run_snapshot(
        profile,
        session_id,
        diagnose_latest_hermes_session=_diagnose_latest_hermes_session,
    )


async def stream_active_run_events(
    request: Request,
    *,
    profile: HermesProfile,
    session_id: str,
    offset: int = 0,
) -> AsyncGenerator[dict[str, str], None]:
    async for event in _streaming_stream_active_run_events(
        request,
        profile=profile,
        session_id=session_id,
        offset=offset,
        heartbeat_seconds=STREAM_EVENT_HEARTBEAT_SECONDS,
    ):
        yield event


def normalize_history(
    messages: list[ChatMessage],
    limit: int = HISTORY_LIMIT,
    *,
    research_identity_scope: Mapping[str, Any] | None = None,
) -> list[dict]:
    return agent_runtime_history.normalize_history(
        messages,
        limit=limit,
        chat_message_has_visible_payload=chat_message_has_visible_payload,
        message_attachments=_message_attachments,
        attachment_reference_context=_attachment_reference_context,
        is_loop_polluted_assistant_message=_is_loop_polluted_assistant_message,
        normalize_evidence_trace_for_display=normalize_evidence_trace_for_display,
        sanitize_assistant_history_reply=_sanitize_assistant_history_reply,
        research_identity_scope=research_identity_scope,
    )


async def load_history(
    async_session: AsyncSession,
    session_id: str,
    *,
    limit: int = HISTORY_LIMIT,
    research_identity_scope: Mapping[str, Any] | None = None,
) -> list[dict]:
    return await agent_runtime_history.load_history(
        async_session,
        session_id,
        limit=limit,
        research_identity_scope=research_identity_scope,
        normalize_messages=lambda messages: normalize_history(messages, limit=limit),
    )


async def load_recent_session_attachments(
    async_session: AsyncSession,
    session_id: str,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    _sync_attachment_owner_config()
    return await agent_runtime_attachments.load_recent_session_attachments(
        async_session,
        session_id,
        limit=limit,
    )


def _message_attachments(message: ChatMessage) -> list[dict[str, Any]]:
    return agent_runtime_attachments._message_attachments(message)


def chat_message_has_visible_payload(message: ChatMessage) -> bool:
    return agent_runtime_attachments.chat_message_has_visible_payload(message)


async def save_message(
    async_session: AsyncSession,
    role: str,
    content: str,
    session_id: str,
    attachments: Any | None = None,
    audit_trace_id: str | None = None,
    *,
    user_id: int | None = None,
    profile: str | None = None,
    tenant_id: str | None = None,
    deal_id: str | None = None,
    project_id: str | None = None,
    visibility: str | None = None,
    research_identity: Mapping[str, Any] | None = None,
) -> None:
    normalized_research_identity = (
        agent_runtime_message_identity.normalize_research_identity_snapshot(research_identity)
    )
    if role == "assistant":
        content = _sanitize_financial_reply_for_display(
            normalize_evidence_trace_for_display(content)
        )
    attachment_items = _attachments_with_fresh_metadata(attachments)
    normalized_audit_trace_id = (
        audit_trace_id
        if role == "assistant" and agent_runtime_answer_audit.is_answer_audit_trace_id(audit_trace_id)
        else None
    )
    await _ensure_chatmessage_attachments_column(async_session)
    msg = ChatMessage(
        role=role,
        content=content,
        session_id=session_id,
        attachments_json=json.dumps(attachment_items, ensure_ascii=False) if attachment_items else None,
        audit_trace_id=normalized_audit_trace_id,
        research_identity_json=agent_runtime_message_identity.encode_research_identity_snapshot(
            normalized_research_identity
        ),
    )
    message_created_at = msg.created_at
    async_session.add(msg)
    await async_session.commit()
    context = agent_memory_service.context_from_session_id(
        session_id,
        profile=profile,
        user_id=user_id,
        tenant_id=tenant_id,
        deal_id=deal_id,
        project_id=project_id,
        visibility=visibility,
        research_identity=normalized_research_identity or None,
    )
    if context is None:
        return
    try:
        memory_message_id = await agent_memory_service.record_message(
            async_session,
            context,
            role=role,
            content=content,
            attachments=attachment_items,
            created_at=message_created_at,
            commit=False,
        )
        await agent_memory_service.maybe_promote_explicit_memory(
            async_session,
            context,
            role=role,
            content=content,
            source_id=memory_message_id,
            commit=False,
        )
        await async_session.commit()
    except Exception as exc:
        await async_session.rollback()
        if os.getenv("SIQ_AGENT_MEMORY_STRICT", "0").strip() == "1":
            raise
        print(f"[agent-memory] failed to mirror chat message for session {session_id}: {exc}")


async def chat_history_response(
    async_session: AsyncSession,
    session_id: str,
    *,
    limit: int = HISTORY_LIMIT,
) -> list[dict[str, Any]]:
    fetch_limit = max(int(limit or HISTORY_LIMIT), 1)
    result = await async_session.exec(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.desc())
        .limit(fetch_limit * 3)
    )
    return agent_runtime_display.chat_history_payload(
        result.all(),
        limit=fetch_limit,
        has_visible_payload=chat_message_has_visible_payload,
        message_payload=_chat_message_payload,
    )


def _chat_message_payload(message: ChatMessage) -> dict[str, Any]:
    return agent_runtime_display.chat_message_payload(
        message,
        message_attachments=_message_attachments,
        assistant_reply_for_display=_assistant_reply_for_display,
        normalize_evidence_trace_for_display=lambda content: _sanitize_financial_reply_for_display(
            normalize_evidence_trace_for_display(content)
        ),
    )


def _session_id_matches_profile(profile: HermesProfile, session_id: str) -> bool:
    prefix = PROFILE_SESSION_PREFIXES.get(profile)
    if prefix and session_id.startswith(prefix):
        return True
    parsed = agent_memory_service.context_from_session_id(session_id)
    if parsed is None:
        return False
    if parsed.profile == profile:
        return True
    return bool(
        str(profile).startswith("siq_ic_")
        and parsed.profile.startswith("primary-market-")
    )


def hermes_runs_session_id(profile: HermesProfile, session_id: str) -> str:
    return f"siq:{profile}:{session_id}"


def _requested_run_route(
    profile: HermesProfile,
    runtime_target: str | None,
    session_id: str,
    context: Any | None = None,
) -> HermesRunRoute | None:
    return resolve_requested_run_route(
        profile,
        runtime_target,
        session_id=session_id,
        context=context,
    )


async def _requested_run_route_with_scope_lifecycle(
    profile: HermesProfile,
    runtime_target: str | None,
    session_id: str,
    context: Any | None = None,
) -> HermesRunRoute | None:
    target = normalize_runtime_target(profile, runtime_target, session_id=session_id)
    if target == "openshell" and profile == "siq_analysis":
        try:
            await openshell_scope_lifecycle.ensure_binding(context)
        except openshell_scope_lifecycle.OpenShellScopeLifecycleError as exc:
            if runtime_target is not None or not openshell_scope_lifecycle.implicit_host_fallback_allowed(context):
                raise RuntimeError(exc.code) from exc
            logger.exception("OpenShell scope auto-provision failed; using Host fallback")
            return None
    return _requested_run_route(profile, runtime_target, session_id, context)


async def _requested_api_route(profile, runtime_target, session_id, context, *, tenant_id, user_id):
    confidential = qwen38_request_selector.confidential_request(profile)
    if confidential and runtime_target not in {None, "openshell"}:
        raise qwen38_request_selector.RequestSelectionError("qwen_request_confidential_route_required")
    selected = await qwen38_request_selector.select(profile=profile, requested_target=runtime_target,
        session_id=session_id, context=context, tenant_id=tenant_id, user_id=user_id)
    if selected is not None:
        await _bind_host_retrieval_scope(selected, tenant_id=tenant_id, user_id=user_id)
        return selected
    route = await _requested_run_route_with_scope_lifecycle(profile, runtime_target, session_id, context)
    if confidential and (route is None or route.target != "openshell"):
        raise qwen38_request_selector.RequestSelectionError("qwen_request_confidential_route_required")
    await _bind_host_retrieval_scope(route, tenant_id=tenant_id, user_id=user_id)
    return route


async def _bind_host_retrieval_scope(route, *, tenant_id, user_id):
    if not confidential_auxiliary_models.required():
        return
    if isinstance(route, qwen38_request_selector.RequestSelection):
        # Selection has just verified the live grant for this exact principal.
        if (route.tenant_id, route.user_id) != (tenant_id, user_id):
            raise agent_runtime_host_scope.HostRetrievalDenied("host_retrieval_principal_mismatch")
        verified = route.authorized.scope_ref
        project = qwen38_request_selector.builder.runtime.ROOT
    else:
        if route is None or route.target != "openshell" or route.pool_binding is None:
            raise agent_runtime_host_scope.HostRetrievalDenied("host_retrieval_scope_missing")
        project = PROJECT_ROOT
        market, company = str(route.pool_market or "").lower(), str(route.pool_company or "")
        project_id = "company:" + route.pool_binding.scope_id
        authorized = openshell_data_scope.issue_authorized_scope(
            tenant_id=tenant_id, user_id=user_id, project_id=project_id,
            market=market, company_directory=company, data_classification="confidential_local",
            object_scopes=("company_wiki", "public_market_data"),
        )
        verified = openshell_data_scope.revalidate_authorized_scope(
            authorized, tenant_id=tenant_id, user_id=user_id, project_id=project_id,
            market=market, company_directory=company,
        )
        async with AsyncSession(async_engine) as business_session:
            await openshell_data_scope.require_live_confidential_scope(business_session, verified, user_id=user_id)
    if verified.data_classification != "confidential_local" or not verified.permits("company_wiki"):
        raise agent_runtime_host_scope.HostRetrievalDenied("host_retrieval_scope_denied")
    roots = qwen38_request_selector.builder.runtime.mounts.COMPANY_ROOTS
    agent_runtime_host_scope.bind(project / roots[verified.market] / verified.company_directory,
        market=verified.market, company_id=verified.company_id,
        public_market_data=verified.permits("public_market_data"))


async def _acquire_pool_route(
    route: HermesRunRoute | None,
    *,
    session_id: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> HermesRunRoute | None:
    if qwen38_request_api.handles(route):
        if (tenant_id is None or user_id is None
                or not await qwen38_request_api.current(route, session_id=session_id,
                    tenant_id=str(tenant_id), user_id=str(user_id))):
            raise RuntimeError("qwen_request_api_admission_denied")
        return route
    if route is None or route.pool_binding is None:
        return route
    if tenant_id is None or user_id is None:
        raise RuntimeError("openshell_pool_principal_incomplete")
    tenant_id = str(tenant_id).strip()
    user_id = str(user_id).strip()
    if (
        not tenant_id
        or len(tenant_id.encode("utf-8")) > 512
        or any(ord(character) < 0x20 for character in tenant_id)
        or re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", user_id) is None
    ):
        raise RuntimeError("openshell_pool_principal_invalid")
    if not session_id.startswith(f"user-{user_id}-analysis-"):
        raise RuntimeError("openshell_pool_principal_session_mismatch")
    from services import openshell_pool_recovery

    if (
        openshell_pool_recovery.recovery_required()
        and not openshell_pool_recovery.recovery_ready()
    ):
        raise RuntimeError("openshell_pool_recovery_not_ready")
    try:
        admission = await openshell_pool_adapter.acquire_wait_async(
            route.pool_binding,
            session_id=session_id,
            tenant_id=tenant_id,
            user_id=user_id,
            timeout_seconds=float(
                _env_int("SIQ_OPENSHELL_POOL_WAIT_SECONDS", 1800, minimum=1)
            ),
            poll_interval=0.25,
        )
    except openshell_pool_adapter.OpenShellPoolAdapterError as exc:
        raise RuntimeError(exc.code) from exc
    if (
        admission.status != "active"
        or admission.target != "openshell"
        or admission.run_id != route.canary_run_id
        or not admission.api_key
        or not admission.session_namespace
        or not admission.owner_token
        or admission.owner_generation < 1
    ):
        raise RuntimeError("openshell_pool_admission_invalid")
    market = str(admission.market or route.pool_market or "").strip().lower()
    company = str(admission.company or route.pool_company or "").strip()
    classification = os.getenv("SIQ_OPENSHELL_DATA_CLASSIFICATION", "public_research").strip()
    leased_route = replace(
        route,
        pool_lease_id=admission.lease_id,
        pool_owner_token=admission.owner_token,
        pool_owner_generation=admission.owner_generation,
        pool_tenant_id=tenant_id,
        pool_user_id=user_id,
    )
    try:
        authorized_scope = openshell_data_scope.issue_authorized_scope(
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=f"company:{admission.scope_id}",
            market=market,
            company_directory=company,
            data_classification=classification,
            object_scopes=("company_wiki", "public_market_data"),
        )
        verified_scope = openshell_data_scope.revalidate_authorized_scope(
            authorized_scope,
            tenant_id=tenant_id,
            user_id=user_id,
            project_id=f"company:{admission.scope_id}",
            market=market,
            company_directory=company,
        )
        if verified_scope.data_classification == "confidential_local":
            async with AsyncSession(async_engine) as business_session:
                await openshell_data_scope.require_live_confidential_scope(
                    business_session, verified_scope, user_id=user_id
                )
        governed_route = governed_model_route.load_manifest(
            PROJECT_ROOT / "infra/model-services/governed-model-routes.json",
            data_classification=verified_scope.data_classification,
        )
    except (
        openshell_data_scope.DataScopeAuthorizationError,
        governed_model_route.GovernedModelRouteError,
    ) as exc:
        await _release_pool_route(
            leased_route, session_id=session_id, terminal_confirmed=True
        )
        raise RuntimeError(str(exc)) from exc
    except BaseException as exc:
        # Admission already reserved a writer, but Hermes creation has not
        # begun. Cancellation/driver failures must release that reservation.
        await _release_pool_route(
            leased_route, session_id=session_id, terminal_confirmed=True
        )
        if not isinstance(exc, Exception):
            raise
        raise RuntimeError("openshell_pool_authorization_unavailable") from None
    return replace(
        route,
        base=admission.base,
        authorization=f"Bearer {admission.api_key}",
        session_namespace=admission.session_namespace,
        pool_lease_id=admission.lease_id,
        pool_owner_token=admission.owner_token,
        pool_owner_generation=admission.owner_generation,
        pool_tenant_id=tenant_id,
        pool_user_id=user_id,
        pool_write_relative_path=admission.write_relative_path,
        data_scope_ref_sha256=verified_scope.digest,
        authorization_snapshot_sha256=authorized_scope.snapshot_sha256,
        data_authorization=authorized_scope,
        pool_market=market,
        pool_company=company,
        data_classification=verified_scope.data_classification,
        model_route_alias=governed_route.alias,
        model_route_sha256=governed_route.route_sha256,
    )


async def _pool_route_authorization_current(route: HermesRunRoute, *, session_id: str) -> bool:
    """Recheck the original scope and live authority before renewing/creating."""
    if qwen38_request_api.handles(route):
        return await qwen38_request_api.current(route, session_id=session_id)
    authorized = route.data_authorization
    if authorized is None:
        # Historical unscoped public routes remain compatible. A scoped route
        # or a confidential deployment cannot recover authority from digests.
        return (
            route.data_classification is None
            and route.data_scope_ref_sha256 is None
            and route.authorization_snapshot_sha256 is None
            and os.getenv("SIQ_OPENSHELL_DATA_CLASSIFICATION", "public_research").strip() == "public_research"
        )

    async def recheck() -> bool:
        if (
            not isinstance(authorized, openshell_data_scope.AuthorizedDataScope)
            or route.pool_binding is None
            or not route.pool_tenant_id
            or not route.pool_user_id
            or not route.pool_market
            or not route.pool_company
            or not session_id.startswith(f"user-{route.pool_user_id}-analysis-")
        ):
            return False
        if (
            route.pool_binding.market != route.pool_market
            or route.pool_binding.company != route.pool_company
            or route.pool_binding.run_id != route.canary_run_id
        ):
            return False
        scope = openshell_data_scope.revalidate_authorized_scope(
            authorized,
            tenant_id=route.pool_tenant_id,
            user_id=route.pool_user_id,
            project_id=f"company:{route.pool_binding.scope_id}",
            market=route.pool_market,
            company_directory=route.pool_company,
        )
        if (
            scope.digest != route.data_scope_ref_sha256
            or authorized.snapshot_sha256 != route.authorization_snapshot_sha256
            or scope.data_classification != route.data_classification
        ):
            return False
        if scope.data_classification == "confidential_local":
            async with AsyncSession(async_engine) as session:
                await openshell_data_scope.require_live_confidential_scope(
                    session, scope, user_id=route.pool_user_id
                )
        return True

    try:
        return await asyncio.wait_for(recheck(), timeout=10)
    except Exception:
        # Database/driver exceptions may contain URLs or bound values. Keep
        # diagnostics categorical; cancellation still propagates normally.
        logger.warning("OpenShell business authorization recheck failed")
        return False


async def _heartbeat_pool_route(route: HermesRunRoute | None, *, session_id: str) -> bool:
    if qwen38_request_api.handles(route):
        # The durable heartbeat already renews the exact original execution row.
        return await qwen38_request_api.current(route, session_id=session_id)
    if route is None or route.pool_binding is None:
        return True
    if (
        not route.pool_lease_id
        or not route.pool_owner_token
        or not route.pool_owner_generation
    ):
        return False
    if not await _pool_route_authorization_current(route, session_id=session_id):
        return False
    try:
        admission = await openshell_pool_adapter.heartbeat_async(
            route.pool_binding,
            session_id=session_id,
            tenant_id=route.pool_tenant_id,
            user_id=route.pool_user_id,
            owner_token=route.pool_owner_token,
            owner_generation=route.pool_owner_generation,
        )
    except openshell_pool_adapter.OpenShellPoolAdapterError:
        logger.exception("OpenShell pool heartbeat failed")
        return False
    return bool(
        admission.status == "active"
        and admission.run_bound
        and admission.run_id == route.canary_run_id
        and admission.lease_id == route.pool_lease_id
    )


async def _mark_pool_route_bound(
    route: HermesRunRoute | None,
    *,
    session_id: str,
) -> HermesRunRoute | None:
    if qwen38_request_api.handles(route):
        if not await qwen38_request_api.current(route, session_id=session_id):
            raise RuntimeError("qwen_request_api_binding_lost")
        return route
    if (
        route is None
        or route.pool_binding is None
        or not route.pool_lease_id
        or not route.pool_owner_token
        or not route.pool_owner_generation
    ):
        return route
    try:
        admission = await openshell_pool_adapter.mark_run_bound_async(
            route.pool_binding,
            session_id=session_id,
            tenant_id=route.pool_tenant_id,
            user_id=route.pool_user_id,
            owner_token=route.pool_owner_token,
            owner_generation=route.pool_owner_generation,
        )
    except openshell_pool_adapter.OpenShellPoolAdapterError as exc:
        raise RuntimeError(exc.code) from exc
    if (
        admission.status != "active"
        or not admission.run_bound
        or admission.lease_id != route.pool_lease_id
        or admission.owner_generation != route.pool_owner_generation
        or admission.run_id != route.canary_run_id
    ):
        raise RuntimeError("openshell_pool_run_bind_invalid")
    return route


async def _active_run_ownership_is_current(state: ActiveRunState) -> bool:
    """Fence postprocessing and child runs against restart/worker takeover."""

    if qwen38_request_api.handles(state.run_route):
        return await _renew_durable_active_run(state)
    if state.run_route is None or not state.run_route.pool_lease_id:
        return True
    if not state.owner_id:
        return False
    durable_ok = await _renew_durable_active_run(state)
    if not durable_ok:
        return False
    return await _heartbeat_pool_route(state.run_route, session_id=state.session_id)


async def _release_pool_route(
    route: HermesRunRoute | None,
    *,
    session_id: str,
    terminal_confirmed: bool,
) -> bool:
    if qwen38_request_api.handles(route):
        return await qwen38_request_api.release(route, session_id=session_id)
    if (
        route is None
        or route.pool_binding is None
        or not route.pool_lease_id
        or not route.pool_owner_token
        or not route.pool_owner_generation
    ):
        return True
    try:
        return await openshell_pool_adapter.release_async(
            session_id=session_id,
            tenant_id=route.pool_tenant_id,
            user_id=route.pool_user_id,
            owner_token=route.pool_owner_token,
            owner_generation=route.pool_owner_generation,
            terminal_confirmed=terminal_confirmed,
        )
    except openshell_pool_adapter.OpenShellPoolAdapterError:
        # A failed release leaves the company slot occupied/orphaned, which is
        # safer than admitting a second writer.
        logger.exception("OpenShell pool release failed")
        return False


def _routed_hermes_session_id(
    profile: HermesProfile,
    session_id: str,
    route: HermesRunRoute | None,
) -> str:
    if route is None:
        return hermes_runs_session_id(profile, session_id)
    return route_session_id(route, profile, session_id)


class _PoolRouteAuthorizationLost(RuntimeError):
    """Known pre-dispatch denial: no Hermes create request has been sent."""


async def _create_routed_run(
    run_input: str | list[dict[str, Any]],
    history: list[dict[str, Any]],
    *,
    profile: HermesProfile,
    session_id: str,
    route: HermesRunRoute | None,
) -> tuple[str, HermesRunRoute | None]:
    if (
        route is not None
        and (qwen38_request_api.handles(route) or route.pool_binding is not None)
        and not await _pool_route_authorization_current(route, session_id=session_id)
    ):
        raise _PoolRouteAuthorizationLost("openshell_pool_authorization_lost")
    routed_session_id = _routed_hermes_session_id(profile, session_id, route)
    if route is None:
        run_id = await create_run(
            run_input,
            history,
            profile=profile,
            session_id=routed_session_id,
        )
    else:
        # Never replay an OpenShell request on Host. Even a pre-connect failure
        # must remain visible so policy/runtime faults cannot be masked by an
        # unsandboxed execution. Operators roll back through the owner-only
        # runtime selector.
        run_id = await create_run(
            run_input,
            history,
            profile=profile,
            session_id=routed_session_id,
            route=route,
        )
    return run_id, route


async def _collect_routed_run_result(
    run_id: str,
    *,
    profile: HermesProfile,
    timeout: float | httpx.Timeout | None,
    route: HermesRunRoute | None,
) -> str:
    discard_run_terminal_result(run_id)
    if route is None:
        return await collect_run_result(run_id, profile=profile, timeout=timeout)
    return await collect_run_result(run_id, profile=profile, timeout=timeout, route=route)


def _stream_routed_run(
    run_id: str,
    *,
    profile: HermesProfile,
    timeout: float | httpx.Timeout | None,
    route: HermesRunRoute | None,
) -> AsyncGenerator[Any, None]:
    if route is None:
        return stream_run(run_id, profile=profile, timeout=timeout)
    return stream_run(run_id, profile=profile, timeout=timeout, route=route)


async def _stop_routed_run(
    run_id: str,
    *,
    profile: HermesProfile,
    route: HermesRunRoute | None,
) -> dict[str, Any]:
    if route is None:
        return await stop_run(run_id, profile=profile)
    return await stop_run(run_id, profile=profile, route=route)


async def _get_routed_run_status(
    run_id: str,
    *,
    profile: HermesProfile,
    route: HermesRunRoute | None,
) -> HermesRunStatus:
    if route is None:
        return await get_run_status(run_id, profile=profile)
    return await get_run_status(run_id, profile=profile, route=route)


async def _wait_routed_run_write_quiesced(
    run_id: str,
    *,
    profile: HermesProfile,
    route: HermesRunRoute | None,
    timeout_seconds: float | None = None,
) -> bool:
    """Require a pinned Hermes receipt that its executor can no longer write."""

    if route is None or not route.pool_lease_id:
        return False
    timeout = timeout_seconds
    if timeout is None:
        timeout = float(_env_int("SIQ_HERMES_STOP_CONFIRM_SECONDS", 15, minimum=1, maximum=120))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            status = await _get_routed_run_status(run_id, profile=profile, route=route)
        except (httpx.HTTPError, RuntimeError):
            status = None
        if status is not None and status.write_quiesced:
            return True
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        await asyncio.sleep(min(0.25, remaining))


async def _stop_and_confirm_routed_run(
    run_id: str,
    *,
    profile: HermesProfile,
    route: HermesRunRoute | None,
    timeout_seconds: float | None = None,
) -> bool:
    """Request stop, then independently prove executor quiescence."""

    if qwen38_request_api.handles(route):
        try:
            binding = qwen38_request_api.context(route, profile=profile,
                session_id=route.request_http.execution_binding.session_id).execution_binding
        except Exception:
            return False
        # The request owns one sandbox: stop its whole execution domain. HTTP
        # requests require live authority and cannot implement revoked cleanup.
        return await qwen38_request_api.contain(route, profile=profile, session_id=binding.session_id)

    try:
        await _stop_routed_run(run_id, profile=profile, route=route)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code != 404:
            logger.debug("failed to request Hermes run stop", exc_info=True)
    except Exception:
        logger.debug("failed to request Hermes run stop", exc_info=True)
    if route is None or not route.pool_lease_id:
        return False
    return await _wait_routed_run_write_quiesced(
        run_id,
        profile=profile,
        route=route,
        timeout_seconds=timeout_seconds,
    )


async def _release_provisional_durable_claim(
    profile: HermesProfile,
    session_id: str,
    provisional_run_id: str,
    owner_id: str,
    *,
    run_id: str | None = None,
    status: str = "failed",
) -> None:
    """Release either side of a bind whose commit result may be uncertain."""

    candidates = [run_id, provisional_run_id] if run_id else [provisional_run_id]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            released = await _release_durable_lease(
                profile,
                session_id,
                candidate,
                owner_id,
                status=status,
            )
        except Exception:
            logger.exception("failed to release provisional durable run claim")
            continue
        if released:
            return


async def _claim_create_and_bind_routed_run(
    run_input: str | list[dict[str, Any]],
    history: list[dict[str, Any]],
    *,
    profile: HermesProfile,
    session_id: str,
    route: HermesRunRoute | None,
    provisional_claim: DurableProvisionalClaim | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> tuple[str, HermesRunRoute | None, str] | None:
    """Own the session before pool admission and clean up every uncertain stage."""

    claim = provisional_claim
    if isinstance(route, qwen38_request_selector.RequestSelection):
        route = await qwen38_request_selector.activate(route, claim, profile=profile,
            session_id=session_id, tenant_id=tenant_id, user_id=user_id)
    if qwen38_request_api.handles(route):
        if (claim is None or claim.profile != profile or claim.session_id != session_id
                or not await qwen38_request_api.current(route, profile=profile,
                    session_id=session_id, owner_id=claim.owner_id, run_id=claim.provisional_run_id)):
            raise RuntimeError("qwen_request_api_original_claim_required")
    if claim is None:
        claim = await _acquire_durable_provisional_claim(profile, session_id)
        if claim is None:
            return None
    elif claim.profile != profile or claim.session_id != session_id:
        await _release_provisional_durable_claim(
            claim.profile,
            claim.session_id,
            claim.provisional_run_id,
            claim.owner_id,
        )
        raise RuntimeError("durable_provisional_claim_scope_mismatch")

    acquired_route = route
    creation_started = False
    pool_bound = False
    run_id: str | None = None

    async def renew_startup() -> bool:
        if qwen38_request_api.handles(acquired_route):
            return await qwen38_request_api.renew(acquired_route, profile=profile,
                session_id=session_id, owner_id=claim.owner_id, run_id=claim.provisional_run_id)
        if pool_bound and not await _heartbeat_pool_route(acquired_route, session_id=session_id):
            return False
        return await _renew_durable_provisional_claim(claim)

    async def acquire_and_create(checkpoint: Callable[[], Awaitable[None]]) -> None:
        nonlocal acquired_route, pool_bound, creation_started, run_id
        pool_principal_kwargs = {}
        if tenant_id is not None:
            pool_principal_kwargs["tenant_id"] = tenant_id
        if user_id is not None:
            pool_principal_kwargs["user_id"] = user_id
        acquired_route = await _acquire_pool_route(
            route,
            session_id=session_id,
            **pool_principal_kwargs,
        )
        if not await _attach_durable_pool_lease(claim, acquired_route):
            raise RuntimeError("openshell_pool_durable_attach_failed")
        acquired_route = await _mark_pool_route_bound(acquired_route, session_id=session_id)
        # Fence ownership after potentially long admission, before any create.
        await checkpoint()
        pool_bound = True
        creation_started = True
        run_id, acquired_route = await _create_routed_run(
            run_input,
            history,
            profile=profile,
            session_id=session_id,
            route=acquired_route,
        )

    try:
        await run_guarded_startup(
            acquire_and_create,
            renew_startup,
            interval=30 if qwen38_request_api.handles(route) else min(60, max(1, lease_seconds() // 3)),
        )
        assert run_id is not None
        bound = (await qwen38_request_api.bind(acquired_route, claim, run_id)
                 if qwen38_request_api.handles(acquired_route)
                 else await _bind_durable_active_run(
                     profile, session_id, claim.provisional_run_id, run_id, claim.owner_id))
        if bound:
            return run_id, acquired_route, claim.owner_id

        terminal_confirmed = await _stop_and_confirm_routed_run(
            run_id,
            profile=profile,
            route=acquired_route,
        )
        if qwen38_request_api.handles(acquired_route):
            await qwen38_request_api.finish(acquired_route, profile=profile, session_id=session_id,
                owner_id=claim.owner_id, run_ids=(claim.provisional_run_id, run_id), status="failed")
            return None
        await _release_provisional_durable_claim(
            profile,
            session_id,
            claim.provisional_run_id,
            claim.owner_id,
            run_id=run_id,
        )
        await _release_pool_route(
            acquired_route,
            session_id=session_id,
            terminal_confirmed=terminal_confirmed,
        )
        return None
    except BaseException as exc:
        terminal_confirmed = not creation_started or isinstance(exc, _PoolRouteAuthorizationLost)
        if run_id is not None:
            try:
                terminal_confirmed = await _stop_and_confirm_routed_run(
                    run_id,
                    profile=profile,
                    route=acquired_route,
                )
            except BaseException:
                terminal_confirmed = False
        if qwen38_request_api.handles(acquired_route):
            await qwen38_request_api.finish(acquired_route, profile=profile, session_id=session_id,
                owner_id=claim.owner_id,
                run_ids=tuple(value for value in (claim.provisional_run_id, run_id) if value), status="failed")
            raise
        await _release_provisional_durable_claim(
            profile,
            session_id,
            claim.provisional_run_id,
            claim.owner_id,
            run_id=run_id,
        )
        await _release_pool_route(
            acquired_route,
            session_id=session_id,
            terminal_confirmed=terminal_confirmed,
        )
        raise


def _strip_local_memory_blocks(text: str) -> str:
    return agent_runtime_memory._strip_local_memory_blocks(text)


def _compact_memory_content(role: str, content: str, *, max_chars: int = LOCAL_MEMORY_SNIPPET_CHARS) -> str:
    return agent_runtime_memory._compact_memory_content(
        role,
        content,
        max_chars=max_chars,
        is_loop_polluted_assistant_message=_is_loop_polluted_assistant_message,
        sanitize_assistant_history_reply=_sanitize_assistant_history_reply,
    )


def _local_memory_turn_line(user_text: str, assistant_text: str | None) -> str:
    return agent_runtime_memory._local_memory_turn_line(user_text, assistant_text)


def build_local_memory_summary(
    messages: list[ChatMessage],
    *,
    max_bullets: int = LOCAL_MEMORY_MAX_BULLETS,
    max_chars: int = LOCAL_MEMORY_MAX_CHARS,
) -> str:
    return agent_runtime_memory.build_local_memory_summary(
        messages,
        max_bullets=max_bullets,
        max_chars=max_chars,
        snippet_chars=LOCAL_MEMORY_SNIPPET_CHARS,
        is_loop_polluted_assistant_message=_is_loop_polluted_assistant_message,
        sanitize_assistant_history_reply=_sanitize_assistant_history_reply,
    )


def build_local_memory_context(summary: str | None) -> str | None:
    return agent_runtime_memory.build_local_memory_context(summary)


async def _load_session_memory_record(
    async_session: AsyncSession,
    profile: HermesProfile,
    session_id: str,
) -> ChatSessionMemory | None:
    return await agent_runtime_memory.load_session_memory_record(
        async_session,
        profile,
        session_id,
    )


async def refresh_session_memory(
    async_session: AsyncSession,
    profile: HermesProfile,
    session_id: str,
    *,
    recent_limit: int = LOCAL_MEMORY_RECENT_LIMIT,
    request_context: Any | None = None,
) -> None:
    await agent_runtime_memory.refresh_session_memory(
        async_session,
        profile,
        session_id,
        recent_limit=recent_limit,
        local_memory_enabled=LOCAL_MEMORY_ENABLED,
        enabled_profiles=LOCAL_MEMORY_ENABLED_PROFILES,
        session_id_matches_profile=_session_id_matches_profile,
        build_summary=build_local_memory_summary,
        request_context=request_context,
        load_record=_load_session_memory_record,
    )


def _chat_memory_save_kwargs(
    profile: HermesProfile,
    context: Any | None,
) -> dict[str, Any]:
    if primary_market_agent_runtime.is_primary_market_ic_runtime(profile, context):
        return agent_runtime_memory.memory_context_kwargs(profile, context)
    identity = agent_runtime_context.research_identity(context)
    return {"research_identity": identity} if identity else {}


async def _refresh_session_memory_for_request(
    async_session: AsyncSession,
    profile: HermesProfile,
    session_id: str,
    context: Any | None,
) -> None:
    if primary_market_agent_runtime.is_primary_market_ic_runtime(profile, context):
        await refresh_session_memory(
            async_session,
            profile,
            session_id,
            request_context=context,
        )
        return
    await refresh_session_memory(async_session, profile, session_id)


async def load_local_memory_context(
    async_session: AsyncSession,
    profile: HermesProfile,
    session_id: str,
) -> str | None:
    return await agent_runtime_memory.load_local_memory_context(
        async_session,
        profile,
        session_id,
        local_memory_enabled=LOCAL_MEMORY_ENABLED,
        enabled_profiles=LOCAL_MEMORY_ENABLED_PROFILES,
        session_id_matches_profile=_session_id_matches_profile,
        load_record=_load_session_memory_record,
        build_context=build_local_memory_context,
    )


async def ensure_local_memory_context(
    async_session: AsyncSession,
    profile: HermesProfile,
    session_id: str,
    *,
    request_context: Any | None = None,
) -> str | None:
    return await agent_runtime_memory.ensure_local_memory_context(
        async_session,
        profile,
        session_id,
        request_context=request_context,
        refresh_memory=refresh_session_memory,
        load_context=load_local_memory_context,
    )


async def ensure_agent_memory_context(
    async_session: AsyncSession,
    profile: HermesProfile,
    session_id: str,
    message: str,
    *,
    research_context: Any | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> str | None:
    research_kwargs = {"research_context": research_context} if research_context is not None else {}
    if tenant_id is not None or user_id is not None:
        research_kwargs.update(tenant_id=tenant_id, user_id=user_id)
    return await agent_runtime_memory.ensure_agent_memory_context(
        async_session,
        profile,
        session_id,
        message,
        min_query_chars=_env_int("SIQ_AGENT_MEMORY_MIN_QUERY_CHARS", 4, minimum=0),
        retrieval_budget_ms=_env_int("SIQ_AGENT_MEMORY_RETRIEVAL_BUDGET_MS", 1200, minimum=100),
        strict=_env_bool("SIQ_AGENT_MEMORY_STRICT", False),
        **research_kwargs,
    )


async def save_message_in_background(
    role: str,
    content: str,
    session_id: str,
    *,
    profile: HermesProfile | None = None,
    audit_trace_id: str | None = None,
    research_identity: Mapping[str, Any] | None = None,
    request_context: Any | None = None,
    refresh_local_memory: bool = True,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> None:
    async with AsyncSession(async_engine) as async_session:
        memory_kwargs = (
            agent_runtime_memory.memory_context_kwargs(profile, request_context)
            if profile
            and primary_market_agent_runtime.is_primary_market_ic_runtime(
                profile,
                request_context,
            )
            else {}
        )
        if research_identity:
            memory_kwargs["research_identity"] = research_identity
        if tenant_id is not None or user_id is not None:
            memory_kwargs.update(agent_runtime_memory.verified_memory_principal(session_id, tenant_id, user_id))
        await save_message(
            async_session,
            role,
            content,
            session_id,
            audit_trace_id=audit_trace_id,
            **memory_kwargs,
        )
        if role == "assistant" and profile and refresh_local_memory:
            await _refresh_session_memory_for_request(
                async_session,
                profile,
                session_id,
                request_context,
            )


def _clean_context_value(value: Any) -> str:
    return agent_runtime_context.clean_context_value(value)


def _context_dict(context: Any | None) -> dict[str, Any]:
    return agent_runtime_context.context_dict(context)


def _context_company(context: Any | None) -> dict[str, Any]:
    return agent_runtime_context.context_company(context)


def _analysis_completed_artifacts(context: Any | None) -> dict[str, str] | None:
    return agent_runtime_context.analysis_completed_artifacts(
        context,
        read_json_file=_read_json_file,
        wiki_root=WIKI_ROOT,
    )


def _analysis_completion_reply(context: Any | None) -> str | None:
    return agent_runtime_context.analysis_completion_reply(
        context,
        analysis_completed_artifacts=_analysis_completed_artifacts,
        analysis_completed_message=ANALYSIS_COMPLETED_MESSAGE,
    )


def _analysis_completion_guard_input(message: str, artifacts: dict[str, str]) -> str:
    return agent_runtime_context.analysis_completion_guard_input(message, artifacts)


def _is_general_assistant_request(message: str) -> bool:
    return agent_runtime_context.is_general_assistant_request(
        message,
        request_terms=GENERAL_ASSISTANT_REQUEST_TERMS,
        subject_terms=GENERAL_ASSISTANT_SUBJECT_TERMS,
    )


def _is_note_detail_query(message: str) -> bool:
    return agent_runtime_context.note_detail_query_applies(
        message,
        note_detail_query_terms=NOTE_DETAIL_QUERY_TERMS,
        note_detail_exclude_terms=NOTE_DETAIL_EXCLUDE_TERMS,
        financial_note_metric_terms=FINANCIAL_NOTE_METRIC_TERMS,
        statement_terms=STATEMENT_QUERY_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
    )


def _should_direct_answer_note_detail(message: str) -> bool:
    return agent_runtime_context.direct_note_detail_answer_applies(
        message,
        note_detail_query_terms=NOTE_DETAIL_QUERY_TERMS,
        note_detail_exclude_terms=NOTE_DETAIL_EXCLUDE_TERMS,
        note_detail_direct_terms=NOTE_DETAIL_DIRECT_TERMS,
        note_detail_analysis_terms=NOTE_DETAIL_ANALYSIS_TERMS,
        financial_note_metric_terms=FINANCIAL_NOTE_METRIC_TERMS,
        statement_terms=STATEMENT_QUERY_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
    )


def _is_financial_note_metric_query(message: str) -> bool:
    return agent_runtime_context.financial_note_metric_query_applies(
        message,
        note_detail_query_terms=NOTE_DETAIL_QUERY_TERMS,
        note_detail_exclude_terms=NOTE_DETAIL_EXCLUDE_TERMS,
        financial_note_metric_terms=FINANCIAL_NOTE_METRIC_TERMS,
        financial_evidence_action_terms=FINANCIAL_EVIDENCE_ACTION_TERMS,
        statement_terms=STATEMENT_QUERY_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
    )


def _should_inject_note_detail_context(message: str) -> bool:
    return agent_runtime_context.note_detail_context_applies(
        message,
        note_detail_query_terms=NOTE_DETAIL_QUERY_TERMS,
        note_detail_exclude_terms=NOTE_DETAIL_EXCLUDE_TERMS,
        financial_note_metric_terms=FINANCIAL_NOTE_METRIC_TERMS,
        financial_evidence_action_terms=FINANCIAL_EVIDENCE_ACTION_TERMS,
        statement_terms=STATEMENT_QUERY_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
    )


def _is_statement_query(message: str) -> bool:
    return agent_runtime_context.statement_query_with_goodwill_applies(
        message,
        statement_terms=STATEMENT_QUERY_TERMS,
        goodwill_main_statement_terms=GOODWILL_MAIN_STATEMENT_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
    )


def _is_goodwill_main_statement_query(message: str | None) -> bool:
    return agent_runtime_context.goodwill_main_statement_query_applies(
        message,
        goodwill_main_statement_terms=GOODWILL_MAIN_STATEMENT_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
    )


def _should_direct_answer_statement_query(message: str) -> bool:
    return agent_runtime_context.direct_statement_answer_with_goodwill_applies(
        message,
        statement_terms=STATEMENT_QUERY_TERMS,
        statement_direct_terms=STATEMENT_DIRECT_TERMS,
        note_detail_analysis_terms=NOTE_DETAIL_ANALYSIS_TERMS,
        goodwill_main_statement_terms=GOODWILL_MAIN_STATEMENT_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
    )


def _context_company_hint(context: Any | None) -> str:
    return agent_runtime_context.context_company_hint(context)


def _forced_context_company_dir(context: Any | None) -> Path | None:
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        return bound
    raw = _context_dict(context)
    company = raw.get("company") if isinstance(raw.get("company"), dict) else {}
    candidate = company.get("dir") if raw.get("force_company") else None
    if candidate:
        try:
            path = Path(str(candidate)).resolve()
        except OSError:
            return None
        for root in _candidate_wiki_roots():
            try:
                resolved_root = root.resolve()
            except OSError:
                continue
            if path != resolved_root and resolved_root in path.parents and path.exists():
                relative = path.relative_to(resolved_root)
                if "companies" in relative.parts:
                    return path
        return None
    return agent_runtime_context.forced_context_company_dir(context, wiki_root=WIKI_ROOT)


def _normalize_financial_text(value: Any) -> str:
    return re.sub(r"[\s（）()_\-：:、,，;；/.。]+", "", str(value or "").lower())


def _wiki_root_path() -> Path:
    if hasattr(WIKI_ROOT, "_path"):
        try:
            return WIKI_ROOT._path()
        except Exception:
            pass
    return Path(WIKI_ROOT)


def _candidate_wiki_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    base_roots = (_wiki_root_path(), PROJECT_WIKI_ROOT, ASSISTANT_WIKI_ROOT, *WIKI_FALLBACK_ROOTS)
    market_roots = (
        market_root
        for base_root in base_roots
        for market_root in agent_runtime_catalog.market_wiki_roots(wiki_root=base_root).values()
    )
    for root in (*base_roots, *market_roots):
        candidate = Path(root).expanduser()
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "companies").exists():
            roots.append(candidate)
    return roots


def _resolve_company_path_across_wiki_roots(rel_path: Any) -> Path | None:
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        relative = str(rel_path or "").strip()
        candidates = {bound.as_posix(), bound.name, bound.relative_to(PROJECT_ROOT).as_posix(),
                      bound.relative_to(PROJECT_ROOT / "data/wiki").as_posix()}
        return bound if relative in candidates else None
    rel = str(rel_path or "").strip().lstrip("/")
    if not rel:
        return None
    for root in _candidate_wiki_roots():
        company_dir = root / rel
        if company_dir.exists():
            return company_dir
    return None


def _load_local_citation_module() -> Any | None:
    try:
        return _configure_wiki_module(
            importlib.import_module("siq_wiki_evidence.local_citations")
        )
    except Exception:
        return None


def _resolve_company_dir(message: str, context: Any | None = None) -> Path | None:
    if _is_general_assistant_request(message):
        return None
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        return bound
    forced_company_dir = _forced_context_company_dir(context)
    if forced_company_dir:
        return forced_company_dir
    identity_market = str(agent_runtime_context.research_identity(context).get("market") or "").upper()
    requested_markets = agent_runtime_catalog.requested_catalog_markets(message)
    explicit_non_cn_market = (
        identity_market not in {"", "CN"}
        or (
            requested_markets != agent_runtime_catalog.MARKET_ORDER
            and "CN" not in requested_markets
        )
    )
    if explicit_non_cn_market:
        # The legacy local-citation resolver is rooted in the A-share Wiki and
        # can treat short foreign tickers such as BA/CAT as CN aliases.  An
        # explicit foreign market must stay inside its authoritative catalog.
        resolved = _resolve_company_dir_from_catalog(message, context)
        if resolved is not None:
            return resolved
        identity = agent_runtime_context.research_identity(context)
        if all(identity.get(field) for field in agent_runtime_context.COMPLETE_RESEARCH_IDENTITY_FIELDS):
            # Legacy catalog company ids can differ from the canonical report
            # manifest (for example UK:AZN versus EU:GB:AZN). Re-resolve only
            # from the explicit market/ticker text, then require the selected
            # package to match the already-bound filing and parse identity.
            fallback_message = " ".join(part for part in (message, _context_company_hint(context)) if part)
            candidate = _resolve_company_dir_from_catalog(fallback_message, None)
            if candidate is not None:
                report = _primary_report_for_company(candidate, message, context)
                if report.get("selection_status") == "identity_exact":
                    return candidate
        return None
    company_hint = _context_company_hint(context)
    if company_hint:
        resolved = _resolve_company_dir_from_catalog(message, context)
        if resolved is not None:
            return resolved
    module = _load_local_citation_module()
    finder = getattr(module, "find_company_dir_from_text", None) if module else None
    if callable(finder):
        candidates = [message]
        if company_hint:
            candidates.extend([company_hint, f"{message}\n{company_hint}"])
        for candidate in candidates:
            try:
                company_dir = finder(candidate, WIKI_ROOT)
            except Exception:
                continue
            if company_dir and Path(company_dir).exists():
                return Path(company_dir)
    return _resolve_company_dir_from_catalog(message, context)


def _resolve_company_dir_from_catalog(message: str, context: Any | None = None) -> Path | None:
    matches = _resolve_company_dirs_from_catalog(message, context, limit=1)
    return matches[0] if matches else None


def _resolve_company_dirs_from_catalog(message: str, context: Any | None = None, *, limit: int = 4) -> list[Path]:
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        return [bound] if limit > 0 else []
    identity = agent_runtime_context.research_identity(context)
    market_hint = identity.get("market")
    haystack = f"{message}\n{_context_company_hint(context)}"
    return agent_runtime_catalog.resolve_catalog_company_dirs(
        haystack,
        wiki_root=_wiki_root_path(),
        normalize_text=_normalize_financial_text,
        alias_overrides=COMPANY_ALIAS_OVERRIDES,
        market_hint=market_hint,
        company_id_hint=identity.get("company_id"),
        company_roots=_candidate_wiki_roots(),
        limit=limit,
        read_json_file=_read_json_file,
    )


def _resolve_company_dirs(message: str, context: Any | None = None, *, limit: int = 4) -> list[Path]:
    if _is_general_assistant_request(message):
        return []
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        return [bound] if limit > 0 else []
    dirs = _resolve_company_dirs_from_catalog(message, context, limit=limit)
    forced = _forced_context_company_dir(context)
    first = forced or (None if dirs else _resolve_company_dir(message, context))
    if first and first not in dirs:
        dirs.insert(0, first)
    output: list[Path] = []
    seen: set[Path] = set()
    for company_dir in dirs:
        if company_dir in seen:
            continue
        seen.add(company_dir)
        output.append(company_dir)
        if len(output) >= limit:
            break
    return output


def _company_query_prefix(company_dir: Path) -> str:
    company = _read_json_file(company_dir / "company.json") or {}
    return (
        company.get("company_short_name")
        or company.get("company_full_name")
        or (company_dir.name.split("-", 1)[1] if "-" in company_dir.name else company_dir.name)
    )


def _context_for_company_dir(company_dir: Path) -> dict[str, Any]:
    company = _read_json_file(company_dir / "company.json") or {}
    return {
        "force_company": True,
        "company": {
            "name": company.get("company_short_name") or company.get("company_full_name") or _company_query_prefix(company_dir),
            "code": company.get("stock_code") or company_dir.name.split("-", 1)[0],
            "dir": str(company_dir),
        }
    }


def _resolved_research_context(message: str, context: Any | None = None) -> dict[str, Any]:
    raw = agent_runtime_context.mutable_context_dict(context)
    # Resolution may record fallback diagnostics. Keep those mutations local so
    # a guard/audit lookup cannot rewrite caller-owned context or benchmark data.
    output = dict(raw)
    existing_events = output.get("_audit_fallback_events")
    if isinstance(existing_events, list):
        output["_audit_fallback_events"] = list(existing_events)
    existing = agent_runtime_context.research_identity(raw)
    if all(existing.get(field) for field in agent_runtime_context.COMPLETE_RESEARCH_IDENTITY_FIELDS):
        return output
    company_dir = _resolve_company_dir(message, context)
    if not company_dir:
        requested_markets = agent_runtime_catalog.requested_catalog_markets(message)
        if requested_markets == ("US",):
            output["research_identity"] = {**existing, "market": requested_markets[0]}
            return agent_runtime_context.context_with_research_identity(output)
        return output
    company = _read_json_file(company_dir / "company.json") or {}
    report = _primary_report_for_company(company_dir, message, output)
    market = str(existing.get("market") or report.get("market") or company.get("market") or "CN").upper()
    # The selected report manifest is the authoritative filing identity. Some
    # legacy company catalog rows contain duplicated market prefixes (for
    # example JP:JP:4502); preferring that stale catalog value makes the same
    # package unreadable as soon as a complete ResearchIdentity is enforced.
    company_id = str(existing.get("company_id") or report.get("company_id") or company.get("company_id") or company_dir.name)
    report_id = str(report.get("report_id") or company.get("primary_report_id") or "")
    filing_id = str(existing.get("filing_id") or report.get("filing_id") or "")
    parse_run_id = str(existing.get("parse_run_id") or report.get("parse_run_id") or "")
    # Legacy A-share Wiki artifacts predate explicit filing/parse identity
    # fields.  Their report id and parser task id are stable and authoritative,
    # so complete the same identity contract without accepting model text.
    if market == "CN":
        filing_id = filing_id or (f"CN:{company_id}:{report_id}" if company_id and report_id else "")
        parse_run_id = parse_run_id or str(report.get("task_id") or "")
    identity = {
        "market": market,
        "company_id": company_id,
        "filing_id": filing_id,
        "parse_run_id": parse_run_id,
    }
    output["research_identity"] = {**existing, **{key: value for key, value in identity.items() if value}}
    output["company"] = {
        **(output.get("company") if isinstance(output.get("company"), dict) else {}),
        "market": market,
        "company_id": identity["company_id"],
        "name": company.get("company_short_name") or company.get("company_name") or company.get("company_full_name"),
        "code": company.get("stock_code") or company.get("ticker"),
        "dir": str(company_dir),
    }
    # The directory was selected by the backend resolver, not supplied by the
    # model. Preserve that verified scope during evidence and guardrail passes
    # so a same-name company in another market cannot replace it.
    output["force_company"] = True
    output["resolved_period"] = {
        **(output.get("resolved_period") if isinstance(output.get("resolved_period"), dict) else {}),
        "market": market,
        "report_id": report_id,
        "filing_id": identity["filing_id"],
        "parse_run_id": identity["parse_run_id"],
    }
    return agent_runtime_context.context_with_research_identity(output)


def _result_with_research_identity(
    result: Mapping[str, Any],
    context: Any | None,
) -> dict[str, Any]:
    """Attach only a matching server-resolved identity to retrieval output."""

    identity = agent_runtime_context.research_identity(context)
    if not all(identity.get(field) for field in agent_runtime_context.COMPLETE_RESEARCH_IDENTITY_FIELDS):
        return dict(result)

    raw_context = agent_runtime_context.context_dict(context)
    expected_report_id = ""
    for candidate in (
        raw_context.get("report_id"),
        (raw_context.get("resolved_period") or {}).get("report_id")
        if isinstance(raw_context.get("resolved_period"), Mapping)
        else None,
        (raw_context.get("report") or {}).get("report_id")
        if isinstance(raw_context.get("report"), Mapping)
        else None,
    ):
        expected_report_id = str(candidate or "").strip()
        if expected_report_id:
            break

    def explicit_values(item: Mapping[str, Any], *fields: str) -> tuple[str, ...]:
        nested_identity = item.get("research_identity")
        mappings = (item, nested_identity) if isinstance(nested_identity, Mapping) else (item,)
        values: list[str] = []
        for mapping in mappings:
            for field in fields:
                value = str(mapping.get(field) or "").strip()
                if value and value not in values:
                    values.append(value)
        return tuple(values)

    def report_matches_filing(report_id: str) -> bool:
        filing_id = identity["filing_id"]
        return filing_id == report_id or filing_id.endswith(f":{report_id}")

    def scope_matches(
        item: Mapping[str, Any],
        *,
        allow_distinct_task: bool = False,
        trusted_task_id: str = "",
    ) -> bool:
        expected_values = (
            (("market",), identity["market"], True),
            (("company_id",), identity["company_id"], False),
            (("filing_id",), identity["filing_id"], False),
        )
        for fields, expected, normalize_market in expected_values:
            for value in explicit_values(item, *fields):
                actual = value.upper() if normalize_market else value
                wanted = expected.upper() if normalize_market else expected
                if actual != wanted:
                    return False
        # A market package may carry both the stable parse-run hash used by
        # ResearchIdentity and a separate parser job/task identifier.  The
        # latter is a locator, not an alternate company identity; rejecting it
        # merely because it differs from the hash discards otherwise exact
        # XBRL evidence.  When no parse hash is present, task_id remains the
        # only legacy binding and must still match exactly.
        parse_values = explicit_values(item, "parse_run_id")
        task_values = explicit_values(item, "task_id")
        allowed_task_values = {identity["parse_run_id"]}
        if trusted_task_id:
            allowed_task_values.add(trusted_task_id)
        if parse_values:
            if any(value != identity["parse_run_id"] for value in parse_values):
                return False
            if not allow_distinct_task and any(value not in allowed_task_values for value in task_values):
                return False
        elif task_values and any(value not in allowed_task_values for value in task_values):
            return False
        for report_id in explicit_values(item, "report_id"):
            if expected_report_id:
                if report_id != expected_report_id:
                    return False
            elif not report_matches_filing(report_id):
                return False
        return True

    def without_trust_binding() -> dict[str, Any]:
        # Preserve the conflicting company/filing/report for diagnostics, but
        # remove the parse-task binding required by trusted evidence builders.
        output = dict(result)
        output.pop("parse_run_id", None)
        output.pop("task_id", None)
        nested_identity = output.get("research_identity")
        if isinstance(nested_identity, Mapping):
            nested_output = dict(nested_identity)
            nested_output.pop("parse_run_id", None)
            output["research_identity"] = nested_output
        return output

    if not scope_matches(result, allow_distinct_task=True):
        return without_trust_binding()

    child_scopes: list[Mapping[str, Any]] = []
    rows = result.get("rows")
    if isinstance(rows, list):
        child_scopes.extend(item for item in rows if isinstance(item, Mapping))
    tables = result.get("tables")
    if isinstance(tables, list):
        for table in tables:
            if not isinstance(table, Mapping):
                continue
            child_scopes.append(table)
            for row_key in ("records", "rows"):
                table_rows = table.get(row_key)
                if isinstance(table_rows, list):
                    child_scopes.extend(item for item in table_rows if isinstance(item, Mapping))
    result_task_id = str(result.get("task_id") or "").strip()
    if any(not scope_matches(item, trusted_task_id=result_task_id) for item in child_scopes):
        return without_trust_binding()

    def complete(item: Mapping[str, Any]) -> dict[str, Any]:
        output = dict(item)
        for field, value in identity.items():
            if not str(output.get(field) or "").strip():
                output[field] = value
        if not str(output.get("task_id") or "").strip() and str(result.get("task_id") or "").strip():
            output["task_id"] = result["task_id"]
        return output

    output = complete(result)
    for key in ("tables", "rows"):
        values = result.get(key)
        if not isinstance(values, list):
            continue
        output[key] = [
            complete(item)
            if isinstance(item, Mapping)
            else item
            for item in values
        ]
    return output


def _message_for_company(message: str, company_dir: Path) -> str:
    return f"{_company_query_prefix(company_dir)} {message}"


def _report_text_blob(report: dict[str, Any]) -> str:
    return agent_runtime_wiki_context.report_text_blob(report)


def _report_is_annual(report: dict[str, Any]) -> bool:
    return agent_runtime_wiki_context.report_is_annual(report)


def _report_is_quarterly(report: dict[str, Any]) -> bool:
    return agent_runtime_wiki_context.report_is_quarterly(report)


def _select_report_from_company_json(company: dict[str, Any], message: str | None = None) -> dict[str, Any]:
    return agent_runtime_wiki_context.select_report_from_company_json(
        company,
        message,
        annual_terms=REPORT_ANNUAL_TERMS,
        quarterly_terms=REPORT_QUARTERLY_TERMS,
    )


def _primary_report_for_company(
    company_dir: Path,
    message: str | None = None,
    context: Any | None = None,
) -> dict[str, Any]:
    agent_runtime_host_scope.require_path(company_dir)
    research_identity = agent_runtime_context.research_identity(context)
    company = _read_json_file(company_dir / "company.json") or {}
    company_id = str(company.get("company_id") or company_dir.name)
    expected_filing_prefix = f"CN:{company_id}:"
    legacy_cn_identity = (
        research_identity.get("market") == "CN"
        and research_identity.get("company_id") == company_id
        and str(research_identity.get("filing_id") or "").startswith(expected_filing_prefix)
        and bool(research_identity.get("parse_run_id"))
    )
    report = agent_runtime_wiki_context.primary_report_for_company(
        company_dir,
        message,
        local_citation_module=_load_local_citation_module(),
        read_json_file=_read_json_file,
        annual_terms=REPORT_ANNUAL_TERMS,
        quarterly_terms=REPORT_QUARTERLY_TERMS,
        research_identity={} if legacy_cn_identity else research_identity,
    )
    if legacy_cn_identity:
        report_id = str(report.get("report_id") or "")
        report_task_id = str(report.get("parse_run_id") or report.get("task_id") or "")
        if (
            report_id
            and research_identity["filing_id"] == f"{expected_filing_prefix}{report_id}"
            and report_task_id == research_identity["parse_run_id"]
        ):
            report = {
                **report,
                "filing_id": research_identity["filing_id"],
                "parse_run_id": research_identity["parse_run_id"],
                "selection_status": "identity_exact",
                "selection_reason": "legacy_cn_identity_completed",
            }
        else:
            report = {
                "selection_status": "identity_mismatch",
                "selection_reason": "legacy_cn_identity_mismatch",
            }
    if report.get("selection_status") == "identity_mismatch" and isinstance(context, dict):
        event = {
            "reason": "research_identity_report_mismatch",
            "stage": "wiki_report_selector_failed",
            "source": "wiki_identity_selector",
            "detail": str(report.get("selection_reason") or "unknown"),
        }
        events = context.setdefault("_audit_fallback_events", [])
        if event not in events:
            events.append(event)
    return report


def _existing_company_file(company_dir: Path, rel_candidates: list[str | None]) -> Path | None:
    return agent_runtime_wiki_context.existing_company_file(company_dir, rel_candidates)


def _company_artifact_paths(
    company_dir: Path,
    report_id: str,
    strict_report: bool = False,
) -> dict[str, Path]:
    return agent_runtime_wiki_context.company_artifact_paths(
        company_dir,
        report_id,
        read_json_file=_read_json_file,
        strict_report=strict_report,
    )


def _report_relpath(path: Path, company_dir: Path) -> str:
    try:
        return str(path.relative_to(company_dir))
    except ValueError:
        return str(path)


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _nearest_report_pdf_page(lines: list[str], line_number: int | None) -> int | None:
    return agent_runtime_fallback_contexts._nearest_report_pdf_page(lines, line_number)


def _html_to_text(value: str) -> str:
    return agent_runtime_fallback_contexts._html_to_text(value)


def _normalize_search_text(value: Any) -> str:
    return agent_runtime_fallback_contexts._normalize_search_text(value)


def _remove_company_aliases(text: str, company_dir: Path) -> str:
    company = _read_json_file(company_dir / "company.json") or {}
    aliases = agent_runtime_fallback_contexts._company_aliases(company_dir.name, company)
    return agent_runtime_fallback_contexts._remove_company_aliases(text, aliases)


def _fallback_search_terms(message: str, company_dir: Path) -> list[str]:
    company = _read_json_file(company_dir / "company.json") or {}
    aliases = agent_runtime_fallback_contexts._company_aliases(company_dir.name, company)
    return agent_runtime_fallback_contexts._fallback_search_terms(
        message,
        aliases,
        REPORT_FULLTEXT_FALLBACK_TERMS,
    )


def _specific_fulltext_terms(terms: list[str]) -> list[str]:
    return agent_runtime_fallback_contexts._specific_fulltext_terms(terms, REPORT_FULLTEXT_GENERIC_TERMS)


def _line_match_score(line: str, terms: list[str]) -> int:
    return agent_runtime_fallback_contexts._line_match_score(line, terms)


def _line_matches_any_term(line: str, terms: list[str]) -> bool:
    return agent_runtime_fallback_contexts._line_matches_any_term(line, terms)


def _snippet_window(lines: list[str], line_number: int, *, radius: int = 2) -> str:
    return agent_runtime_fallback_contexts._snippet_window(
        lines,
        line_number,
        radius=radius,
        snippet_chars=REPORT_FULLTEXT_SNIPPET_CHARS,
    )


def _table_meta_by_line(company_dir: Path, report_id: str) -> list[dict[str, Any]]:
    return agent_runtime_wiki_context.table_meta_by_line(
        company_dir,
        report_id,
        read_json_file=_read_json_file,
    )


def _nearest_table_meta(tables: list[dict[str, Any]], line_number: int | None, *, max_distance: int = 3) -> dict[str, Any] | None:
    return agent_runtime_fallback_contexts._nearest_table_meta(
        tables,
        line_number,
        max_distance=max_distance,
    )


def _document_full_text_items(document_full: dict[str, Any], terms: list[str]) -> list[dict[str, Any]]:
    return agent_runtime_wiki_context.document_full_text_items(
        document_full,
        terms,
        snippet_chars=REPORT_FULLTEXT_SNIPPET_CHARS,
    )


def _should_consider_wiki_fulltext_fallback(message: str, context: Any | None = None) -> bool:
    return agent_runtime_wiki_context.should_consider_wiki_fulltext_fallback(
        message,
        context,
        fallback_terms=REPORT_FULLTEXT_FALLBACK_TERMS,
        generic_terms=REPORT_FULLTEXT_GENERIC_TERMS,
        is_general_assistant_request=_is_general_assistant_request,
        resolve_company_dir=_resolve_company_dir,
        context_company=_context_company,
    )


def _is_runtime_connectivity_question(message: str) -> bool:
    text = re.sub(r"\s+", "", str(message or "")).casefold()
    if not text:
        return False
    runtime_terms = (
        "openshell",
        "hermes",
        "链路",
        "连接",
        "连通",
        "接入",
        "在线",
        "握手",
        "烟测",
        "端口",
        "runtime",
        "health",
        "connectivity",
    )
    if not any(term in text for term in runtime_terms):
        return False
    financial_terms = (
        "营收",
        "收入",
        "利润",
        "净利",
        "现金流",
        "资产",
        "负债",
        "商誉",
        "roe",
        "业绩",
        "表现",
        "风险",
        "基本面",
        "经营情况",
        "财务分析",
        "revenue",
        "profit",
        "income",
        "cashflow",
        "asset",
        "liabilit",
        "goodwill",
        "financial",
        "earnings",
        "valuation",
        "risk",
    )
    return not any(term in text for term in financial_terms)


def _wiki_fulltext_fallback_result(message: str, context: Any | None = None) -> dict[str, Any] | None:
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    return agent_runtime_wiki_context.wiki_fulltext_fallback_result(
        message,
        context,
        fallback_terms=REPORT_FULLTEXT_FALLBACK_TERMS,
        generic_terms=REPORT_FULLTEXT_GENERIC_TERMS,
        max_snippets=REPORT_FULLTEXT_MAX_SNIPPETS,
        snippet_chars=REPORT_FULLTEXT_SNIPPET_CHARS,
        is_general_assistant_request=_is_general_assistant_request,
        resolve_company_dir=_resolve_company_dir,
        context_company=_context_company,
        read_json_file=_read_json_file,
        primary_report_for_company=_primary_report_for_company,
    )


def _render_wiki_fulltext_fallback_context(result: dict[str, Any]) -> str:
    return agent_runtime_wiki_context.render_wiki_fulltext_fallback_context(
        result,
        evidence_url=_evidence_url,
    )


def build_wiki_fulltext_fallback_context(message: str, context: Any | None = None) -> str | None:
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    return agent_runtime_wiki_context.build_wiki_fulltext_fallback_context(
        message,
        context,
        fallback_terms=REPORT_FULLTEXT_FALLBACK_TERMS,
        generic_terms=REPORT_FULLTEXT_GENERIC_TERMS,
        max_snippets=REPORT_FULLTEXT_MAX_SNIPPETS,
        snippet_chars=REPORT_FULLTEXT_SNIPPET_CHARS,
        is_general_assistant_request=_is_general_assistant_request,
        resolve_company_dir=_resolve_company_dir,
        context_company=_context_company,
        read_json_file=_read_json_file,
        primary_report_for_company=_primary_report_for_company,
        evidence_url=_evidence_url,
    )


def build_company_wiki_scope_context(message: str, context: Any | None = None) -> str | None:
    """Pin a single-company question to the resolved local Wiki workset."""
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    return agent_runtime_wiki_context.build_company_wiki_scope_context(
        message,
        context,
        wiki_root=WIKI_ROOT,
        resolve_company_dir=_resolve_company_dir,
        read_json_file=_read_json_file,
        primary_report_for_company=_primary_report_for_company,
        company_artifact_paths=_company_artifact_paths,
        clean_context_value=_clean_context_value,
    )


def _iter_metric_records(obj: Any) -> list[dict[str, Any]]:
    return agent_runtime_market_facts.normalize_statement_records(obj)


def _period_sort_key(value: Any) -> tuple[int, str]:
    return agent_runtime_statement_context.period_sort_key(value)


def _record_source(record: dict[str, Any]) -> dict[str, Any]:
    return agent_runtime_statement_context.record_source(record)


def _record_source_value(record: dict[str, Any], key: str) -> Any:
    return agent_runtime_statement_context.record_source_value(record, key)


def _normalize_wiki_metric_file_name(file_name: str) -> str:
    return agent_runtime_financial_sources.normalize_wiki_metric_file_name(
        file_name,
        default_source_type=_current_default_source_type(),
    )


def _normalize_wiki_metric_file_refs(markdown: str) -> str:
    return agent_runtime_financial_sources.normalize_wiki_metric_file_refs(
        markdown,
        default_source_type=_current_default_source_type(),
    )


def _statement_record_rank(record: dict[str, Any], statement_type: str) -> tuple[int, int, str]:
    return agent_runtime_statement_context.statement_record_rank(
        record,
        statement_type,
        core_keys=THREE_STATEMENT_CORE_KEYS,
        core_name_terms=THREE_STATEMENT_CORE_NAME_TERMS,
        normalize_financial_text=_normalize_financial_text,
    )


def _is_core_statement_record(record: dict[str, Any], statement_type: str) -> bool:
    return agent_runtime_statement_context.is_core_statement_record(
        record,
        statement_type,
        statement_record_rank_fn=_statement_record_rank,
    )


def _latest_records_by_statement(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return agent_runtime_statement_context.latest_records_by_statement(
        records,
        is_core_statement_record_fn=_is_core_statement_record,
        statement_record_rank_fn=_statement_record_rank,
    )


def _append_source_access_token(url: str | None, task_id: Any) -> str | None:
    """Make PDF/source evidence links independently openable for a short TTL.

    The web client still resolves authenticated source links dynamically, but
    citation links are also copied into reports and chat history.  A signed
    task-bound token keeps those links usable without exposing a user JWT.
    """
    if not url or not task_id:
        return url
    try:
        from routers.source import create_source_access_token

        token = create_source_access_token(str(task_id))
        parsed = urlsplit(url)
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in {"source_token", "access_token"}
        ]
        query.append(("source_token", token))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    except Exception:
        # A citation must remain renderable even when token configuration is
        # unavailable; the authenticated frontend fallback can still resolve it.
        return url


def _evidence_url(task_id: Any, pdf_page: Any, table_index: Any, kind: str) -> str | None:
    if not task_id:
        return None
    module = _load_note_detail_module()
    public_api_url = getattr(module, "public_api_url", None) if module else None
    if kind == "pdf" and pdf_page:
        path = f"/api/pdf_page/{task_id}/{pdf_page}?format=html"
    elif kind == "page" and pdf_page:
        path = f"/api/source/{task_id}/page/{pdf_page}?format=html"
    elif kind == "table" and table_index not in (None, ""):
        path = f"/api/source/{task_id}/table/{table_index}?format=html"
    else:
        return None
    if callable(public_api_url):
        try:
            return _append_source_access_token(public_api_url(path), task_id)
        except Exception:
            pass
    from services.runtime_security import public_origin_from_env

    origin = public_origin_from_env()
    return _append_source_access_token(f"{origin}{path}", task_id)


def _statement_record_to_row(record: dict[str, Any], report_id: str, metrics_file: Path, company_dir: Path) -> dict[str, Any]:
    source = _record_source(record)
    task_id = record.get("task_id") or source.get("task_id")
    pdf_page = record.get("pdf_page") or source.get("pdf_page") or source.get("pdf_page_number")
    table_index = record.get("table_index") if record.get("table_index") not in (None, "") else source.get("table_index")
    md_line = (
        record.get("md_line")
        or record.get("line")
        or source.get("md_line")
        or source.get("line")
    )
    file_name = str(metrics_file.relative_to(company_dir)) if metrics_file.is_relative_to(company_dir) else str(metrics_file)
    source_quote = source.get("quote_text") or source.get("html_snippet")
    source_id = source.get("evidence_id") or source.get("source_id")
    raw_value = record.get("raw_value")
    if raw_value in (None, ""):
        raw_value = record.get("value")
    if raw_value in (None, ""):
        raw_value = record.get("normalized_value")
    base_scale = record.get("base_scale")
    if base_scale in (None, ""):
        base_scale = source.get("base_scale")
    scale = record.get("scale")
    if scale in (None, ""):
        scale = base_scale
    if scale in (None, ""):
        scale = source.get("scale")
    evidence_id = source_id or "wiki:" + uuid.uuid5(
        uuid.NAMESPACE_URL,
        "|".join(
            str(value or "")
            for value in (
                task_id,
                report_id,
                record.get("statement_type"),
                record.get("metric_key") or record.get("canonical_name"),
                record.get("period") or source.get("period"),
                pdf_page,
                table_index,
                md_line,
                raw_value,
            )
        ),
    ).hex
    return {
        "statement_type": record.get("statement_type"),
        "statement_label": THREE_STATEMENT_LABELS.get(str(record.get("statement_type") or ""), str(record.get("statement_type") or "")),
        "metric_key": record.get("metric_key") or record.get("canonical_name"),
        "metric_name": record.get("metric_name") or record.get("name") or record.get("item_name") or record.get("metric_key"),
        "period": record.get("period") or source.get("period"),
        "raw_value": raw_value,
        "unit": record.get("unit_hint") or record.get("raw_unit") or record.get("unit"),
        "currency": record.get("currency") or source.get("currency"),
        "scale": scale,
        "base_scale": base_scale,
        "normalized_value": record.get("normalized_value"),
        "report_id": report_id,
        "source_type": "wiki_metrics",
        "file": _normalize_wiki_metric_file_name(file_name),
        "task_id": task_id,
        "pdf_page": pdf_page,
        "table_index": table_index,
        "md_line": md_line,
        "evidence_source_type": source.get("source_type"),
        "source_url": source.get("source_url") or source.get("url"),
        "source_anchor": source.get("source_anchor") or source.get("anchor") or source.get("xpath"),
        "source_quote": source_quote,
        "evidence_id": evidence_id,
        "source_id": source_id,
        "xbrl_tag": source.get("xbrl_tag"),
        "open_pdf_page_url": _evidence_url(task_id, pdf_page, table_index, "pdf"),
        "open_source_page_url": _evidence_url(task_id, pdf_page, table_index, "page"),
        "open_source_table_url": _evidence_url(task_id, pdf_page, table_index, "table"),
    }


def _question_needs_three_statement_context(message: str, context: Any | None = None) -> bool:
    text = re.sub(r"\s+", "", message or "")
    if not text or _is_general_assistant_request(text):
        return False
    if _is_runtime_connectivity_question(message):
        return False
    if _resolve_company_dir(message, context) is None:
        return False
    if _is_human_capital_query(message):
        return False
    # Goodwill questions require the balance-sheet net amount first. When the
    # wording also asks for detail/impairment, note evidence is appended later
    # by the shared context builder instead of replacing this block.
    if "商誉" in text:
        return True
    if _is_statement_query(message):
        return True
    if any(term.lower() in text.lower() for term in CORE_KEY_METRIC_TERMS):
        return True
    return any(
        term in text
        for term in (
            "财务",
            "业绩",
            "表现",
            "分析",
            "评价",
            "评估",
            "对比",
            "趋势",
            "风险",
            "亮点",
            "怎么样",
            "如何",
            "核心数据",
            "主要数据",
            "基本面",
            "经营情况",
        )
    )


def _three_statement_core_result(message: str, context: Any | None = None) -> dict[str, Any] | None:
    if not _question_needs_three_statement_context(message, context):
        return None
    company_dir = _resolve_company_dir(message, context)
    if not company_dir:
        return None
    report = _primary_report_for_company(company_dir, message, context)
    if report.get("selection_status") == "identity_mismatch":
        return None
    report_id = str(report.get("report_id") or "2025-annual")
    metrics_file = _company_artifact_paths(
        company_dir,
        report_id,
        report.get("selection_status") == "identity_exact",
    ).get("three_statements")
    if not metrics_file:
        return None
    payload = _read_json_file(metrics_file)
    if not isinstance(payload, dict):
        return None
    records = _latest_records_by_statement(_iter_metric_records(payload.get("data") or payload))
    if not records:
        return None
    company = _read_json_file(company_dir / "company.json") or {}
    artifact_paths = _company_artifact_paths(
        company_dir,
        report_id,
        report.get("selection_status") == "identity_exact",
    )
    validation_file = artifact_paths.get("validation")
    validation = agent_runtime_market_facts.validation_summary(
        _read_json_file(validation_file) if validation_file else None
    )
    validation_blocked = str(validation.get("status") or "").casefold() == "fail"
    rows = [
        _statement_record_to_row(record, report_id, metrics_file, company_dir)
        for record in records
    ]
    requested_terms = _postgres_requested_metric_terms(message)
    if requested_terms:
        requested_norms = [_normalize_financial_text(term) for term in requested_terms]
        matched_rows = []
        for row in rows:
            row_text = _normalize_financial_text(
                " ".join(
                    str(row.get(key) or "")
                    for key in ("metric_key", "metric_name", "source_quote")
                )
            )
            if any(term and term in row_text for term in requested_norms):
                matched_rows.append(row)
        if matched_rows:
            if any(
                term in requested_norms
                for term in (
                    "净资产",
                    "totalequity",
                    "equityattributableparent",
                    "shareholdersequity",
                    "stockholdersequity",
                )
            ):
                direct_equity_rows = [
                    row
                    for row in matched_rows
                    if str(row.get("metric_key") or "")
                    in {"total_equity", "equity_attributable_parent", "shareholders_equity"}
                ]
                if direct_equity_rows:
                    matched_rows = direct_equity_rows
            rows = matched_rows
        else:
            return None
    else:
        normalized_query = _normalize_financial_text(message)
        statement_filters = (
            (("资产负债表", "balancesheet", "財政状態計算書", "재무상태표"), "balance_sheet"),
            (("利润表", "损益表", "incomestatement", "profitandloss"), "income_statement"),
            (("现金流量表", "cashflowstatement", "キャッシュフロー", "현금흐름표"), "cash_flow_statement"),
        )
        for terms, statement_type in statement_filters:
            if any(term in normalized_query for term in terms):
                rows = [row for row in rows if row.get("statement_type") == statement_type]
                break
    if not rows:
        return None
    return _result_with_research_identity({
        "company_dir": company_dir,
        "market": report.get("market") or company.get("market") or "CN",
        "company_id": report.get("company_id") or company.get("company_id") or company_dir.name,
        "company_name": company.get("company_short_name")
        or company.get("company_name")
        or company.get("company_full_name")
        or company_dir.name,
        "stock_code": company.get("stock_code") or company.get("ticker") or company_dir.name.split("-", 1)[0],
        "report_id": report_id,
        "filing_id": report.get("filing_id"),
        "parse_run_id": report.get("parse_run_id"),
        "task_id": report.get("task_id"),
        "metrics_file": metrics_file,
        "validation_file": validation_file,
        "validation": validation,
        "validation_blocked": validation_blocked,
        "unit": payload.get("unit"),
        "rows": [] if validation_blocked else rows,
        "blocked_row_count": len(rows) if validation_blocked else 0,
    }, context)


def _format_statement_value(row: dict[str, Any]) -> str:
    value = row.get("raw_value")
    unit = row.get("unit") or ""
    if value in (None, ""):
        value = row.get("normalized_value")
    return f"{value} {unit}".strip()


def _render_three_statement_context(result: dict[str, Any]) -> str:
    if result.get("validation_blocked"):
        return "\n".join(
            [
                "## 财务事实质量门禁阻断",
                f"- 公司: {result.get('company_name')} / 市场 {result.get('market')} / company_id={result.get('company_id')}",
                f"- report_id={result.get('report_id')} / validation_status=fail / file={result.get('validation_file') or '未返回'}",
                f"- 已阻断 {result.get('blocked_row_count') or 0} 条三大表候选记录，不得将其作为确定性数字回答。",
                "- 只允许说明 Wiki validation 未通过；如需继续，必须使用绑定同一 market/company_id/filing_id/parse_run_id 的 PostgreSQL Agent view fallback，并保留 fallback_reason。",
            ]
        )
    rows = result.get("rows") or []
    lines = [
        "以下是后端从本地 Wiki 三大表 `three_statements.json` 提取的核心数据底稿。模型可以润色、概括和解释数据本质，但不得改写任何 `raw_value`、期间、单位、公司、report_id、task_id、pdf_page、table_index、md_line 或来源路径。",
        "输出要求：",
        "- 回答先讲三大表透视出的经营本质，例如增长、盈利、现金流含金量、资产负债结构；再给关键数据表格。",
        "- 所有关键数字必须来自下方底稿；如果要做金额单位归一或百分比，只能复制后端确定性结果包/计算器输出作为补充表述，并同时保留下方原始披露值。",
        "- `## 引用来源` 必须保留每张相关表的 `source_type/file/task_id/pdf_page/table_index/md_line` 和可打开链接。",
        f"- 公司: {result.get('company_name')} / 市场 {result.get('market')} / 代码 {result.get('stock_code')} / "
        f"company_id={result.get('company_id')} / report_id={result.get('report_id')} / 默认单位={result.get('unit') or '按科目披露'}",
        f"- 质量门禁: validation_status={result.get('validation', {}).get('status') or 'not_available'} / "
        f"summary={json.dumps(result.get('validation', {}).get('summary') or {}, ensure_ascii=False)} / "
        f"file={result.get('validation_file') or '未返回'}",
        "",
        "## 三大表核心底稿",
    ]
    if str(result.get("market") or "").upper() == "US":
        lines.insert(
            7,
            "- 美股 SEC/XBRL 金额优先保留原始 USD 或后端结果包中的 billion USD；不要把 215,938,000,000 USD 自行改写成 215.938 亿美元。",
        )
    for statement_type in ("income_statement", "cash_flow_statement", "balance_sheet"):
        statement_rows = [row for row in rows if row.get("statement_type") == statement_type]
        if not statement_rows:
            continue
        lines.extend([
            "",
            f"### {THREE_STATEMENT_LABELS.get(statement_type, statement_type)}",
            "| 科目 | 期间 | 原始披露值 | 单位/币种 | pdf_page | table_index | SEC/XBRL anchor | md_line |",
            "| --- | --- | ---: | --- | ---: | ---: | --- | ---: |",
        ])
        for row in statement_rows:
            lines.append(
                f"| {row.get('metric_name') or row.get('metric_key')} | {row.get('period') or '未返回'} | "
                f"{row.get('raw_value') if row.get('raw_value') not in (None, '') else row.get('normalized_value')} | "
                f"{row.get('unit') or row.get('currency') or '未返回'} | {row.get('pdf_page') or '未返回'} | "
                f"{row.get('table_index') if row.get('table_index') not in (None, '') else '未返回'} | "
                f"{row.get('source_anchor') or '未返回'} | "
                f"{row.get('md_line') or '未返回'} |"
            )
    lines.extend(["", "## 底稿引用"])
    seen_sources: set[tuple[Any, ...]] = set()
    source_index = 1
    for row in rows:
        key = (
            row.get("task_id"),
            row.get("pdf_page"),
            row.get("table_index"),
            row.get("md_line"),
            row.get("file"),
            row.get("source_url"),
            row.get("source_anchor"),
            row.get("xbrl_tag"),
        )
        if key in seen_sources:
            continue
        seen_sources.add(key)
        links = []
        if row.get("open_pdf_page_url"):
            links.append(f"[打开PDF页]({row['open_pdf_page_url']})")
        if row.get("open_source_page_url"):
            links.append(f"[查看页来源]({row['open_source_page_url']})")
        if row.get("open_source_table_url"):
            links.append(f"[查看表格]({row['open_source_table_url']})")
        if row.get("source_url"):
            source_url = str(row["source_url"])
            if row.get("source_anchor") and "#" not in source_url:
                source_url = f"{source_url}#{row['source_anchor']}"
            links.append(f"[打开披露原文]({source_url})")
        lines.append(
            f"[S{source_index}] source_type={_current_source_type('metrics')}, file={row.get('file')}, "
            f"metric={row.get('statement_label')}, period={row.get('report_id')}, "
            f"task_id={row.get('task_id') or '未返回'}, pdf_page={row.get('pdf_page') or '未返回'}, "
            f"table_index={row.get('table_index') if row.get('table_index') not in (None, '') else '未返回'}, "
            f"md_line={row.get('md_line') or '未返回'}, evidence_source_type={row.get('evidence_source_type') or '未返回'}, "
            f"source_url={row.get('source_url') or '未返回'}, source_anchor={row.get('source_anchor') or '未返回'}, "
            f"xbrl_tag={row.get('xbrl_tag') or '未返回'}, "
            f"quote={json.dumps(str(row.get('source_quote') or ''), ensure_ascii=False)}"
            + (("，" + "，".join(links)) if links else "")
        )
        source_index += 1
    return "\n".join(lines)


def build_three_statement_core_context(message: str, context: Any | None = None) -> str | None:
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    result = _three_statement_core_result(message, context)
    if not result:
        return None
    return _render_three_statement_context(result)


def _load_note_detail_module() -> Any | None:
    script_path = str(NOTE_DETAIL_SCRIPT_DIR)
    if script_path not in sys.path:
        sys.path.insert(0, script_path)
    try:
        module = _configure_wiki_module(importlib.import_module("note_detail_lookup"))
        _configure_wiki_module(getattr(module, "local_citations", None))
        return module
    except Exception:
        return None


def _load_note_detail_tools() -> tuple[Callable[..., dict[str, Any]] | None, Callable[..., str] | None]:
    module = _load_note_detail_module()
    if module is None:
        return None, None
    resolver = getattr(module, "resolve_note_detail_tables", None)
    renderer = getattr(module, "render_markdown", None)
    if not callable(resolver) or not callable(renderer):
        return None, None
    return resolver, renderer


def _load_statement_metric_tools(
    context: Any | None = None,
) -> tuple[Callable[..., dict[str, Any]] | None, Callable[..., str] | None]:
    script_path = str(NOTE_DETAIL_SCRIPT_DIR)
    if script_path not in sys.path:
        sys.path.insert(0, script_path)
    try:
        module = _configure_wiki_module(importlib.import_module("statement_metric_lookup"))
        _configure_wiki_module(getattr(module, "local_citations", None))
        _configure_wiki_module(getattr(module, "note_detail_lookup", None))
        forced_company_dir = _forced_context_company_dir(context)
        if forced_company_dir is not None and forced_company_dir.parent.name == "companies":
            # PDF-market Wiki roots are split into data/wiki/{market}; the
            # legacy lookup script otherwise searches only data/wiki/companies.
            module.WIKI_BASE = forced_company_dir.parent.parent
            dependencies = (
                getattr(module, "local_citations", None),
                getattr(module, "note_detail_lookup", None),
                sys.modules.get("local_citations"),
                sys.modules.get("note_detail_lookup"),
            )
            for dependency in dependencies:
                if dependency is not None:
                    dependency.WIKI_BASE = forced_company_dir.parent.parent
        _configure_wiki_module(getattr(module, "local_citations", None))
        _configure_wiki_module(getattr(module, "note_detail_lookup", None))
    except Exception:
        return None, None
    resolver = getattr(module, "resolve_statement_metrics", None)
    renderer = getattr(module, "render_markdown", None)
    if not callable(resolver) or not callable(renderer):
        return None, None
    return resolver, renderer


def _is_human_capital_query(message: str) -> bool:
    text = re.sub(r"\s+", "", message or "")
    if not text or _is_general_assistant_request(text):
        return False
    return any(term in text for term in HUMAN_CAPITAL_QUERY_TERMS) or any(
        term in text
        for term in (
            "员工人数",
            "员工总数",
            "在职员工",
            "研发人员",
            "研发人员情况",
        )
    )


def _is_human_efficiency_query(message: str) -> bool:
    text = re.sub(r"\s+", "", message or "")
    if not text or _is_general_assistant_request(text):
        return False
    return any(term in text for term in HUMAN_EFFICIENCY_QUERY_TERMS)


def _human_capital_table_score(table: dict[str, Any]) -> int:
    text = " ".join(str(table.get(key) or "") for key in ("heading", "preview", "unit"))
    score = 0
    for term in HUMAN_CAPITAL_TABLE_TERMS:
        if term in text:
            score += 20
    if "母公司在职员工的数量" in text and "专业构成" in text and "教育程度" in text:
        score += 100
    return score


def _nearest_pdf_page_for_md_line(report_md: Path, md_line: int) -> int | None:
    try:
        agent_runtime_host_scope.require_path(report_md)
        lines = report_md.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    for line in reversed(lines[:max(0, min(len(lines), md_line))]):
        match = re.search(r"\[PDF_PAGE:\s*(\d+)\]", line)
        if match:
            return int(match.group(1))
    return None


def _human_capital_table_meta(company_dir: Path, report_id: str) -> dict[str, Any] | None:
    report_json = _read_json_file(company_dir / "reports" / report_id / "report.json")
    tables = report_json.get("tables") if isinstance(report_json, dict) else None
    if isinstance(tables, list):
        scored = [
            (_human_capital_table_score(table), table)
            for table in tables
            if isinstance(table, dict)
        ]
        scored = [(score, table) for score, table in scored if score > 0]
        if scored:
            scored.sort(
                key=lambda item: (
                    -item[0],
                    int(item[1].get("table_index") or 10**9),
                    int(item[1].get("line") or 10**9),
                )
            )
            return scored[0][1]

    report_md = company_dir / "reports" / report_id / "report.md"
    try:
        agent_runtime_host_scope.require_path(report_md)
        lines = report_md.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return None
    for index, line in enumerate(lines, start=1):
        if "母公司在职员工的数量" in line and "<table" in line:
            return {
                "line": index,
                "pdf_page_number": _nearest_pdf_page_for_md_line(report_md, index),
                "table_index": None,
                "heading": "员工情况",
            }
    return None


def _parse_count(value: Any) -> int | None:
    text = str(value or "").replace(",", "").replace("人", "").strip()
    if not text or not re.fullmatch(r"-?\d+", text):
        return None
    return int(text)


def _ratio_text(count_text: Any, total: int | None) -> str:
    count = _parse_count(count_text)
    if count is None or not total:
        return ""
    return f"{count / total * 100:.2f}%"


def _split_human_capital_rows(rows: list[list[str]]) -> dict[str, list[tuple[str, str]]]:
    sections: dict[str, list[tuple[str, str]]] = {
        "scale": [],
        "profession": [],
        "education": [],
    }
    section = "scale"
    for row in rows:
        if len(row) < 2:
            continue
        label = str(row[0] or "").strip()
        value = str(row[1] or "").strip()
        if not label:
            continue
        if label == "专业构成":
            section = "profession"
            continue
        if label == "教育程度":
            section = "education"
            continue
        if label in {"专业构成类别", "教育程度类别"}:
            continue
        sections[section].append((label, value))
    return sections


MARKET_HUMAN_CAPITAL_TABLE_TERMS: dict[str, tuple[str, ...]] = {
    "HK": ("僱員", "雇員", "员工", "employee", "staff", "workforce", "headcount"),
    "JP": ("従業員", "社員", "employee", "staff", "workforce", "headcount"),
    "KR": ("직원", "직원수", "평균근속연수", "성별합계", "employee", "workforce"),
    "EU": ("employee", "employees", "workforce", "personnel", "mitarbeiter", "effectif"),
}


def _market_human_table_quality(market: str, rows: list[list[str]]) -> int:
    text = " ".join(" ".join(map(str, row)) for row in rows)
    normalized = _normalize_financial_text(text)
    numeric_values: list[float] = []
    percentage_cells = 0
    for row in rows:
        for cell in row:
            cell_text = str(cell or "").strip()
            if not cell_text or "page" in cell_text.lower():
                continue
            if not re.fullmatch(r"\(?[-+]?\d[\d,.\s]*(?:%|％)?\)?", cell_text):
                continue
            value = _parse_number(cell_text)
            if value is None or (1900 <= abs(value) <= 2100 and re.fullmatch(r"\d{4}", cell_text)):
                continue
            numeric_values.append(abs(value))
            if "%" in cell_text or "％" in cell_text:
                percentage_cells += 1
    material_counts = sum(1 for value in numeric_values if value >= 100)
    if market == "KR":
        return 20 if "직원수" in normalized and "평균근속연수" in normalized and material_counts >= 3 else 0
    if market == "JP":
        has_employee_measure = any(term in normalized for term in ("従業員数", "平均勤続年数", "平均年間給与"))
        return 20 if has_employee_measure and material_counts >= 2 else 0
    latin = text.lower()
    has_employee = bool(re.search(r"\b(?:employees?|workforce|headcount|personnel)\b", latin)) or any(
        term in text for term in ("僱員", "雇員", "員工", "员工")
    )
    if any(term in latin for term in ("fatalit", "injur", "lost days", "health and safety")):
        return 0
    if "items of the annex" in latin and "pages" in latin:
        return 0
    has_headcount_measure = bool(
        re.search(
            r"(?:number of employees|total (?:group )?(?:number of )?employees|total workforce|headcount|"
            r"breakdown of (?:total )?employees|employees by (?:gender|geography|age|contract))",
            latin,
        )
    ) or any(term in text for term in ("僱員人數", "雇員人數", "員工人數", "员工人数", "總人數", "总人数"))
    has_structure_measure = bool(
        re.search(r"(?:share of women|gender distribution|workforce composition|diversity metrics)", latin)
    )
    if has_employee and has_headcount_measure and material_counts >= 2:
        return 40
    if has_employee and has_structure_measure and percentage_cells >= 2:
        return 20
    return 0


def _market_human_capital_table_result(
    message: str,
    context: Any | None,
    *,
    extract: Callable[[Path, int], str],
    parser: Callable[[str], dict[str, Any]],
) -> dict[str, Any] | None:
    """Resolve PDF-market employee tables from parser artifacts, never model locators."""
    for company_dir in _resolve_company_dirs(message, context, limit=4):
        company = _read_json_file(company_dir / "company.json") or {}
        market = str(company.get("market") or "").upper()
        # US filings use SEC/XBRL/HTML anchors and have a separate evidence path.
        if market not in MARKET_HUMAN_CAPITAL_TABLE_TERMS:
            continue
        report_id = str(company.get("primary_report_id") or "").strip()
        reports = company.get("reports") if isinstance(company.get("reports"), list) else []
        report = next(
            (item for item in reports if isinstance(item, dict) and str(item.get("report_id") or "") == report_id),
            {},
        )
        if not report_id and reports:
            report = next((item for item in reports if isinstance(item, dict)), {})
            report_id = str(report.get("report_id") or "").strip()
        if not report_id:
            continue
        report_md = company_dir / "reports" / report_id / "report.md"
        table_index_file = company_dir / "reports" / report_id / "tables" / "table_index.json"
        payload = _read_json_file(table_index_file) or {}
        tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
        terms = MARKET_HUMAN_CAPITAL_TABLE_TERMS[market]
        candidates: list[tuple[int, int, int, dict[str, Any], list[list[str]]]] = []
        for table in tables:
            if not isinstance(table, dict):
                continue
            text = _normalize_financial_text(
                " ".join(str(table.get(key) or "") for key in ("heading", "near_text", "preview"))
            )
            hits = sum(1 for term in terms if _normalize_financial_text(term) in text)
            if hits <= 0:
                continue
            line = _safe_int(table.get("line"))
            if not line:
                continue
            try:
                parsed = parser(extract(report_md, line) or "")
            except Exception:
                continue
            rows = parsed.get("rows") if isinstance(parsed, dict) else None
            if not isinstance(rows, list) or len(rows) < 2:
                continue
            normalized_rows = [row for row in rows if isinstance(row, list)]
            row_text = _normalize_financial_text(" ".join(" ".join(map(str, row)) for row in normalized_rows))
            row_hits = sum(1 for term in terms if _normalize_financial_text(term) in row_text)
            quality = _market_human_table_quality(market, normalized_rows)
            if row_hits <= 0 or quality <= 0:
                continue
            confidence = 2 if str(table.get("source_confidence") or "").lower() == "high" else 1
            physical_source = 1 if table.get("content_table_source_id") is not None else 0
            candidates.append((quality + hits + row_hits, confidence, physical_source, table, normalized_rows))
        if not candidates:
            continue
        candidates.sort(
            key=lambda item: (
                -item[1],
                -item[2],
                -item[0],
                int(item[3].get("table_index") or 10**9),
            )
        )
        _score, _confidence, _physical, table, rows = candidates[0]
        task_id = report.get("task_id")
        pdf_page = table.get("pdf_page_number") or table.get("pdf_page")
        table_index = table.get("table_index")
        footnotes = [str(item).strip() for item in (table.get("source_footnote") or []) if str(item).strip()]
        if not footnotes and report_md.is_file():
            try:
                agent_runtime_host_scope.require_path(report_md)
                report_lines = report_md.read_text(encoding="utf-8", errors="ignore").splitlines()
                start = max(0, int(table.get("line") or 1))
                for candidate_line in report_lines[start : start + 16]:
                    note = candidate_line.strip()
                    if note.startswith("※"):
                        footnotes.append(note)
                    elif footnotes and (note.startswith("#") or note.startswith("[PDF_PAGE:")):
                        break
            except Exception:
                footnotes = []
        return {
            "market_table": True,
            "market": market,
            "company_id": company.get("company_id") or company_dir.name,
            "company_name": company.get("company_name") or company.get("company_short_name") or company_dir.name,
            "report_id": report_id,
            "task_id": task_id,
            "pdf_page": pdf_page,
            "table_index": table_index,
            "md_line": table.get("line"),
            "raw_rows": rows,
            "source_footnote": footnotes,
            "open_pdf_page_url": _evidence_url(task_id, pdf_page, table_index, "pdf"),
            "open_source_page_url": _evidence_url(task_id, pdf_page, table_index, "page"),
            "open_source_table_url": _evidence_url(task_id, pdf_page, table_index, "table"),
        }
    return None


def _human_capital_result(message: str, context: Any | None = None) -> dict[str, Any] | None:
    if not _is_human_capital_query(message):
        return None
    module = _load_note_detail_module()
    if module is None:
        return None
    finder = getattr(module, "find_company_dir_from_text", None)
    primary = getattr(module, "primary_report", None)
    extract = getattr(module, "extract_table_html", None)
    parser = getattr(module, "parse_html_table", None)
    if not all(callable(item) for item in (finder, primary, extract, parser)):
        return None

    company_hint = _context_company_hint(context)
    company_text_candidates = [message]
    if company_hint:
        company_text_candidates.append(company_hint)
        company_text_candidates.append(f"{message}\n{company_hint}")
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        company_text_candidates = [bound.name]

    for company_text in company_text_candidates:
        company_dir = finder(company_text, WIKI_ROOT)
        if not company_dir:
            continue
        report = primary(company_dir)
        report_id = report.get("report_id") or "2025-annual"
        meta = _human_capital_table_meta(company_dir, report_id)
        if not meta:
            continue
        md_line = int(meta.get("line") or meta.get("md_line") or 0)
        if md_line <= 0:
            continue
        report_md = company_dir / "reports" / report_id / "report.md"
        html = extract(report_md, md_line)
        parsed = parser(html or "")
        rows = parsed.get("rows") if isinstance(parsed, dict) else None
        if not rows:
            continue
        sections = _split_human_capital_rows(rows)
        if not any(sections.values()):
            continue
        task_id = report.get("task_id")
        pdf_page = (
            meta.get("pdf_page_number")
            or meta.get("pdf_page")
            or _nearest_pdf_page_for_md_line(report_md, md_line)
        )
        table_index = meta.get("table_index")
        return {
            "company_id": company_dir.name,
            "report_id": report_id,
            "task_id": task_id,
            "pdf_page": pdf_page,
            "table_index": table_index,
            "md_line": md_line,
            "sections": sections,
            "open_pdf_page_url": _evidence_url(task_id, pdf_page, table_index, "pdf"),
            "open_source_page_url": _evidence_url(task_id, pdf_page, table_index, "page"),
            "open_source_table_url": _evidence_url(task_id, pdf_page, table_index, "table"),
        }
    return _market_human_capital_table_result(message, context, extract=extract, parser=parser)


def _human_capital_section_table(
    title: str,
    rows: list[tuple[str, str]],
    *,
    total: int | None = None,
    include_ratio: bool = False,
) -> list[str]:
    if not rows:
        return []
    lines = [f"### {title}"]
    if include_ratio:
        lines.extend(["| 类别 | 人数 | 占比 |", "| --- | ---: | ---: |"])
        for label, value in rows:
            lines.append(f"| {label} | {value} | {_ratio_text(value, total)} |")
    else:
        lines.extend(["| 项目 | 人数 |", "| --- | ---: |"])
        for label, value in rows:
            lines.append(f"| {label} | {value} |")
    return lines


def _first_value(rows: list[tuple[str, str]], label: str) -> str:
    for row_label, value in rows:
        if row_label == label:
            return value
    return ""


def _render_market_human_capital_markdown(result: dict[str, Any]) -> str:
    rows = [row for row in (result.get("raw_rows") or []) if isinstance(row, list)]
    market = str(result.get("market") or "").upper()
    company_name = str(result.get("company_name") or result.get("company_id") or "该公司")
    lines = ["## 结论"]
    if market == "KR" and len(rows) >= 4 and any("사업부문" in str(cell) for cell in rows[0]):
        data_rows = [row for row in rows[3:] if len(row) >= 10]
        total_row = next((row for row in data_rows if str(row[0]).replace(" ", "") == "합계"), None)
        male_row = next((row for row in data_rows if str(row[0]) == "성별합계" and str(row[1]) == "남"), None)
        female_row = next((row for row in data_rows if str(row[0]) == "성별합계" and str(row[1]) == "여"), None)
        if total_row:
            lines.append(
                f"- {company_name} 本期披露的母公司员工总数为 **{total_row[6]} 人**，"
                f"平均工龄 **{total_row[7]} 年**。"
            )
        if male_row and female_row:
            lines.append(f"- 其中男性 **{male_row[6]} 人**，女性 **{female_row[6]} 人**。")
        footnote_text = " ".join(str(item) for item in (result.get("source_footnote") or []))
        if "본사(별도)" in footnote_text or "별도" in footnote_text:
            lines.append(
                "- 该表明确是总部/母公司单体口径，不是合并集团口径；当前底稿没有提供可核验的集团员工总数、学历或年龄分布，不能据此补写。"
            )
        else:
            lines.append("- 员工口径以原表及其脚注为准；当前表未披露的学历或年龄分布不能补写。")
        lines.extend(
            [
                "",
                "## 依据/数据",
                "| 业务部门 | 性别 | 正式员工 | 期间制员工 | 员工合计 | 平均工龄 | 年薪酬总额 | 人均薪酬 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in data_rows:
            lines.append(
                "| {business} | {gender} | {regular} | {fixed} | {total} | {tenure} | {payroll} | {average_pay} |".format(
                    business=_markdown_table_cell(row[0]),
                    gender=_markdown_table_cell(row[1]),
                    regular=_markdown_table_cell(row[2]),
                    fixed=_markdown_table_cell(row[4]),
                    total=_markdown_table_cell(row[6]),
                    tenure=_markdown_table_cell(row[7]),
                    payroll=_markdown_table_cell(row[8]),
                    average_pay=_markdown_table_cell(row[9]),
                )
            )
        footnotes = [str(item).strip() for item in (result.get("source_footnote") or []) if str(item).strip()]
        if footnotes:
            lines.extend(["", "### 原文口径", *[f"- {item}" for item in footnotes]])
    else:
        lines.append(f"- 已从 {market or '非 A 股'} PDF 解析产物定位到 {company_name} 的员工披露表；以下仅展示原表记录。")
        width = max((len(row) for row in rows), default=0)
        if width:
            lines.extend(["", "## 依据/数据"])
            header = [
                _markdown_table_cell(rows[0][index] if index < len(rows[0]) else "") or ("项目" if index == 0 else f"列 {index + 1}")
                for index in range(width)
            ]
            lines.append("| " + " | ".join(header) + " |")
            lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
            for row in rows[1:20]:
                cells = [_markdown_table_cell(row[index] if index < len(row) else "") for index in range(width)]
                lines.append("| " + " | ".join(cells) + " |")

    if "### 原文口径" not in lines:
        footnotes = [str(item).strip() for item in (result.get("source_footnote") or []) if str(item).strip()]
        if footnotes:
            lines.extend(["", "### 原文口径", *[f"- {item}" for item in footnotes]])

    links = []
    if result.get("open_pdf_page_url"):
        links.append(f"[打开PDF页]({result['open_pdf_page_url']})")
    if result.get("open_source_page_url"):
        links.append(f"[查看页来源]({result['open_source_page_url']})")
    if result.get("open_source_table_url"):
        links.append(f"[查看表格]({result['open_source_table_url']})")
    lines.extend(["", "## 引用来源"])
    lines.append(
        f"[1] source_type=wiki_report_table, file=reports/{result.get('report_id')}/report.md, "
        f"metric=employee_headcount, period={result.get('report_id')}, task_id={result.get('task_id')}, "
        f"pdf_page={result.get('pdf_page')}, table_index={result.get('table_index')}, md_line={result.get('md_line')}"
        + (("，" + "，".join(links)) if links else "")
    )
    return "\n".join(lines)


def render_human_capital_markdown(result: dict[str, Any]) -> str:
    if result.get("market_table"):
        return _render_market_human_capital_markdown(result)
    sections = result.get("sections") or {}
    scale = sections.get("scale") or []
    profession = sections.get("profession") or []
    education = sections.get("education") or []
    total_text = _first_value(scale, "在职员工的数量合计") or _first_value(profession, "合计") or _first_value(education, "合计")
    total = _parse_count(total_text)
    company_name = str(result.get("company_id") or "").split("-", 1)[-1] or "该公司"

    lines = ["## 结论"]
    if total_text:
        parent = _first_value(scale, "母公司在职员工的数量")
        subsidiaries = _first_value(scale, "主要子公司在职员工的数量")
        detail = []
        if parent:
            detail.append(f"母公司 {parent} 人")
        if subsidiaries:
            detail.append(f"主要子公司 {subsidiaries} 人")
        suffix = f"；其中{('，'.join(detail))}" if detail else ""
        lines.append(f"- **员工规模**：{company_name}在职员工数量合计 **{total_text} 人**{suffix}。")
    if profession:
        ranked = sorted(
            [(label, value, _parse_count(value) or -1) for label, value in profession if label != "合计"],
            key=lambda item: item[2],
            reverse=True,
        )
        if ranked:
            top = "、".join(
                f"{label} {value} 人"
                + (f"（{_ratio_text(value, total)}）" if _ratio_text(value, total) else "")
                for label, value, _count in ranked[:2]
            )
            lines.append(f"- **专业构成**：人数最多的类别为 {top}。")
    if education:
        ranked = sorted(
            [(label, value, _parse_count(value) or -1) for label, value in education if label != "合计"],
            key=lambda item: item[2],
            reverse=True,
        )
        if ranked:
            top = "、".join(
                f"{label} {value} 人"
                + (f"（{_ratio_text(value, total)}）" if _ratio_text(value, total) else "")
                for label, value, _count in ranked[:3]
            )
            lines.append(f"- **教育程度**：主要分布为 {top}。")

    lines.extend(["", "## 依据/数据"])
    lines.append(f"- 来源表：报告期末母公司和主要子公司的员工情况；pdf_page={result.get('pdf_page')}, table_index={result.get('table_index')}, md_line={result.get('md_line')}")
    lines.append("")
    lines.extend(_human_capital_section_table("员工规模", scale))
    if profession:
        lines.append("")
        lines.extend(_human_capital_section_table("专业构成", profession, total=total, include_ratio=True))
    if education:
        lines.append("")
        lines.extend(_human_capital_section_table("教育程度", education, total=total, include_ratio=True))

    links = []
    if result.get("open_pdf_page_url"):
        links.append(f"[打开PDF页]({result['open_pdf_page_url']})")
    if result.get("open_source_page_url"):
        links.append(f"[查看页来源]({result['open_source_page_url']})")
    if result.get("open_source_table_url"):
        links.append(f"[查看表格]({result['open_source_table_url']})")
    lines.extend(["", "## 引用来源"])
    lines.append(
        f"[1] source_type=wiki_report_table, file=reports/{result.get('report_id')}/report.md, "
        f"metric=员工情况/人才结构, period={result.get('report_id')}, task_id={result.get('task_id')}, "
        f"pdf_page={result.get('pdf_page')}, table_index={result.get('table_index')}, md_line={result.get('md_line')}"
        + (("，" + "，".join(links)) if links else "")
    )
    return "\n".join(lines)


def _result_has_research_identity_conflict(
    result: Mapping[str, Any],
    expected_identity: Mapping[str, str],
) -> bool:
    """Reject an otherwise stamped result when a nested scope disagrees."""

    # ``task_id`` is an independently usable source locator for some market
    # packages; it is not interchangeable with parse_run_id.
    aliases = {
        "market": "market",
        "company_id": "company_id",
        "companyid": "company_id",
        "filing_id": "filing_id",
        "filingid": "filing_id",
        "parse_run_id": "parse_run_id",
        "parserunid": "parse_run_id",
    }

    def walk(value: Any) -> bool:
        if isinstance(value, Mapping):
            for key, item in value.items():
                field = aliases.get(str(key).strip().lower().replace("-", "_"))
                if field and item not in (None, ""):
                    actual = str(item).strip()
                    expected = str(expected_identity.get(field) or "").strip()
                    if field == "market":
                        actual = actual.upper()
                        expected = expected.upper()
                    if expected and actual != expected:
                        return True
                if isinstance(item, (Mapping, list, tuple)) and walk(item):
                    return True
            return False
        if isinstance(value, (list, tuple)):
            return any(walk(item) for item in value)
        return False

    return walk(result)


def _statement_metric_result(message: str, context: Any | None = None) -> tuple[dict[str, Any] | None, Callable[..., str] | None]:
    resolver, renderer = _load_statement_metric_tools(context)
    if not resolver or not renderer:
        return None, None
    lookup_message = message
    goodwill_terms = ("商誉", "商譽", "goodwill", "のれん", "영업권")
    normalized_message = _normalize_financial_text(message)
    is_goodwill_query = any(term in normalized_message for term in goodwill_terms)
    if is_goodwill_query and not _is_goodwill_main_statement_query(message):
        lookup_message = f"{message} 资产负债表 商誉账面价值"
    company_hint = _context_company_hint(context)
    company_text_candidates = [message]
    if company_hint:
        company_text_candidates.append(company_hint)
        company_text_candidates.append(f"{message}\n{company_hint}")
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        company_text_candidates = [bound.name]
    for company_text in company_text_candidates:
        try:
            result = resolver(company_text, lookup_message)
        except Exception:
            continue
        if result.get("tables"):
            bound_result = _result_with_research_identity(result, context)
            expected_identity = agent_runtime_context.research_identity(context)
            if (
                expected_identity.get("market") in agent_runtime_context.NON_CN_RESEARCH_MARKETS
                and all(
                    expected_identity.get(field)
                    for field in agent_runtime_context.COMPLETE_RESEARCH_IDENTITY_FIELDS
                )
            ):
                actual_identity = agent_runtime_context.research_identity(bound_result)
                if (
                    _result_has_research_identity_conflict(bound_result, expected_identity)
                    or any(
                        actual_identity.get(field) != expected_identity[field]
                        for field in agent_runtime_context.COMPLETE_RESEARCH_IDENTITY_FIELDS
                    )
                ):
                    continue
            return bound_result, renderer
    return None, renderer


def _us_sec_geographical_revenue_result(
    message: str,
    context: Any | None = None,
) -> dict[str, Any] | None:
    """Resolve SEC revenue facts carrying the customer-headquarters dimension."""

    if not agent_runtime_sec_dimensions.geographical_revenue_query_applies(message):
        return None
    resolved_context = _resolved_research_context(message, context)
    identity = agent_runtime_context.research_identity(resolved_context)
    if identity.get("market") != "US" or not all(
        identity.get(field) for field in agent_runtime_context.COMPLETE_RESEARCH_IDENTITY_FIELDS
    ):
        return None
    company_dir = _resolve_company_dir(message, resolved_context)
    if not company_dir:
        return None
    report = _primary_report_for_company(company_dir, message, resolved_context)
    if report.get("selection_status") == "identity_mismatch":
        return None
    report_id = str(report.get("report_id") or "").strip()
    if not report_id:
        return None
    result = agent_runtime_sec_dimensions.resolve_us_geographical_revenue(
        company_dir,
        report_id,
        read_json_file=_read_json_file,
    )
    if not result:
        return None
    bound = _result_with_research_identity(result, resolved_context)
    bound_identity = agent_runtime_context.research_identity(bound)
    if any(bound_identity.get(field) != identity.get(field) for field in ("market", "company_id", "filing_id", "parse_run_id")):
        return None
    return bound


def build_us_sec_geographical_revenue_context(
    message: str,
    context: Any | None = None,
) -> str | None:
    result = _us_sec_geographical_revenue_result(message, context)
    if not result:
        return None
    return agent_runtime_sec_dimensions.render_us_geographical_revenue_context(result)


def _append_missing_us_geographical_revenue_refs(
    reply: str,
    result: Mapping[str, Any] | None,
) -> str:
    if not isinstance(result, Mapping):
        return reply
    rows = result.get("rows")
    if not isinstance(rows, list):
        return reply
    visible = "\n".join(_extract_reference_lines(reply))
    refs: list[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            continue
        anchor = str(row.get("source_anchor") or "").strip()
        evidence_id = str(row.get("evidence_id") or "").strip()
        if (anchor and anchor in visible) or (evidence_id and evidence_id in visible):
            continue
        refs.append(
            _primary_data_source_ref(
                index,
                source_type="sec_xbrl_fact",
                file=str(result.get("facts_file") or "xbrl/facts_raw.json"),
                metric=str(row.get("metric_name") or row.get("metric") or "地区营收"),
                period=row.get("period") or result.get("period"),
                task_id=None,
                pdf_page=None,
                table_index=None,
                md_line=None,
                canonical_name=row.get("canonical_name") or "operating_revenue",
                metric_name=row.get("metric_name") or row.get("region"),
                value=row.get("value"),
                raw_value=row.get("raw_value") or row.get("value"),
                unit=row.get("unit") or "USD",
                currency=row.get("currency") or "USD",
                scale=row.get("scale"),
                market=result.get("market") or "US",
                company_id=result.get("company_id"),
                report_id=result.get("report_id"),
                filing_id=result.get("filing_id"),
                parse_run_id=result.get("parse_run_id"),
                evidence_id=evidence_id,
                quote=row.get("quote"),
                evidence_source_type=row.get("evidence_source_type") or "sec_xbrl_fact",
                source_url=row.get("source_url") or result.get("source_url"),
                source_anchor=anchor,
                xbrl_tag=row.get("xbrl_tag"),
            )
        )
    return _merge_refs_into_reference_section(reply, refs) if refs else reply


def _correct_us_geographical_revenue_answer(
    reply: str,
    result: Mapping[str, Any] | None,
) -> str:
    """Replace stale no-data statements when SEC geography facts are present."""

    if not isinstance(result, Mapping) or not isinstance(result.get("rows"), list):
        return reply
    rows = [row for row in result["rows"] if isinstance(row, Mapping)]
    us_row = next((row for row in rows if row.get("member") == "country:US"), None)
    if us_row is None:
        return reply
    try:
        us_value = Decimal(str(us_row.get("value") or "").replace(",", ""))
    except (InvalidOperation, AttributeError):
        return reply
    if not us_value.is_finite():
        return reply
    replacement = (
        f"- 已披露按客户总部所在地划分的地区营收：美国为 {us_value / Decimal('1000000000'):.3f} billion USD"
        f"（{us_value / Decimal('100000000'):,.2f} 亿美元）。"
    )
    unavailable = re.compile(
        r"^\s*[-*]?\s*.*(?:未提供|未披露|无法|没有).*(?:地区|美国市场营收|geographic|region).*$",
        re.IGNORECASE,
    )
    lines = [replacement if unavailable.search(line) else line for line in (reply or "").splitlines()]
    normalized_reply = "\n".join(lines)
    expected_tokens = (
        f"{us_value / Decimal('1000000000'):.3f} billion USD",
        f"{us_value / Decimal('100000000'):,.2f} 亿美元",
        f"{us_value:,.0f} USD",
    )
    has_us_value = any(token in normalized_reply for token in expected_tokens) and any(
        term in normalized_reply for term in ("美国", "United States")
    )
    if has_us_value:
        return normalized_reply
    table_lines = [
        "## 地区营收（按客户总部所在地）",
        "| 客户总部所在地 | 营收（billion USD） | 营收（亿美元） |",
        "| --- | ---: | ---: |",
    ]
    for row in rows:
        try:
            value = Decimal(str(row.get("value") or "").replace(",", ""))
        except (InvalidOperation, AttributeError):
            continue
        table_lines.append(
            f"| {row.get('region') or row.get('region_en') or '未返回'} | "
            f"{value / Decimal('1000000000'):.3f} | {value / Decimal('100000000'):,.2f} |"
        )
    table = "\n".join(table_lines)
    reference_heading = re.search(r"(?m)^## 引用来源[:：]?\s*$", normalized_reply)
    if reference_heading:
        before = normalized_reply[: reference_heading.start()].rstrip()
        after = normalized_reply[reference_heading.start() :].lstrip()
        return f"{before}\n\n{table}\n\n{after}".strip()
    return f"{normalized_reply.rstrip()}\n\n{table}".strip()


def build_statement_metric_context(message: str, context: Any | None = None) -> str | None:
    """Inject deterministic main-statement rows for cash-flow/balance/profit questions."""
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    if not _is_statement_query(message):
        return None
    result, renderer = _statement_metric_result(message, context)
    if not result or not renderer:
        return None
    try:
        markdown = renderer(result, max_rows=40)
    except Exception:
        return None
    markdown = _normalize_wiki_metric_file_refs(markdown)
    return (
        "以下是后端从本地 Wiki 三大表结构化数据确定性解析出的主表数据，优先作为本题事实依据；"
        "主表指标不得改用 `semantic/document_links.json` 附注表溯源。\n"
        "涉及现金流/利润表/资产负债表核心数值时，必须保留 `source_type=wiki_metrics`、"
        "`file=metrics/three_statements.json`、`pdf_page/table_index/md_line`，不得编造或替换为其他页表。\n\n"
        f"{markdown}"
    )


def build_direct_statement_metric_reply(message: str, context: Any | None = None) -> str | None:
    """Return main-statement rows directly for deterministic statement data requests."""
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    if not _should_direct_answer_statement_query(message):
        return None
    result, renderer = _statement_metric_result(message, context)
    if not result or not renderer:
        return None
    try:
        return _normalize_wiki_metric_file_refs(renderer(result, max_rows=40))
    except Exception:
        return None


def _note_detail_result(
    message: str,
    context: Any | None = None,
    *,
    limit: int = 8,
) -> tuple[dict[str, Any] | None, Callable[..., str] | None]:
    resolver, renderer = _load_note_detail_tools()
    if not resolver or not renderer:
        return None, renderer

    company_hint = _context_company_hint(context)
    company_text_candidates = [message]
    if company_hint:
        company_text_candidates.append(company_hint)
        company_text_candidates.append(f"{message}\n{company_hint}")
    bound = agent_runtime_host_scope.company_dir()
    if bound is not None:
        company_text_candidates = [bound.name]

    metric_queries = [message]
    normalized_message = _normalize_financial_text(message)
    if any(term in normalized_message for term in ("商誉", "商譽", "goodwill", "のれん", "영업권")):
        # Compound questions with formulas/numbers can over-constrain the
        # semantic note matcher. Retry the same resolved company with the
        # canonical note subject instead of dropping the note evidence chain.
        metric_queries.append("商誉")
    for company_text in company_text_candidates:
        for metric_query in dict.fromkeys(metric_queries):
            try:
                result = resolver(company_text, metric_query, limit=limit)
            except Exception:
                continue
            if result.get("tables"):
                return _result_with_research_identity(result, context), renderer
    return None, renderer


def build_note_detail_context(message: str, context: Any | None = None) -> str | None:
    """Inject deterministic Wiki note-table rows for detail/composition questions."""
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    if not _should_inject_note_detail_context(message):
        return None

    result, renderer = _note_detail_result(message, context, limit=4)
    if not result:
        return None

    try:
        markdown = renderer(result, max_rows=12)
    except Exception:
        return None

    return (
        "以下是后端从本地 Wiki 确定性解析出的附注表格行，优先作为本题事实依据；"
        "不得再回答“非结构化所以无法展示”。\n"
        "如果用户询问明细/构成/分布，请完整列出表格记录；不要用“等/部分”省略行。"
        "英文名称必须原样保留，空白单元格不得改写为 `0`，不得调换列含义。\n"
        "回答时请保留或引用其中的 `source_type/file/task_id/pdf_page/table_index/md_line` 字段，"
        "并保留可打开表格链接。\n\n"
        f"{markdown}"
    )


def build_direct_note_detail_reply(message: str, context: Any | None = None) -> str | None:
    """Return the Wiki table directly for deterministic note-detail requests."""
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    if not _should_direct_answer_note_detail(message):
        return None

    result, renderer = _note_detail_result(message, context, limit=8)
    if result and renderer:
        return renderer(result, max_rows=80)
    return None


def build_human_capital_context(message: str, context: Any | None = None) -> str | None:
    """Inject deterministic employee/talent-structure table rows."""
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    result = _human_capital_result(message, context)
    if not result:
        return None
    return (
        "以下是后端从本地年报员工情况表确定性解析出的人才/人员结构数据，优先作为本题事实依据；"
        "不得沿用上一轮其他公司的员工数据，也不得把 `metrics/three_statements.json` 伪装成员工来源。\n"
        "回答时必须保留 `source_type/file/task_id/pdf_page/table_index/md_line`，并保留可打开表格链接。\n\n"
        f"{render_human_capital_markdown(result)}"
    )


def build_direct_human_capital_reply(message: str, context: Any | None = None) -> str | None:
    """Return employee/talent structure directly for deterministic HR table requests."""
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    result = _human_capital_result(message, context)
    if not result:
        return None
    return render_human_capital_markdown(result)


def deterministic_pdf_market_reply(message: str, context: Any | None = None) -> str | None:
    """Return parser-bound facts for intents where the table is fully deterministic."""
    if not _is_human_capital_query(message):
        return None
    return build_direct_human_capital_reply(message, context)


def _parse_number(value: Any) -> float | None:
    return agent_runtime_financial_format._parse_number(value)


def _row_numeric_values(row: list[str] | None) -> list[float]:
    return agent_runtime_financial_format._row_numeric_values(row)


def _find_report_table(tables: list[dict[str, Any]], *terms: str) -> dict[str, Any] | None:
    normalized_terms = [_normalize_financial_text(term) for term in terms if term]
    if not normalized_terms:
        return None
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for table in tables:
        text = _normalize_financial_text(" ".join(str(table.get(key) or "") for key in ("heading", "preview", "unit")))
        score = sum(1 for term in normalized_terms if term and term in text)
        if score <= 0:
            continue
        candidates.append((score, int(table.get("line") or 10**9), table))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], int(item[2].get("table_index") or 10**9)))
    return candidates[0][2]


def _find_group_income_statement_table(tables: list[dict[str, Any]], report_md: Path) -> dict[str, Any] | None:
    candidates: list[tuple[float, int, dict[str, Any]]] = []
    for table in tables:
        text = _normalize_financial_text(" ".join(str(table.get(key) or "") for key in ("heading", "preview", "unit")))
        if "statementofincome" not in text or "salesrevenue" not in text:
            continue
        row = _row_by_label(_parse_report_table_rows(report_md, table.get("line")), "Sales revenue")
        values = _row_numeric_values(row)
        if not values:
            continue
        candidates.append((values[0], int(table.get("line") or 10**9), table))
    if not candidates:
        return _find_report_table(tables, "Statement of income", "Sales revenue")
    candidates.sort(key=lambda item: (-item[0], item[1], int(item[2].get("table_index") or 10**9)))
    return candidates[0][2]


def _find_average_employee_table(tables: list[dict[str, Any]], report_md: Path) -> dict[str, Any] | None:
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for table in tables:
        text = _normalize_financial_text(" ".join(str(table.get(key) or "") for key in ("heading", "preview", "unit")))
        if "averagenumberofemployees" not in text:
            continue
        rows = _parse_report_table_rows(report_md, table.get("line"))
        labels = {_normalize_financial_text(row[0]) for row in rows if row}
        score = 1
        if _normalize_financial_text("BASF Group") in labels:
            score += 10
        if _normalize_financial_text("Europe") in labels and _normalize_financial_text("North America") in labels:
            score += 10
        candidates.append((score, int(table.get("line") or 10**9), table))
    if not candidates:
        return _find_report_table(tables, "Average number of employees")
    candidates.sort(key=lambda item: (-item[0], item[1], int(item[2].get("table_index") or 10**9)))
    return candidates[0][2]


def _latest_statement_rows_for_company(
    company_dir: Path,
    report_id: str,
    *,
    strict_report: bool = False,
) -> list[dict[str, Any]]:
    metrics_file = _company_artifact_paths(company_dir, report_id, strict_report).get("three_statements")
    if not metrics_file:
        return []
    payload = _read_json_file(metrics_file)
    if not isinstance(payload, dict):
        return []
    records = _latest_records_by_statement(_iter_metric_records(payload.get("data") or payload))
    return [
        _statement_record_to_row(record, report_id, metrics_file, company_dir)
        for record in records
    ]


def _find_statement_metric_row(rows: list[dict[str, Any]], aliases: tuple[str, ...]) -> dict[str, Any] | None:
    normalized_aliases = [_normalize_financial_text(alias) for alias in aliases if alias]
    for row in rows:
        key = _normalize_financial_text(row.get("metric_key"))
        name = _normalize_financial_text(row.get("metric_name"))
        if any(alias and (alias == key or alias in name) for alias in normalized_aliases):
            return row
    return None


def _human_capital_result_for_company(company_dir: Path) -> dict[str, Any] | None:
    return _human_capital_result(
        f"{_company_query_prefix(company_dir)} 员工情况",
        _context_for_company_dir(company_dir),
    )


def _employee_total_from_human_capital(result: dict[str, Any] | None) -> int | None:
    sections = (result or {}).get("sections") or {}
    for label, value in sections.get("scale") or []:
        if label == "在职员工的数量合计":
            return _parse_count(value)
    for rows in (sections.get("profession") or [], sections.get("education") or []):
        for label, value in rows:
            if label == "合计":
                count = _parse_count(value)
                if count:
                    return count
    return None


def _find_employee_compensation_table(
    tables: list[dict[str, Any]],
    report_md: Path,
) -> tuple[dict[str, Any], list[str], float | None] | None:
    candidates: list[tuple[int, int, dict[str, Any], list[str], float | None]] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        text = _normalize_financial_text(" ".join(str(table.get(key) or "") for key in ("heading", "preview", "unit")))
        score = 0
        if _normalize_financial_text("应付职工薪酬") in text:
            score += 30
        if _normalize_financial_text("短期薪酬") in text:
            score += 20
        if _normalize_financial_text("离职后福利") in text:
            score += 20
        if score <= 0:
            continue
        rows = _parse_report_table_rows(report_md, table.get("line"))
        total_row = _row_by_label(rows, "合计")
        values = _row_numeric_values(total_row)
        if total_row:
            score += 20
        if len(values) >= 4:
            score += 20
        increase = values[1] if len(values) > 1 else None
        candidates.append((score, int(table.get("line") or 10**9), table, total_row or [], increase))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1], int(item[2].get("table_index") or 10**9)))
    _score, _line, table, row, increase = candidates[0]
    return table, row, increase


def _generic_human_efficiency_result(message: str, context: Any | None = None) -> dict[str, Any] | None:
    company_dir = _resolve_company_dir(message, context)
    if not company_dir:
        return None
    report = _primary_report_for_company(company_dir, message, context)
    if report.get("selection_status") == "identity_mismatch":
        return None
    report_id = str(report.get("report_id") or "2025-annual")
    report_md = company_dir / "reports" / report_id / "report.md"
    report_json = _read_json_file(company_dir / "reports" / report_id / "report.json") or {}
    tables = report_json.get("tables") if isinstance(report_json, dict) else []
    if not isinstance(tables, list):
        tables = []

    statement_rows = _latest_statement_rows_for_company(
        company_dir,
        report_id,
        strict_report=report.get("selection_status") == "identity_exact",
    )
    revenue_row = _find_statement_metric_row(statement_rows, CORE_KEY_METRIC_ALIASES["营业收入"])
    parent_profit_row = _find_statement_metric_row(statement_rows, CORE_KEY_METRIC_ALIASES["归母净利润"])
    net_profit_row = _find_statement_metric_row(statement_rows, CORE_KEY_METRIC_ALIASES["净利润"])
    employee_result = _human_capital_result_for_company(company_dir)
    employee_total = _employee_total_from_human_capital(employee_result)
    compensation = _find_employee_compensation_table(tables, report_md)

    revenue = _parse_number((revenue_row or {}).get("raw_value") or (revenue_row or {}).get("normalized_value"))
    parent_profit = _parse_number((parent_profit_row or {}).get("raw_value") or (parent_profit_row or {}).get("normalized_value"))
    net_profit = _parse_number((net_profit_row or {}).get("raw_value") or (net_profit_row or {}).get("normalized_value"))
    compensation_table: dict[str, Any] | None = None
    compensation_row: list[str] = []
    compensation_increase: float | None = None
    if compensation:
        compensation_table, compensation_row, compensation_increase = compensation

    if not revenue or not employee_total:
        return None

    company = _read_json_file(company_dir / "company.json") or {}
    return {
        "mode": "generic_cny",
        "company_id": company_dir.name,
        "company_name": company.get("company_short_name") or company.get("company_full_name") or company_dir.name,
        "report_id": report_id,
        "task_id": report.get("task_id"),
        "rows": {
            "revenue": revenue_row,
            "parent_profit": parent_profit_row,
            "net_profit": net_profit_row,
        },
        "employee_result": employee_result,
        "compensation_table": compensation_table,
        "compensation_row": compensation_row,
        "values": {
            "revenue_2025": revenue,
            "parent_profit_2025": parent_profit,
            "net_profit_2025": net_profit,
            "employees_2025": employee_total,
            "compensation_increase_2025": compensation_increase,
        },
    }


def _parse_report_table_rows(report_md: Path, line: Any) -> list[list[str]]:
    module = _load_note_detail_module()
    extract = getattr(module, "extract_table_html", None) if module else None
    parser = getattr(module, "parse_html_table", None) if module else None
    if not callable(extract) or not callable(parser):
        return []
    md_line = _safe_int(line)
    if not md_line:
        return []
    try:
        parsed = parser(extract(report_md, md_line) or "")
    except Exception:
        return []
    rows = parsed.get("rows") if isinstance(parsed, dict) else None
    return [row for row in rows if isinstance(row, list)] if isinstance(rows, list) else []


def _row_by_label(rows: list[list[str]], label: str) -> list[str] | None:
    normalized_label = _normalize_financial_text(label)
    for row in rows:
        if row and normalized_label in _normalize_financial_text(row[0]):
            return row
    return None


def _table_source_links(task_id: Any, pdf_page: Any, table_index: Any) -> str:
    links: list[str] = []
    pdf_url = _evidence_url(task_id, pdf_page, table_index, "pdf")
    page_url = _evidence_url(task_id, pdf_page, table_index, "page")
    table_url = _evidence_url(task_id, pdf_page, table_index, "table")
    if pdf_url:
        links.append(f"[打开PDF页]({pdf_url})")
    if page_url:
        links.append(f"[查看页来源]({page_url})")
    if table_url:
        links.append(f"[查看表格]({table_url})")
    return "，".join(links)


def _table_trace(
    index: int,
    *,
    source_type: str,
    file: str,
    metric: str,
    report_id: str,
    task_id: Any,
    table: dict[str, Any],
) -> str:
    pdf_page = table.get("pdf_page_number") or table.get("pdf_page") or "未返回"
    table_index = table.get("table_index") if table.get("table_index") not in (None, "") else "未返回"
    links = _table_source_links(task_id, pdf_page, table_index)
    return agent_runtime_financial_format._table_trace(
        index,
        source_type=source_type,
        file=file,
        metric=metric,
        report_id=report_id,
        task_id=task_id,
        table=table,
        links=links,
    )


def _human_efficiency_result(message: str, context: Any | None = None) -> dict[str, Any] | None:
    if not _is_human_efficiency_query(message):
        return None
    company_dir = _resolve_company_dir(message, context)
    if not company_dir:
        return None
    report = _primary_report_for_company(company_dir, message, context)
    if report.get("selection_status") == "identity_mismatch":
        return None
    report_id = str(report.get("report_id") or "2025-annual")
    report_md = company_dir / "reports" / report_id / "report.md"
    report_json = _read_json_file(company_dir / "reports" / report_id / "report.json") or {}
    tables = report_json.get("tables") if isinstance(report_json, dict) else []
    if not isinstance(tables, list):
        return None

    income_table = _find_group_income_statement_table(tables, report_md)
    personnel_table = _find_report_table(tables, "Personnel expenses")
    employees_table = _find_report_table(tables, "Number of employees as of December")
    average_employees_table = _find_average_employee_table(tables, report_md)
    regional_sales_table = _find_report_table(tables, "Regions 2025", "Location of company", "Sales")
    if not all((income_table, personnel_table, employees_table)):
        return _generic_human_efficiency_result(message, context)

    income_row = _row_by_label(_parse_report_table_rows(report_md, income_table.get("line")), "Sales revenue")
    personnel_row = _row_by_label(_parse_report_table_rows(report_md, personnel_table.get("line")), "Personnel expenses")
    employee_rows = _parse_report_table_rows(report_md, employees_table.get("line"))
    avg_employee_rows = _parse_report_table_rows(report_md, average_employees_table.get("line") if average_employees_table else None)
    employees_group_row = _row_by_label(employee_rows, "BASF Group")
    avg_employees_group_row = _row_by_label(avg_employee_rows, "BASF Group")

    revenue_values = _row_numeric_values(income_row)
    personnel_values = _row_numeric_values(personnel_row)
    employee_values_group = _row_numeric_values(employees_group_row)
    avg_employee_values_group = _row_numeric_values(avg_employees_group_row)
    revenue_2025 = revenue_values[0] if len(revenue_values) > 0 else None
    revenue_2024 = revenue_values[1] if len(revenue_values) > 1 else None
    personnel_2025 = personnel_values[0] if len(personnel_values) > 0 else None
    personnel_2024 = personnel_values[1] if len(personnel_values) > 1 else None
    employees_2025 = employee_values_group[0] if len(employee_values_group) > 0 else None
    employees_2024 = employee_values_group[1] if len(employee_values_group) > 1 else None
    avg_employees_2025 = avg_employee_values_group[0] if len(avg_employee_values_group) > 0 else None
    avg_employees_2024 = avg_employee_values_group[1] if len(avg_employee_values_group) > 1 else None

    regional_rows: list[dict[str, Any]] = []
    if regional_sales_table:
        regional_sales_rows = _parse_report_table_rows(report_md, regional_sales_table.get("line"))
        location_company_sales_seen = False
        for row in regional_sales_rows:
            if row and _normalize_financial_text(row[0]) == _normalize_financial_text("Location of company"):
                location_company_sales_seen = True
                continue
            if not location_company_sales_seen or not row or _normalize_financial_text(row[0]) != "sales":
                continue
            region_specs = [
                ("Europe", "Europe", 2),
                ("North America", "North America", 4),
                ("Asia Pacific", "Asia Pacific", 5),
                ("South America, Africa and Middle East", "South America, Africa, Middle East", 6),
            ]
            employee_values = {
                _normalize_financial_text(employee_row[0]): _row_numeric_values(employee_row)[0]
                for employee_row in employee_rows
                if employee_row and _row_numeric_values(employee_row)
            }
            for region, employee_label, sales_index in region_specs:
                sales = _parse_number(row[sales_index]) if len(row) > sales_index else None
                employee_count = employee_values.get(_normalize_financial_text(employee_label))
                if sales is None or employee_count is None:
                    continue
                regional_rows.append(
                    {
                        "region": region,
                        "sales_million_eur": sales,
                        "employees": employee_count,
                        "revenue_per_employee": _calculator_per_capita(
                            sales,
                            amount_unit="百万欧元",
                            count=employee_count,
                            currency="EUR",
                        ),
                    }
                )
            break

    company = _read_json_file(company_dir / "company.json") or {}
    return {
        "company_id": company_dir.name,
        "company_name": company.get("company_short_name") or company.get("company_full_name") or company_dir.name,
        "report_id": report_id,
        "task_id": report.get("task_id"),
        "tables": {
            "income": income_table,
            "personnel": personnel_table,
            "employees": employees_table,
            "average_employees": average_employees_table,
            "regional_sales": regional_sales_table,
        },
        "values": {
            "revenue_2025": revenue_2025,
            "revenue_2024": revenue_2024,
            "personnel_2025": personnel_2025,
            "personnel_2024": personnel_2024,
            "employees_2025": employees_2025,
            "employees_2024": employees_2024,
            "avg_employees_2025": avg_employees_2025,
            "avg_employees_2024": avg_employees_2024,
        },
        "regional_rows": regional_rows,
    }


def _fmt_number(value: Any, digits: int = 1) -> str:
    return agent_runtime_financial_format._fmt_number(value, digits)


def _calculator_per_capita(
    amount: Any,
    *,
    amount_unit: str,
    count: Any,
    count_unit: str = "人",
    currency: str = "CNY",
) -> dict[str, Any] | None:
    if amount is None or count is None:
        return None
    calculator = _load_financial_calculator_module()
    try:
        payload = calculator.per_capita(
            SimpleNamespace(
                amount=str(amount),
                amount_unit=amount_unit,
                currency=currency,
                count=str(count),
                count_unit=count_unit,
                fx_to_cny="",
                fx_date="",
                fx_source="",
                reported_native_per="",
                reported_native_10k="",
                reported_cny_per="",
                reported_cny_10k="",
            )
        )
    except Exception:
        return None
    return payload if isinstance(payload, dict) and payload.get("status") == "ok" else payload


def _calculator_per_capita_display(payload: dict[str, Any] | None, *, preferred: str = "cny_10k") -> str:
    return agent_runtime_financial_format._calculator_per_capita_display(payload, preferred=preferred)


def _calculator_formula_text(payload: dict[str, Any] | None) -> str:
    return agent_runtime_financial_format._calculator_formula_text(payload)


def _statement_row_table(row: dict[str, Any] | None) -> dict[str, Any]:
    return agent_runtime_financial_format._statement_row_table(row)


def _render_generic_human_efficiency_evidence_markdown(result: dict[str, Any]) -> str:
    return agent_runtime_financial_format._render_generic_human_efficiency_evidence_markdown(
        result,
        calculator_per_capita=_calculator_per_capita,
        table_source_links=_table_source_links,
    )


def render_human_efficiency_evidence_markdown(result: dict[str, Any]) -> str:
    return agent_runtime_financial_format.render_human_efficiency_evidence_markdown(
        result,
        calculator_per_capita=_calculator_per_capita,
        table_source_links=_table_source_links,
    )


def build_human_efficiency_evidence_context(message: str, context: Any | None = None) -> str | None:
    if _non_cn_financial_retrieval_blocked(message, context):
        return None
    result = _human_efficiency_result(message, context)
    if not result:
        return None
    return (
        "以下是后端从本地年报表格确定性解析出的人效/人均财务指标底稿。"
        "回答涉及人均营收、人力成本、人均人力成本、区域人效时，必须逐项保留到唯一的 `## 引用来源`。"
        "派生指标必须说明分子、分母和对应 PDF/表格来源。\n\n"
        f"{render_human_efficiency_evidence_markdown(result)}"
    )


def append_human_efficiency_evidence_if_needed(
    message: str,
    context: Any | None,
    reply: str,
) -> str:
    if not _is_human_efficiency_query(message):
        return reply
    reply = _merge_primary_data_refs_into_citations(reply)
    evidence = build_human_efficiency_evidence_context(message, context)
    if not evidence:
        return reply
    return _merge_primary_data_refs_into_citations(reply, evidence)


def _has_primary_data_evidence_trace(reply: str) -> bool:
    return agent_runtime_citations._has_primary_data_evidence_trace(
        reply,
        markers=PRIMARY_DATA_EVIDENCE_MARKERS,
    )


def _source_locator_text(
    *,
    task_id: Any,
    pdf_page: Any,
    table_index: Any,
    md_line: Any,
) -> str:
    return agent_runtime_citations._source_locator_text(
        task_id=task_id,
        pdf_page=pdf_page,
        table_index=table_index,
        md_line=md_line,
        table_source_links=_table_source_links,
    )


def _primary_data_source_ref(
    index: int,
    *,
    source_type: str,
    file: str,
    metric: str,
    period: Any,
    task_id: Any,
    pdf_page: Any,
    table_index: Any,
    md_line: Any,
    **structured_fields: Any,
) -> str:
    return agent_runtime_citations._primary_data_source_ref(
        index,
        source_type=source_type,
        file=file,
        metric=metric,
        period=period,
        task_id=task_id,
        pdf_page=pdf_page,
        table_index=table_index,
        md_line=md_line,
        table_source_links=_table_source_links,
        **structured_fields,
    )


def _append_unique_source_ref(
    refs: list[str],
    seen: set[tuple[Any, Any, Any, str, str]],
    *,
    source_type: str,
    file: str,
    metric: str,
    period: Any,
    task_id: Any,
    pdf_page: Any,
    table_index: Any,
    md_line: Any,
) -> None:
    agent_runtime_citations._append_unique_source_ref(
        refs,
        seen,
        source_type=source_type,
        file=file,
        metric=metric,
        period=period,
        task_id=task_id,
        pdf_page=pdf_page,
        table_index=table_index,
        md_line=md_line,
        table_source_links=_table_source_links,
    )


def _markdown_heading(line: str) -> tuple[int, str] | None:
    return agent_runtime_citations._markdown_heading(line)


def _is_reference_line(line: str) -> bool:
    return agent_runtime_citations._is_reference_line(line)


def _extract_reference_lines(lines: list[str] | str) -> list[str]:
    return agent_runtime_citations._extract_reference_lines(lines)


def _source_field_value(line: str, field: str) -> str:
    return agent_runtime_citations._source_field_value(line, field)


def _source_reference_key(line: str) -> tuple[str, str, str, str] | tuple[str]:
    return agent_runtime_citations._source_reference_key(line)


def _reply_has_requested_metric_evidence(message: str, reply: str) -> bool:
    return agent_runtime_citations._reply_has_requested_metric_evidence(
        message,
        reply,
        postgres_requested_metric_terms=_postgres_requested_metric_terms,
        normalize_financial_text=_normalize_financial_text,
    )


def _reply_has_wiki_metrics_source(reply: str) -> bool:
    return agent_runtime_financial_sources.reply_has_wiki_metrics_source(
        reply,
        deps=_primary_data_evidence_dependencies(),
    )


def _reply_has_wiki_note_source(reply: str) -> bool:
    return agent_runtime_financial_sources.reply_has_wiki_note_source(
        reply,
        deps=_primary_data_evidence_dependencies(),
    )


def _reply_missing_required_wiki_source(message: str, reply: str) -> bool:
    return agent_runtime_financial_sources.reply_missing_required_wiki_source(
        message,
        reply,
        deps=_primary_data_evidence_dependencies(),
    )


def _strip_auto_evidence_sections(markdown: str) -> tuple[str, list[str]]:
    return agent_runtime_citations._strip_auto_evidence_sections(
        markdown,
        auto_evidence_section_titles=AUTO_EVIDENCE_SECTION_TITLES,
    )


def _merge_refs_into_reference_section(markdown: str, refs: list[str]) -> str:
    return agent_runtime_citations._merge_refs_into_reference_section(markdown, refs)


def _merge_primary_data_refs_into_citations(reply: str, supplement: str | None = None) -> str:
    return agent_runtime_citations._merge_primary_data_refs_into_citations(
        reply,
        supplement,
        auto_evidence_section_titles=AUTO_EVIDENCE_SECTION_TITLES,
    )


def _render_three_statement_primary_data_supplement(result: dict[str, Any]) -> str | None:
    if result.get("validation_blocked"):
        return None
    markdown = agent_runtime_citations._render_three_statement_primary_data_supplement(
        result,
        primary_data_supplement_max_rows=PRIMARY_DATA_SUPPLEMENT_MAX_ROWS,
        table_source_links=_table_source_links,
    )
    return _normalize_wiki_metric_file_refs(markdown) if markdown else None


def _first_record_label(record: dict[str, Any]) -> str:
    return agent_runtime_citations._first_record_label(record)


def _record_values_preview(record: dict[str, Any], *, max_values: int = 4) -> str:
    return agent_runtime_citations._record_values_preview(record, max_values=max_values)


def _render_statement_table_primary_data_supplement(result: dict[str, Any]) -> str | None:
    markdown = agent_runtime_citations._render_statement_table_primary_data_supplement(
        result,
        primary_data_supplement_max_rows=PRIMARY_DATA_SUPPLEMENT_MAX_ROWS,
        table_source_links=_table_source_links,
    )
    return _normalize_wiki_metric_file_refs(markdown) if markdown else None


def _render_note_detail_primary_data_supplement(result: dict[str, Any]) -> str | None:
    return agent_runtime_citations._render_note_detail_primary_data_supplement(
        result,
        primary_data_supplement_max_rows=PRIMARY_DATA_SUPPLEMENT_MAX_ROWS,
        table_source_links=_table_source_links,
    )


def _render_human_capital_primary_data_supplement(result: dict[str, Any]) -> str | None:
    return agent_runtime_citations._render_human_capital_primary_data_supplement(
        result,
        primary_data_supplement_max_rows=PRIMARY_DATA_SUPPLEMENT_MAX_ROWS,
        table_source_links=_table_source_links,
    )


def _render_wiki_fulltext_primary_data_supplement(result: dict[str, Any]) -> str | None:
    return agent_runtime_citations._render_wiki_fulltext_primary_data_supplement(
        result,
        primary_data_supplement_max_rows=PRIMARY_DATA_SUPPLEMENT_MAX_ROWS,
        table_source_links=_table_source_links,
    )


def _render_postgres_primary_data_supplement(result: dict[str, Any]) -> str | None:
    return agent_runtime_citations._render_postgres_primary_data_supplement(
        result,
        primary_data_supplement_max_rows=PRIMARY_DATA_SUPPLEMENT_MAX_ROWS,
        evidence_url=_evidence_url,
        markdown_table_cell=_markdown_table_cell,
        table_source_links=_table_source_links,
        postgres_row_pdf_page=_postgres_row_pdf_page,
        postgres_row_table_index=_postgres_row_table_index,
        postgres_row_md_line=_postgres_row_md_line,
        postgres_row_metric_name=_postgres_row_metric_name,
        postgres_row_value=_postgres_row_value,
        postgres_row_unit=_postgres_row_unit,
    )


def _primary_data_evidence_dependencies() -> agent_runtime_financial_sources.PrimaryDataEvidenceDependencies:
    return agent_runtime_financial_sources.PrimaryDataEvidenceDependencies(
        extract_reference_lines=_extract_reference_lines,
        source_field_value=_source_field_value,
        is_statement_query=_is_statement_query,
        should_inject_note_detail_context=_should_inject_note_detail_context,
        has_structured_evidence_trace=_has_structured_evidence_trace,
        is_runtime_status_reply=_is_runtime_status_reply,
        reply_has_requested_metric_evidence=_reply_has_requested_metric_evidence,
        merge_primary_data_refs_into_citations=_merge_primary_data_refs_into_citations,
        human_efficiency_result=_human_efficiency_result,
        render_human_efficiency_evidence_markdown=render_human_efficiency_evidence_markdown,
        human_capital_result=_human_capital_result,
        render_human_capital_primary_data_supplement=_render_human_capital_primary_data_supplement,
        statement_metric_result=_statement_metric_result,
        render_statement_table_primary_data_supplement=_render_statement_table_primary_data_supplement,
        three_statement_core_result=_three_statement_core_result,
        render_three_statement_primary_data_supplement=_render_three_statement_primary_data_supplement,
        note_detail_result=_note_detail_result,
        render_note_detail_primary_data_supplement=_render_note_detail_primary_data_supplement,
        wiki_fulltext_fallback_result=_wiki_fulltext_fallback_result,
        render_wiki_fulltext_primary_data_supplement=_render_wiki_fulltext_primary_data_supplement,
        record_postgres_fallback_event=agent_runtime_postgres_fallback.record_postgres_fallback_event,
        audit_context_with_fallback_event=agent_runtime_postgres_fallback.audit_context_with_fallback_event,
        postgres_fallback_result=_postgres_fallback_result,
        render_postgres_primary_data_supplement=_render_postgres_primary_data_supplement,
    )


def build_primary_data_evidence_supplement(message: str, context: Any | None = None) -> str | None:
    return agent_runtime_financial_sources.build_primary_data_evidence_supplement(
        message,
        context,
        deps=_primary_data_evidence_dependencies(),
    )


def append_primary_data_evidence_if_needed(
    message: str,
    context: Any | None,
    reply: str,
) -> str:
    return agent_runtime_financial_sources.append_primary_data_evidence_if_needed(
        message,
        context,
        reply,
        deps=_primary_data_evidence_dependencies(),
    )


def _load_financial_query_api() -> Any | None:
    return agent_runtime_postgres_fallback.load_financial_query_api()


def _financial_query_connection_factory(module: Any) -> Callable[[], Any] | None:
    return agent_runtime_postgres_fallback.financial_query_connection_factory(module)


def _should_consider_postgres_fallback(message: str, context: Any | None = None) -> bool:
    return agent_runtime_postgres_fallback.should_consider_postgres_fallback(
        message,
        context,
        is_general_assistant_request=_is_general_assistant_request,
        is_human_capital_query=_is_human_capital_query,
        is_statement_query=_is_statement_query,
        should_inject_note_detail_context=_should_inject_note_detail_context,
        postgres_fallback_terms=POSTGRES_FALLBACK_TERMS,
        context_company=_context_company,
    )


def _postgres_query_text(message: str, context: Any | None = None) -> str:
    return agent_runtime_postgres_fallback.postgres_query_text(
        message,
        context,
        context_company_hint=_context_company_hint,
    )


def _answer_audit_trace_id(record: Mapping[str, Any] | None) -> str | None:
    if not record:
        return None
    trace_id = str(record.get("trace_id") or "").strip()
    return trace_id if agent_runtime_answer_audit.is_answer_audit_trace_id(trace_id) else None


def _postgres_prepare_parsed(parsed: dict[str, Any], message: str) -> dict[str, Any]:
    return agent_runtime_postgres_fallback.postgres_prepare_parsed(parsed, message)


def _postgres_requested_metric_terms(message: str) -> list[str]:
    return agent_runtime_postgres_fallback.postgres_requested_metric_terms(
        message,
        financial_note_metric_terms=FINANCIAL_NOTE_METRIC_TERMS,
        core_key_metric_terms=CORE_KEY_METRIC_TERMS,
        core_key_metric_aliases=CORE_KEY_METRIC_ALIASES,
    )


def _postgres_row_matches_requested_terms(row: dict[str, Any], requested_terms: list[str]) -> bool:
    return agent_runtime_postgres_fallback.postgres_row_matches_requested_terms(
        row,
        requested_terms,
        normalize_financial_text=_normalize_financial_text,
        postgres_row_payload=_postgres_row_payload,
    )


def _postgres_query_metric_rows(
    module: Any,
    cur: Any,
    parsed: dict[str, Any],
    company: dict[str, Any],
    query_text: str,
    limit: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    return agent_runtime_postgres_fallback.postgres_query_metric_rows(
        module,
        cur,
        parsed,
        company,
        query_text,
        limit,
    )


def _postgres_market_agent_view_result(
    module: Any,
    message: str,
    context: Any | None,
    parsed: dict[str, Any],
    query_text: str,
    limit: int,
) -> dict[str, Any] | None:
    def log_exception(exc: BaseException) -> None:
        logger.info("market agent view fallback failed", exc_info=exc)

    return agent_runtime_postgres_fallback.postgres_market_agent_view_result(
        module,
        message,
        context,
        parsed,
        query_text,
        limit,
        context_company=_context_company,
        log_exception=log_exception,
    )


def _postgres_enrich_rows_with_table_pages(cur: Any, rows: list[dict[str, Any]]) -> None:
    agent_runtime_postgres_fallback.postgres_enrich_rows_with_table_pages(
        cur,
        rows,
        postgres_row_pdf_page=_postgres_row_pdf_page,
        postgres_row_table_index=_postgres_row_table_index,
    )


def _postgres_fallback_dependencies() -> agent_runtime_postgres_fallback.PostgresFallbackDependencies:
    def normalize_json(module: Any, value: Any) -> Any:
        return module.normalize_json(value)

    def log_exception(exc: BaseException) -> None:
        logger.info("legacy PostgreSQL fallback failed", exc_info=exc)

    return agent_runtime_postgres_fallback.PostgresFallbackDependencies(
        should_consider_postgres_fallback=_should_consider_postgres_fallback,
        record_postgres_fallback_event=agent_runtime_postgres_fallback.record_postgres_fallback_event,
        load_financial_query_api=_load_financial_query_api,
        postgres_query_text=_postgres_query_text,
        postgres_prepare_parsed=_postgres_prepare_parsed,
        postgres_market_agent_view_result=_postgres_market_agent_view_result,
        financial_query_connection_factory=_financial_query_connection_factory,
        postgres_requested_metric_terms=_postgres_requested_metric_terms,
        postgres_query_metric_rows=_postgres_query_metric_rows,
        postgres_row_matches_requested_terms=_postgres_row_matches_requested_terms,
        postgres_enrich_rows_with_table_pages=_postgres_enrich_rows_with_table_pages,
        normalize_json=normalize_json,
        log_exception=log_exception,
    )


def _postgres_fallback_result(
    message: str,
    context: Any | None = None,
    *,
    limit: int = POSTGRES_FALLBACK_ROW_LIMIT,
) -> dict[str, Any] | None:
    resolved_context = _resolved_research_context(message, context)
    result = agent_runtime_postgres_fallback.postgres_fallback_result(
        message,
        resolved_context,
        limit=limit,
        deps=_postgres_fallback_dependencies(),
    )
    # Identity completion stays local, but fallback decisions are audit state
    # and must survive after this helper returns.
    if isinstance(context, dict):
        events = resolved_context.get("_audit_fallback_events")
        if isinstance(events, list):
            context["_audit_fallback_events"] = list(events)
        fallback_reason = resolved_context.get("fallback_reason")
        if fallback_reason:
            context.setdefault("fallback_reason", fallback_reason)
    return result


def _render_postgres_fallback_context(result: dict[str, Any]) -> str:
    return agent_runtime_citations._render_postgres_fallback_context(
        result,
        evidence_url=_evidence_url,
        markdown_table_cell=_markdown_table_cell,
        table_source_links=_table_source_links,
        postgres_row_pdf_page=_postgres_row_pdf_page,
        postgres_row_table_index=_postgres_row_table_index,
        postgres_row_md_line=_postgres_row_md_line,
        postgres_row_metric_name=_postgres_row_metric_name,
        postgres_row_value=_postgres_row_value,
        postgres_row_unit=_postgres_row_unit,
    )


def _postgres_fallback_context_dependencies() -> agent_runtime_postgres_fallback.PostgresFallbackContextDependencies:
    return agent_runtime_postgres_fallback.PostgresFallbackContextDependencies(
        record_postgres_fallback_event=agent_runtime_postgres_fallback.record_postgres_fallback_event,
        audit_context_with_fallback_event=agent_runtime_postgres_fallback.audit_context_with_fallback_event,
        postgres_fallback_result=_postgres_fallback_result,
        render_postgres_fallback_context=_render_postgres_fallback_context,
    )


def build_postgres_fallback_context(message: str, context: Any | None = None) -> str | None:
    return agent_runtime_postgres_fallback.build_postgres_fallback_context(
        message,
        context,
        deps=_postgres_fallback_context_dependencies(),
    )


def _needs_financial_evidence_contract(message: str, context: Any | None = None) -> bool:
    if agent_memory_analytics.is_memory_management_query(message):
        return False
    if _is_runtime_connectivity_question(message):
        return False
    return (
        _is_human_efficiency_query(message)
        or _is_statement_query(message)
        or _should_inject_note_detail_context(message)
        or _question_needs_three_statement_context(message, context)
        or _should_consider_wiki_fulltext_fallback(message, context)
        or _should_consider_postgres_fallback(message, context)
        or _should_consider_pdf2md_parse_only_context(message, context)
    )


def _non_cn_financial_retrieval_blocked(message: str, context: Any | None = None) -> bool:
    if not _needs_financial_evidence_contract(message, context):
        return False
    market, missing_fields = agent_runtime_context.incomplete_non_cn_research_identity(context)
    return bool(market and missing_fields)


def _has_structured_evidence_trace(reply: str) -> bool:
    return agent_runtime_citations._has_structured_evidence_trace(reply)


def _financial_llm_model_identity(profile: HermesProfile) -> tuple[str, str]:
    return agent_runtime_financial_provenance.model_identity_for_profile(
        _runtime_profile(profile),
        profile_dirs=HERMES_PROFILE_DIRS,
    )


def _record_financial_llm_provenance_if_needed(
    *,
    message: str,
    context: Any | None,
    profile: HermesProfile,
    model_input: Any,
    raw_output: str,
    stored_output: str,
    attachments: Any | None = None,
    terminal_runtime: Any | None = None,
    runtime_provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    return agent_runtime_financial_provenance.record_financial_llm_provenance_if_needed(
        message=message,
        context=context,
        profile=_runtime_profile(profile),
        model_input=model_input,
        raw_output=raw_output,
        stored_output=stored_output,
        attachments=attachments,
        profile_dirs=HERMES_PROFILE_DIRS,
        runtime_metadata=terminal_runtime,
        runtime_provenance=runtime_provenance,
        is_runtime_status_reply=_is_runtime_status_reply,
        needs_financial_evidence_contract=_needs_financial_evidence_contract,
    )


def _is_runtime_status_reply(reply: str) -> bool:
    return agent_runtime_financial_guard._is_runtime_status_reply(reply, runtime_status_prefixes=RUNTIME_STATUS_PREFIXES)


def _reply_has_derived_financial_metric(reply: str) -> bool:
    return agent_runtime_financial_guard._reply_has_derived_financial_metric(reply)


def _reply_has_calculator_trace(reply: str) -> bool:
    return agent_runtime_financial_guard._reply_has_calculator_trace(reply)


def _reply_has_reconciliation_trace(reply: str) -> bool:
    return agent_runtime_financial_guard._reply_has_reconciliation_trace(reply)


def _reply_has_reconciliation_metric(reply: str) -> bool:
    return agent_runtime_financial_guard._reply_has_reconciliation_metric(reply)


def append_financial_tool_availability_correction_if_needed(reply: str) -> str:
    return agent_runtime_financial_guard.append_financial_tool_availability_correction_if_needed(
        reply,
        calculator_path=FINANCIAL_CALCULATOR_PATH,
        reconciliation_validator_path=FINANCIAL_RECONCILIATION_VALIDATOR_PATH,
    )


def append_calculation_trace_warning_if_needed(message: str, reply: str) -> str:
    return agent_runtime_financial_guard.append_calculation_trace_warning_if_needed(
        message,
        reply,
        runtime_status_prefixes=RUNTIME_STATUS_PREFIXES,
        calculator_path=FINANCIAL_CALCULATOR_PATH,
        reconciliation_validator_path=FINANCIAL_RECONCILIATION_VALIDATOR_PATH,
        calculator_path_text=FINANCIAL_CALCULATOR_PATH_TEXT,
        reconciliation_validator_path_text=FINANCIAL_RECONCILIATION_VALIDATOR_PATH_TEXT,
    )


def _trusted_financial_calculation_evidence(
    message: str,
    context: Any | None,
) -> tuple[Mapping[str, Any], ...]:
    resolved_context = _resolved_research_context(message, context)
    identity = agent_runtime_context.research_identity(resolved_context)
    if not all(identity.get(field) for field in agent_runtime_context.COMPLETE_RESEARCH_IDENTITY_FIELDS):
        return ()
    statement_result, _statement_renderer = _statement_metric_result(message, resolved_context)
    note_result: Mapping[str, Any] | None = None
    if _should_inject_note_detail_context(message):
        note_result, _note_renderer = _note_detail_result(message, resolved_context, limit=8)
    evidence = list(
        agent_runtime_financial_evidence.build_trusted_calculation_evidence(
            statement_result=statement_result,
            note_result=note_result,
            expected_identity=identity,
        )
    )
    core_result = _three_statement_core_result(message, resolved_context)
    if isinstance(core_result, Mapping):
        core_identity = agent_runtime_context.research_identity(core_result)
        if all(
            not core_identity.get(field) or core_identity.get(field) == identity.get(field)
            for field in ("market", "company_id", "filing_id")
        ):
            metrics_file = Path(str(core_result.get("metrics_file") or ""))
            company_dir = Path(str(core_result.get("company_dir") or ""))
            metric_keys = {
                str(row.get("metric_key") or "").strip()
                for row in core_result.get("rows") or ()
                if isinstance(row, Mapping) and str(row.get("metric_key") or "").strip()
            }
            payload = _read_json_file(metrics_file) if metrics_file.is_file() else None
            if metric_keys and isinstance(payload, Mapping):
                rows = [
                    _statement_record_to_row(record, str(core_result.get("report_id") or ""), metrics_file, company_dir)
                    for record in _iter_metric_records(payload.get("data") or payload)
                    if str(record.get("metric_key") or record.get("canonical_name") or "").strip() in metric_keys
                ]
                evidence.extend(
                    agent_runtime_financial_evidence.build_trusted_statement_row_evidence(
                        rows,
                        expected_identity=identity,
                    )
                )
    geographical_result = _us_sec_geographical_revenue_result(message, resolved_context)
    if geographical_result:
        evidence.extend(
            agent_runtime_financial_evidence.build_trusted_sec_dimension_evidence(
                geographical_result,
                expected_identity=identity,
            )
        )
    normalized_message = _normalize_financial_text(message)
    if any(term in normalized_message for term in ("偿债", "流动性", "现金流", "现金流量")):
        company_hint = _context_company_hint(resolved_context) or message
        cashflow_result, _cashflow_renderer = _statement_metric_result(
            f"{company_hint} 经营活动现金流量净额",
            resolved_context,
        )
        evidence.extend(
            agent_runtime_financial_evidence.build_trusted_calculation_evidence(
                statement_result=cashflow_result,
                note_result=None,
                expected_identity=identity,
            )
        )
    if any(term in normalized_message for term in ("商誉", "商譽", "goodwill", "のれん", "영업권")):
        # Goodwill analysis commonly compares the main-statement net amount
        # with total assets and parent equity even when the user did not name
        # those denominators explicitly. Resolve the same report's balance
        # sheet totals up front so any such ratio remains source-bound.
        company_hint = _context_company_hint(resolved_context) or message
        scale_result, _scale_renderer = _statement_metric_result(
            f"{company_hint} 总资产",
            resolved_context,
        )
        scale_evidence = agent_runtime_financial_evidence.build_trusted_calculation_evidence(
            statement_result=scale_result,
            note_result=None,
            expected_identity=identity,
        )
        evidence.extend(
            item
            for item in scale_evidence
            if str(item.get("metric") or "")
            in {"total_assets", "parent_shareholders_equity"}
        )
    seen: set[str] = set()
    output: list[Mapping[str, Any]] = []
    for item in evidence:
        evidence_id = str(item.get("evidence_id") or "")
        if not evidence_id or evidence_id in seen:
            continue
        seen.add(evidence_id)
        output.append(item)
    return tuple(output)


def _financial_evidence_contract_dependencies() -> agent_runtime_financial_guard.FinancialEvidenceContractDependencies:
    return agent_runtime_financial_guard.FinancialEvidenceContractDependencies(
        build_primary_data_evidence_supplement=build_primary_data_evidence_supplement,
        merge_primary_data_refs_into_citations=_merge_primary_data_refs_into_citations,
        build_human_efficiency_evidence_context=build_human_efficiency_evidence_context,
        build_three_statement_core_context=build_three_statement_core_context,
        is_statement_query=_is_statement_query,
        statement_metric_result=_statement_metric_result,
        should_inject_note_detail_context=_should_inject_note_detail_context,
        note_detail_result=_note_detail_result,
        build_wiki_fulltext_fallback_context=build_wiki_fulltext_fallback_context,
        build_postgres_fallback_context=build_postgres_fallback_context,
        build_pdf2md_parse_only_context=build_pdf2md_parse_only_context,
        is_runtime_status_reply=_is_runtime_status_reply,
        invalid_task_ids_in_reply=_invalid_task_ids_in_reply,
        needs_financial_evidence_contract=_needs_financial_evidence_contract,
        append_primary_data_evidence_if_needed=append_primary_data_evidence_if_needed,
        append_calculation_trace_warning_if_needed=append_calculation_trace_warning_if_needed,
        has_primary_data_evidence_trace=_has_primary_data_evidence_trace,
        has_structured_evidence_trace=_has_structured_evidence_trace,
    )


def build_financial_evidence_fallback_reply(message: str, context: Any | None = None) -> str | None:
    return agent_runtime_financial_guard.build_financial_evidence_fallback_reply(
        message,
        context,
        deps=_financial_evidence_contract_dependencies(),
    )


def recover_financial_tool_loop_reply(
    message: str,
    context: Any | None,
    reply: str,
) -> str | None:
    return agent_runtime_financial_guard.recover_financial_tool_loop_reply(
        message,
        context,
        reply,
        deps=_financial_evidence_contract_dependencies(),
    )


def build_invalid_task_id_evidence_reply(
    message: str,
    context: Any | None,
    invalid_task_ids: list[str],
) -> str:
    return agent_runtime_financial_guard.build_invalid_task_id_evidence_reply(
        message,
        context,
        invalid_task_ids,
        deps=_financial_evidence_contract_dependencies(),
    )


def enforce_financial_evidence_contract(
    message: str,
    context: Any | None,
    reply: str,
) -> str:
    reply = strip_guardrail_diagnostics(reply)
    resolved_context = _resolved_research_context(message, context)
    geographical_result = _us_sec_geographical_revenue_result(message, resolved_context)
    reply = _append_missing_us_geographical_revenue_refs(reply, geographical_result)
    trusted_evidence = _trusted_financial_calculation_evidence(message, resolved_context)
    reply = agent_runtime_citations.sanitize_sec_xbrl_reference_lines(
        reply,
        trusted_evidence,
        table_source_links=_table_source_links,
    )
    reply = _append_missing_calculation_evidence_locators(reply, trusted_evidence)
    reply = agent_runtime_financial_claim_verifier.correct_evidence_bound_unit_normalizations(
        reply,
        trusted_evidence,
    )
    reply = _correct_us_geographical_revenue_answer(reply, geographical_result)
    baseline_events = list(resolved_context.get("_audit_fallback_events") or [])
    guarded_reply = agent_runtime_financial_guard.enforce_financial_evidence_contract(
        message,
        resolved_context,
        reply,
        deps=_financial_evidence_contract_dependencies(),
        trusted_calculation_runs=agent_runtime_financial_trace.current_trusted_runs(),
        trusted_calculation_evidence=trusted_evidence,
        deterministic_calculation_pack=agent_runtime_financial_evidence.render_deterministic_calculation_pack(
            trusted_evidence
        ),
        strict_validation=True,
    )
    guarded_reply = _strip_inline_financial_evidence_labels_for_display(guarded_reply)
    if isinstance(context, dict):
        resolved_events = list(resolved_context.get("_audit_fallback_events") or [])
        new_events = resolved_events[len(baseline_events) :]
        target_events = context.setdefault("_audit_fallback_events", [])
        if isinstance(target_events, list):
            for event in new_events:
                if event not in target_events:
                    target_events.append(event)
    return guarded_reply


_INLINE_FINANCIAL_EVIDENCE_LABEL_RE = re.compile(
    r"(?:\[|〔)(?:calc|recon|trusted):[^\]\n〕]+(?:\]|〕)",
    re.IGNORECASE,
)
_INLINE_FINANCIAL_EVIDENCE_EXPRESSION_RE = re.compile(
    r"[（(]\s*"
    r"(?:\[|〔)(?:calc|recon|trusted):[^\]\n〕]+(?:\]|〕)"
    r"(?:\s*[/÷+\-]\s*(?:\[|〔)(?:calc|recon|trusted):[^\]\n〕]+(?:\]|〕))*"
    r"\s*[)）]",
    re.IGNORECASE,
)


def _strip_inline_financial_evidence_labels_for_display(reply: str) -> str:
    text = _INLINE_FINANCIAL_EVIDENCE_EXPRESSION_RE.sub("", reply or "")
    text = _INLINE_FINANCIAL_EVIDENCE_LABEL_RE.sub("", text)
    text = re.sub(r"[，,]\s*([)）])", r"\1", text)
    text = re.sub(r"[（(]\s*[)）]", "", text)
    text = re.sub(r"[ \t]+(?=[，。；;：:,])", "", text)
    return text


def _sanitize_financial_reply_for_display(reply: str) -> str:
    """Hide machine validation metadata after it has served the guardrail."""

    text = _compact_financial_validation_sections_for_display(reply or "")
    text = _strip_inline_financial_evidence_labels_for_display(text)
    text = re.sub(r"[ \t]+\|", " |", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _append_missing_calculation_evidence_locators(
    reply: str,
    trusted_evidence: Sequence[Mapping[str, Any]],
) -> str:
    """Expose each calculation source table once so cross-page operands remain auditable."""

    missing_refs: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()
    statement_labels = {
        "balance_sheet": "资产负债表",
        "income_statement": "利润表",
        "cash_flow_statement": "现金流量表",
    }

    def statement_label(item: Mapping[str, Any]) -> str:
        explicit = statement_labels.get(str(item.get("statement_type") or "").strip())
        if explicit:
            return explicit
        metric_text = " ".join(
            str(item.get(field) or "")
            for field in ("metric", "metric_name", "canonical_name")
        ).casefold()
        if any(term in metric_text for term in ("cash_flow", "现金流", "经营活动")):
            return "现金流量表"
        if any(
            term in metric_text
            for term in ("revenue", "income", "profit", "营业收入", "营业总收入", "利润")
        ):
            return "利润表"
        if any(
            term in metric_text
            for term in ("asset", "liabilit", "equity", "goodwill", "资产", "负债", "权益", "商誉")
        ):
            return "资产负债表"
        return str(item.get("metric_name") or item.get("metric") or "").strip()

    for item in trusted_evidence:
        task_id = str(item.get("task_id") or item.get("parse_run_id") or "").strip()
        pdf_page = str(item.get("pdf_page") or item.get("pdf_page_number") or "").strip()
        table_index = str(item.get("table_index") or "").strip()
        md_line = str(item.get("md_line") or "").strip()
        key = (task_id, pdf_page, table_index, md_line)
        if not task_id or not any(key[1:]) or key in seen:
            continue
        seen.add(key)
        locator_tokens = [
            token
            for token in (
                f"pdf_page={pdf_page}" if pdf_page else "",
                f"table_index={table_index}" if table_index else "",
                f"md_line={md_line}" if md_line else "",
            )
            if token
        ]
        if any(
            "source_type=" in line
            and f"task_id={task_id}" in line
            and any(token in line for token in locator_tokens)
            for line in reply.splitlines()
        ):
            continue
        label = f"C{len(missing_refs) + 1}"
        metric = statement_label(item)
        metric_field = f", metric={metric}" if metric else ""
        missing_refs.append(
            f"[{label}] source_type=wiki_metrics{metric_field}, task_id={task_id}, "
            + ", ".join(locator_tokens)
        )
    if not missing_refs:
        return reply
    return _merge_refs_into_reference_section(reply, missing_refs)


_FINANCIAL_VALIDATION_BLOCK_MARKER = "guardrail_status=blocked"
_FINANCIAL_VALIDATION_FAILURE_HEADING = "## 校验失败详情"


def _financial_validation_failed(guarded_reply: str) -> bool:
    return _FINANCIAL_VALIDATION_BLOCK_MARKER in (guarded_reply or "")


def _financial_validation_is_repairable(guarded_reply: str) -> bool:
    return _financial_validation_failed(guarded_reply) and "calculation_trace_reason=" in (
        guarded_reply or ""
    )


def _financial_repair_run_input(
    *,
    message: str,
    draft: str,
    validation_failure: str,
) -> str:
    """Build the single bounded repair turn from machine-produced failures."""

    return (
        "你正在执行财务回答的唯一一次校验修复。不得重新路由、重新选公司或输出思考过程。\n"
        "请对第一轮草稿做最小范围编辑，不得重新概括或整体重写。保留原稿的分析深度、章节、表格、风险提示和后续建议；"
        "只修正校验失败涉及的数字、公式、口径或证据绑定，并删除机器措辞。\n"
        "纯事实问答使用“结论 / 关键数据 / 引用来源”；若原始问题要求分析、解读、风险、原因或重要性，必须在关键数据后增加“解读要点”章节。"
        "解读要点写 3–5 条数据含义，不复述表格，且区分披露事实与分析判断。结论 3–5 条，同一金额只选一种易读单位，精确原值集中放在一张表中。"
        "验证通过时可在引用来源前增加简短的“计算器校验 / 勾稽校验”摘要，每栏只保留可读结论。\n"
        "不要输出后端结果包、trace、calculation_id、evidence_id、trusted 标签、运行记录或“无二次心算”等内部信息。\n"
        "所有金额换算、变动额、比例、勾稽关系必须采用校验器给出的期望值或后端确定性结果包；"
        "不要手写工具调用记录，不要声称调用了未实际调用的工具。"
        "若失败项是原值/准备/净额勾稽，正文必须出现一条同时含三个金额的完整算式，或在同一张紧凑表中列出三项精确金额。\n\n"
        "若失败原因为 trace_operation_missing，所有占比必须各自单独成句并明确分子、分母和结果；无法绑定证据的占比应删除。\n\n"
        f"## 原始问题\n{message}\n\n"
        f"## 第一轮草稿\n{draft}\n\n"
        f"## 第一轮校验失败项\n{validation_failure}"
    )


_FINANCIAL_REPAIR_QUALITY_HEADINGS = (
    "依据/数据",
    "关键数据",
    "解读要点",
    "风险/关注点",
    "风险与提示",
    "后续动作建议",
    "引用来源",
)


def _financial_repair_preserves_content_quality(original: str, repaired: str) -> bool:
    """Reject a valid-but-materially-degraded rewrite of the streamed answer."""

    original_text = (original or "").strip()
    repaired_text = (repaired or "").strip()
    if not repaired_text:
        return False
    if len(original_text) >= 800 and len(repaired_text) < len(original_text) * 0.72:
        return False
    for heading in _FINANCIAL_REPAIR_QUALITY_HEADINGS:
        if heading in original_text and heading not in repaired_text:
            return False
    original_tables = len(re.findall(r"(?m)^\|\s*---", original_text))
    repaired_tables = len(re.findall(r"(?m)^\|\s*---", repaired_text))
    if original_tables >= 2 and repaired_tables == 0:
        return False
    return True


def _select_financial_repair_result(
    *,
    first_draft: str,
    first_validation: str,
    repaired_draft: str,
    repaired_validation: str,
) -> str:
    """Keep the streamed draft and expose the suggested repair for comparison."""

    original = normalize_evidence_trace_for_display(first_draft).strip()
    suggested = normalize_evidence_trace_for_display(repaired_draft).strip()
    preserves_quality = _financial_repair_preserves_content_quality(original, suggested)
    validation_passed = not _financial_validation_failed(repaired_validation)
    if validation_passed:
        suggested_display = repaired_validation.strip()
        status = "校验通过" if preserves_quality else "校验通过，但内容保真检查未通过"
    else:
        suggested_display = _reply_with_financial_validation_failures(suggested, repaired_validation)
        status = "仍有校验项未通过"
    return (
        "# 原始回答（流式原稿）\n"
        "> 原稿完整保留，未被建议修复稿静默覆盖；其中派生计算仍以校验状态为准。\n\n"
        f"{original}\n\n"
        "# 建议修复稿（对照）\n"
        f"> 状态：{status}。当前仅作对照展示，便于核对修改内容。\n\n"
        f"{suggested_display}"
    ).strip()


def _strip_verbose_financial_validation_sections(draft: str) -> str:
    """Remove model-authored machine traces while keeping analysis and sources."""

    content = draft or ""
    content = re.sub(
        r"(?ms)^## (?:计算器校验|勾稽校验)\s*\n.*?(?=^## (?!计算器校验|勾稽校验)|\Z)",
        "",
        content,
    )
    return re.sub(r"\n{3,}", "\n\n", content).strip()


_FINANCIAL_VALIDATION_SECTION_RE = re.compile(
    r"(?ms)^(?P<heading>## (?:计算器校验|勾稽校验)(?:[（(][^\n）)]*[）)])?)\s*\n"
    r"(?P<body>.*?)(?=^## |\Z)"
)
_FINANCIAL_VALIDATION_INTERNAL_LINE_RE = re.compile(
    r"(?:trace_id|trace_schema|schema_version|calculation_id|evidence_id|trusted:|"
    r"\binputs?\s*[:=]|\bresult\s*[:=]|\boperation\s*[:=]|\bstatus\s*[:=]|"
    r"financial_calculator\.py|financial_reconciliation_validator\.py|后端确定性财务结果包)",
    re.IGNORECASE,
)


def _compact_financial_validation_sections_for_display(draft: str) -> str:
    """Keep user-facing validation summaries while hiding machine trace fields."""

    def replace(match: re.Match[str]) -> str:
        safe_lines = [
            line.rstrip()
            for line in match.group("body").splitlines()
            if line.strip() and not _FINANCIAL_VALIDATION_INTERNAL_LINE_RE.search(line)
        ][:100]
        if not safe_lines:
            return ""
        return f"{match.group('heading')}\n" + "\n".join(safe_lines) + "\n\n"

    content = _FINANCIAL_VALIDATION_SECTION_RE.sub(replace, draft or "")
    return re.sub(r"\n{3,}", "\n\n", content).strip()


def _financial_validation_cards_for_display(validation: str) -> str:
    cards = []
    for match in _FINANCIAL_VALIDATION_SECTION_RE.finditer(validation or ""):
        card = _compact_financial_validation_sections_for_display(match.group(0))
        if card:
            cards.append(card)
    return "\n\n".join(cards)


def _compact_financial_validation_failure(validation_failure: str) -> str:
    diagnostic = validation_failure or ""
    reason_match = re.search(r"(?m)^calculation_trace_reason=(\S+)\s*$", diagnostic)
    reason = reason_match.group(1) if reason_match else "unknown_validation_failure"
    failure_lines = re.findall(r"(?m)^- failure_\d+:\s*(.+)$", diagnostic)
    labels = {
        "calculator_trace_missing": "计算器运行记录缺失",
        "reconciliation_trace_missing": "勾稽校验运行记录缺失",
        "trace_unstructured": "计算记录不是可信结构化 trace",
        "trace_claim_result_mismatch": "正文计算结果与后端重算不一致",
        "trace_evidence_mismatch": "计算输入与证据绑定不一致",
    }
    lines = [f"- 失败项目：{labels.get(reason, '财务计算自动校验未通过')}。"]
    lines.extend(f"- 失败明细：{detail}" for detail in failure_lines[:3])
    lines.extend(
        (
            "- 影响范围：正文中的派生计算或勾稽声明暂未通过自动验证；原始披露数据、引用和文字分析仍保留。",
            f"- 原因代码：`{reason}`",
        )
    )
    return "\n".join(lines)


def _reply_with_financial_validation_failures(draft: str, validation_failure: str) -> str:
    """Second failure is non-blocking, but must remain explicit and inspectable."""

    cleaned_draft = _strip_verbose_financial_validation_sections(
        normalize_evidence_trace_for_display(draft)
    )
    cleaned_draft = _strip_inline_financial_evidence_labels_for_display(cleaned_draft)
    failure = _compact_financial_validation_failure(validation_failure)
    return (
        f"{cleaned_draft}\n\n{_FINANCIAL_VALIDATION_FAILURE_HEADING}\n"
        "- 第二轮修复后仍有项目未通过；正文已保留，仅下列项目不应视为已验证事实。\n"
        f"{failure}"
    ).strip()


def _reply_with_financial_repair_suggestion(draft: str, validation_failure: str) -> str:
    """Legacy fallback: preserve the draft and fold diagnostics into one card."""

    original = _strip_verbose_financial_validation_sections(
        normalize_evidence_trace_for_display(draft)
    )
    original = _strip_inline_financial_evidence_labels_for_display(original)
    validation_cards = _financial_validation_cards_for_display(validation_failure)
    if validation_cards:
        return f"{original}\n\n{validation_cards}".strip()
    failure = _compact_financial_validation_failure(validation_failure)
    return f"{original}\n\n## 计算器校验（存在待核对项）\n{failure}".strip()


async def _run_single_financial_repair(
    *,
    profile: HermesProfile,
    session_id: str,
    route: HermesRunRoute | None,
    message: str,
    draft: str,
    validation_failure: str,
    parent_state: ActiveRunState | None = None,
) -> tuple[str, HermesRunRoute | None]:
    repair_input = _financial_repair_run_input(
        message=message,
        draft=draft,
        validation_failure=validation_failure,
    )
    repair_run_id: str | None = None
    repair_route = route
    try:
        repair_run_id, repair_route = await _create_routed_run(
            repair_input,
            [],
            profile=profile,
            session_id=session_id,
            route=route,
        )
        repaired = await asyncio.wait_for(
            _collect_routed_run_result(
                repair_run_id,
                profile=profile,
                timeout=hermes_timeout(),
                route=repair_route,
            ),
            timeout=STREAM_TIMEOUT_SECONDS,
        )
        return repaired, repair_route
    except RunTerminalError as exc:
        terminal_confirmed = exc.result.status == "failed"
        if repair_run_id is not None and exc.result.status == "cancelled":
            terminal_confirmed = await _wait_routed_run_write_quiesced(
                repair_run_id,
                profile=profile,
                route=repair_route,
            )
        elif repair_run_id is not None and exc.result.status not in {"failed", "cancelled"}:
            terminal_confirmed = await _stop_and_confirm_routed_run(
                repair_run_id,
                profile=profile,
                route=repair_route,
            )
        if parent_state is not None and not terminal_confirmed:
            parent_state.runtime_children_terminal_confirmed = False
        raise
    except BaseException:
        terminal_confirmed = False
        if repair_run_id is not None:
            try:
                terminal_confirmed = await _stop_and_confirm_routed_run(
                    repair_run_id,
                    profile=profile,
                    route=repair_route,
                )
            except BaseException:
                terminal_confirmed = False
        if parent_state is not None and not terminal_confirmed:
            parent_state.runtime_children_terminal_confirmed = False
        raise


def _trusted_financial_receipts(
    profile: HermesProfile,
    session_id: str,
    *,
    route: HermesRunRoute | None = None,
) -> tuple[Mapping[str, Any], ...]:
    runtime_profile = _runtime_profile(profile)
    if route is not None and route.target == "openshell":
        run_id = str(route.canary_run_id or "")
        if re.fullmatch(r"canary-[0-9a-f]{12}", run_id) is None:
            return ()
        profile_root = PROJECT_ROOT / "var/openshell/siq-analysis/runtime-snapshots" / run_id
        try:
            resolved_root = profile_root.resolve(strict=True)
            expected_parent = (
                PROJECT_ROOT / "var/openshell/siq-analysis/runtime-snapshots"
            ).resolve(strict=True)
        except OSError:
            return ()
        if resolved_root.parent != expected_parent or not resolved_root.is_dir():
            return ()
        profile_root = resolved_root
        live_profile_roots = (resolved_root / "runtime-state",)
        hermes_session_id = _routed_hermes_session_id(profile, session_id, route)
    else:
        profile_root = HERMES_PROFILE_ROOTS.get(runtime_profile)
        if profile_root is None:
            return ()
        live_alias = HERMES_LIVE_PROFILE_ALIASES.get(runtime_profile)
        live_profile_roots = (HERMES_PROFILES_ROOT / live_alias,) if live_alias else ()
        hermes_session_id = hermes_runs_session_id(profile, session_id)
    allowed_paths = {
        "financial_calculator.py": (
            FINANCIAL_CALCULATOR_PATH,
            HERMES_SHARED_SCRIPTS_ROOT / "financial_calculator.py",
            HERMES_HOST_SHARED_SCRIPTS_ROOT / "financial_calculator.py",
        ),
        "financial_reconciliation_validator.py": (
            FINANCIAL_RECONCILIATION_VALIDATOR_PATH,
            HERMES_SHARED_SCRIPTS_ROOT / "financial_reconciliation_validator.py",
            HERMES_HOST_SHARED_SCRIPTS_ROOT / "financial_reconciliation_validator.py",
        ),
    }
    return agent_runtime_financial_trace.extract_runtime_financial_receipts(
        profile_dir=profile_root,
        profile_dirs=live_profile_roots,
        hermes_session_id=hermes_session_id,
        allowed_script_paths=allowed_paths,
    )


async def _trusted_financial_receipts_after_run(
    profile: HermesProfile,
    session_id: str,
    *,
    message: str,
    reply: str,
    route: HermesRunRoute | None = None,
) -> tuple[Mapping[str, Any], ...]:
    receipts = _trusted_financial_receipts(profile, session_id, route=route)
    if receipts or not agent_runtime_financial_guard.requires_financial_calculation_trace(message, reply):
        return receipts
    for delay in (0.02, 0.05, 0.1):
        await asyncio.sleep(delay)
        receipts = _trusted_financial_receipts(profile, session_id, route=route)
        if receipts:
            return receipts
    return ()


def format_chat_context(context: Any | None) -> str | None:
    return agent_runtime_context.build_format_chat_context(
        wiki_root=WIKI_ROOT,
        context=context,
        context_header=CONTEXT_HEADER,
    )


def get_session_default_context(
    profile: HermesProfile,
    session_id: str,
    context: Any | None = None,
    *,
    allow_initialize: bool = False,
) -> str | None:
    profile = _runtime_profile(profile)
    return agent_runtime_context.get_session_default_context(
        profile,
        session_id,
        context,
        allow_initialize=allow_initialize,
        session_default_contexts=SESSION_DEFAULT_CONTEXTS,
        active_key=_active_key,
        format_chat_context=format_chat_context,
    )


def build_session_contextual_input(
    message: str,
    *,
    profile: HermesProfile,
    session_id: str,
    context: Any | None = None,
    allow_initialize: bool = False,
    local_memory_context: str | None = None,
) -> str:
    profile = _runtime_profile(profile)
    primary_market_agent_runtime.validate_market_runtime_context(profile, context)
    if agent_memory_analytics.is_memory_management_query(message):
        blocks = [MEMORY_MANAGEMENT_CONTEXT]
        if local_memory_context:
            blocks.append(local_memory_context)
        blocks.append(f"用户问题：{message}")
        return "\n\n".join(blocks)
    if primary_market_agent_runtime.is_primary_market_ic_runtime(profile, context):
        return primary_market_agent_runtime.build_primary_market_ic_input(
            message,
            profile=profile,
            context=context,
            local_memory_context=local_memory_context,
        )
    contextual_input = agent_runtime_context.build_session_contextual_input(
        message,
        profile=profile,
        profile_label=PROFILE_LABELS.get(profile, profile),
        session_id=session_id,
        context=context,
        allow_initialize=allow_initialize,
        local_memory_context=local_memory_context,
        is_general_assistant_request=_is_general_assistant_request,
        session_default_context=get_session_default_context,
        resolve_company_dirs=_resolve_company_dirs,
        context_for_company_dir=_context_for_company_dir,
        message_for_company=_message_for_company,
        build_company_wiki_scope_context=build_company_wiki_scope_context,
        build_human_efficiency_evidence_context=build_human_efficiency_evidence_context,
        build_human_capital_context=build_human_capital_context,
        build_three_statement_core_context=build_three_statement_core_context,
        build_statement_metric_context=build_statement_metric_context,
        build_note_detail_context=build_note_detail_context,
        build_wiki_fulltext_fallback_context=build_wiki_fulltext_fallback_context,
        build_postgres_fallback_context=build_postgres_fallback_context,
        build_pdf2md_parse_only_context=build_pdf2md_parse_only_context,
        general_assistant_context=GENERAL_ASSISTANT_CONTEXT,
        chat_output_contract=CHAT_OUTPUT_CONTRACT,
        financial_calculation_runtime_contract=FINANCIAL_CALCULATION_RUNTIME_CONTRACT,
    )
    calculation_pack = agent_runtime_financial_evidence.render_deterministic_calculation_pack(
        _trusted_financial_calculation_evidence(message, context)
    )
    geographical_context = build_us_sec_geographical_revenue_context(message, context)
    if geographical_context:
        contextual_input = contextual_input.replace(
            f"用户问题：{message}",
            f"{geographical_context}\n\n用户问题：{message}",
        )
    if calculation_pack:
        contextual_input = contextual_input.replace(
            f"用户问题：{message}",
            f"{calculation_pack}\n\n用户问题：{message}",
        )
    return contextual_input


def build_hermes_run_input(
    message: str,
    *,
    profile: HermesProfile,
    session_id: str,
    context: Any | None = None,
    allow_initialize: bool = False,
    attachments: Any | None = None,
    local_memory_context: str | None = None,
    image_analysis_context: str | None = None,
    use_hermes_image_fallback: bool = True,
) -> str | list[dict[str, Any]]:
    profile = _runtime_profile(profile)
    contextual_text = build_session_contextual_input(
        message,
        profile=profile,
        session_id=session_id,
        context=context,
        allow_initialize=allow_initialize,
        local_memory_context=local_memory_context,
    )
    all_attachments = _attachment_dicts(attachments)
    image_attachments = _image_attachment_dicts(all_attachments)
    document_context = _document_attachment_context(all_attachments)
    image_path_hints = agent_runtime_context.image_attachment_path_hints(image_attachments)
    image_data_urls: list[str] = []
    if use_hermes_image_fallback:
        for item in image_attachments:
            data_url = _image_attachment_data_url(item)
            if data_url:
                image_data_urls.append(data_url)
    return agent_runtime_context.build_hermes_run_input_payload(
        contextual_text,
        has_attachments=bool(all_attachments),
        document_context=document_context,
        image_analysis_context=image_analysis_context,
        image_path_hints=image_path_hints,
        image_data_urls=image_data_urls,
        use_hermes_image_fallback=use_hermes_image_fallback,
    )


def hermes_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        READ_TIMEOUT_SECONDS,
        connect=10.0,
        read=READ_TIMEOUT_SECONDS,
    )


def stream_idle_timeout(profile: HermesProfile) -> int:
    return _streaming_stream_idle_timeout(
        profile,
        assistant_timeout_seconds=ASSISTANT_STREAM_IDLE_TIMEOUT_SECONDS,
        specialist_timeout_seconds=SPECIALIST_STREAM_IDLE_TIMEOUT_SECONDS,
    )


async def _prepare_chat_request_envelope(
    message: str,
    async_session: AsyncSession,
    *,
    session_id: str,
    context: Any | None = None,
    display_message: str | None = None,
    attachments: Any | None = None,
) -> ChatRequestEnvelope:
    return await agent_runtime_preflight.prepare_chat_request_envelope(
        message,
        async_session,
        session_id=session_id,
        context=context,
        display_message=display_message,
        attachments=attachments,
        attachment_dicts=_attachment_dicts,
        should_reuse_recent_attachments=_should_reuse_recent_attachments,
        load_recent_session_attachments=load_recent_session_attachments,
        dedupe_hash_with_attachments=_dedupe_hash_with_attachments,
        display_message_with_attachments=_display_message_with_attachments,
    )


async def _load_chat_run_preflight_context(
    async_session: AsyncSession,
    *,
    session_id: str,
    profile: HermesProfile,
    attachments: list[dict[str, Any]],
    history_limit: int,
    message: str = "",
    context: Any | None = None,
    isolate_runtime_context: bool = False,
    research_identity_scope: Mapping[str, Any] | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> ChatRunPreflightContext:
    async def scoped_history(
        scoped_session: AsyncSession,
        scoped_session_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not isolate_runtime_context:
            return await load_history(scoped_session, scoped_session_id, limit=limit)
        if research_identity_scope is None:
            return []
        return await load_history(
            scoped_session,
            scoped_session_id,
            limit=limit,
            research_identity_scope=research_identity_scope,
        )

    async def scoped_local_memory_context(
        scoped_session: AsyncSession,
        scoped_profile: HermesProfile,
        scoped_session_id: str,
    ) -> str | None:
        if isolate_runtime_context:
            return None
        if primary_market_agent_runtime.is_primary_market_ic_runtime(
            scoped_profile,
            context,
        ):
            return await ensure_local_memory_context(
                scoped_session,
                scoped_profile,
                scoped_session_id,
                request_context=context,
            )
        return await ensure_local_memory_context(
            scoped_session,
            scoped_profile,
            scoped_session_id,
        )

    async def scoped_agent_memory_context(
        scoped_session: AsyncSession,
        scoped_profile: HermesProfile,
        scoped_session_id: str,
        scoped_message: str,
        *,
        research_context: Any | None = None,
    ) -> str | None:
        if isolate_runtime_context and research_identity_scope is None:
            return None
        principal_kwargs = {}
        if isolate_runtime_context or tenant_id is not None or user_id is not None:
            agent_runtime_memory.verified_memory_principal(scoped_session_id, tenant_id, user_id)
            principal_kwargs = {"tenant_id": tenant_id, "user_id": user_id}
        if research_context is None:
            return await ensure_agent_memory_context(
                scoped_session,
                scoped_profile,
                scoped_session_id,
                scoped_message,
                **principal_kwargs,
            )
        return await ensure_agent_memory_context(
            scoped_session,
            scoped_profile,
            scoped_session_id,
            scoped_message,
            research_context=research_context,
            **principal_kwargs,
        )

    return await agent_runtime_preflight.load_chat_run_preflight_context_with_agent_memory(
        async_session,
        session_id=session_id,
        profile=profile,
        attachments=attachments,
        history_limit=history_limit,
        message=message,
        request_context=context,
        load_history=scoped_history,
        ensure_local_memory_context=scoped_local_memory_context,
        ensure_agent_memory_context=scoped_agent_memory_context,
    )


def _terminal_user_message(result: RunTerminalResult, *, user_stopped: bool = False) -> str:
    if user_stopped or result.status == "cancelled":
        return STOPPED_MESSAGE if user_stopped else RUN_CANCELLED_MESSAGE
    if result.status == "timed_out":
        return TIMEOUT_MESSAGE
    if result.status == "protocol_eof":
        return PROTOCOL_EOF_MESSAGE
    return RUN_FAILED_MESSAGE


def _terminal_error_payload(
    result: RunTerminalResult,
    *,
    message: str,
) -> dict[str, Any]:
    return {
        "message": message,
        "reason": result.error_code or result.status,
        "terminal": result.to_payload(),
        "status": result.status,
        "error_code": result.error_code,
        "retryable": result.retryable,
        "trace_id": result.run_id,
    }


def _runtime_provenance(route: HermesRunRoute | None) -> dict[str, str]:
    payload = {"runtime_target": route.target if route is not None else "host"}
    if route is not None and route.canary_run_id:
        payload["canary_run_id"] = route.canary_run_id
    if route is not None and route.target == "openshell" and route.pool_lease_id:
        scope_id = str(getattr(route.pool_binding, "scope_id", "") or "")
        generation_material = "\0".join(
            (
                route.session_namespace,
                route.canary_run_id or "",
                scope_id,
            )
        )
        payload["sandbox_generation_id"] = hashlib.sha256(
            generation_material.encode("utf-8")
        ).hexdigest()[:16]
        if scope_id:
            payload["sandbox_scope_id"] = scope_id
        if route.pool_company:
            payload["sandbox_company"] = route.pool_company
        if route.data_scope_ref_sha256:
            payload["data_scope_ref_sha256"] = route.data_scope_ref_sha256
        if route.authorization_snapshot_sha256:
            payload["authorization_snapshot_sha256"] = route.authorization_snapshot_sha256
        if route.data_classification:
            payload["data_classification"] = route.data_classification
        if route.model_route_alias:
            payload["model_route_alias"] = route.model_route_alias
        if route.model_route_sha256:
            payload["model_route_sha256"] = route.model_route_sha256
    return payload


def _runtime_research_identity_scope(
    context: Any | None,
    route: HermesRunRoute | None,
) -> dict[str, str] | None:
    if route is None or route.target != "openshell":
        return None
    scope = agent_runtime_context.research_identity(context)
    route_market = str(route.pool_market or "").strip().upper()
    if route_market:
        if scope.get("market") and scope["market"] != route_market:
            return None
        scope["market"] = route_market
    if not scope.get("company_id") and route.pool_company:
        company_id = str(route.pool_company).partition("-")[0].strip()
        if company_id:
            scope["company_id"] = company_id
    if not scope.get("market") or not scope.get("company_id"):
        return None
    return scope


def _memory_context_with_scope(
    context: Mapping[str, Any],
    scope: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if scope is None:
        return dict(context)
    existing = context.get("research_identity")
    identity = dict(existing) if isinstance(existing, Mapping) else {}
    return {**context, "research_identity": {**identity, **scope}}


def _record_answer_audit_trace_compat(**kwargs: Any) -> dict[str, Any]:
    """Keep test/runtime adapters compatible while trusted receipts roll out."""
    enriched = dict(kwargs)
    message = str(enriched.get("message") or "")
    raw_reply = str(enriched.get("raw_reply") or "")
    final_reply = str(enriched.get("final_reply") or "")
    needs_calculation_trace = agent_runtime_financial_guard.requires_financial_calculation_trace(
        message,
        final_reply,
    ) or bool(
        raw_reply
        and agent_runtime_financial_guard.requires_financial_calculation_trace(message, raw_reply)
    )
    if needs_calculation_trace:
        resolved_context = _resolved_research_context(message, enriched.get("context"))
        enriched["context"] = resolved_context
    else:
        resolved_context = enriched.get("context")
    if "trusted_calculation_evidence" not in enriched and needs_calculation_trace:
        enriched["trusted_calculation_evidence"] = _trusted_financial_calculation_evidence(
            message,
            resolved_context,
        )
    try:
        return agent_runtime_answer_audit.record_answer_audit_trace_for_reply(**enriched)
    except TypeError as exc:
        unsupported = {
            key
            for key in (
                "trusted_calculation_runs",
                "trusted_calculation_evidence",
                "runtime_provenance",
            )
            if key in str(exc)
        }
        if not unsupported:
            raise
        fallback = dict(enriched)
        for key in (
            "trusted_calculation_runs",
            "trusted_calculation_evidence",
            "runtime_provenance",
        ):
            fallback.pop(key, None)
        return agent_runtime_answer_audit.record_answer_audit_trace_for_reply(**fallback)


async def _collect_chat_reply_impl(
    message: str,
    async_session: AsyncSession,
    *,
    session_id: str,
    profile: HermesProfile,
    context: Any | None = None,
    display_message: str | None = None,
    attachments: Any | None = None,
    history_limit: int = HISTORY_LIMIT,
    enforce_evidence_contract: bool = True,
    answer_audit_callback: AnswerAuditCallback | None = None,
    runtime_target: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> str:
    primary_market_agent_runtime.validate_market_runtime_context(profile, context)
    governed = qwen38_request_selector.confidential_request(profile)
    selected_route = None
    if governed:
        selected_route = await _requested_api_route(profile, runtime_target, session_id, context,
            tenant_id=tenant_id, user_id=user_id)
    envelope = await _prepare_chat_request_envelope(
        message,
        async_session,
        session_id=session_id,
        context=context,
        display_message=display_message,
        attachments=attachments,
    )
    all_attachments = envelope.all_attachments
    message_hash = envelope.message_hash
    user_display_message = envelope.user_display_message
    audit_context = agent_runtime_context.mutable_context_dict(context)
    memory_save_kwargs = _chat_memory_save_kwargs(profile, audit_context)
    if tenant_id is not None or user_id is not None:
        memory_save_kwargs.update(agent_runtime_memory.verified_memory_principal(session_id, tenant_id, user_id))
    primary_market_ic_runtime = primary_market_agent_runtime.is_primary_market_ic_runtime(profile, audit_context)
    catalog_reply = None if primary_market_ic_runtime or governed else build_wiki_catalog_reply(message)
    short_circuit = agent_runtime_preflight.plan_chat_preflight_short_circuit(
        catalog_reply=catalog_reply,
        is_general_assistant_request=_is_general_assistant_request(message),
    )
    if short_circuit.forget_recent_completed_run:
        _forget_recent_completed_run(profile, session_id, message_hash)
    elif short_circuit.should_check_duplicate and not governed:
        duplicate_reply = _recent_duplicate_reply(profile, session_id, message_hash)
        if duplicate_reply:
            return duplicate_reply

    provisional_claim = await _acquire_durable_provisional_claim(profile, session_id)
    if provisional_claim is None:
        return _ACTIVE_RUN_CONFLICT_MESSAGE

    if short_circuit.catalog_reply:
        try:
            await save_message(
                async_session,
                "user",
                user_display_message,
                session_id,
                attachments=all_attachments,
                **memory_save_kwargs,
            )
            await save_message(
                async_session,
                "assistant",
                short_circuit.catalog_reply,
                session_id,
                **memory_save_kwargs,
            )
            await _refresh_session_memory_for_request(
                async_session,
                profile,
                session_id,
                audit_context,
            )
            _remember_completed_run(profile, session_id, message_hash, short_circuit.catalog_reply)
        except BaseException:
            await _release_provisional_durable_claim(
                provisional_claim.profile,
                provisional_claim.session_id,
                provisional_claim.provisional_run_id,
                provisional_claim.owner_id,
            )
            raise
        await _release_provisional_durable_claim(
            provisional_claim.profile,
            provisional_claim.session_id,
            provisional_claim.provisional_run_id,
            provisional_claim.owner_id,
            status="succeeded",
        )
        return short_circuit.catalog_reply

    completed_guard_input: str | None = None
    if profile == "siq_analysis" and _should_use_analysis_completion_guard(message):
        completed_artifacts = _analysis_completed_artifacts(context)
        if completed_artifacts:
            completed_guard_input = _analysis_completion_guard_input(message, completed_artifacts)

    claim_transferred = False
    try:
        run_route = selected_route if selected_route is not None else await _requested_api_route(
            profile, runtime_target, session_id, audit_context, tenant_id=tenant_id, user_id=user_id)
        isolate_runtime_context = bool(run_route is not None and run_route.target == "openshell")
        history_scope = _runtime_research_identity_scope(audit_context, run_route)
        memory_context = _memory_context_with_scope(audit_context, history_scope)
        if isolate_runtime_context and history_scope is not None:
            memory_save_kwargs = {**memory_save_kwargs, "research_identity": history_scope}
        preflight_context = await _load_chat_run_preflight_context(
            async_session,
            message=(
                primary_market_agent_runtime.primary_market_retrieval_query(
                    profile,
                    audit_context,
                )
                if primary_market_ic_runtime
                else completed_guard_input or message
            ),
            session_id=session_id,
            profile=profile,
            attachments=all_attachments,
            history_limit=history_limit,
            context=memory_context,
            isolate_runtime_context=isolate_runtime_context,
            research_identity_scope=history_scope,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        await wait_for_pdf_attachment_parses(preflight_context.attachments)
        all_attachments = _attachments_with_fresh_metadata(preflight_context.attachments)
        await save_message(
            async_session,
            "user",
            user_display_message,
            session_id,
            attachments=all_attachments,
            **memory_save_kwargs,
        )
        image_analysis_context, image_model_succeeded = await analyze_images_with_primary_model(
            completed_guard_input or message,
            all_attachments,
        )
        run_input = build_hermes_run_input(
            completed_guard_input or message,
            profile=profile,
            session_id=session_id,
            context=audit_context,
            allow_initialize=preflight_context.allow_initialize,
            attachments=all_attachments,
            local_memory_context=preflight_context.local_memory_context,
            image_analysis_context=image_analysis_context,
            use_hermes_image_fallback=not image_model_succeeded,
        )
        claim_transferred = True
        claimed_run = await _claim_create_and_bind_routed_run(
            run_input,
            preflight_context.history,
            profile=profile,
            session_id=session_id,
            route=run_route,
            provisional_claim=provisional_claim,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except BaseException:
        if not claim_transferred:
            await _release_provisional_durable_claim(
                provisional_claim.profile,
                provisional_claim.session_id,
                provisional_claim.provisional_run_id,
                provisional_claim.owner_id,
            )
        raise
    if claimed_run is None:
        return _ACTIVE_RUN_CONFLICT_MESSAGE
    run_id, run_route, owner_id = claimed_run
    state = ActiveRunState(profile=profile, session_id=session_id, run_id=run_id)
    state.run_route = run_route
    state.owner_id = owner_id
    state.lease_heartbeat_task = asyncio.create_task(_active_run_lease_heartbeat(state))
    state.message_hash = message_hash
    state.original_message = message
    state.context = audit_context
    ACTIVE_RUNS[_active_key(profile, session_id)] = state
    siq_security_export.emit_run_event(state, event_type="agent_run.admitted")
    owner_task = asyncio.current_task()
    if owner_task is not None:
        def _cleanup_nonstream_after_task_done(_task: asyncio.Task) -> None:
            if state.status == "postprocessing":
                asyncio.create_task(_release_durable_active_run(state, status="failed"))
                ACTIVE_RUNS.pop(_active_key(profile, session_id), None)

        owner_task.add_done_callback(_cleanup_nonstream_after_task_done)
    try:
        reply = await asyncio.wait_for(
            _collect_routed_run_result(
                run_id,
                profile=profile,
                timeout=hermes_timeout(),
                route=run_route,
            ),
            timeout=STREAM_TIMEOUT_SECONDS,
        )
        captured_terminal = pop_run_terminal_result(run_id)
        state.terminal_result = (
            captured_terminal
            if captured_terminal is not None and captured_terminal.succeeded
            else RunTerminalResult(
                run_id=run_id,
                status="succeeded",
                received_text=reply,
            )
        )
        state.runtime_terminal_confirmed = True
        state.status = "postprocessing"
        if not await _active_run_ownership_is_current(state):
            state.runtime_children_terminal_confirmed = False
            state.status = "failed"
            state.error = "active_run_lease_lost"
            state.terminal_result = RunTerminalResult(
                run_id=run_id, status="failed", received_text=reply,
                error_code="active_run_lease_lost", retryable=False,
                diagnostic="Runtime ownership changed before postprocessing",
            )
            return _ACTIVE_RUN_AUTHORITY_LOST_MESSAGE
    except RunTerminalError as exc:
        state.terminal_result = exc.result
        if exc.result.status == "failed":
            state.runtime_terminal_confirmed = True
        elif exc.result.status == "cancelled":
            state.runtime_terminal_confirmed = await _wait_routed_run_write_quiesced(
                run_id,
                profile=profile,
                route=run_route,
            )
        else:
            state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
                run_id,
                profile=profile,
                route=run_route,
            )
        state.status = exc.result.status
        state.error = exc.result.error_code or exc.result.status
        return _terminal_user_message(exc.result)
    except (asyncio.TimeoutError, httpx.TimeoutException):
        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
            run_id,
            profile=profile,
            route=run_route,
        )
        state.terminal_result = RunTerminalResult(
            run_id=run_id,
            status="timed_out",
            error_code="hermes_run_timed_out",
            retryable=True,
            diagnostic="Agent runtime deadline exceeded",
        )
        state.status = "timed_out"
        state.error = "hermes_run_timed_out"
        return TIMEOUT_MESSAGE
    except httpx.TransportError:
        # A supervisor can cut the stream when current authority becomes
        # invalid. A broken connection is not a successful terminal event and
        # must never replay the task or publish a partial answer as complete.
        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
            run_id,
            profile=profile,
            route=run_route,
        )
        state.terminal_result = RunTerminalResult(
            run_id=run_id,
            status="failed",
            error_code="hermes_transport_interrupted",
            retryable=False,
            diagnostic="Agent runtime connection interrupted before terminal confirmation",
        )
        state.status = "failed"
        state.error = "hermes_transport_interrupted"
        return TRANSPORT_FAILURE_MESSAGE
    finally:
        if state.status != "postprocessing":
            siq_security_export.emit_run_event(state, event_type="agent_run.terminal")
            await _release_durable_active_run(
                state,
                status=state.status if state.status != "running" else "failed",
            )
            ACTIVE_RUNS.pop(_active_key(profile, session_id), None)

    raw_reply = reply
    answer_audit_record: Mapping[str, Any] | None = None
    if primary_market_ic_runtime:
        reply = normalize_evidence_trace_for_display(reply)
    else:
        trusted_runs = await _trusted_financial_receipts_after_run(
            profile,
            session_id,
            message=message,
            reply=reply,
            route=run_route,
        )
        trusted_token = agent_runtime_financial_trace.set_current_trusted_runs(trusted_runs)
        try:
            recovered_reply = recover_financial_tool_loop_reply(message, audit_context, reply)
            reply = deterministic_pdf_market_reply(message, audit_context) or recovered_reply or reply
            reply = normalize_evidence_trace_for_display(reply)
            if enforce_evidence_contract:
                first_draft = reply
                first_validation = enforce_financial_evidence_contract(message, audit_context, first_draft)
                if _financial_validation_is_repairable(first_validation):
                    reply = _reply_with_financial_repair_suggestion(first_draft, first_validation)
                else:
                    reply = first_validation
            reply = normalize_evidence_trace_for_display(reply)
            audit_context = agent_runtime_postgres_fallback.audit_context_for_final_reply(audit_context, reply)
            answer_audit_record = _record_answer_audit_trace_compat(
                message=message,
                context=audit_context,
                profile=profile,
                session_id=session_id,
                raw_reply=raw_reply,
                final_reply=reply,
                enforce_evidence_contract=enforce_evidence_contract,
                trusted_calculation_runs=trusted_runs,
                runtime_provenance=_runtime_provenance(run_route),
            )
        finally:
            agent_runtime_financial_trace.reset_current_trusted_runs(trusted_token)
    if answer_audit_callback and isinstance(answer_audit_record, dict):
        answer_audit_callback(answer_audit_record)
    if not primary_market_ic_runtime:
        reply = _sanitize_financial_reply_for_display(reply)
    if not primary_market_ic_runtime:
        _record_financial_llm_provenance_if_needed(
            message=message,
            context=audit_context,
            profile=profile,
            model_input=run_input,
            raw_output=raw_reply,
            stored_output=reply,
            attachments=all_attachments,
            terminal_runtime=state.terminal_result.runtime,
            runtime_provenance=_runtime_provenance(run_route),
        )
    await save_message(
        async_session,
        "assistant",
        reply,
        session_id,
        audit_trace_id=_answer_audit_trace_id(answer_audit_record),
        **memory_save_kwargs,
    )
    if not isolate_runtime_context:
        await _refresh_session_memory_for_request(
            async_session,
            profile,
            session_id,
            audit_context,
        )
    _remember_completed_run(profile, session_id, message_hash, reply)
    state.content = reply
    state.status = "succeeded"
    siq_security_export.emit_run_event(
        state,
        event_type="agent_run.terminal",
        audit_trace_id=_answer_audit_trace_id(answer_audit_record),
    )
    await _release_durable_active_run(state, status="succeeded")
    ACTIVE_RUNS.pop(_active_key(profile, session_id), None)
    return reply


def _confidential_auxiliary_request(profile):
    return qwen38_request_selector.confidential_request(profile)


async def collect_chat_reply(
    message: str,
    async_session: AsyncSession,
    *,
    session_id: str,
    profile: HermesProfile,
    context: Any | None = None,
    display_message: str | None = None,
    attachments: Any | None = None,
    history_limit: int = HISTORY_LIMIT,
    enforce_evidence_contract: bool = True,
    answer_audit_callback: AnswerAuditCallback | None = None,
    runtime_target: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> str:
    with (_profile_wiki_context(profile),
          confidential_auxiliary_models.scope(_confidential_auxiliary_request(profile)),
          agent_runtime_host_scope.scope()):
        return await _collect_chat_reply_impl(
            message,
            async_session,
            session_id=session_id,
            profile=profile,
            context=context,
            display_message=display_message,
            attachments=attachments,
            history_limit=history_limit,
            enforce_evidence_contract=enforce_evidence_contract,
            answer_audit_callback=answer_audit_callback,
            runtime_target=runtime_target,
            tenant_id=tenant_id,
            user_id=user_id,
        )


async def _collect_stream_run(
    state: ActiveRunState,
    done_payload_factory: Callable[[str], Awaitable[dict]] | None,
    enforce_evidence_contract: bool = True,
    emit_audit_trace_id: bool = False,
) -> None:
    full_reply = ""
    display_filter = ExternalToolLoopStreamFilter()
    audit_trace_id: str | None = None
    failed = False
    loop_detected = False
    idle_timed_out = False
    terminal_accumulator = RunTerminalAccumulator(state.run_id)
    terminal_result: RunTerminalResult | None = None

    async def append_model_delta(text: str, *, final: bool = False) -> None:
        display_text = display_filter.feed(text, final=final)
        if display_text:
            await _append_state_event(state, "delta", {"content": display_text, "source": "model"})

    try:
        await _append_progress_event(
            state,
            agent_runtime_progress.task_started_progress_payload(),
        )
        async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
            event_stream = _stream_routed_run(
                state.run_id,
                profile=state.profile,
                timeout=hermes_timeout(),
                route=state.run_route,
            ).__aiter__()
            while True:
                try:
                    ev = await asyncio.wait_for(
                        event_stream.__anext__(),
                        timeout=stream_idle_timeout(state.profile),
                    )
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    idle_timed_out = True
                    raise
                if ev.type == "delta":
                    terminal_accumulator.accept(ev)
                    full_reply += ev.text
                    state.tool_events_since_delta = 0
                    state.consecutive_same_tool_calls = 0
                    await append_model_delta(ev.text)
                    progress = _extract_progress_from_text(full_reply)
                    if progress:
                        await _append_progress_event(state, progress)
                    text_loop = _detect_stream_output_loop(state.profile, full_reply)
                    if text_loop:
                        loop_detected = True
                        failed = True
                        terminal_result = RunTerminalResult(
                            run_id=state.run_id,
                            status="failed",
                            received_text=full_reply,
                            error_code=text_loop["reason"],
                            retryable=True,
                            diagnostic=text_loop["sample"],
                        )
                        state.stop_requested = True
                        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
                            state.run_id,
                            profile=state.profile,
                            route=state.run_route,
                        )
                        loop_delta = (
                            f"\n\n{OUTPUT_LOOP_STOP_MESSAGE}\n\n"
                            f"循环样本：{text_loop['sample']}\n"
                            f"重复状态行：{text_loop['repeated_lines']}，"
                            f"不同状态行：{text_loop['unique_lines']}"
                        )
                        full_reply = f"{full_reply}{loop_delta}"
                        await _append_progress_event(
                            state,
                            agent_runtime_progress.output_loop_stop_progress_payload(text_loop["sample"]),
                        )
                        await _append_state_event(state, "delta", {"content": loop_delta})
                        await _append_state_event(
                            state,
                            "error",
                            {
                                **_terminal_error_payload(
                                    terminal_result,
                                    message=OUTPUT_LOOP_STOP_MESSAGE,
                                ),
                                "sample": text_loop["sample"],
                            },
                        )
                        break
                elif ev.type == "tool.started":
                    projection = project_tool_started(
                        state,
                        tool=ev.tool,
                        preview=ev.preview,
                        display_tool_label=_display_tool_label,
                        hash_text=_hash_text,
                        repeated_tool_call_limit=REPEATED_TOOL_CALL_LIMIT,
                    )
                    await _append_progress_event(state, projection.progress_payload)
                    await _append_state_event(state, "tool", projection.state_event_payload)
                    if projection.repeated_call_limit_reached:
                        failed = True
                        terminal_result = RunTerminalResult(
                            run_id=state.run_id,
                            status="failed",
                            received_text=full_reply,
                            error_code="repeated_tool_calls_without_delta",
                            retryable=True,
                            diagnostic=projection.tool_label,
                        )
                        state.stop_requested = True
                        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
                            state.run_id,
                            profile=state.profile,
                            route=state.run_route,
                        )
                        repeated_delta = (
                            f"\n\n{REPEATED_TOOL_CALL_STOP_MESSAGE}\n\n"
                            f"重复工具：{projection.tool_label}\n"
                            f"重复次数：{state.consecutive_same_tool_calls}\n"
                            f"工具输入预览：{state.last_tool_preview or '未返回'}"
                        )
                        full_reply = f"{full_reply}{repeated_delta}" if full_reply else repeated_delta.strip()
                        await _append_progress_event(
                            state,
                            agent_runtime_progress.repeated_tool_call_stop_progress_payload(
                                projection.tool_label,
                                state.consecutive_same_tool_calls,
                            ),
                        )
                        await _append_state_event(state, "delta", {"content": repeated_delta})
                        await _append_state_event(
                            state,
                            "error",
                            {
                                **_terminal_error_payload(
                                    terminal_result,
                                    message=REPEATED_TOOL_CALL_STOP_MESSAGE,
                                ),
                                "tool": projection.tool_label,
                                "count": state.consecutive_same_tool_calls,
                            },
                        )
                        break
                elif ev.type == "tool.completed":
                    projection = project_tool_completed(
                        state,
                        tool=ev.tool,
                        duration=ev.duration,
                        error=ev.error,
                        display_tool_label=_display_tool_label,
                        hash_text=_hash_text,
                        consecutive_tool_error_limit=CONSECUTIVE_TOOL_ERROR_LIMIT,
                    )
                    await _append_progress_event(state, projection.progress_payload)
                    await _append_state_event(state, "tool", projection.state_event_payload)
                    if projection.consecutive_error_limit_reached:
                        failed = True
                        terminal_result = RunTerminalResult(
                            run_id=state.run_id,
                            status="failed",
                            received_text=full_reply,
                            error_code="consecutive_tool_errors",
                            retryable=True,
                            diagnostic=projection.tool_label,
                        )
                        state.stop_requested = True
                        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
                            state.run_id,
                            profile=state.profile,
                            route=state.run_route,
                        )
                        failure_delta = (
                            f"\n\n{TOOL_FAILURE_STOP_MESSAGE}\n\n"
                            f"连续失败工具：{projection.tool_label}\n"
                            f"连续失败次数：{state.consecutive_tool_errors}"
                        )
                        full_reply = f"{full_reply}{failure_delta}" if full_reply else failure_delta.strip()
                        await _append_progress_event(
                            state,
                            agent_runtime_progress.consecutive_tool_error_stop_progress_payload(
                                projection.tool_label,
                                state.consecutive_tool_errors,
                            ),
                        )
                        await _append_state_event(state, "delta", {"content": failure_delta})
                        await _append_state_event(
                            state,
                            "error",
                            {
                                **_terminal_error_payload(
                                    terminal_result,
                                    message=TOOL_FAILURE_STOP_MESSAGE,
                                ),
                                "tool": projection.tool_label,
                                "count": state.consecutive_tool_errors,
                            },
                        )
                        break
                elif ev.type == "reasoning":
                    await _append_reasoning_active_run(state, ev.text)
                elif ev.type == "done":
                    terminal_result = terminal_accumulator.accept(ev)
                    state.runtime_terminal_confirmed = True
                    if loop_detected:
                        break
                    if ev.text and not full_reply:
                        full_reply = ev.text
                        await append_model_delta(ev.text)
                    elif ev.text and ev.text.startswith(full_reply):
                        suffix = ev.text[len(full_reply):]
                        if suffix:
                            full_reply = ev.text
                            await append_model_delta(suffix)
                    await append_model_delta("", final=True)
                    if not await _active_run_ownership_is_current(state):
                        failed = True
                        state.runtime_children_terminal_confirmed = False
                        state.stop_requested = True
                        terminal_result = RunTerminalResult(
                            run_id=state.run_id,
                            status="failed",
                            received_text=full_reply,
                            error_code="active_run_lease_lost",
                            retryable=False,
                            diagnostic="Runtime ownership changed before postprocessing",
                            runtime=terminal_result.runtime if terminal_result is not None else None,
                        )
                        await _append_state_event(
                            state,
                            "error",
                            _terminal_error_payload(
                                terminal_result,
                                message=_ACTIVE_RUN_AUTHORITY_LOST_MESSAGE,
                            ),
                        )
                    break
                elif ev.type in {"failed", "cancelled"}:
                    failed = True
                    terminal_result = terminal_accumulator.accept(ev)
                    state.runtime_terminal_confirmed = ev.type == "failed"
                    if ev.type == "cancelled":
                        state.runtime_terminal_confirmed = await _wait_routed_run_write_quiesced(
                            state.run_id,
                            profile=state.profile,
                            route=state.run_route,
                        )
                    status_message = (
                        RUN_FAILED_MESSAGE
                        if ev.type == "failed"
                        else (STOPPED_MESSAGE if state.user_stop_requested else RUN_CANCELLED_MESSAGE)
                    )
                    detail = _trim_tool_preview(ev.text, 600)
                    if agent_runtime_financial_guard.is_external_tool_loop_guard_reply(detail):
                        detail = ""
                    if ev.type == "cancelled" and state.user_stop_requested:
                        full_reply = status_message
                        await _append_state_event(state, "replace", {"content": status_message})
                    else:
                        failure_delta = f"\n\n{status_message}"
                        if detail:
                            failure_delta = f"{failure_delta}\n\n{detail}"
                        full_reply = f"{full_reply}{failure_delta}" if full_reply else failure_delta.strip()
                        await _append_state_event(state, "delta", {"content": failure_delta})
                    await _append_progress_event(
                        state,
                        agent_runtime_progress.terminal_run_event_progress_payload(
                            ev.type,
                            detail or status_message,
                        ),
                    )
                    await _append_state_event(
                        state,
                        "error",
                        {
                            **_terminal_error_payload(terminal_result, message=status_message),
                            "detail": detail,
                        },
                    )
                    break
            if terminal_result is None and not failed:
                failed = True
                terminal_result = terminal_accumulator.protocol_eof()
                state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
                    state.run_id,
                    profile=state.profile,
                    route=state.run_route,
                )
                failure_delta = f"\n\n{PROTOCOL_EOF_MESSAGE}" if full_reply else PROTOCOL_EOF_MESSAGE
                full_reply = f"{full_reply}{failure_delta}" if full_reply else failure_delta
                await _append_progress_event(
                    state,
                    agent_runtime_progress.terminal_run_event_progress_payload(
                        "failed",
                        PROTOCOL_EOF_MESSAGE,
                    ),
                )
                await _append_state_event(state, "delta", {"content": failure_delta})
                await _append_state_event(
                    state,
                    "error",
                    _terminal_error_payload(terminal_result, message=PROTOCOL_EOF_MESSAGE),
                )
    except asyncio.TimeoutError:
        failed = True
        terminal_result = terminal_accumulator.timed_out(
            "Hermes stream idle timeout" if idle_timed_out else "Agent runtime deadline exceeded"
        )
        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
            state.run_id,
            profile=state.profile,
            route=state.run_route,
        )
        timeout_message = IDLE_TIMEOUT_MESSAGE if idle_timed_out else TIMEOUT_MESSAGE
        timeout_delta = f"\n\n{timeout_message}" if full_reply else timeout_message
        full_reply = f"{full_reply}{timeout_delta}" if full_reply else timeout_delta
        await _append_progress_event(
            state,
            agent_runtime_progress.timeout_progress_payload(timeout_message),
        )
        await _append_state_event(state, "delta", {"content": timeout_delta})
        await _append_state_event(
            state,
            "error",
            _terminal_error_payload(terminal_result, message=timeout_message),
        )
    except httpx.TimeoutException:
        failed = True
        terminal_result = terminal_accumulator.timed_out("Hermes HTTP stream timeout")
        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
            state.run_id,
            profile=state.profile,
            route=state.run_route,
        )
        timeout_delta = f"\n\n{TIMEOUT_MESSAGE}" if full_reply else TIMEOUT_MESSAGE
        full_reply = f"{full_reply}{timeout_delta}" if full_reply else timeout_delta
        await _append_progress_event(
            state,
            agent_runtime_progress.timeout_progress_payload(TIMEOUT_MESSAGE),
        )
        await _append_state_event(state, "delta", {"content": timeout_delta})
        await _append_state_event(
            state,
            "error",
            _terminal_error_payload(terminal_result, message=TIMEOUT_MESSAGE),
        )
    except Exception as exc:
        failed = True
        state.runtime_terminal_confirmed = await _stop_and_confirm_routed_run(
            state.run_id,
            profile=state.profile,
            route=state.run_route,
        )
        exception_detail = str(exc)
        external_tool_loop_guard = agent_runtime_financial_guard.is_external_tool_loop_guard_reply(
            exception_detail
        )
        diagnostic = (
            "Hermes upstream tool loop guard stopped the run"
            if external_tool_loop_guard
            else exception_detail
        )
        terminal_result = RunTerminalResult(
            run_id=state.run_id,
            status="failed",
            received_text=terminal_accumulator.received_text,
            error_code="agent_runtime_exception",
            retryable=True,
            diagnostic=diagnostic,
        )
        error_text = (
            f"\n\n{TOOL_FAILURE_STOP_MESSAGE}"
            if external_tool_loop_guard
            else f"\n\n[错误] {exception_detail}"
        )
        full_reply = f"{full_reply}{error_text}" if full_reply else error_text.strip()
        await _append_progress_event(
            state,
            agent_runtime_progress.runtime_exception_progress_payload(
                TOOL_FAILURE_STOP_MESSAGE if external_tool_loop_guard else exc
            ),
        )
        await _append_state_event(state, "delta", {"content": error_text})
        await _append_state_event(
            state,
            "error",
            _terminal_error_payload(terminal_result, message="Agent runtime execution failed"),
        )
    finally:
        try:
            if state.user_stop_requested and full_reply != STOPPED_MESSAGE:
                full_reply = STOPPED_MESSAGE
                await _append_state_event(state, "replace", {"content": STOPPED_MESSAGE})
            if state.user_stop_requested and not full_reply:
                full_reply = STOPPED_MESSAGE
                await _append_progress_event(
                    state,
                    agent_runtime_progress.user_stopped_progress_payload(STOPPED_MESSAGE),
                )
                await _append_state_event(state, "delta", {"content": STOPPED_MESSAGE})

            if state.user_stop_requested and terminal_result is None:
                terminal_result = RunTerminalResult(
                    run_id=state.run_id,
                    status="cancelled",
                    received_text=terminal_accumulator.received_text,
                    error_code="hermes_run_cancelled",
                    retryable=False,
                    diagnostic="Run stopped by user",
                )
            if failed and terminal_result is None:
                terminal_result = RunTerminalResult(
                    run_id=state.run_id,
                    status="failed",
                    received_text=terminal_accumulator.received_text,
                    error_code="agent_runtime_guard_failed",
                    retryable=True,
                    diagnostic="Agent runtime guard stopped the run",
                )
            state.terminal_result = terminal_result
            if terminal_result is not None:
                state.status = (
                    "postprocessing"
                    if terminal_result.succeeded and not state.user_stop_requested
                    else terminal_result.status
                )

            if full_reply and terminal_result is not None and terminal_result.succeeded:
                trusted_runs: tuple[Mapping[str, Any], ...] = ()
                raw_full_reply = full_reply
                primary_market_ic_runtime = primary_market_agent_runtime.is_primary_market_ic_runtime(
                    state.profile,
                    state.context,
                )
                answer_audit_record: Mapping[str, Any] | None = None
                audit_context = state.context
                if primary_market_ic_runtime:
                    reply = (
                        _failed_run_reply_for_history(full_reply)
                        if failed or _is_loop_polluted_assistant_message(full_reply)
                        else normalize_evidence_trace_for_display(full_reply)
                    )
                else:
                    recovered_reply = recover_financial_tool_loop_reply(
                        state.original_message or "",
                        state.context,
                        full_reply,
                    )
                    if recovered_reply is not None:
                        reply = deterministic_pdf_market_reply(
                            state.original_message or "",
                            state.context,
                        ) or recovered_reply
                        reply = normalize_evidence_trace_for_display(reply)
                        trusted_runs = await _trusted_financial_receipts_after_run(
                            state.profile,
                            state.session_id,
                            message=state.original_message or "",
                            reply=reply,
                            route=state.run_route,
                        )
                        trusted_token = agent_runtime_financial_trace.set_current_trusted_runs(trusted_runs)
                        try:
                            if enforce_evidence_contract:
                                first_draft = reply
                                first_validation = enforce_financial_evidence_contract(
                                    state.original_message or "",
                                    state.context,
                                    first_draft,
                                )
                                if _financial_validation_is_repairable(first_validation):
                                    reply = _reply_with_financial_repair_suggestion(
                                        first_draft,
                                        first_validation,
                                    )
                                else:
                                    reply = first_validation
                        finally:
                            agent_runtime_financial_trace.reset_current_trusted_runs(trusted_token)
                        reply = normalize_evidence_trace_for_display(reply)
                    elif failed or _is_loop_polluted_assistant_message(full_reply):
                        reply = _failed_run_reply_for_history(full_reply)
                    else:
                        reply = deterministic_pdf_market_reply(state.original_message or "", state.context) or full_reply
                        reply = normalize_evidence_trace_for_display(reply)
                        trusted_runs = await _trusted_financial_receipts_after_run(
                            state.profile,
                            state.session_id,
                            message=state.original_message or "",
                            reply=reply,
                            route=state.run_route,
                        )
                        trusted_token = agent_runtime_financial_trace.set_current_trusted_runs(trusted_runs)
                        try:
                            if enforce_evidence_contract:
                                first_draft = reply
                                first_validation = enforce_financial_evidence_contract(
                                    state.original_message or "",
                                    state.context,
                                    first_draft,
                                )
                                if _financial_validation_is_repairable(first_validation):
                                    reply = _reply_with_financial_repair_suggestion(
                                        first_draft,
                                        first_validation,
                                    )
                                else:
                                    reply = first_validation
                        finally:
                            agent_runtime_financial_trace.reset_current_trusted_runs(trusted_token)
                        reply = normalize_evidence_trace_for_display(reply)

                    audit_context = agent_runtime_postgres_fallback.audit_context_for_final_reply(
                        state.context,
                        reply,
                    )
                    answer_audit_record = _record_answer_audit_trace_compat(
                        message=state.original_message or "",
                        context=audit_context,
                        profile=state.profile,
                        session_id=state.session_id,
                        raw_reply=raw_full_reply,
                        final_reply=reply,
                        enforce_evidence_contract=enforce_evidence_contract,
                        trusted_calculation_runs=trusted_runs,
                        runtime_provenance=_runtime_provenance(state.run_route),
                    )

                if not primary_market_ic_runtime:
                    reply = _sanitize_financial_reply_for_display(reply)

                if reply != full_reply and not failed:
                    full_reply = reply
                    await _append_state_event(state, "replace", {"content": reply})
                audit_trace_id = _answer_audit_trace_id(answer_audit_record)
                if not failed:
                    full_reply = reply
                if (
                    not primary_market_ic_runtime
                    and not failed
                    and not _is_loop_polluted_assistant_message(raw_full_reply)
                ):
                    _record_financial_llm_provenance_if_needed(
                        message=state.original_message or "",
                        context=audit_context,
                        profile=state.profile,
                        model_input=getattr(state, "provenance_input", None),
                        raw_output=raw_full_reply,
                        stored_output=reply,
                        attachments=getattr(state, "provenance_attachments", None),
                        terminal_runtime=terminal_result.runtime,
                        runtime_provenance=_runtime_provenance(state.run_route),
                    )
                stream_memory_identity = (
                    dict(state.memory_research_identity)
                    if state.memory_research_identity is not None
                    else agent_runtime_context.research_identity(state.context)
                )
                stream_memory_kwargs: dict[str, Any] = {}
                if primary_market_ic_runtime:
                    stream_memory_kwargs["request_context"] = state.context
                elif stream_memory_identity:
                    stream_memory_kwargs["research_identity"] = stream_memory_identity
                if state.run_route is not None and state.run_route.target == "openshell":
                    stream_memory_kwargs["refresh_local_memory"] = False
                    route_tenant = state.run_route.pool_tenant_id
                    route_user = state.run_route.pool_user_id
                    if route_tenant is not None or route_user is not None:
                        stream_memory_kwargs.update(tenant_id=route_tenant, user_id=route_user)
                await save_message_in_background(
                    "assistant",
                    reply,
                    state.session_id,
                    profile=state.profile,
                    audit_trace_id=audit_trace_id,
                    **stream_memory_kwargs,
                )
                _remember_completed_run(state.profile, state.session_id, state.message_hash, reply)

            if terminal_result is not None and terminal_result.succeeded and not state.user_stop_requested:
                try:
                    done_payload = await done_payload_factory(full_reply) if done_payload_factory else {"new_achievements": []}
                except Exception as exc:
                    done_payload = {"new_achievements": [], "warning": str(exc)}
                if emit_audit_trace_id and audit_trace_id:
                    done_payload = {**done_payload, "audit_trace_id": audit_trace_id}
                if full_reply:
                    done_payload = {**done_payload, "content": full_reply}
                done_payload = {**done_payload, "terminal": terminal_result.to_payload()}
                done_payload = {
                    **done_payload,
                    "runtime_provenance": _runtime_provenance(state.run_route),
                }
                await _append_completed_active_run(state, done_payload)
            elif state.user_stop_requested:
                await _append_user_stopped_active_run(state, STOPPED_MESSAGE)
        finally:
            siq_security_export.emit_run_event(
                state,
                event_type="agent_run.terminal",
                audit_trace_id=audit_trace_id,
            )
            await _release_durable_active_run(
                state,
                status="cancelled" if state.user_stop_requested else (state.status if state.status != "running" else "failed"),
            )
            _clear_active_run(state)


async def _start_streaming_chat_run(
    *,
    profile: HermesProfile,
    session_id: str,
    run_id: str,
    message_hash: str | None,
    message: str,
    context: Any | None,
    done_payload_factory: Callable[[str], Awaitable[dict]] | None,
    provenance_input: Any | None = None,
    provenance_attachments: Any | None = None,
    enforce_evidence_contract: bool = True,
    emit_audit_trace_id: bool = False,
    owner_id: str | None = None,
    run_route: HermesRunRoute | None = None,
    memory_research_identity: Mapping[str, Any] | None = None,
) -> ActiveRunState:
    state = ActiveRunState(profile=profile, session_id=session_id, run_id=run_id)
    state.run_route = run_route
    state.memory_research_identity = memory_research_identity
    state.message_hash = message_hash
    state.original_message = message
    state.context = context
    state.owner_id = owner_id
    state.lease_heartbeat_task = asyncio.create_task(_active_run_lease_heartbeat(state))
    state.provenance_input = provenance_input
    state.provenance_attachments = provenance_attachments
    ACTIVE_RUNS[_active_key(profile, session_id)] = state
    await _append_state_event(state, "run", {"run_id": run_id, "session_id": session_id})
    siq_security_export.emit_run_event(state, event_type="agent_run.admitted")
    if emit_audit_trace_id:
        state.task = asyncio.create_task(
            _collect_stream_run(
                state,
                done_payload_factory,
                enforce_evidence_contract,
                emit_audit_trace_id=True,
            )
        )
    else:
        state.task = asyncio.create_task(_collect_stream_run(state, done_payload_factory, enforce_evidence_contract))
    return state


async def _stream_chat_reply_impl(
    message: str,
    request: Request,
    async_session: AsyncSession,
    *,
    session_id: str,
    profile: HermesProfile,
    context: Any | None = None,
    display_message: str | None = None,
    attachments: Any | None = None,
    history_limit: int = HISTORY_LIMIT,
    done_payload_factory: Callable[[str], Awaitable[dict]] | None = None,
    enforce_evidence_contract: bool = True,
    emit_audit_trace_id: bool = False,
    runtime_target: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    primary_market_agent_runtime.validate_market_runtime_context(profile, context)
    governed = qwen38_request_selector.confidential_request(profile)
    selected_route = None
    if governed:
        selected_route = await _requested_api_route(profile, runtime_target, session_id, context,
            tenant_id=tenant_id, user_id=user_id)
    envelope = await _prepare_chat_request_envelope(
        message,
        async_session,
        session_id=session_id,
        context=context,
        display_message=display_message,
        attachments=attachments,
    )
    all_attachments = envelope.all_attachments
    message_hash = envelope.message_hash
    user_display_message = envelope.user_display_message
    audit_context = agent_runtime_context.mutable_context_dict(context)
    memory_save_kwargs = _chat_memory_save_kwargs(profile, audit_context)
    if tenant_id is not None or user_id is not None:
        memory_save_kwargs.update(agent_runtime_memory.verified_memory_principal(session_id, tenant_id, user_id))

    if has_active_run(profile, session_id):
        if governed:
            yield {"event": "error", "data": json.dumps({
                "message": _ACTIVE_RUN_CONFLICT_MESSAGE, "error_code": "active_run_conflict",
                "retryable": True}, ensure_ascii=False)}
            return
        async for event in stream_active_run_events(
            request,
            profile=profile,
            session_id=session_id,
        ):
            yield event
        return

    primary_market_ic_runtime = primary_market_agent_runtime.is_primary_market_ic_runtime(profile, audit_context)
    catalog_reply = None if primary_market_ic_runtime or governed else build_wiki_catalog_reply(message)
    short_circuit = agent_runtime_preflight.plan_chat_preflight_short_circuit(
        catalog_reply=catalog_reply,
        is_general_assistant_request=_is_general_assistant_request(message),
    )
    if short_circuit.forget_recent_completed_run:
        _forget_recent_completed_run(profile, session_id, message_hash)
    elif short_circuit.should_check_duplicate and not governed:
        duplicate_reply = _recent_duplicate_reply(profile, session_id, message_hash)
        if duplicate_reply:
            yield {"event": "delta", "data": json.dumps({"content": duplicate_reply}, ensure_ascii=False)}
            yield {
                "event": "done",
                "data": json.dumps(
                    {"new_achievements": [], "deduped": True, "content": duplicate_reply},
                    ensure_ascii=False,
                ),
            }
            return

    provisional_claim = await _acquire_durable_provisional_claim(profile, session_id)
    if provisional_claim is None:
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "message": _ACTIVE_RUN_CONFLICT_MESSAGE,
                    "error_code": "active_run_conflict",
                    "retryable": True,
                },
                ensure_ascii=False,
            ),
        }
        return

    if short_circuit.catalog_reply:
        try:
            await save_message(
                async_session,
                "user",
                user_display_message,
                session_id,
                attachments=all_attachments,
                **memory_save_kwargs,
            )
            await save_message(
                async_session,
                "assistant",
                short_circuit.catalog_reply,
                session_id,
                **memory_save_kwargs,
            )
            await _refresh_session_memory_for_request(
                async_session,
                profile,
                session_id,
                audit_context,
            )
            _remember_completed_run(profile, session_id, message_hash, short_circuit.catalog_reply)
        except BaseException:
            await _release_provisional_durable_claim(
                provisional_claim.profile,
                provisional_claim.session_id,
                provisional_claim.provisional_run_id,
                provisional_claim.owner_id,
            )
            raise
        await _release_provisional_durable_claim(
            provisional_claim.profile,
            provisional_claim.session_id,
            provisional_claim.provisional_run_id,
            provisional_claim.owner_id,
            status="succeeded",
        )
        yield {"event": "delta", "data": json.dumps({"content": short_circuit.catalog_reply}, ensure_ascii=False)}
        yield {
            "event": "done",
            "data": json.dumps(
                {"new_achievements": [], "catalog": True, "content": short_circuit.catalog_reply},
                ensure_ascii=False,
            ),
        }
        return

    completed_guard_input: str | None = None
    completed_guard_active = False
    if profile == "siq_analysis" and _should_use_analysis_completion_guard(message):
        completed_artifacts = _analysis_completed_artifacts(context)
        if completed_artifacts:
            completed_guard_active = True
            completed_guard_input = _analysis_completion_guard_input(message, completed_artifacts)

    try:
        run_route = selected_route if selected_route is not None else await _requested_api_route(
            profile, runtime_target, session_id, audit_context, tenant_id=tenant_id, user_id=user_id)
        isolate_runtime_context = bool(run_route is not None and run_route.target == "openshell")
        history_scope = _runtime_research_identity_scope(audit_context, run_route)
        memory_context = _memory_context_with_scope(audit_context, history_scope)
        if isolate_runtime_context and history_scope is not None:
            memory_save_kwargs = {**memory_save_kwargs, "research_identity": history_scope}
        preflight_context = await _load_chat_run_preflight_context(
            async_session,
            message=(
                primary_market_agent_runtime.primary_market_retrieval_query(
                    profile,
                    audit_context,
                )
                if primary_market_ic_runtime
                else completed_guard_input or message
            ),
            session_id=session_id,
            profile=profile,
            attachments=all_attachments,
            history_limit=history_limit,
            context=memory_context,
            isolate_runtime_context=isolate_runtime_context,
            research_identity_scope=history_scope,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        all_attachments = preflight_context.attachments
        if _pdf_attachment_parse_dirs(all_attachments):
            yield {
                "event": "progress",
                "data": json.dumps(
                    _progress_payload(
                        status="running",
                        title="正在等待 PDF 解析",
                        detail="聊天附件只走 MinerU 直连解析，不进入财报解析前端队列；正在等待独立解析产物写入本地后再启动智能体。",
                        source="runtime",
                    ),
                    ensure_ascii=False,
                ),
            }
            await wait_for_pdf_attachment_parses(all_attachments)
            all_attachments = _attachments_with_fresh_metadata(all_attachments)
        await save_message(
            async_session,
            "user",
            user_display_message,
            session_id,
            attachments=all_attachments,
            **memory_save_kwargs,
        )
        image_analysis_context, image_model_succeeded = await analyze_images_with_primary_model(
            completed_guard_input or message,
            all_attachments,
        )
        run_input = build_hermes_run_input(
            completed_guard_input or message,
            profile=profile,
            session_id=session_id,
            context=audit_context,
            allow_initialize=preflight_context.allow_initialize,
            attachments=all_attachments,
            local_memory_context=preflight_context.local_memory_context,
            image_analysis_context=image_analysis_context,
            use_hermes_image_fallback=not image_model_succeeded,
        )
        if run_route is not None and run_route.pool_binding is not None:
            yield {
                "event": "progress",
                "data": json.dumps(
                    _progress_payload(
                        status="running",
                        title="正在等待公司分析运行槽",
                        detail="同一公司写任务按提交顺序串行执行；其他公司可并行运行。",
                        source="openshell_pool",
                    ),
                    ensure_ascii=False,
                ),
            }
    except BaseException:
        await _release_provisional_durable_claim(
            provisional_claim.profile,
            provisional_claim.session_id,
            provisional_claim.provisional_run_id,
            provisional_claim.owner_id,
        )
        raise
    try:
        claimed_run = await _claim_create_and_bind_routed_run(
            run_input,
            preflight_context.history,
            profile=profile,
            session_id=session_id,
            route=run_route,
            provisional_claim=provisional_claim,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except qwen38_request_selector.RequestSelectionError as exc:
        from services.qwen38_http_errors import public_error

        _, error = public_error(exc)
        yield {"event": "error", "data": json.dumps({
            "message": error["detail"], "error_code": error["error_code"],
            "retryable": error["retryable"],
        }, ensure_ascii=False)}
        return
    except HermesRuntimeSelectionError as exc:
        from services.hermes_runtime_http_errors import public_error

        _, error = public_error(exc)
        yield {"event": "error", "data": json.dumps({
            "message": error["detail"], "error_code": error["error_code"],
            "retryable": error["retryable"],
        }, ensure_ascii=False)}
        return
    except RuntimeError as exc:
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "message": "OpenShell 公司运行槽暂不可用，请稍后重试。",
                    "error_code": str(exc),
                    "retryable": True,
                },
                ensure_ascii=False,
            ),
        }
        return
    if claimed_run is None:
        yield {
            "event": "error",
            "data": json.dumps(
                {
                    "message": _ACTIVE_RUN_CONFLICT_MESSAGE,
                    "error_code": "active_run_conflict",
                    "retryable": True,
                },
                ensure_ascii=False,
            ),
        }
        return
    run_id, run_route, owner_id = claimed_run
    async def guarded_done_payload(reply: str) -> dict:
        if completed_guard_active:
            return {"new_achievements": [], "stage": "already_completed_llm_reply", "deduped": True}
        return await done_payload_factory(reply) if done_payload_factory else {"new_achievements": []}

    await _start_streaming_chat_run(
        profile=profile,
        session_id=session_id,
        run_id=run_id,
        message_hash=message_hash,
        message=message,
        context=audit_context,
        provenance_input=run_input,
        provenance_attachments=all_attachments,
        done_payload_factory=guarded_done_payload,
        enforce_evidence_contract=enforce_evidence_contract,
        emit_audit_trace_id=emit_audit_trace_id,
        owner_id=owner_id,
        run_route=run_route,
        memory_research_identity=history_scope,
    )

    async for event in stream_active_run_events(
        request,
        profile=profile,
        session_id=session_id,
    ):
        yield event


async def stream_chat_reply(
    message: str,
    request: Request,
    async_session: AsyncSession,
    *,
    session_id: str,
    profile: HermesProfile,
    context: Any | None = None,
    display_message: str | None = None,
    attachments: Any | None = None,
    history_limit: int = HISTORY_LIMIT,
    done_payload_factory: Callable[[str], Awaitable[dict]] | None = None,
    enforce_evidence_contract: bool = True,
    emit_audit_trace_id: bool = False,
    runtime_target: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> AsyncGenerator[dict, None]:
    from services import agent_runtime_read_access as read_access

    with _profile_wiki_context(profile):
        confidential = _confidential_auxiliary_request(profile)
        host_scope = agent_runtime_host_scope.RequestScope()
        iterator = _stream_chat_reply_impl(
            message,
            request,
            async_session,
            session_id=session_id,
            profile=profile,
            context=context,
            display_message=display_message,
            attachments=attachments,
            history_limit=history_limit,
            done_payload_factory=done_payload_factory,
            enforce_evidence_contract=enforce_evidence_contract,
            emit_audit_trace_id=emit_audit_trace_id,
            runtime_target=runtime_target,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        access = None
        try:
            while True:
                with confidential_auxiliary_models.scope(confidential), agent_runtime_host_scope.scope(host_scope):
                    try:
                        event = await anext(iterator)
                    except StopAsyncIteration:
                        break
                state = ACTIVE_RUNS.get((profile, session_id))
                route = state.run_route if state is not None else None
                protected = qwen38_request_selector.confidential_request(profile) or (
                    route is not None and route.data_classification not in {None, "public_research"})
                if access is not None or protected:
                    try:
                        if access is None:
                            selected = read_access.capture(profile=profile, session_id=session_id,
                                tenant_id=tenant_id, user_id=user_id, completed_original=True)
                            if selected is None or selected.state is None:
                                if event.get("event") not in {"progress", "error"}:
                                    raise read_access._denied()
                            else:
                                access = selected
                        await read_access.require_current(access)
                    except read_access.HTTPException:
                        yield {"event": "error", "data": json.dumps({
                            "code": "read_authorization_lost", "message": "当前无权读取任务输出"}, ensure_ascii=False)}
                        return
                yield event
        except (HermesRuntimeSelectionError, qwen38_request_selector.RequestSelectionError) as exc:
            # Selection can fail before the first event, while an SSE response
            # has already started. Send one terminal error, never a done event
            # or a retry on another runtime. The iterator's cleanup still runs.
            if isinstance(exc, HermesRuntimeSelectionError):
                from services.hermes_runtime_http_errors import public_error
            else:
                from services.qwen38_http_errors import public_error
            _, error = public_error(exc)
            yield {"event": "error", "data": json.dumps({
                "message": error["detail"], "error_code": error["error_code"],
                "retryable": error["retryable"],
            }, ensure_ascii=False)}
        finally:
            with confidential_auxiliary_models.scope(confidential), agent_runtime_host_scope.scope(host_scope):
                await iterator.aclose()


async def stop_active_run(profile: HermesProfile, session_id: str) -> dict:
    return await _streaming_stop_active_run(
        profile,
        session_id,
        stop_run_call=stop_run,
        stopped_message=STOPPED_MESSAGE,
        orphaned_run_message=ORPHANED_RUN_MESSAGE,
    )
