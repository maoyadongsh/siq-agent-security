"""Fence bound request tool identities before acknowledging business revocation.

Uses durable leases in this API's database, including other API workers' runs.
It never restores execution authority or revokes a shared/root identity. Normal
runtime cleanup still owns sandbox termination and lease finalization.
"""
from dataclasses import fields
import json

from sqlmodel import Session, select

from scripts.openshell import qwen38_request_identity as identity
from services import (
    openshell_data_scope as authority,
    qwen38_request_origin as origin,
    qwen38_request_recovery as recovery,
    runtime_coordination as coordination,
)

ERROR = 'data_scope_execution_revocation_unconfirmed'


def _fence(session, row, grant):
    handle = recovery.load(row.pool_binding_run_id)
    binding = handle.execution_binding
    if (binding.row_id != row.id or any(getattr(row, f.name) != getattr(binding, f.name)
            for f in fields(binding) if f.name != 'row_id')
            or not origin.require(lambda: Session(session.get_bind()), row.pool_binding_run_id, binding)):
        raise authority.DataScopeAuthorizationError(ERROR)
    supervisor = handle.gateway.supervised.service.supervisor
    scope = supervisor.scope
    if any(getattr(scope, key) != getattr(grant, key) for key in (
            'tenant_id', 'project_id', 'market', 'company_id', 'company_directory', 'data_classification')):
        raise authority.DataScopeAuthorizationError(ERROR)
    # A different exact object scope uses a different business grant.
    if list(scope.object_scopes) != json.loads(grant.object_scopes_json):
        return
    manifest = supervisor.manifest
    reference = identity.validate_reference(manifest['agentshield_identity'])
    prepared = identity.PreparedIdentity(supervisor.directory, reference['record_sha256'])
    identity.revoke(prepared, run_id=row.pool_binding_run_id, scope=scope,
                    execution_binding=binding.as_dict())


def fence_revoked_grant_executions(session, grant):
    """Fail closed on unknown live bindings; an idempotent retry rechecks them.

    The business grant must already be durably revoked. Startup and dispatch
    revalidate that authority; existing bound requests additionally lose their
    SIQ child identity here, without waiting for the 30-second heartbeat.
    """
    try:
        if grant.revoked_at is None:
            raise ValueError
        rows = session.exec(select(coordination.ActiveRunLease).where(
            coordination.ActiveRunLease.status == 'running',
            coordination.ActiveRunLease.pool_tenant_id == grant.tenant_id,
            coordination.ActiveRunLease.pool_user_id == str(grant.user_id),
            coordination.ActiveRunLease.pool_scope_id == grant.project_id.removeprefix('company:'),
        )).all()
        failed = False
        for row in rows:
            try:
                # Do not silently call legacy sessions fenced by this contract.
                if row.profile != 'siq_analysis' or not coordination.is_qwen_request_row(row):
                    raise ValueError
                _fence(session, row, grant)
            except Exception:
                failed = True
        if failed:
            raise ValueError
    except Exception:
        # Keep the committed grant withdrawal; never expose credentials, SQL
        # values or filesystem details and never report an unconfirmed success.
        raise authority.DataScopeAuthorizationError(ERROR) from None
