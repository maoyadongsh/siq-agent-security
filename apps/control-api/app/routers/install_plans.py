"""Authenticated discovery-only install plan projection; no registration or grant."""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.install_catalog import InstallOptions, InstallRequest, load_install_catalog
from app.install_plan import EnterpriseInstallPlan
from app.outbox import audit
from app.routers.environments import _env_or_404
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=["environments"])


@router.get("/api/v1/environments/{environment_id}/install-options", response_model=InstallOptions)
def get_install_options(
    environment_id: str,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    environment = _env_or_404(session, identity.tenant_id, environment_id)
    ensure_permission(identity, "edge:manage")
    ensure_permission(identity, "env:manage")
    try:
        catalog = load_install_catalog()
        # The shipped setup orchestrator currently supports user services only.
        if "user" not in catalog.allowed_service_modes:
            raise ValueError("no_supported_service_mode")
        options = InstallOptions.model_validate(
            {
                **catalog.model_dump(),
                "schema_version": "enterprise-install-options/v1",
                "environment_id": environment.id,
                "allowed_service_modes": ["user"],
            }
        )
    except (OSError, ValueError, RecursionError):
        raise HTTPException(status_code=503, detail="install_options_unavailable") from None
    response.headers["Cache-Control"] = "no-store"
    return options


@router.post("/api/v1/environments/{environment_id}/install-plans", response_model=EnterpriseInstallPlan)
def create_install_plan(
    environment_id: str,
    body: InstallRequest,
    response: Response,
    session: Session = Depends(get_session),
    identity: Identity = Depends(get_identity),
):
    environment = _env_or_404(session, identity.tenant_id, environment_id)
    ensure_permission(identity, "edge:manage")
    ensure_permission(identity, "env:manage")
    try:
        catalog = load_install_catalog()
    except (OSError, ValueError, RecursionError):
        raise HTTPException(status_code=503, detail="install_catalog_unavailable") from None
    if body.service_mode not in catalog.allowed_service_modes:
        raise HTTPException(status_code=409, detail="install_service_mode_unavailable")
    release = next((r for r in catalog.releases if r.target_arch == body.target_arch), None)
    if release is None:
        raise HTTPException(status_code=409, detail="install_architecture_unavailable")
    available = {c.id: c for c in release.connectors}
    if any(name not in available for name in body.connectors):
        raise HTTPException(status_code=409, detail="install_connector_unavailable")
    now = datetime.now(UTC)
    try:
        plan = EnterpriseInstallPlan(
            schema_version="enterprise-install-plan/v1",
            plan_id="eip-" + secrets.token_hex(16),
            tenant_id=identity.tenant_id,
            environment_id=environment.id,
            control_plane_origin=catalog.control_plane_origin,
            issued_at=now.isoformat().replace("+00:00", "Z"),
            expires_at=(now + timedelta(minutes=15)).isoformat().replace("+00:00", "Z"),
            target_os="linux",
            target_arch=body.target_arch,
            service_mode=body.service_mode,
            release_version=release.release_version,
            release_manifest_sha256=release.release_manifest_sha256,
            connectors=[available[name] for name in body.connectors],
            purpose="discovery_only",
        )
    except ValueError:
        raise HTTPException(status_code=503, detail="install_catalog_unavailable") from None
    plan_digest = hashlib.sha256(
        json.dumps(plan.model_dump(), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    audit(
        session,
        identity.tenant_id,
        identity.identity_type,
        identity.actor_id,
        "install.plan.create",
        "environment",
        resource_id=environment.id,
        summary={
            "plan_id": plan.plan_id,
            "plan_sha256": plan_digest,
            "connector_count": len(plan.connectors),
            "purpose": "discovery_only",
        },
    )
    session.commit()  # Audit must succeed before returning a plan.
    response.headers["Cache-Control"] = "no-store"
    return plan
