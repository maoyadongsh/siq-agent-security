"""Initial discovery from a previously issued exact plan; no business grants."""

import hashlib
import json
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db import get_session
from app.edge_capabilities import can_claim_skills, claimable_connectors
from app.install_plan import EnterpriseInstallPlan, StrictWire
from app.models import AuditEvent, EdgeInitialScan, EdgeTask, Environment, utcnow
from app.outbox import audit, emit_event
from app.security import verify_edge_secret
from app.signing import sign_task_payload

router = APIRouter(tags=["environments"])


class InitialScanRequest(StrictWire):
    schema_version: Literal["edge-initial-scan/v1", "edge-initial-scan/v2"]
    plan: EnterpriseInstallPlan


@router.post("/edge/v1/initial-scan")
def initial_scan(
    body: InitialScanRequest, request: Request, response: Response, session: Session = Depends(get_session)
):
    identity = request.headers.get("X-Edge-Identity")
    if not identity:
        raise HTTPException(status_code=401, detail="missing_edge_identity")
    edge = verify_edge_secret(request, identity, session)
    env = session.get(Environment, edge.environment_id)
    plan = body.plan
    if env is None or plan.environment_id != env.id or plan.tenant_id != env.tenant_id:
        raise HTTPException(status_code=404, detail="not_found")
    skills = (
        [c for c in plan.connectors if c.id == "directory" and "SKILL.md" in c.scope.include]
        if body.schema_version.endswith("/v2")
        else []
    )
    if any(len(c.scope.roots) > 16 or any("*" in root for root in c.scope.roots) for c in skills):
        raise HTTPException(status_code=409, detail="initial_scan_skill_scope_unsupported")
    ordinary = [c for c in plan.connectors if c not in skills or c.scope.include != ["SKILL.md"]]
    task_count = len(ordinary) + len(skills)
    result_schema = body.schema_version.replace("edge-initial-scan/", "edge-initial-scan-result/")
    digest = hashlib.sha256(json.dumps(plan.model_dump(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    previous = session.get(EdgeInitialScan, edge.id)
    response.headers["Cache-Control"] = "no-store"
    if previous is not None:
        if previous.plan_digest != digest:
            raise HTTPException(status_code=409, detail="initial_scan_plan_conflict")
        stored_types = list(
            session.scalars(
                select(EdgeTask.task_type).where(
                    EdgeTask.id.in_(previous.task_ids),
                    EdgeTask.environment_id == env.id,
                )
            )
        )
        if len(previous.task_ids) != task_count or sorted(stored_types) != sorted(
            ["scan"] * len(ordinary) + ["skill_scan"] * len(skills)
        ):
            raise HTTPException(status_code=409, detail="initial_scan_version_conflict")
        return {"schema_version": result_schema, "task_ids": previous.task_ids, "replay": True}
    issued = session.scalar(
        select(AuditEvent.id)
        .where(
            AuditEvent.tenant_id == env.tenant_id,
            AuditEvent.resource_id == env.id,
            AuditEvent.action == "install.plan.create",
            AuditEvent.decision == "allow",
            AuditEvent.summary["plan_id"].as_string() == plan.plan_id,
            AuditEvent.summary["plan_sha256"].as_string() == digest,
        )
        .limit(1)
    )
    if issued is None:
        raise HTTPException(status_code=409, detail="initial_scan_plan_unverified")
    try:
        plan.require_current()
    except ValueError:
        raise HTTPException(status_code=409, detail="initial_scan_plan_expired") from None
    now = utcnow()
    settings = load_settings()
    available = claimable_connectors(
        edge.capabilities, edge.last_seen_at, now, now - timedelta(seconds=settings.heartbeat_stale_seconds)
    )
    versions = edge.capabilities.get("connector_versions", {})
    if available is None or any(c.id not in available or versions.get(c.id) != c.version for c in plan.connectors):
        raise HTTPException(status_code=409, detail="initial_scan_capabilities_unverified")
    if skills and not can_claim_skills(
        edge.capabilities, edge.last_seen_at, now, now - timedelta(seconds=settings.heartbeat_stale_seconds)
    ):
        raise HTTPException(status_code=409, detail="initial_scan_skill_capabilities_unverified")
    envs = select(Environment.id).where(Environment.tenant_id == env.tenant_id)
    pending = (
        session.scalar(
            select(func.count(EdgeTask.id)).where(
                EdgeTask.environment_id.in_(envs),
                EdgeTask.task_type.in_(("scan", "skill_scan")),
                EdgeTask.status == "pending",
            )
        )
        or 0
    )
    if pending + task_count > settings.scan_quota_per_tenant:
        raise HTTPException(status_code=429, detail="scan_quota_exceeded")
    task_ids = []
    expires = now + timedelta(seconds=settings.edge_task_ttl_seconds)
    for connector, kind in [(c, "scan") for c in ordinary] + [(c, "skill_scan") for c in skills]:
        payload = {
            "connector": connector.id,
            "scope": connector.scope.model_dump(),
            "target_device_identity": identity,
        }
        if kind == "skill_scan":
            payload["scope"] = {"roots": connector.scope.roots, "include": ["SKILL.md"]}
            payload["inventory_kind"] = "skills"
        elif connector in skills:
            payload["scope"] = {
                "roots": connector.scope.roots,
                "include": [name for name in connector.scope.include if name != "SKILL.md"],
            }
        task = EdgeTask(
            environment_id=env.id,
            task_type=kind,
            expires_at=expires,
            payload=payload,
        )
        session.add(task)
        session.flush()
        task.signature = sign_task_payload(task.id, task.task_type, env.id, task.payload, expires.isoformat())
        task_ids.append(task.id)
        event = "skill.scan.created.v1" if kind == "skill_scan" else "scan.created.v1"
        emit_event(session, env.tenant_id, event, {"task_id": task.id, "environment_id": env.id})
    session.add(EdgeInitialScan(edge_agent_id=edge.id, plan_digest=digest, task_ids=task_ids))
    audit(
        session,
        env.tenant_id,
        "edge",
        identity,
        "scan.initial.create",
        "environment",
        resource_id=env.id,
        summary={"plan_id": plan.plan_id, "task_count": len(task_ids)},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="initial_scan_retry_same_plan") from None
    return {"schema_version": result_schema, "task_ids": task_ids, "replay": False}
