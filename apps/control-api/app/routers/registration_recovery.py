"""Initial registration response recovery; never general credential rotation."""

import hashlib
import json
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.evidence_signing import verify_hex_signature
from app.models import EdgeAgent, EdgeCredentialRotation, EdgeRegistrationRecovery, Environment, utcnow
from app.outbox import audit
from app.rate_limit import check_register_rate
from app.signing import public_key_base64

router = APIRouter()


class RecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    schema_version: Literal["edge-registration-recovery/v1"]
    device_identity: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    environment_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")
    secret_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")

    def signed_bytes(self) -> bytes:
        return json.dumps(
            self.model_dump(exclude={"signature"}),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")


def denied():
    return HTTPException(status_code=401, detail="registration_recovery_denied")


@router.post("/edge/v1/registration-recovery")
def recover_registration(body: RecoveryRequest, response: Response, session: Session = Depends(get_session)):
    allowed, retry_after = check_register_rate(
        device_identity=body.device_identity,
        enrollment_code="recovery:" + body.device_identity,
    )
    if not allowed:
        raise HTTPException(429, "registration_rate_limited", headers={"Retry-After": str(retry_after)})
    now = utcnow()
    earliest = now - timedelta(minutes=15)
    edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == body.device_identity).with_for_update())
    if (
        edge is None
        or edge.revoked_at is not None
        or not earliest < edge.registered_at <= now
        or edge.environment_id != body.environment_id
        or not verify_hex_signature(edge.public_key_pem, body.signed_bytes(), body.signature)
    ):
        raise denied()
    env = session.get(Environment, edge.environment_id)
    if env is None:
        raise denied()
    if session.scalar(select(EdgeCredentialRotation.rotation_id).where(
        EdgeCredentialRotation.edge_agent_id == edge.id,
    ).limit(1)) is not None:
        raise denied()
    digest = hashlib.sha256(body.signed_bytes()).hexdigest()
    previous = session.get(EdgeRegistrationRecovery, edge.id)
    if previous is not None:
        if previous.request_digest != digest or edge.secret_hash != body.secret_hash:
            raise denied()
    else:
        if edge.last_seen_at is not None:
            raise denied()
        changed = session.execute(
            update(EdgeAgent)
            .where(
                EdgeAgent.id == edge.id,
                EdgeAgent.revoked_at.is_(None),
                EdgeAgent.last_seen_at.is_(None),
                EdgeAgent.secret_hash == edge.secret_hash,
                EdgeAgent.registered_at > earliest,
            )
            .values(secret_hash=body.secret_hash)
        )
        if changed.rowcount != 1:
            raise denied()
        session.add(EdgeRegistrationRecovery(edge_agent_id=edge.id, request_digest=digest))
        audit(
            session,
            env.tenant_id,
            "edge",
            edge.device_identity,
            "edge.registration.recover",
            "edge_agent",
            resource_id=edge.id,
        )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise denied() from None
    response.headers["Cache-Control"] = "no-store"
    return {
        "schema_version": "edge-registration-recovery/v1",
        "edge_agent_id": edge.id,
        "environment_id": edge.environment_id,
        "control_plane_public_key": public_key_base64(),
        "status": "recovered",
    }
