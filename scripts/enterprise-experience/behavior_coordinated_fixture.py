"""Disposable local database for real owned-gateway coordination acceptance.

Database identities/approvers are synthetic. This is not an authenticated API
acceptance and never connects to the user's application database.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.adapters.openshell.behavior_coordinator import BehaviorCoordinator
from app.adapters.openshell.behavior_journal import BehaviorJournal
from app.adapters.openshell.behavior_protocol import BehaviorChallengeV2
from app.adapters.openshell.durable_operations import DurablePolicyOperations, OperationContext
from app.adapters.openshell.sealed_snapshot import SnapshotCipher
from app.db import Base
from app.models import (
    AgentAsset,
    AgentInstance,
    AuditEvent,
    ChangeRequest,
    Deployment,
    DesiredPolicy,
    Environment,
    OpenShellBehaviorOperation,
    RuntimeBinding,
    Tenant,
)
from app.outbox import audit


class CoordinatedFixture:
    def __init__(self, out, backend, target):
        self.out, self.backend, self.target = out, backend, target
        self.profile_directory = None
        self.engine = create_engine(f"sqlite:///{out / 'coordination.db'}")
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(self.engine)  # Explicitly disposable development acceptance only.
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.cipher = SnapshotCipher({"fixture": secrets.token_bytes(32)}, "fixture")
        self.caps = backend.probe()
        self.gateway_hash = hashlib.sha256(self.caps.handshake_gateway.encode()).hexdigest()
        with self.sessions.begin() as session:
            session.add(Tenant(id="t", name="synthetic"))
            session.flush()
            session.add(Environment(id="e", tenant_id="t", name="synthetic"))
            session.add(AgentAsset(id="a", tenant_id="t", name="synthetic"))
            session.add(DesiredPolicy(id="p", tenant_id="t", name="synthetic", selector={"agent_ids": ["a"]},
                                      enforcement_mode="block", status="effective"))
            session.flush()
            session.add(AgentInstance(id="i", tenant_id="t", asset_id="a", environment_id="e"))
            session.add(ChangeRequest(id="c", tenant_id="t", policy_id="p", proposer_user_id="proposer",
                                      approver_user_id="approver", idempotency_key=uuid.uuid4().hex,
                                      status="effective"))
            session.flush()
            session.add(RuntimeBinding(id="b", tenant_id="t", environment_id="e", agent_instance_id="i", asset_id="a",
                                       backend="openshell-cli", backend_target_id=target))
            session.flush()
            session.add(Deployment(id="d", tenant_id="t", environment_id="e", runtime_binding_id="b",
                                   change_request_id="c", execution_backend="openshell-cli", target=target,
                                   to_revision="synthetic", status="pending"))
        self.context = OperationContext(tenant_id="t", environment_id="e", binding_id="b", deployment_id="d",
                                        target=target, gateway_fingerprint=self.caps.endpoint_fingerprint,
                                        gateway_name_sha256=self.gateway_hash)
        backend._operations = DurablePolicyOperations(self.sessions, self.engine, self.cipher, self.context,
            actor_type="user", actor_id="synthetic-operator", before_apply=self._authorize_apply)

    def _authorize_apply(self):
        with self.sessions() as session:
            self._check_database(session, expected_state="pending")

    def _check_database(self, session, *, expected_state="effective"):
        tenant = session.get(Tenant, "t", populate_existing=True)
        binding = session.get(RuntimeBinding, "b", populate_existing=True)
        change = session.get(ChangeRequest, "c", populate_existing=True)
        deployment = session.get(Deployment, "d", populate_existing=True)
        assert tenant.status == "active" and binding.status == "active" and binding.revoked_at is None
        assert change.status == "effective" and change.approver_user_id == "approver"
        assert change.proposer_user_id != change.approver_user_id
        assert deployment.status == expected_state and deployment.target == self.target
        assert binding.backend_target_id == self.target and deployment.runtime_binding_id == binding.id

    def apply(self, network):
        compiled = self.backend.compile({"policy_id": "p", "version": 1, "selector": {"agent_ids": ["a"]},
                                         "network": network, "enforcement_mode": "block"}, self.caps)
        plan = self.backend.plan_change(self.target, compiled)
        assert plan.kind == "dynamic"
        receipt = self.backend.apply_dynamic(self.target, plan, plan.expected_revision)
        with self.sessions.begin() as session:
            deployment = session.get(Deployment, "d")
            deployment.receipt = {**asdict(receipt), "endpoint_fingerprint": self.caps.endpoint_fingerprint,
                                  "gateway_name_sha256": self.gateway_hash}
            deployment.status = "effective"
            deployment.verification = {"level": "readback_verified"}
            audit(session, "t", "user", "synthetic-operator", "fixture.deployment.recorded", "deployment",
                  resource_id="d", summary={"operation_id": receipt.operation_id})
        self.receipt = receipt

    def binding(self, image, probe, protected_digest):
        return {"tenant_id": "t", "environment_id": "e", "binding_id": "b", "deployment_id": "d",
                "operation_id": self.receipt.operation_id, "target": self.target,
                "gateway_fingerprint": self.caps.endpoint_fingerprint,
                "policy_revision": self.receipt.backend_revision, "policy_digest": self.receipt.applied_policy_digest,
                "image_digest": image, "probe_sha256": probe, "protected_execution_sha256": protected_digest}

    def collect(self, challenge, protection_target):
        profile = {k: v for k, v in challenge.model_dump().items()
                   if k not in ("schema_version", "verification_id", "nonce")}
        profile.update(profile_id="owned-acceptance", gateway_name_sha256=self.gateway_hash,
                       protection=asdict(protection_target))
        self.profile_directory = tempfile.TemporaryDirectory(prefix="siq-behavior-profile-")
        path = Path(self.profile_directory.name) / "profiles.json"
        raw = json.dumps({"schema_version": "openshell-behavior-profiles/v1", "profiles": [profile]}, indent=2)
        path.write_text(raw)
        (self.out / "approved-profiles.json").write_text(raw)
        path.chmod(0o600)
        os.environ["SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE"] = str(path)
        j = BehaviorJournal(self.sessions, self.cipher, tenant_id="t", deployment_id="d",
                            actor_type="user", actor_id="synthetic-operator")

        def authorize(_):
            with self.sessions() as session:
                self._check_database(session)

        coordinator = BehaviorCoordinator(j, self.engine, self.backend, authorize=authorize,
                                          before_accept=lambda session, _: self._check_database(session))
        fact = coordinator.run(profile["profile_id"], challenge.verification_id)
        assert fact.state == "accepted"
        assert coordinator.run(profile["profile_id"], challenge.verification_id) == fact
        with self.sessions.begin() as session:
            session.get(RuntimeBinding, "b").status = "revoked"
        new_id = "opv-" + uuid.uuid4().hex
        try:
            coordinator.run(profile["profile_id"], new_id)
        except AssertionError:
            pass
        else:
            raise AssertionError("revoked fixture binding was accepted")
        with self.sessions.begin() as session:
            assert session.get(OpenShellBehaviorOperation, new_id) is None
            session.get(RuntimeBinding, "b").status = "active"  # Restore only disposable test identity.
        with self.sessions() as session:
            audits = list(session.scalars(select(AuditEvent).where(AuditEvent.action.like("openshell.behavior.%"))))
            assert sorted(row.action for row in audits) == [
                "openshell.behavior.accepted", "openshell.behavior.prepared", "openshell.behavior.running"]
            assert session.get(Deployment, "d").verification == {"level": "readback_verified"}
        (self.out / "coordinator.json").write_text(json.dumps({
            "schema_version": "behavior-coordinated-live-fixture/v1", "passed": True,
            "database_backend": "disposable_sqlite", "synthetic_database_authority": True,
            "authenticated_api": False, "real_durable_apply": True, "same_run_behavior_state": fact.state,
            "repeat_does_not_reexecute": True, "revoked_binding_prevents_new_operation": True,
            "audit_actions": [row.action for row in audits], "verification_id": fact.verification_id,
            "deployment_grade_promoted": False, "recorded_at": datetime.now(UTC).isoformat(),
        }, indent=2) + "\n")
        return BehaviorChallengeV2.model_validate(fact.challenge), fact.result

    def close(self):
        self.engine.dispose()
        if self.profile_directory is not None:
            self.profile_directory.cleanup()
            assert not Path(self.profile_directory.name).exists()
