"""资产发现与纳管路由（设计文档 §10/§18.2）。

不变量：
- Edge 上传的候选/证据按 Edge 所属环境归租户，客户端不可指定 tenant；
- 上传批次校验：每个 evidence 必须被本批至少一个 candidate 引用（Connector 合同硬性要求）；
- confirm/dismiss 是受控动作：审计 + outbox 事件 + 状态机约束。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.evidence_signing import batch_signed_bytes, evidence_signed_bytes, verify_hex_signature
from app.models import AgentAsset, AgentInstance, EdgeTask, Environment, Evidence, PermissionFact, System, utcnow
from app.outbox import audit, emit_event
from app.schemas import (
    AgentAssetOut,
    AgentInstanceCreate,
    AgentInstanceOut,
    CandidateConfirm,
    CandidateDismiss,
    EdgeBatchIn,
    EvidenceOut,
    PermissionFactOut,
    ScanCreate,
    ScanOut,
)
from app.security import Identity, ensure_permission, get_identity, require_permission, verify_edge_secret

router = APIRouter(tags=["inventory"])

_MAX_EDGE_BATCH_BYTES = 8 * 1024 * 1024


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
    # 租户级扫描配额（威胁 T19：扫描风暴 DoS）
    from sqlalchemy import func

    from app.config import load_settings
    from app.models import Environment as EnvModel

    pending_env_ids = session.scalars(
        select(EnvModel.id).where(EnvModel.tenant_id == identity.tenant_id)
    ).all()
    pending_scans = session.scalar(
        select(func.count(EdgeTask.id)).where(
            EdgeTask.environment_id.in_(pending_env_ids),
            EdgeTask.task_type == "scan",
            EdgeTask.status == "pending",
        )
    )
    if pending_scans >= load_settings().scan_quota_per_tenant:
        raise HTTPException(
            status_code=429,
            detail=f"scan_quota_exceeded: {pending_scans} >= {load_settings().scan_quota_per_tenant}",
        )
    expires_at = utcnow() + timedelta(seconds=_task_ttl(session))
    payload: dict = {"scope": body.scope}
    if body.connector:
        payload["connector"] = body.connector
    task = EdgeTask(
        environment_id=env.id,
        task_type="scan",
        payload=payload,
        expires_at=expires_at,
    )
    session.add(task)
    session.flush()  # 获取 task.id 用于签名信封
    from app.signing import sign_task_payload

    task.signature = sign_task_payload(
        task.id, task.task_type, env.id, task.payload, expires_at.isoformat()
    )
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


@router.post("/api/v1/scans/smart")
def smart_scan(
    environment_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """智能扫描（用户一键发现）：标准安全范围一次下发。

    范围（§10.1 默认排除原则）：Hermes profiles、OpenClaw 配置、Docker 容器、
    systemd 服务、进程列表、Kubernetes pod、MCP 客户端配置、PiAgent/WorkBuddy 约定目录。
    不含目录扫描与 Dify 部署目录——受控目录必须用户显式授权（§10.1 无默认范围）。
    scope 为 None 的 Connector 使用其众所周知默认路径（payload 不带 scope 键，
    避免空 scope 被 validate_scope 拒绝）。
    """
    from sqlalchemy import func

    from app.config import load_settings
    from app.models import Environment as _Env

    ensure_permission(identity, "env:manage")
    env = session.scalar(
        select(_Env).where(_Env.id == environment_id, _Env.tenant_id == identity.tenant_id)
    )
    if env is None:
        raise HTTPException(status_code=404, detail="not_found")

    standard_scans = [
        ("hermes", {"roots": ["~/.hermes/profiles/*"], "include": ["config.yaml", "SOUL.md"]}),
        ("openclaw", {"roots": ["~/.openclaw"]}),
        ("docker", {}),
        ("systemd", {}),
        ("process", {}),
        ("kubernetes", {}),
        ("mcp", None),
        ("piagent", None),
        ("workbuddy", None),
    ]
    env_ids = list(session.scalars(select(_Env.id).where(_Env.tenant_id == identity.tenant_id)))
    pending = session.scalar(
        select(func.count(EdgeTask.id)).where(
            EdgeTask.environment_id.in_(env_ids),
            EdgeTask.task_type == "scan",
            EdgeTask.status == "pending",
        )
    )
    quota = load_settings().scan_quota_per_tenant
    if pending + len(standard_scans) > quota:
        raise HTTPException(
            status_code=429,
            detail=f"scan_quota_exceeded: {pending} + {len(standard_scans)} > {quota}",
        )

    from app.signing import sign_task_payload

    tasks = []
    for connector, scope in standard_scans:
        expires_at = utcnow() + timedelta(seconds=_task_ttl(session))
        # scope 为 None 时不带 scope 键：Connector 回退众所周知默认路径（空 scope 会被 validate_scope 拒绝）
        payload: dict = {"connector": connector}
        if scope is not None:
            payload["scope"] = scope
        task = EdgeTask(
            environment_id=env.id,
            task_type="scan",
            payload=payload,
            expires_at=expires_at,
        )
        session.add(task)
        session.flush()
        task.signature = sign_task_payload(task.id, task.task_type, env.id, task.payload, expires_at.isoformat())
        tasks.append({"task_id": task.id, "connector": connector})
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "scan.smart",
        "environment",
        resource_id=env.id,
        summary={"connectors": [t["connector"] for t in tasks]},
    )
    session.commit()
    return {"tasks": tasks, "note": "受控目录与 Dify 部署目录扫描需显式授权，不包含在智能扫描内（§10.1）"}


@router.get("/api/v1/scans/{task_id}")
def get_scan(
    task_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """扫描任务状态查询（§18.2 首批 API 清单）。租户隔离：任务经环境归属租户。"""
    from app.models import Environment as _Env

    task = session.scalar(
        select(EdgeTask).where(
            EdgeTask.id == task_id,
            EdgeTask.environment_id.in_(
                select(_Env.id).where(_Env.tenant_id == identity.tenant_id)
            ),
        )
    )
    if task is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "env:read")
    return {
        "id": task.id,
        "task_type": task.task_type,
        "payload": task.payload,
        "status": task.status,
        "expires_at": task.expires_at.isoformat() if task.expires_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def _task_ttl(session: Session) -> int:
    from app.config import load_settings

    return load_settings().edge_task_ttl_seconds


@router.post("/edge/v1/batches")
async def edge_upload_batch(request: Request, session: Session = Depends(get_session)):
    """验签、任务绑定和 Schema 校验后写入不可变 Evidence observations。"""
    device_identity = request.headers.get("X-Edge-Identity")
    if not device_identity:
        raise HTTPException(status_code=401, detail="missing_edge_identity")
    edge = verify_edge_secret(request, device_identity, session)
    raw_body = await _read_json(request)
    signature = raw_body.get("signature", "")
    if not verify_hex_signature(edge.public_key_pem, batch_signed_bytes(raw_body), signature):
        raise HTTPException(status_code=401, detail="batch_signature_invalid")
    try:
        body = EdgeBatchIn.model_validate(raw_body)
    except ValidationError as exc:
        errors = [{"loc": list(error["loc"]), "type": error["type"]} for error in exc.errors()]
        raise HTTPException(status_code=422, detail={"code": "batch_schema_invalid", "errors": errors}) from None

    candidates = body.candidates
    evidence = body.evidence
    permission_facts = body.permission_facts

    if not candidates and not evidence and not permission_facts:
        raise HTTPException(status_code=422, detail="empty_batch")
    task = session.scalar(
        select(EdgeTask).where(
            EdgeTask.id == body.task_id,
            EdgeTask.environment_id == edge.environment_id,
            EdgeTask.task_type == "scan",
            EdgeTask.status.in_(["pending", "uploaded"]),
        )
    )
    if task is None or task.expires_at < utcnow():
        raise HTTPException(status_code=409, detail="batch_task_binding_invalid")
    result_digest = hashlib.sha256(batch_signed_bytes(raw_body)).hexdigest()
    if task.status == "uploaded":
        if task.result_digest != result_digest:
            raise HTTPException(status_code=409, detail="batch_task_replay_conflict")
        return {"candidates": 0, "evidence": 0, "permission_facts": 0, "idempotent": True}

    raw_evidence = raw_body.get("evidence") or []
    for item in raw_evidence:
        if item.get("collector_id") != edge.device_identity:
            raise HTTPException(status_code=422, detail="evidence_collector_mismatch")
        if not verify_hex_signature(edge.public_key_pem, evidence_signed_bytes(item), item.get("signature", "")):
            raise HTTPException(status_code=401, detail="evidence_signature_invalid")

    now = utcnow()
    for item in evidence:
        collected_at = _parse_dt(item.collected_at)
        if collected_at is None or abs(now - collected_at) > timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="evidence_collection_stale")

    # 安全不变量：effective 只能来自权威源解析（Phase 2 Resolver），Edge 不得自报
    for pf in permission_facts:
        if pf.state == "effective":
            raise HTTPException(status_code=422, detail="edge_cannot_assert_effective")
    candidate_ids = [cand.candidate_id for cand in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise HTTPException(status_code=422, detail="duplicate_candidate_id")
    candidate_id_set = set(candidate_ids)
    for pf in permission_facts:
        if pf.subject.type == "agent_asset" and pf.subject.id not in candidate_id_set:
            raise HTTPException(status_code=422, detail="permission_subject_candidate_missing")
    evidence_ids = {ev.evidence_id for ev in evidence}
    referenced: set[str] = set()
    for cand in candidates:
        referenced.update(cand.evidence_ids)
    orphan = evidence_ids - referenced
    if orphan:
        # Connector 合同：每批 evidence 必须被本批 candidate 引用
        raise HTTPException(status_code=422, detail=f"orphan_evidence: {sorted(orphan)[:3]}")
    missing = referenced - evidence_ids
    if missing:
        raise HTTPException(status_code=422, detail=f"candidate_evidence_missing: {sorted(missing)[:3]}")
    permission_refs = {ref for pf in permission_facts for ref in pf.evidence_ids}
    missing_permission_refs = permission_refs - evidence_ids
    if missing_permission_refs:
        raise HTTPException(
            status_code=422,
            detail=f"permission_evidence_missing: {sorted(missing_permission_refs)[:3]}",
        )

    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(status_code=404, detail="environment_gone")
    tenant_id = env.tenant_id
    inserted_evidence = 0
    for ev in evidence:
        existing_ev = session.scalar(
            select(Evidence).where(
                Evidence.tenant_id == tenant_id,
                Evidence.environment_id == env.id,
                Evidence.evidence_id == ev.evidence_id,
                Evidence.content_hash == ev.content_hash,
            )
        )
        if existing_ev is not None:
            continue
        session.add(
            Evidence(
                evidence_id=ev.evidence_id,
                tenant_id=tenant_id,
                environment_id=env.id,
                source_type=ev.source_type,
                source_locator=ev.source_locator,
                subject_ref=ev.subject_ref,
                observed_at=_parse_dt(ev.observed_at),
                collected_at=_parse_dt(ev.collected_at) or now,
                collector_id=edge.device_identity,
                connector_version=ev.connector_version,
                content_hash=ev.content_hash,
                redaction_profile=ev.redaction_profile,
                classification=ev.classification,
                payload_ref=ev.payload_ref,
                signature=ev.signature,
                expires_at=_parse_dt(ev.expires_at),
            )
        )
        inserted_evidence += 1

    inserted_candidates = 0
    candidate_asset_ids: dict[str, str] = {}
    for cand in candidates:
        existing = session.scalar(
            select(AgentAsset).where(
                AgentAsset.tenant_id == tenant_id,
                AgentAsset.source_type == cand.source_type,
                AgentAsset.source_locator == cand.source_locator,
            )
        )
        cand_evidence_ids = cand.evidence_ids
        if existing is not None:
            existing.updated_at = now
            existing.evidence_ids = sorted(set((existing.evidence_ids or []) + cand_evidence_ids))
            attrs = dict(existing.attributes or {})
            if cand.attributes:
                # 脱敏候选属性合并入账（后到的观察覆盖同名键）
                attrs.update(cand.attributes)
            if cand.artifact_digest and cand.artifact_digest != existing.artifact_digest:
                # P1-8 变更痕迹：旧 digest 不静默丢弃，写入 attributes.digest_observations
                observations = list(attrs.get("digest_observations", []))
                observations.append(
                    {
                        "from": existing.artifact_digest,
                        "to": cand.artifact_digest,
                        "observed_at": now.isoformat(),
                    }
                )
                attrs["digest_observations"] = observations[-20:]
                existing.artifact_digest = cand.artifact_digest
            existing.attributes = attrs
            candidate_asset_ids[cand.candidate_id] = existing.id
            continue
        asset = AgentAsset(
            tenant_id=tenant_id,
            name=cand.name,
            framework=cand.framework,
            status="candidate",
            source_type=cand.source_type,
            source_locator=cand.source_locator,
            artifact_digest=cand.artifact_digest,
            attributes=dict(cand.attributes or {}),
            evidence_ids=cand_evidence_ids,
        )
        session.add(asset)
        session.flush()
        candidate_asset_ids[cand.candidate_id] = asset.id
        inserted_candidates += 1

    inserted_permissions = 0
    for pf in permission_facts:
        subject_id = candidate_asset_ids[pf.subject.id] if pf.subject.type == "agent_asset" else pf.subject.id
        existing_pf = session.scalar(
            select(PermissionFact).where(
                PermissionFact.tenant_id == tenant_id,
                PermissionFact.environment_id == env.id,
                PermissionFact.subject_type == pf.subject.type,
                PermissionFact.subject_id == subject_id,
                PermissionFact.domain == pf.domain,
                PermissionFact.action == pf.action,
                PermissionFact.resource_type == pf.resource.type,
                PermissionFact.resource_value == pf.resource.value,
                PermissionFact.effect == pf.effect,
                PermissionFact.state == pf.state,
                PermissionFact.authority == pf.authority,
            )
        )
        if existing_pf is not None:
            existing_pf.delegated_user = pf.delegated_user
            existing_pf.conditions = pf.conditions
            existing_pf.authority_revision = pf.authority_revision
            existing_pf.evidence_ids = pf.evidence_ids
            existing_pf.valid_from = _parse_dt(pf.valid_from)
            existing_pf.valid_until = _parse_dt(pf.valid_until)
            continue
        session.add(
            PermissionFact(
                tenant_id=tenant_id,
                environment_id=env.id,
                subject_type=pf.subject.type,
                subject_id=subject_id,
                delegated_user=pf.delegated_user,
                domain=pf.domain,
                action=pf.action,
                resource_type=pf.resource.type,
                resource_value=pf.resource.value,
                effect=pf.effect,
                conditions=pf.conditions,
                state=pf.state,
                authority=pf.authority,
                authority_revision=pf.authority_revision,
                evidence_ids=pf.evidence_ids,
                valid_from=_parse_dt(pf.valid_from),
                valid_until=_parse_dt(pf.valid_until),
            )
        )
        inserted_permissions += 1

    audit(
        session,
        tenant_id,
        "edge",
        device_identity,
        "evidence.batch.upload",
        "environment",
        resource_id=env.id,
        summary={
            "candidates": inserted_candidates,
            "evidence": inserted_evidence,
            "permission_facts": inserted_permissions,
        },
    )
    task.status = "uploaded"
    task.result_digest = result_digest
    session.commit()
    return {
        "candidates": inserted_candidates,
        "evidence": inserted_evidence,
        "permission_facts": inserted_permissions,
    }


def _parse_dt(value) -> datetime | None:
    """ISO 字符串/aware datetime → naive UTC（与模型 utcnow() 口径一致）。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value
        return value.astimezone(UTC).replace(tzinfo=None)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)


