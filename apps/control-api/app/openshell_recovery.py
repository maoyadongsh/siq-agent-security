"""Bind verified API identity and deployment provenance to private recovery."""

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.durable_operations import DurablePolicyOperations, OperationContext
from app.adapters.openshell.operation_journal import JournalError
from app.adapters.openshell.recovery_keys import load_recovery_cipher
from app.adapters.openshell.sealed_snapshot import SnapshotError
from app.db import get_engine, get_session_factory
from app.models import OpenShellOperation


class RecoveryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["openshell-operation-recovery/v1"] = "openshell-operation-recovery/v1"
    deployment_id: str
    operation_id: str | None = None
    state: Literal["missing", "prepared", "applying", "applied", "rollback_pending", "rolled_back", "unknown"]
    applied_revision: str | None = None
    restored_revision: str | None = None
    rollback_material_available: bool = False
    automatic_replay_allowed: Literal[False] = False


def recovery_fact(deployment, identity):
    try:
        sessions = get_session_factory()
        with sessions() as session:
            row = session.scalar(select(OpenShellOperation).where(
                OpenShellOperation.tenant_id == identity.tenant_id,
                OpenShellOperation.deployment_id == deployment.id,
            ))
            if row is None:
                return None
            from app.adapters.openshell.sealed_snapshot import SnapshotOrigin

            origin = SnapshotOrigin(**row.origin)
            context = OperationContext(
                tenant_id=identity.tenant_id, environment_id=deployment.environment_id,
                deployment_id=deployment.id, binding_id=deployment.runtime_binding_id,
                target=deployment.target, gateway_fingerprint=origin.gateway_fingerprint,
                gateway_name_sha256=origin.gateway_name_sha256,
            )
            registry = DurablePolicyOperations(sessions, get_engine(), load_recovery_cipher(), context,
                actor_type=identity.identity_type, actor_id=identity.actor_id)
            return registry._journal(row.id).read()
    except (JournalError, SnapshotError, SQLAlchemyError, ValueError, TypeError):
        raise AdapterError("openshell_recovery_unavailable") from None


def receipt_from_fact(fact):
    if fact is None or fact.state not in {"applied", "rolled_back"} or not fact.applied_revision:
        raise AdapterError("openshell_recovery_outcome_unconfirmed")
    origin = fact.origin
    return {
        "operation_id": origin.operation_id, "target": origin.target,
        "base_revision": origin.base_revision, "base_policy_digest": origin.base_digest,
        "backend_revision": fact.applied_revision, "applied_policy_digest": fact.applied_digest,
        "result": "no_op" if origin.expected_digest == origin.base_digest else "applied",
        "endpoint_fingerprint": origin.gateway_fingerprint, "gateway_name_sha256": origin.gateway_name_sha256,
    }


def bind_recovery(adapter, deployment, identity, *, fingerprint, gateway_hash, before_apply=None):
    try:
        cipher = load_recovery_cipher()
    except SnapshotError:
        raise AdapterError("openshell_recovery_key_unavailable") from None
    registry = DurablePolicyOperations(
        get_session_factory(), get_engine(), cipher,
        OperationContext(
            tenant_id=identity.tenant_id, environment_id=deployment.environment_id,
            deployment_id=deployment.id, binding_id=deployment.runtime_binding_id,
            target=deployment.target, gateway_fingerprint=fingerprint, gateway_name_sha256=gateway_hash,
        ), actor_type=identity.identity_type, actor_id=identity.actor_id, before_apply=before_apply,
    )
    adapter._operations = registry
    return registry
