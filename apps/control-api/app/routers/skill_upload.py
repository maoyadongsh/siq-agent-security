"""Independent signed skill observations; no candidate or permission writes."""

import hashlib
from datetime import UTC, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import load_settings
from app.db import get_session
from app.evidence_signing import batch_signed_bytes, canonical_json, verify_hex_signature
from app.models import EdgeTask, Environment, SkillInstallation, SkillManifestObservation, SkillUploadReceipt, utcnow
from app.outbox import audit, emit_event
from app.routers.inventory import _read_json
from app.security import verify_edge_secret
from app.signing import build_task_envelope, public_key_base64, verify_task_signature
from app.skill_upload import SkillBatchIn

router = APIRouter(tags=["skill-inventory"])


@router.post("/edge/v1/skill-batches")
async def upload_skills(request: Request, session: Session = Depends(get_session)):
    device = request.headers.get("X-Edge-Identity")
    if not device:
        raise HTTPException(401, "missing_edge_identity")
    edge = verify_edge_secret(request, device, session)
    raw = await _read_json(request)
    signed = batch_signed_bytes(raw)
    if not verify_hex_signature(edge.public_key_pem, signed, raw.get("signature", "")):
        raise HTTPException(401, "batch_signature_invalid")
    try:
        body = SkillBatchIn.model_validate(raw)
    except ValidationError:
        raise HTTPException(422, "skill_batch_schema_invalid") from None
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(404, "not_found")
    task = session.scalar(
        select(EdgeTask).where(
            EdgeTask.id == body.task_id,
            EdgeTask.environment_id == env.id,
            EdgeTask.task_type == "skill_scan",
        )
    )
    now = utcnow()
    if task is None or task.expires_at < now or task.status not in ("pending", "uploaded"):
        raise HTTPException(409, "skill_task_invalid")
    if not task.signature or not verify_task_signature(
        public_key_base64(),
        build_task_envelope(task.id, task.task_type, env.id, task.payload, task.expires_at.isoformat()),
        task.signature,
    ):
        raise HTTPException(409, "skill_task_signature_invalid")
    payload = task.payload
    scope = payload.get("scope")
    if (
        payload.get("connector") != "directory"
        or payload.get("inventory_kind") != "skills"
        or payload.get("target_device_identity") != device
        or not isinstance(scope, dict)
        or scope.get("include") != ["SKILL.md"]
        or not scope.get("roots")
        or hashlib.sha256(canonical_json(scope)).hexdigest() != body.scope_digest
    ):
        raise HTTPException(409, "skill_task_scope_mismatch")
    digest = hashlib.sha256(signed).hexdigest()
    if task.status == "uploaded":
        if task.result_digest != digest:
            raise HTTPException(409, "skill_task_replay_conflict")
        return {
            "schema_version": "enterprise-skill-upload-result/v1",
            "task_id": task.id,
            "batch_digest": digest,
            "observations": 0,
            "idempotent": True,
        }
    if any(
        abs(now - item.observed_at.astimezone(UTC).replace(tzinfo=None)) > timedelta(minutes=5)
        for item in body.observations
    ):
        raise HTTPException(422, "skill_observation_stale")
    cutoff = now - timedelta(seconds=load_settings().heartbeat_stale_seconds)
    reserved = session.execute(
        update(EdgeTask)
        .where(
            EdgeTask.id == task.id,
            EdgeTask.status == "pending",
            EdgeTask.lease_owner == device,
            EdgeTask.leased_at >= cutoff,
            EdgeTask.leased_at <= now,
        )
        .values(status="uploaded", result_digest=digest)
    )
    if reserved.rowcount != 1:
        raise HTTPException(409, "skill_task_lease_invalid")
    try:
        session.add(
            SkillUploadReceipt(
                task_id=task.id,
                tenant_id=env.tenant_id,
                edge_agent_id=edge.id,
                batch_digest=digest,
                signed_payload=signed.decode("utf-8"),
                signature=body.signature,
            )
        )
        for item in body.observations:
            installation = session.scalar(
                select(SkillInstallation).where(
                    SkillInstallation.tenant_id == env.tenant_id,
                    SkillInstallation.edge_agent_id == edge.id,
                    SkillInstallation.locator_sha256 == item.locator_sha256,
                )
            )
            if installation is None:
                installation = SkillInstallation(
                    tenant_id=env.tenant_id, edge_agent_id=edge.id, locator_sha256=item.locator_sha256
                )
                session.add(installation)
                session.flush()
            session.add(
                SkillManifestObservation(
                    tenant_id=env.tenant_id,
                    installation_id=installation.id,
                    manifest_sha256=item.manifest_sha256,
                    parser_version=item.parser_version,
                    parse_status=item.parse_status,
                    name=item.name,
                    allowed_tools_present=item.allowed_tools_present,
                    declared_tools=item.declared_tools,
                    observed_at=item.observed_at.astimezone(UTC).replace(tzinfo=None),
                    batch_digest=digest,
                    batch_signature=body.signature,
                )
            )
        summary = {"observations": len(body.observations), "task_id": task.id, "batch_digest": digest}
        audit(
            session,
            env.tenant_id,
            "edge",
            device,
            "skill.batch.upload",
            "environment",
            resource_id=env.id,
            summary=summary,
        )
        emit_event(session, env.tenant_id, "skill.batch.uploaded", summary, environment_id=env.id, resource_ref=task.id)
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "skill_batch_conflict") from None
    return {
        "schema_version": "enterprise-skill-upload-result/v1",
        "task_id": task.id,
        "batch_digest": digest,
        "observations": len(body.observations),
        "idempotent": False,
    }
