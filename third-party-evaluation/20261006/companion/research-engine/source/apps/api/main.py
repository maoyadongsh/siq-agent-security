import asyncio
import contextlib
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager

from database import create_db_and_tables
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from routers import (
    achievements,
    agent,
    analysis,
    auth,
    chat,
    deals,
    document_parser,
    downloads,
    eval_e2e,
    factchecker,
    legal,
    market_reports,
    meeting_exports,
    meeting_imports,
    meeting_native_captures,
    meeting_stream,
    meetings,
    openshell_data_grants,
    primary_market_materials,
    primary_market_meeting,
    research_universe,
    settings,
    source,
    system,
    tracking_agent,
    wiki,
    workflow,
    workspace,
)
from seed import seed_data
from services.auth_dependencies import get_current_user
from services.auth_service import AuthService
from services.meeting_database import get_meeting_async_session
from services.meeting_metrics import render_meeting_database_metrics, render_meeting_process_metrics
from services.meeting_stream_deployment import embedded_meeting_stream_gateway_enabled
from services.observability import (
    REQUEST_ID_HEADER,
    emit_json_log,
    metrics_snapshot,
    monotonic_ms,
    normalize_request_id,
    record_http_request,
    render_prometheus_metrics,
    reset_request_id,
    set_request_id,
)
from services.path_config import FRONTEND_ROOT
from services.runtime_security import cors_origins_from_env, validate_runtime_security_config
from sqlmodel.ext.asyncio.session import AsyncSession

from services import (
    hermes_runtime_http_errors,
    openshell_pool_recovery as openshell_pool_recovery_service,
    primary_market_materials as primary_market_materials_service,
    qwen38_http_errors,
    qwen38_recovery_manager as qwen38_recovery_service,
    qwen38_request_deployment,
)

FRONT_DIR = str(FRONTEND_ROOT)
logger = logging.getLogger("siq.api")


