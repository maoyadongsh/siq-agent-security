"""OCSF 事件导出路由（SIEM/工单/取证）。

不变量：
- audit:read 权限；tenant_id 只从验证身份派生；
- 只读导出，但导出动作本身写审计（与读操作同事务提交，summary 只含 class/条数/since，不含导出内容）；
- NDJSON 流式格式，时间正序；敏感导出响应带 Cache-Control: no-store；
- 非法参数（含时区换算越界的极端 since）在导出前受控拒绝，拒绝不留导出审计。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AuditEvent, Finding
from app.ocsf import audit_to_ocsf, finding_to_ocsf
from app.outbox import audit
from app.security import Identity, require_permission

router = APIRouter(tags=["export"])

_EXPORT_CLASSES = {
    "detection_finding": (Finding, Finding.last_seen_at, finding_to_ocsf),
    "api_activity": (AuditEvent, AuditEvent.created_at, audit_to_ocsf),
}


def _parse_since(raw: str) -> datetime:
    """ISO 8601 → naive UTC（与库内时间戳一致）；非法输入 422。

    极端的显式偏移（如 `9999-12-31T23:59:59-14:00`）换算到 UTC 会越过 `datetime` 上下限，
    `astimezone` 抛 OverflowError——同样按非法输入受控拒绝，不返回 500、不回显输入、
    也不放宽解析去接受它。
    """
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    except (ValueError, OverflowError):
        raise HTTPException(status_code=422, detail="invalid_since") from None
    return parsed


@router.get("/api/v1/export/ocsf")
def export_ocsf(
    request: Request,
    class_: str | None = Query(default=None, alias="class"),
    since: str | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("audit:read")),
):
    if class_ not in _EXPORT_CLASSES:
        raise HTTPException(status_code=422, detail="invalid_class")
    model, time_column, mapper = _EXPORT_CLASSES[class_]

    query = select(model).where(model.tenant_id == identity.tenant_id)
    if since is not None:
        query = query.where(time_column >= _parse_since(since))
    rows = list(session.scalars(query.order_by(time_column.asc(), model.id).limit(limit)))

    lines = [json.dumps(mapper(row), ensure_ascii=False) for row in rows]
    body = "\n".join(lines) + ("\n" if lines else "")

    # 导出动作审计：summary 只含 class/条数/since，不含任何导出内容
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "export.ocsf",
        "export",
        resource_id=class_,
        request_id=getattr(request.state, "request_id", None),
        summary={"class": class_, "count": len(rows), "since": since},
    )
    session.commit()
    # 敏感导出：禁止任何层级缓存（媒体类型与正文不变）
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store"},
    )
