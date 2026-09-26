"""设备侧待确认周期发现计划的只读枚举（R01 安装→持续发现联动的最小补齐）。

背景缺口：组织侧创建计划要求设备已注册（`app/routers/discovery_schedules.py::create_schedule`
在找不到 `EdgeAgent` 时返回 404），而设备侧原先只有
`GET /edge/v1/discovery-schedules/{schedule_id}`——设备必须先通过带外渠道知道 schedule_id
才能读取并签名确认。新设备因此无法自行发现"有一个计划在等我确认"。

本模块只新增一个只读枚举端点，把可发现范围严格限制在**当前认证设备自身**的
`pending_confirmation` 行；不改变组织侧创建语义，不新增自动授权，不弱化设备侧确认：
列出的每一项仍需设备按既有 `POST /edge/v1/discovery-schedules/confirm` 完成签名确认才生效。

只读语义与物化投影校验复用既有按 ID 读取路径（`discovery_schedule_confirmation.read_schedule_intent`）：
同一套绑定校验、同一套投影一致性校验、同样在租户行锁下重读设备凭据哈希。
`active`/`paused`/`revoked` 不进本列表：前两者继续走既有按 ID 读取，后者不应被当作待办。

已在 `app/main.py` 注册；设备 CLI 自动发现与确认衔接仍需单独验收。
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.discovery_schedule import DiscoverySchedule
from app.discovery_scheduler import digest
from app.models import DiscoveryScheduleRecord, EdgeAgent, Environment
from app.routers.discovery_schedules import _utc_z, lock_tenant
from app.security import verify_edge_secret

router = APIRouter(tags=["edge"])

# 唯一可枚举的状态：需要设备侧显式确认的那些行。
PENDING_STATUS = "pending_confirmation"


def _pending_item(row, edge) -> dict:
    """白名单投影；与按 ID 读取使用完全相同的绑定与一致性校验，失败即不投影。"""
    intent = DiscoverySchedule.model_validate(row.intent)
    intent.require_binding(edge.device_identity, row.installation_plan_digest)
    if (intent.schedule_id != row.id or digest(intent.model_dump()) != row.intent_digest
            or row.starts_at != intent.start.replace(tzinfo=None)
            or row.expires_at != intent.end.replace(tzinfo=None)
            or row.interval_seconds != intent.interval_seconds or row.max_runs != intent.max_runs):
        raise ValueError("inconsistent_projection")
    return {"schedule_id": row.id, "status": row.status, "revision": row.revision,
            "intent": intent.model_dump(), "intent_digest": row.intent_digest}


@router.get("/edge/v1/discovery-schedules")
def list_pending_schedules(request: Request, response: Response,
                           cursor: str | None = Query(default=None, pattern=r"^eds-[a-f0-9]{32}$"),
                           limit: int = Query(default=20, ge=1, le=100),
                           session: Session = Depends(get_session)):
    edge = verify_edge_secret(request, request.headers.get("X-Edge-Identity", ""), session)
    authenticated_hash = edge.secret_hash
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(404, "not_found")
    lock_tenant(session, env.tenant_id)
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.id == edge.id).with_for_update()
                          .execution_options(populate_existing=True))
    if (edge is None or edge.revoked_at is not None or edge.secret_hash != authenticated_hash
            or edge.environment_id != env.id):
        raise HTTPException(409, "discovery_schedule_device_changed")
    query = select(DiscoveryScheduleRecord).where(
        DiscoveryScheduleRecord.tenant_id == env.tenant_id,
        DiscoveryScheduleRecord.environment_id == env.id,
        DiscoveryScheduleRecord.edge_agent_id == edge.id,
        DiscoveryScheduleRecord.status == PENDING_STATUS,
    )
    if cursor is not None:
        query = query.where(DiscoveryScheduleRecord.id > cursor)
    rows = list(session.scalars(query.order_by(DiscoveryScheduleRecord.id).limit(limit + 1)))
    page = rows[:limit]
    items, integrity_failed = [], []
    for row in page:
        try:
            items.append(_pending_item(row, edge))
        except ValueError:
            # 不投影不可信内容，也不静默当作"没有待办"：单独列出该 schedule_id，
            # 让设备与审计都能看到"这一行存在但无法安全读取"。分页仍继续推进，
            # 否则一行损坏会让后续所有待办永久不可达。
            integrity_failed.append(row.id)
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "enterprise-discovery-schedule-pending-list/v1",
            "evaluated_at": _utc_z(datetime.now(UTC)), "items": items,
            "integrity_failed": integrity_failed,
            "next_cursor": page[-1].id if len(rows) > limit else None}
