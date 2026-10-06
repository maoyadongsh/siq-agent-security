"""Candidate-only local business grant administration for confidential OpenShell data."""

from __future__ import annotations

import os

from database import get_session
from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from services.agent_memory_service import DEFAULT_TENANT_ID
from services.auth_dependencies import require_permission
from services.auth_service import User
from sqlmodel import Session

from services import openshell_data_scope, openshell_grant_revocation

router = APIRouter(prefix="/auth/openshell-data-grants", tags=["authentication"])


class LocalGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    market: str
    company_directory: str
    object_scopes: list[str] = Field(min_length=1, max_length=3)
    ttl_seconds: int = Field(default=900, ge=1, le=3600)


def _require_candidate_admin_mode() -> None:
    enabled = os.getenv("SIQ_OPENSHELL_LOCAL_GRANT_ADMIN_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }
    environment = os.getenv("SIQ_ENV", "development").strip().lower()
    if not enabled or environment in {"production", "prod"}:
        raise HTTPException(503, "local_grant_admin_not_enabled")


def _http_error(exc: openshell_data_scope.DataScopeAuthorizationError) -> HTTPException:
    code = str(exc)
    if code in {"data_scope_live_authority_unavailable", openshell_grant_revocation.ERROR}:
        return HTTPException(503, code)
    if code == "data_scope_local_grant_missing":
        return HTTPException(404, code)
    if code == "data_scope_local_grant_input_invalid":
        return HTTPException(400, code)
    if code == "data_scope_local_request_conflict":
        return HTTPException(409, code)
    return HTTPException(403, code)


@router.post("/users/{target_user_id}")
def create_local_grant(
    target_user_id: int,
    body: LocalGrantRequest,
    response: Response,
    request_key: str = Header(alias="Idempotency-Key"),  # noqa: B008
    actor: User = Depends(require_permission("user.manage")),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, int | bool]:
    _require_candidate_admin_mode()
    try:
        grant = openshell_data_scope.create_local_confidential_grant(
            session,
            actor=actor,
            target_user_id=target_user_id,
            tenant_id=DEFAULT_TENANT_ID,
            project_id=body.project_id,
            market=body.market,
            company_directory=body.company_directory,
            object_scopes=body.object_scopes,
            ttl_seconds=body.ttl_seconds,
            request_key=request_key,
        )
    except openshell_data_scope.DataScopeAuthorizationError as exc:
        raise _http_error(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    return {"grant_id": grant.id, "expires_at": grant.expires_at, "revoked": grant.revoked_at is not None}


@router.post("/{grant_id}/revoke")
def revoke_local_grant(
    grant_id: int,
    response: Response,
    actor: User = Depends(require_permission("user.manage")),  # noqa: B008
    session: Session = Depends(get_session),  # noqa: B008
) -> dict[str, int | bool]:
    _require_candidate_admin_mode()
    try:
        grant = openshell_data_scope.revoke_local_confidential_grant(
            session,
            actor=actor,
            grant_id=grant_id,
            tenant_id=DEFAULT_TENANT_ID,
        )
        openshell_grant_revocation.fence_revoked_grant_executions(session, grant)
    except openshell_data_scope.DataScopeAuthorizationError as exc:
        raise _http_error(exc) from exc
    response.headers["Cache-Control"] = "no-store"
    return {"grant_id": grant.id, "revoked": True}
