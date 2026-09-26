"""Authenticated, signed Edge credential rotation with durable response recovery."""
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db import get_session
from app.evidence_signing import verify_hex_signature
from app.models import EdgeAgent, EdgeCredentialRotation, Environment
from app.outbox import audit, emit_event
from app.security import verify_edge_secret

router = APIRouter(tags=["edge"])


class RotateCredential(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["edge-credential-rotation/v1"]
    device_identity: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    environment_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    rotation_id: str = Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")
    expected_secret_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    new_secret_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")

    def signed_bytes(self) -> bytes:
        return json.dumps(self.model_dump(exclude={"signature"}), sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True).encode("ascii")


@router.post("/edge/v1/credential-rotation")
def rotate(body: RotateCredential, request: Request, response: Response, session: Session = Depends(get_session)):
    edge = verify_edge_secret(request, request.headers.get("X-Edge-Identity", ""), session)
    authenticated_hash = edge.secret_hash
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.id == edge.id).with_for_update()
                          .execution_options(populate_existing=True))
    if edge is None or edge.revoked_at is not None or edge.secret_hash != authenticated_hash:
        raise HTTPException(409, "credential_rotation_conflict")
    if (body.device_identity != edge.device_identity or body.environment_id != edge.environment_id
            or not verify_hex_signature(edge.public_key_pem, body.signed_bytes(), body.signature)):
        raise HTTPException(401, "credential_rotation_denied")
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise HTTPException(401, "credential_rotation_denied")
    digest = hashlib.sha256(body.signed_bytes()).hexdigest()
    previous = session.get(EdgeCredentialRotation, (edge.id, body.rotation_id))
    if previous is not None:
        if previous.request_digest != digest or edge.secret_hash != previous.new_secret_hash:
            raise HTTPException(409, "credential_rotation_conflict")
    else:
        reused = session.scalar(select(EdgeCredentialRotation.rotation_id).where(
            EdgeCredentialRotation.edge_agent_id == edge.id,
            or_(EdgeCredentialRotation.old_secret_hash == body.new_secret_hash,
                EdgeCredentialRotation.new_secret_hash == body.new_secret_hash),
        ).limit(1))
        if body.expected_secret_hash != edge.secret_hash or body.new_secret_hash == edge.secret_hash or reused:
            raise HTTPException(409, "credential_rotation_conflict")
        try:
            changed = session.execute(update(EdgeAgent).where(
                EdgeAgent.id == edge.id, EdgeAgent.revoked_at.is_(None),
                EdgeAgent.secret_hash == body.expected_secret_hash,
            ).values(secret_hash=body.new_secret_hash)).rowcount
            if changed != 1:
                raise HTTPException(409, "credential_rotation_conflict")
            session.add(EdgeCredentialRotation(edge_agent_id=edge.id, rotation_id=body.rotation_id,
                        request_digest=digest, old_secret_hash=body.expected_secret_hash,
                        new_secret_hash=body.new_secret_hash))
            summary = {"environment_id": env.id, "device_id": edge.id, "rotation_id": body.rotation_id}
            audit(session, env.tenant_id, "edge", edge.device_identity, "edge.credential.rotate", "edge_agent",
                  resource_id=edge.id, request_id=request.state.request_id, summary=summary)
            emit_event(session, env.tenant_id, "edge.credential.rotated.v1", summary, environment_id=env.id,
                       resource_ref=edge.id, request_id=request.state.request_id)
            session.commit()
        except HTTPException:
            session.rollback()
            raise
        except Exception:
            session.rollback()
            raise HTTPException(503, "credential_rotation_unavailable") from None
    response.headers["Cache-Control"] = "no-store"
    return {"schema_version": "edge-credential-rotation-result/v1", "edge_agent_id": edge.id,
            "environment_id": env.id, "rotation_id": body.rotation_id, "status": "rotated",
            "runtime_permissions_changed": False}