async def _read_json(request: Request) -> dict:
    content_length = request.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > _MAX_EDGE_BATCH_BYTES:
                raise HTTPException(status_code=413, detail="batch_too_large")
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid_content_length") from None
    raw = bytearray()
    try:
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > _MAX_EDGE_BATCH_BYTES:
                raise HTTPException(status_code=413, detail="batch_too_large")
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise ValueError
        return body
    except HTTPException:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid_json") from None


@router.get("/api/v1/permissions", response_model=list[PermissionFactOut])
def list_permissions(
    authority: str | None = None,
    domain: str | None = None,
    state: str | None = None,
    subject_id: str | None = None,
    environment_id: str | None = None,
    cursor: str | None = None,
    limit: int = 100,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """统一权限视图（§20.2）：按权限域/权威源/状态过滤，租户隔离。"""
    if environment_id:
        env = session.scalar(
            select(Environment).where(
                Environment.id == environment_id,
                Environment.tenant_id == identity.tenant_id,
            )
        )
        if env is None:
            raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "agent:read")
    query = select(PermissionFact).where(PermissionFact.tenant_id == identity.tenant_id)
    if authority:
        query = query.where(PermissionFact.authority == authority)
    if domain:
        query = query.where(PermissionFact.domain == domain)
    if state:
        query = query.where(PermissionFact.state == state)
    if subject_id:
        query = query.where(PermissionFact.subject_id == subject_id)
    if environment_id:
        query = query.where(PermissionFact.environment_id == environment_id)
    if cursor:
        query = _apply_cursor(query, PermissionFact, cursor)
    return list(
        session.scalars(
            query.order_by(PermissionFact.authority, PermissionFact.domain, PermissionFact.id).limit(min(limit, 500))
        )
    )


