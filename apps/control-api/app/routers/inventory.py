"""资产发现与纳管路由（设计文档 §10/§18.2）。

不变量：
- Edge 上传的候选/证据按 Edge 所属环境归租户，客户端不可指定 tenant；
- 上传批次校验：每个 evidence 必须被本批至少一个 candidate 引用（Connector 合同硬性要求）；
- confirm/dismiss 是受控动作：审计 + outbox 事件 + 状态机约束。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AgentAsset, AgentInstance, EdgeTask, Environment, Evidence, PermissionFact, utcnow
from app.outbox import audit, emit_event
from app.schemas import (
    AgentAssetOut,
    CandidateConfirm,
    CandidateDismiss,
    EvidenceOut,
    PermissionFactOut,
    ScanCreate,
    ScanOut,
)
from app.security import Identity, ensure_permission, get_identity, require_permission, verify_edge_secret

router = APIRouter(tags=["inventory"])


@router.post("/api/v1/scans", response_model=ScanOut)
def create_scan(
    body: ScanCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("env:manage")),
):
    """创建限定范围扫描任务（设计文档 §9.3 数据流起点）。范围校验在 Connector 侧二次执行。"""
    env = session.scalar(
        select(Environment).where(Environment.id == body.environment_id, Environment.tenant_id == identity.tenant_id)
    )
    if env is None:
        raise HTTPException(status_code=404, detail="not_found")
    task = EdgeTask(
        environment_id=env.id,
        task_type="scan",
        payload={"scope": body.scope},
        expires_at=utcnow() + timedelta(seconds=_task_ttl(session)),
    )
    session.add(task)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "scan.create",
        "environment",
        resource_id=env.id,
        summary={"scope_keys": sorted(body.scope.keys())},
    )
    emit_event(session, identity.tenant_id, "scan.created.v1", {"task_id": task.id, "environment_id": env.id})
    session.commit()
    return ScanOut(task_id=task.id)


def _task_ttl(session: Session) -> int:
    from app.config import load_settings

    return load_settings().edge_task_ttl_seconds


@router.post("/edge/v1/batches")
async def edge_upload_batch(request: Request, session: Session = Depends(get_session)):
    """Edge 上传候选与证据批次。签名校验为 Phase 0 后续项（当前记录并告警，不静默放行未知签名）。"""
    device_identity = request.headers.get("X-Edge-Identity")
    if not device_identity:
        raise HTTPException(status_code=401, detail="missing_edge_identity")
    edge = verify_edge_secret(request, device_identity)
    body = await _read_json(request)
    candidates = body.get("candidates") or []
    evidence = body.get("evidence") or []

    if not candidates and not evidence:
        raise HTTPException(status_code=422, detail="empty_batch")
    evidence_ids = {ev.get("evidence_id") for ev in evidence}
    if evidence_ids:
        referenced: set[str] = set()
        for cand in candidates:
            referenced.update(cand.get("evidence_ids") or [])
        orphan = evidence_ids - referenced
        if orphan:
            # Connector 合同：每批 evidence 必须被本批 candidate 引用
            raise HTTPException(status_code=422, detail=f"orphan_evidence: {sorted(orphan)[:3]}")

    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="environment_gone")
    tenant_id = env.tenant_id
    now = utcnow()

    inserted_evidence = 0
    for ev in evidence:
        session.add(
            Evidence(
                id=ev["evidence_id"],
                tenant_id=tenant_id,
                environment_id=env.id,
                source_type=ev["source_type"],
                source_locator=ev["source_locator"],
                subject_ref=ev.get("subject_ref"),
                observed_at=_parse_dt(ev["observed_at"]),
                collected_at=_parse_dt(ev.get("collected_at")) or now,
                collector_id=edge.device_identity,
                connector_version=ev.get("connector_version", "0"),
                content_hash=ev["content_hash"],
                redaction_profile=ev.get("redaction_profile", "siq.redaction.v1"),
                classification=ev.get("classification", "internal"),
                payload_ref=ev.get("payload_ref"),
                signature=ev.get("signature", ""),
                expires_at=_parse_dt(ev.get("expires_at")),
            )
        )
        inserted_evidence += 1

    inserted_candidates = 0
    for cand in candidates:
        existing = session.scalar(
            select(AgentAsset).where(
                AgentAsset.tenant_id == tenant_id,
                AgentAsset.source_type == cand["source_type"],
                AgentAsset.source_locator == cand["source_locator"],
            )
        )
        if existing is not None:
            existing.updated_at = now
            continue
        session.add(
            AgentAsset(
                tenant_id=tenant_id,
                name=cand["name"],
                framework=cand.get("framework", "unknown"),
                status="candidate",
                source_type=cand["source_type"],
                source_locator=cand["source_locator"],
            )
        )
        inserted_candidates += 1

    audit(
        session,
        tenant_id,
        "edge",
        device_identity,
        "evidence.batch.upload",
        "environment",
        resource_id=env.id,
        summary={"candidates": inserted_candidates, "evidence": inserted_evidence},
    )
    session.commit()
    return {"candidates": inserted_candidates, "evidence": inserted_evidence}


def _parse_dt(value) -> datetime | None:
    """ISO 字符串/aware datetime → naive UTC（与模型 utcnow() 口径一致）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC).replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)


