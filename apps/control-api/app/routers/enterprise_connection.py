from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.openshell.enterprise_connection import inspect_connection
from app.db import get_session
from app.models import Environment
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["environments"])


@router.get("/api/v1/environments/{environment_id}/openshell-connection")
def openshell_connection(
    environment_id: str,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    environment = session.scalar(select(Environment).where(
        Environment.id == environment_id, Environment.tenant_id == identity.tenant_id,
    ))
    if environment is None:
        raise HTTPException(404, "not_found")
    ensure_permission(identity, "env:manage")
    ensure_permission(identity, "policy:read")
    response.headers["Cache-Control"] = "no-store"
    return {**inspect_connection(), "environment_id": environment.id}