@router.get("/api/v1/permissions/diff")
def permissions_diff(
    subject_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """declared vs effective 权限 Diff（§12.4 第 6 步 / §20.2）。

    对指定主体按 (domain, action, resource_value) 比对：
    - declared_not_effective：声明了但无有效事实（待验证/风险）；
    - effective_not_declared：生效但未声明（潜在带外）；
    - consistent：两者一致。
    """
    ensure_permission(identity, "agent:read")
    facts = list(
        session.scalars(
            select(PermissionFact).where(
                PermissionFact.tenant_id == identity.tenant_id,
                PermissionFact.subject_id == subject_id,
            )
        )
    )

    def key(f: PermissionFact) -> tuple:
        return (f.domain, f.action, f.resource_value)

    declared = {key(f): f for f in facts if f.state == "declared"}
    effective = {key(f): f for f in facts if f.state == "effective"}
    declared_only = [
        {"domain": k[0], "action": k[1], "resource": k[2], "detail": "声明了但无有效事实（待验证）"}
        for k in declared.keys() - effective.keys()
    ]
    effective_only = [
        {"domain": k[0], "action": k[1], "resource": k[2], "detail": "生效但未声明（潜在带外）"}
        for k in effective.keys() - declared.keys()
    ]
    consistent = [
        {"domain": k[0], "action": k[1], "resource": k[2], "detail": "一致"}
        for k in declared.keys() & effective.keys()
    ]
    return {
        "subject_id": subject_id,
        "declared_count": len(declared),
        "effective_count": len(effective),
        "declared_not_effective": declared_only,
        "effective_not_declared": effective_only,
        "consistent": consistent,
    }


@router.post("/api/v1/permissions/check-drift")
def check_drift_endpoint(
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """漂移检测（§13.3）：期望状态 vs 执行端实际状态 → Finding。fail-closed。"""
    from app.adapters.openshell.contracts import AdapterError as _AE
    from app.drift import check_policy_drift, upsert_drift_findings

    ensure_permission(identity, "env:manage")
    try:
        results = check_policy_drift(session, identity.tenant_id)
    except _AE:
        session.rollback()
        raise HTTPException(status_code=502, detail="openshell_unreachable") from None
    counts = upsert_drift_findings(session, identity.tenant_id, results)
    session.commit()
    return {
        "drift_results": [
            {
                "deployment_id": r.deployment_id,
                "severity": r.severity,
                "kind": r.details.get("kind"),
                "summary": r.summary,
            }
            for r in results
        ],
        **counts,
    }


@router.post("/api/v1/permissions/sync-openshell")
def sync_openshell_permissions(
    environment_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """拉取真实 OpenShell 有效策略入 PermissionFacts（权威来源：openshell）。

    fail-closed：网关不可达 → 502，绝不产出空权限冒充安全状态。
    """
    from app.adapters.openshell.contracts import AdapterError
    from app.openshell_sync import sync_openshell

    env = session.scalar(
        select(Environment).where(
            Environment.id == environment_id,
            Environment.tenant_id == identity.tenant_id,
        )
    )
    if env is None:
        raise HTTPException(status_code=404, detail="not_found")
    ensure_permission(identity, "env:manage")
    try:
        result = sync_openshell(session, identity.tenant_id, environment_id)
    except AdapterError:
        session.rollback()
        raise HTTPException(status_code=502, detail="openshell_unreachable") from None
    return result


@router.get("/api/v1/candidates", response_model=list[AgentAssetOut])
def list_candidates(
    cursor: str | None = None,  # 形如 "<updated_at_iso>|<id>"（§18.1 稳定 Cursor 分页）
    limit: int = 50,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("agent:read")),
):
    query = (
        select(AgentAsset)
        .where(
            AgentAsset.tenant_id == identity.tenant_id,
            AgentAsset.status.in_(["candidate", "needs_review"]),
        )
        .order_by(AgentAsset.updated_at.desc(), AgentAsset.id)
    )
    if cursor:
        query = _apply_cursor(query, AgentAsset, cursor)
    return list(session.scalars(query.limit(min(limit, 200))))


def _apply_cursor(query, model, cursor: str):
    """稳定游标：<iso时间>|<id>，晚于游标的行（§18.1）。解析失败按 id 兜底。"""
    from datetime import datetime

    try:
        ts, rid = cursor.split("|", 1)
        cursor_time = datetime.fromisoformat(ts)
        return query.where(
            (model.updated_at < cursor_time) | ((model.updated_at == cursor_time) & (model.id > rid))
        )
    except ValueError:
        return query.where(model.id > cursor)


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
    # P1-7：body 里的外键引用必须解析到本租户对象。system_id 是请求体引用而非路径定位，
    # 不存在或跨租户统一 422（与 invalid_edge_public_key 等体校验惯例一致），不泄露存在性。
    if body.system_id is not None:
        system = session.scalar(
            select(System).where(System.id == body.system_id, System.tenant_id == identity.tenant_id)
        )
        if system is None:
            raise HTTPException(status_code=422, detail="invalid_system_ref")
    asset.status = "confirmed"
    asset.role = body.role or asset.role
    asset.system_id = body.system_id or asset.system_id
    asset.owner_user_id = body.owner_user_id or asset.owner_user_id
    asset.confirmed_by = identity.actor_id

    # R-1 修复：资产确认时自动创建默认 AgentInstance（若尚无实例）
    existing_inst = session.scalar(
        select(AgentInstance).where(
            AgentInstance.asset_id == asset.id,
            AgentInstance.tenant_id == identity.tenant_id,
        )
    )
    if existing_inst is None:
        env_id = None
        if asset.evidence_ids:
            ev_obj = session.scalar(
                select(Evidence).where(
                    Evidence.tenant_id == identity.tenant_id,
                    Evidence.evidence_id.in_(asset.evidence_ids),
                    Evidence.environment_id.isnot(None),
                ).limit(1)
            )
            if ev_obj:
                env_id = ev_obj.environment_id
        inst = AgentInstance(
            tenant_id=identity.tenant_id,
            asset_id=asset.id,
            environment_id=env_id,
            runtime=asset.framework if asset.framework and asset.framework != "unknown" else "hermes",
            artifact_digest=asset.artifact_digest,
            location={"source_type": asset.source_type, "source_locator": asset.source_locator},
            status="observed",
        )
        session.add(inst)

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


@router.post("/api/v1/candidates/{asset_id}/classify")
def classify_candidate(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """触发候选分类（设计文档 §11）。分类永远不自动纳管；低置信 → needs_review。"""
    asset = _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:confirm")
    if asset.status not in ("candidate", "needs_review"):
        raise HTTPException(status_code=409, detail="invalid_state")
    from app.classification import classify_asset

    run = classify_asset(session, identity.tenant_id, asset)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "agent.classify",
        "agent_asset",
        resource_id=asset.id,
        summary={"classifier": run.classifier, "is_agent_candidate": run.output.get("is_agent_candidate")},
    )
    emit_event(
        session,
        identity.tenant_id,
        "agent.asset.classified.v1",
        {"agent_asset_id": asset.id, "classification_run_id": run.id},
        resource_ref=asset.id,
    )
    session.commit()
    return {
        "classification_run_id": run.id,
        "classifier": run.classifier,
        "asset_status": asset.status,
        "output": run.output,
    }


@router.get("/api/v1/agents", response_model=list[AgentAssetOut])
def list_agents(
    cursor: str | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
    identity: Identity = Depends(require_permission("agent:read")),
):
    query = (
        select(AgentAsset)
        .where(
            AgentAsset.tenant_id == identity.tenant_id,
            AgentAsset.status.in_(["confirmed", "managed", "stale", "retired"]),
        )
        .order_by(AgentAsset.updated_at.desc(), AgentAsset.id)
    )
    if cursor:
        query = _apply_cursor(query, AgentAsset, cursor)
    return list(session.scalars(query.limit(min(limit, 200))))


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
    asset = _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    # 关联口径：批次写入的 evidence_ids 为主，subject_ref 直连为辅
    linked = (asset.evidence_ids or [])
    return list(
        session.scalars(
            select(Evidence)
            .where(
                Evidence.tenant_id == identity.tenant_id,
                Evidence.evidence_id.in_(linked) | (Evidence.subject_ref == asset_id),
            )
            .order_by(Evidence.observed_at.desc())
            .limit(200)
        )
    )


@router.get("/api/v1/assets/{asset_id}/instances", response_model=list[AgentInstanceOut])
@router.get("/api/v1/agents/{asset_id}/instances", response_model=list[AgentInstanceOut])
def list_asset_instances(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """查询资产运行实例列表（支持 /assets/ 与 /agents/ 路径别名）。"""
    asset = _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    return list(
        session.scalars(
            select(AgentInstance)
            .where(
                AgentInstance.tenant_id == identity.tenant_id,
                AgentInstance.asset_id == asset.id,
            )
            .order_by(AgentInstance.observed_at.desc(), AgentInstance.id)
        )
    )


@router.post("/api/v1/assets/{asset_id}/instances", response_model=AgentInstanceOut, status_code=201)
@router.post("/api/v1/agents/{asset_id}/instances", response_model=AgentInstanceOut, status_code=201)
def create_asset_instance(
    asset_id: str,
    body: AgentInstanceCreate,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """显式登记资产运行实例（支持 /assets/ 与 /agents/ 路径别名）。"""
    asset = _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "policy:manage")
    if body.environment_id:
        env = session.scalar(
            select(Environment).where(
                Environment.id == body.environment_id,
                Environment.tenant_id == identity.tenant_id,
            )
        )
        if env is None:
            raise HTTPException(status_code=422, detail="invalid_environment_ref")

    inst = AgentInstance(
        tenant_id=identity.tenant_id,
        asset_id=asset.id,
        environment_id=body.environment_id,
        runtime=body.runtime,
        version=body.version,
        artifact_digest=body.artifact_digest or asset.artifact_digest,
        location=body.location,
        status=body.status,
    )
    session.add(inst)
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "agent.instance.create",
        "agent_instance",
        resource_id=inst.id,
        summary={"asset_id": asset.id, "runtime": inst.runtime, "environment_id": inst.environment_id},
    )
    emit_event(
        session,
        identity.tenant_id,
        "agent.instance.created.v1",
        {"agent_instance_id": inst.id, "asset_id": asset.id, "runtime": inst.runtime},
        environment_id=inst.environment_id,
        resource_ref=inst.id,
    )
    session.commit()
    session.refresh(inst)
    return inst


@router.get("/api/v1/agents/{asset_id}/policies")
def get_agent_policies(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """该智能体的 Desired Policy 列表（selector.agent_ids 匹配）。"""
    from app.models import DesiredPolicy

    _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    policies = list(
        session.scalars(
            select(DesiredPolicy)
            .where(DesiredPolicy.tenant_id == identity.tenant_id)
            .order_by(DesiredPolicy.updated_at.desc())
            .limit(200)
        )
    )
    matched = [p for p in policies if asset_id in ((p.selector or {}).get("agent_ids") or [])]
    return [
        {
            "id": p.id,
            "name": p.name,
            "enforcement_mode": p.enforcement_mode,
            "version": p.version,
            "status": p.status,
            "unsupported_by_backend": p.unsupported_by_backend,
        }
        for p in matched
    ]


@router.get("/api/v1/agents/{asset_id}/enforcement")
def get_agent_enforcement(
    asset_id: str,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    """该智能体的管控状态（诚实边界，§6.5 控制面≠执行面）：
    enforced=存在 effective 部署（真实强制）；declared_only=只有期望策略未部署（⚠️声明未强制）。"""
    from app.models import ChangeRequest, Deployment, DesiredPolicy

    _asset_or_404(session, identity.tenant_id, asset_id)
    ensure_permission(identity, "agent:read")
    policies = list(
        session.scalars(
            select(DesiredPolicy)
            .where(DesiredPolicy.tenant_id == identity.tenant_id)
            .order_by(DesiredPolicy.updated_at.desc())
            .limit(200)
        )
    )
    matched = [p for p in policies if asset_id in ((p.selector or {}).get("agent_ids") or [])]
    deployments: list[dict] = []
    for policy in matched:
        crs = list(
            session.scalars(
                select(ChangeRequest).where(
                    ChangeRequest.tenant_id == identity.tenant_id,
                    ChangeRequest.policy_id == policy.id,
                )
            )
        )
        for cr in crs:
            for dep in session.scalars(
                select(Deployment).where(Deployment.change_request_id == cr.id)
            ):
                deployments.append(
                    {
                        "id": dep.id,
                        "policy_id": policy.id,
                        "target": dep.target,
                        "status": dep.status,
                        "verification": dep.verification,
                    }
                )
    enforced = [d for d in deployments if d["status"] == "effective"]
    return {
        "agent_id": asset_id,
        "enforce_status": "enforced" if enforced else "declared_only",
        "policy_count": len(matched),
        "effective_deployments": enforced,
        "all_deployments": deployments,
    }


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