async def _primary_market_material_reconciler() -> None:
    interval = max(5.0, float(os.environ.get("SIQ_PRIMARY_MARKET_RECONCILE_INTERVAL_SECONDS", "20")))
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(
                primary_market_materials_service.recover_primary_market_materials_on_startup
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("primary_market_periodic_reconcile_failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    AuthService.validate_runtime_config()
    validate_runtime_security_config()
    isolated_request_api = qwen38_request_deployment.isolated()
    create_db_and_tables()
    seed_data()
    if os.environ.get("SIQ_PRIMARY_MARKET_RECONCILE_ON_STARTUP", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }:
        try:
            await asyncio.to_thread(
                primary_market_materials_service.recover_primary_market_materials_on_startup
            )
        except Exception:
            logger.exception("primary_market_startup_reconcile_failed")
    pool_recovery_manager: openshell_pool_recovery_service.OpenShellPoolRecoveryManager | None = None
    request_recovery_manager = None
    reconciler: asyncio.Task[None] | None = None
    try:
        if openshell_pool_recovery_service.recovery_enabled():
            pool_recovery_manager = openshell_pool_recovery_service.OpenShellPoolRecoveryManager()
            try:
                await pool_recovery_manager.start()
            except Exception:
                logger.exception("openshell_pool_startup_recovery_failed")
                await pool_recovery_manager.stop()
                pool_recovery_manager = None
        if openshell_pool_recovery_service.recovery_enabled() or isolated_request_api:
            request_recovery_manager = qwen38_recovery_service.RequestRecoveryManager()
            try:
                await request_recovery_manager.start()
            except Exception:
                logger.warning("qwen_request_startup_recovery_failed")
                await request_recovery_manager.stop()
                request_recovery_manager = None
        if os.environ.get("SIQ_PRIMARY_MARKET_RECONCILE_PERIODIC", "1").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            reconciler = asyncio.create_task(_primary_market_material_reconciler())
        yield
    finally:
        if request_recovery_manager is not None:
            await request_recovery_manager.stop()
        if pool_recovery_manager is not None:
            await pool_recovery_manager.stop()
        if reconciler is not None:
            reconciler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reconciler


app = FastAPI(title="SIQ API", lifespan=lifespan)
app.add_exception_handler(qwen38_http_errors.RequestSelectionError, qwen38_http_errors.handle)
app.add_exception_handler(hermes_runtime_http_errors.HermesRuntimeSelectionError, hermes_runtime_http_errors.handle)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins_from_env(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_observability_middleware(request, call_next):
    request_id = normalize_request_id(request.headers.get(REQUEST_ID_HEADER))
    request_id_token = set_request_id(request_id)
    start = time.perf_counter()
    status_code = 500
    recorded = False
    route_template = None
    try:
        response = await call_next(request)
        status_code = response.status_code
        route = request.scope.get("route")
        route_template = getattr(route, "path", None)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
    except Exception:
        duration_ms = monotonic_ms(start)
        record_http_request(
            request.method,
            request.url.path,
            status_code,
            duration_ms,
            route_template=route_template,
        )
        recorded = True
        emit_json_log(
            logger,
            "api_request_failed",
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        raise
    finally:
        duration_ms = monotonic_ms(start)
        if not recorded:
            route = request.scope.get("route")
            route_template = route_template or getattr(route, "path", None)
            record_http_request(
                request.method,
                request.url.path,
                status_code,
                duration_ms,
                route_template=route_template,
            )
        if status_code < 500:
            emit_json_log(
                logger,
                "api_request_completed",
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
        reset_request_id(request_id_token)

# 认证路由（无需认证）
app.include_router(auth.router, prefix="/api/auth")
app.include_router(openshell_data_grants.router, prefix="/api")

# 只读展示路由。报告 iframe 入口保持公开；来源/PDF 页码链接在 source router
# 内做任务归属校验，并使用短期签名 token 支持无 Bearer 头的页面跳转。
app.include_router(wiki.router, prefix="/api")
app.include_router(research_universe.router, prefix="/api")
app.include_router(source.router, prefix="/api")

# 业务路由
app.include_router(agent.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(chat.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(achievements.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(analysis.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(factchecker.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(legal.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(tracking_agent.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(settings.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(system.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(market_reports.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(meetings.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(meeting_exports.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(meeting_imports.router, prefix="/api", dependencies=[Depends(get_current_user)])
# Native batch endpoints authenticate with a capture-scoped Bearer token; only
# token issuance/renewal routes use the normal user dependency internally.
app.include_router(meeting_native_captures.router, prefix="/api")
# Ticket issuance stays in the API control plane. Development may embed the
# data plane; protected deployments default to the standalone gateway process.
app.include_router(
    meeting_stream.router
    if embedded_meeting_stream_gateway_enabled()
    else meeting_stream.control_router,
    prefix="/api",
)
app.include_router(document_parser.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(deals.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(primary_market_materials.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(primary_market_meeting.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(downloads.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(workflow.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(eval_e2e.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(workspace.router, prefix="/api", dependencies=[Depends(get_current_user)])
app.include_router(workspace.pdf_router, prefix="/api", dependencies=[Depends(get_current_user)])


@app.get("/health")
def health():
    snapshot = metrics_snapshot()
    return {
        "status": "ok",
        "uptime_seconds": snapshot["uptime_seconds"],
        "requests_total": snapshot["request_count"],
        "request_errors_total": snapshot["request_error_count"],
        "answer_traces_total": snapshot["answer_trace_count"],
        "openshell_recovery": openshell_pool_recovery_service.readiness_snapshot(),
        "qwen_request_recovery": qwen38_recovery_service.readiness_snapshot(),
    }


def _metrics_token() -> str:
    return str(os.getenv("SIQ_METRICS_TOKEN") or os.getenv("SIQ_INTERNAL_METRICS_TOKEN") or "").strip()


def _require_metrics_access(request: Request) -> None:
    expected = _metrics_token()
    protected_profile = str(os.getenv("SIQ_DEPLOYMENT_PROFILE") or "development").strip().lower() in {
        "docker",
        "prod",
        "production",
    }
    if not expected:
        if protected_profile:
            raise HTTPException(503, "Metrics authentication is not configured")
        return
    supplied = str(request.headers.get("X-SIQ-Service-Token") or "").strip()
    authorization = str(request.headers.get("Authorization") or "")
    if not supplied and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Metrics authentication required", headers={"WWW-Authenticate": "Bearer"})


@app.get("/metrics", response_class=PlainTextResponse, dependencies=[Depends(_require_metrics_access)])
async def metrics(
    meeting_session: AsyncSession = Depends(get_meeting_async_session),  # noqa: B008
):
    payload = render_prometheus_metrics() + render_meeting_process_metrics()
    try:
        payload += await render_meeting_database_metrics(meeting_session)
    except Exception:
        # Meeting metrics are optional and must never make the aggregate API
        # health/metrics surface depend on the additive meeting domain.
        logger.exception("meeting_metrics_collection_failed")
        payload += "# TYPE meeting_metrics_collection_error gauge\nmeeting_metrics_collection_error 1\n"
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@app.get("/", include_in_schema=False)
def chat_page():
    index_path = os.path.join(FRONT_DIR, "index.html")
    return FileResponse(index_path)
