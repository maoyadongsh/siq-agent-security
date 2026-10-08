"""Authenticated enterprise authorization for a fixed, operator-approved probe."""
from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.openshell.behavior_profiles import BehaviorProfile
from app.adapters.openshell.contracts import AdapterError
from app.binding_identity import require_binding_source_identity
from app.models import ChangeRequest, Deployment, DesiredPolicy, Environment, QuarantineCase, RuntimeBinding, Tenant
from app.security import Identity, ensure_permission, get_identity_with_expiry
from app.target_authority import authorize_runtime_target


class BehaviorAuthority:
    def __init__(self, request: Request, identity: Identity, sessions, adapter, *,
                 permissions=("policy:manage", "policy:read")):
        self.request, self.identity, self.sessions, self.adapter = request, identity, sessions, adapter
        self.permissions = permissions
        self.deadline = None
        self.assignment = None
        self.gateway_fingerprint = None
        self.gateway_hash = None
        self.chain = None

    def _database(self, session: Session, profile: BehaviorProfile, *, lock: bool):
        def row(model, object_id):
            query = select(model).where(model.id == object_id)
            if model is not Tenant:
                query = query.where(model.tenant_id == self.identity.tenant_id)
            if lock:
                query = query.with_for_update()
            return session.scalar(query.execution_options(populate_existing=True))

        b = profile.binding
        if b.tenant_id != self.identity.tenant_id:
            raise AdapterError("behavior_authorization_changed")
        tenant = row(Tenant, self.identity.tenant_id)
        deployment = row(Deployment, b.deployment_id)
        runtime = row(RuntimeBinding, b.binding_id)
        environment = row(Environment, b.environment_id)
        if (tenant is None or tenant.status != "active" or deployment is None or runtime is None
            or environment is None or environment.mode != "enforce" or deployment.status != "effective"
            or deployment.execution_backend != "openshell-cli" or deployment.runtime_binding_id != runtime.id
            or deployment.environment_id != environment.id or deployment.target != b.target
            or runtime.environment_id != environment.id or runtime.backend != "openshell-cli"
            or runtime.backend_target_id != b.target or runtime.status != "active" or runtime.revoked_at is not None):
            raise AdapterError("behavior_authorization_changed")
        change = row(ChangeRequest, deployment.change_request_id)
        if (change is None or change.status != "effective" or change.approved_at is None
            or not change.approver_user_id
            or (change.approver_user_id == change.proposer_user_id and change.approval_policy != "break_glass")):
            raise AdapterError("behavior_approval_unavailable")
        policy = row(DesiredPolicy, change.policy_id)
        if (policy is None or policy.status in {"rejected", "failed", "superseded", "rolled_back"}
            or policy.enforcement_mode != "block"):
            raise AdapterError("behavior_policy_unavailable")
        quarantined = session.scalar(select(QuarantineCase.id).where(
            QuarantineCase.tenant_id == self.identity.tenant_id,
            QuarantineCase.asset_id == runtime.asset_id, QuarantineCase.status == "quarantined"))
        if quarantined is not None:
            raise AdapterError("behavior_authorization_changed")
        from app.routers.policies import _ensure_binding_in_selector
        require_binding_source_identity(session, runtime, self.identity.tenant_id)
        _ensure_binding_in_selector(session, self.identity.tenant_id, policy, runtime)
        receipt = deployment.receipt or {}
        if any(receipt.get(key) != value for key, value in {
            "operation_id": b.operation_id, "target": b.target, "backend_revision": b.policy_revision,
            "applied_policy_digest": b.policy_digest, "endpoint_fingerprint": b.gateway_fingerprint,
            "gateway_name_sha256": profile.gateway_name_sha256,
        }.items()):
            raise AdapterError("behavior_deployment_origin_changed")
        chain = (deployment.change_request_id, change.policy_id, change.approver_user_id, change.approved_at,
                 runtime.asset_id, runtime.agent_instance_id, policy.version)
        if self.chain is not None and self.chain != chain:
            raise AdapterError("behavior_authorization_changed")
        self.chain = chain
        return runtime

    def authorize(self, profile: BehaviorProfile) -> None:
        try:
            current, deadline = get_identity_with_expiry(self.request)
            if current != self.identity:
                raise AdapterError("behavior_identity_changed")
            for permission in self.permissions:
                ensure_permission(current, permission)
            if os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none") != "openshell-cli":
                raise AdapterError("behavior_backend_unavailable")
            self.deadline = deadline
            # Close database reads before any CLI/gateway request.
            with self.sessions() as session:
                runtime = self._database(session, profile, lock=False)
            caps = self.adapter.probe()
            gateway_hash = hashlib.sha256(caps.handshake_gateway.encode()).hexdigest()
            if (not caps.handshake_verified or caps.endpoint_fingerprint != profile.binding.gateway_fingerprint
                or gateway_hash != profile.gateway_name_sha256):
                raise AdapterError("behavior_gateway_changed")
            assignment = authorize_runtime_target(runtime, current.tenant_id, caps.endpoint_fingerprint, gateway_hash)
            if self.assignment is not None and assignment != self.assignment:
                raise AdapterError("behavior_target_authority_changed")
            self.assignment = assignment
            self.gateway_fingerprint, self.gateway_hash = caps.endpoint_fingerprint, gateway_hash
        except (HTTPException, ValueError):
            raise AdapterError("behavior_authorization_changed") from None

    def before_accept(self, session: Session, profile: BehaviorProfile) -> None:
        # No JWT/JWKS or gateway access inside this transaction. Expiry came from
        # the most recent fully verified request, repeated before every arm.
        if (self.assignment is None or (self.deadline is not None and datetime.now(UTC) >= self.deadline)
            or os.getenv("SIQ_AS_ENFORCEMENT_BACKEND", "none") != "openshell-cli"):
            raise AdapterError("behavior_authorization_changed")
        try:
            runtime = self._database(session, profile, lock=True)
            current = authorize_runtime_target(runtime, self.identity.tenant_id,
                                               self.gateway_fingerprint, self.gateway_hash)
            if current != self.assignment:
                raise AdapterError("behavior_target_authority_changed")
        except (HTTPException, ValueError):
            raise AdapterError("behavior_authorization_changed") from None
