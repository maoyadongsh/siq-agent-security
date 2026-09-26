"""Final task receipt gate for independent skill inventory; not runtime grants."""

import hashlib
import json
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select, update

from app.config import load_settings
from app.evidence_signing import verify_hex_signature
from app.models import EdgeTask, Environment, SkillInstallation, SkillManifestObservation, SkillUploadReceipt, utcnow
from app.outbox import audit, emit_event
from app.signing import build_task_envelope, public_key_base64, verify_task_signature


def complete_skill_task(session, edge, task, body):
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(404, "not_found")
    if (
        task.payload.get("target_device_identity") != edge.device_identity
        or body.task_id != task.id
        or body.device_identity != edge.device_identity
    ):
        raise HTTPException(409, "skill_receipt_identity_mismatch")
    now = utcnow()
    if task.expires_at < now or task.status == "expired":
        raise HTTPException(409, "receipt_task_expired")
    if not task.signature or not verify_task_signature(
        public_key_base64(),
        build_task_envelope(task.id, task.task_type, env.id, task.payload, task.expires_at.isoformat()),
        task.signature,
    ):
        raise HTTPException(409, "skill_task_signature_invalid")
    if body.candidate_count or body.evidence_count or body.evidence_ids:
        raise HTTPException(422, "skill_receipt_not_agent_evidence")
    upload = session.get(SkillUploadReceipt, task.id)
    if body.status == "success":
        if (
            body.truncated
            or body.skill_batch_digest is None
            or body.skill_observation_count is None
            or upload is None
            or upload.tenant_id != env.tenant_id
            or upload.edge_agent_id != edge.id
            or upload.batch_digest != body.skill_batch_digest
            or task.result_digest != body.skill_batch_digest
        ):
            raise HTTPException(409, "skill_receipt_upload_unconfirmed")
        signed = upload.signed_payload.encode("utf-8")
        if hashlib.sha256(signed).hexdigest() != upload.batch_digest or not verify_hex_signature(
            edge.public_key_pem, signed, upload.signature
        ):
            raise HTTPException(409, "skill_receipt_provenance_invalid")
        try:
            payload = json.loads(signed)
            valid = (
                payload["task_id"] == task.id
                and isinstance(payload["observations"], list)
                and len(payload["observations"]) == body.skill_observation_count
            )
        except (ValueError, TypeError, KeyError):
            valid = False
        count = session.scalar(
            select(func.count(SkillManifestObservation.id))
            .join(
                SkillInstallation,
                SkillManifestObservation.installation_id == SkillInstallation.id,
            )
            .where(
                SkillManifestObservation.tenant_id == env.tenant_id,
                SkillInstallation.tenant_id == env.tenant_id,
                SkillInstallation.edge_agent_id == edge.id,
                SkillManifestObservation.batch_digest == upload.batch_digest,
            )
        )
        if not valid or count != body.skill_observation_count:
            raise HTTPException(409, "skill_receipt_count_mismatch")
        terminal, expected = "delivered", "uploaded"
    else:
        if upload is not None or body.skill_batch_digest is not None or body.skill_observation_count is not None:
            raise HTTPException(409, "skill_receipt_failure_conflict")
        terminal, expected = "failed", "pending"
    if task.status == terminal:
        return {"ok": True, "idempotent": True}
    cutoff = now - timedelta(seconds=load_settings().heartbeat_stale_seconds)
    result = session.execute(
        update(EdgeTask)
        .where(
            EdgeTask.id == task.id,
            EdgeTask.status == expected,
            EdgeTask.lease_owner == edge.device_identity,
            EdgeTask.leased_at >= cutoff,
            EdgeTask.leased_at <= now,
        )
        .values(status=terminal)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "skill_receipt_state_or_lease_invalid")
    summary = {"task_id": task.id, "status": terminal, "observations": body.skill_observation_count or 0}
    audit(
        session,
        env.tenant_id,
        "edge",
        edge.device_identity,
        "skill.scan.receipt",
        "edge_task",
        resource_id=task.id,
        summary=summary,
    )
    emit_event(session, env.tenant_id, "skill.scan.completed", summary, environment_id=env.id, resource_ref=task.id)
    session.commit()
    return {"ok": True, "idempotent": False}