async def _read_json(request: Request) -> dict:
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
        return body
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json") from None


@router.get("/api/v1/candidates", response_model=list[AgentAssetOut])
def list_candidates(
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("agent:read")),
):
    return list(
        session.scalars(
            select(AgentAsset)
            .where(
                AgentAsset.tenant_id == identity.tenant_id,
                AgentAsset.status.in_(["candidate", "needs_review"]),
            )
            .order_by(AgentAsset.updated_at.desc())
            .limit(200)
        )
    )


def _asset_or_404(session: Session, tenant_id: str, asset_id: str) -> AgentAsset:
    asset = session.scalar(
        select(AgentAsset).where(AgentAsset.id == asset_id, AgentAsset.tenant_id == tenant_id)
    )
    if asset is None:
        raise HTTPException(status_code=404, detail="not_found")
    return asset


@router.post("/api/v1/candidates/{asset_id}/confirm", response_model=AgentAssetOut)
def confirm_candidate(
    asset_id: str,
    body: CandidateConfirm,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("agent:confirm")),
):
    asset = _asset_or_404(session, identity.tenant_id, asset_id)
    if asset.status not in ("candidate", "needs_review"):
        raise HTTPException(status_code=409, detail="invalid_state")
    asset.status = "confirmed"
    asset.role = body.role or asset.role
    asset.system_id = body.system_id or asset.system_id
    asset.owner_user_id = body.owner_user_id or asset.owner_user_id
    asset.confirmed_by = identity.actor_id
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "agent.confirm",
        "agent_asset",
        resource_id=asset.id,
    )
    emit_event(
        session,
        identity.tenant_id,
        "agent.asset.confirmed.v1",
        {"agent_asset_id": asset.id, "role": asset.role},
        resource_ref=asset.id,
    )
    session.commit()
    session.refresh(asset)
    return asset


@router.post("/api/v1/candidates/{asset_id}/dismiss", response_model=AgentAssetOut)
def dismiss_candidate(
    asset_id: str,
    body: CandidateDismiss,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("agent:confirm")),
):
    asset = _asset_or_404(session, identity.tenant_id, asset_id)
    if asset.status in ("managed", "retired"):
        raise HTTPException(status_code=409, detail="invalid_state")
    asset.status = "dismissed"
    asset.dismissed_reason = body.reason
    asset.dismissed_expires_at = body.expires_at
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "agent.dismiss",
        "agent_asset",
        resource_id=asset.id,
        summary={"reason": body.reason},
    )
    session.commit()
    session.refresh(asset)
    return asset


@router.get("/api/v1/agents", response_model=list[AgentAssetOut])
def list_agents(
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("agent:read")),
):
    return list(
        session.scalars(
            select(AgentAsset)
            .where(
                AgentAsset.tenant_id == identity.tenant_id,
                AgentAsset.status.in_(["confirmed", "managed", "stale", "retired"]),
            )
            .order_by(AgentAsset.name)
            .limit(200)
        )
    )


@router.get("/api/v1/agents/{asset_id}", response_model=AgentAssetOut)
def get_agent(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    # 先租户定位（404）再权限（403）：跨租户 ID 猜测与不存在不可区分
    asset = _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    return asset


@router.get("/api/v1/agents/{asset_id}/permissions", response_model=list[PermissionFactOut])
def get_agent_permissions(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    return list(
        session.scalars(
            select(PermissionFact)
            .where(
                PermissionFact.tenant_id == identity.tenant_id,
                PermissionFact.subject_id == asset_id,
            )
            .order_by(PermissionFact.domain, PermissionFact.action)
        )
    )


@router.get("/api/v1/agents/{asset_id}/evidence", response_model=list[EvidenceOut])
def get_agent_evidence(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    return list(
        session.scalars(
            select(Evidence)
            .where(Evidence.tenant_id == identity.tenant_id, Evidence.subject_ref == asset_id)
            .order_by(Evidence.observed_at.desc())
            .limit(200)
        )
    )


@router.get("/api/v1/agents/{asset_id}/instances")
def get_agent_instances(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    instances = session.scalars(
        select(AgentInstance).where(
            AgentInstance.tenant_id == identity.tenant_id, AgentInstance.asset_id == asset_id
        )
    )
    return [
        {
            "id": i.id,
            "runtime": i.runtime,
            "version": i.version,
            "artifact_digest": i.artifact_digest,
            "location": i.location,
            "status": i.status,
            "observed_at": i.observed_at.isoformat() if i.observed_at else None,
        }
        for i in instances
    ]
