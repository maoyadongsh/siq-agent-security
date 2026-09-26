import copy
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.evidence_signing import batch_signed_bytes, canonical_json, verify_hex_signature
from app.models import (
    AuditEvent,
    EdgeAgent,
    EdgeTask,
    SkillInstallation,
    SkillManifestObservation,
    SkillUploadReceipt,
    utcnow,
)
from app.signing import sign_task_payload
from app.tests.edge_helpers import register_edge


@pytest.fixture
def upload_case(client, tenant_a):
    identity = "skill-fixture-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": identity}).json()["id"]
    headers, key = register_edge(client, tenant_a, env, identity)
    scope = {"roots": ["/fixture/skills"], "include": ["SKILL.md"]}
    with session_scope() as session:
        edge = session.scalar(select(EdgeAgent).where(EdgeAgent.device_identity == identity))
        edge_id = edge.id
        task = EdgeTask(
            environment_id=env,
            task_type="skill_scan",
            expires_at=utcnow() + timedelta(minutes=10),
            lease_owner=identity,
            leased_at=utcnow(),
            payload={
                "connector": "directory",
                "inventory_kind": "skills",
                "target_device_identity": identity,
                "scope": scope,
            },
        )
        session.add(task)
        session.flush()
        task_id = task.id
        task.signature = sign_task_payload(task.id, task.task_type, env, task.payload, task.expires_at.isoformat())
    body = {
        "schema_version": "enterprise-skill-upload/v1",
        "task_id": task_id,
        "scope_digest": hashlib.sha256(canonical_json(scope)).hexdigest(),
        "observations": [
            {
                "locator_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "parser_version": "enterprise-skill-manifest/v1",
                "parse_status": "parsed",
                "name": "sample",
                "allowed_tools_present": True,
                "declared_tools": ["read_file"],
                "observed_at": datetime.now(UTC).isoformat(),
            }
        ],
    }

    def upload(value=None, credentials=None, resign=True):
        value = copy.deepcopy(body if value is None else value)
        if resign:
            value["signature"] = key.sign(batch_signed_bytes(value)).hex()
        return client.post("/edge/v1/skill-batches", headers=credentials or headers, json=value)

    def receipt(value):
        return client.post(
            f"/edge/v1/tasks/{task_id}/receipt",
            headers=headers,
            json={"task_id": task_id, "device_identity": identity, **value},
        )

    upload.receipt = receipt
    yield body, upload, task_id, edge_id, identity, env
    with session_scope() as session:
        session.get(EdgeTask, task_id).status = "expired"


def test_skill_upload_signed_replay_and_audit(upload_case):
    body, upload, task_id, edge_id, _, env = upload_case
    response = upload()
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["observations"] == 1 and value["idempotent"] is False
    assert value["schema_version"] == "enterprise-skill-upload-result/v1" and value["task_id"] == task_id
    assert upload().json() == {**value, "observations": 0, "idempotent": True}
    changed = copy.deepcopy(body)
    changed["observations"][0]["manifest_sha256"] = "c" * 64
    assert upload(changed).status_code == 409
    with session_scope() as session:
        installations = session.scalars(
            select(SkillInstallation).where(SkillInstallation.edge_agent_id == edge_id)
        ).all()
        assert len(installations) == 1
        observations = session.scalars(
            select(SkillManifestObservation).where(SkillManifestObservation.installation_id == installations[0].id)
        ).all()
        assert len(observations) == 1 and observations[0].declared_tools == ["read_file"]
        assert session.get(EdgeTask, task_id).result_digest == observations[0].batch_digest
        receipt = session.get(SkillUploadReceipt, task_id)
        signed_bytes = receipt.signed_payload.encode("utf-8")
        assert hashlib.sha256(signed_bytes).hexdigest() == observations[0].batch_digest
        assert verify_hex_signature(session.get(EdgeAgent, edge_id).public_key_pem, signed_bytes, receipt.signature)
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.resource_id == env, AuditEvent.action == "skill.batch.upload")
        ).all()
        assert len(events) == 1


@pytest.mark.parametrize("mutation", ["scope", "unsigned", "effective", "partial", "stale", "duplicate", "secret"])
def test_skill_upload_rejects_invalid_declarations_without_writes(upload_case, mutation):
    body, upload, task_id, edge_id, _, _ = upload_case
    if mutation == "scope":
        body["scope_digest"] = "0" * 64
    elif mutation == "unsigned":
        body["signature"] = "0" * 128
    elif mutation == "effective":
        body["observations"][0]["effective"] = True
    elif mutation == "partial":
        body["observations"][0]["parse_status"] = "unsupported"
    elif mutation == "stale":
        body["observations"][0]["observed_at"] = "2000-01-01T00:00:00Z"
    elif mutation == "duplicate":
        body["observations"] *= 2
    elif mutation == "secret":
        body["observations"][0]["name"] = "sk-synthetic-secret-1234567890"
    response = upload(body, resign=mutation != "unsigned")
    assert response.status_code in (401, 409, 422), response.text
    assert "synthetic-secret" not in response.text
    with session_scope() as session:
        assert session.scalar(select(SkillInstallation).where(SkillInstallation.edge_agent_id == edge_id)) is None
        assert session.get(EdgeTask, task_id).status == "pending"


@pytest.mark.parametrize(
    "mutation", ["old_scan", "wrong_target", "no_lease", "expired_lease", "expired_task", "revoked", "unsigned_task"]
)
def test_skill_upload_task_and_device_gates(upload_case, mutation):
    _, upload, task_id, edge_id, _, _ = upload_case
    with session_scope() as session:
        task = session.get(EdgeTask, task_id)
        if mutation == "old_scan":
            task.task_type = "scan"
        elif mutation == "wrong_target":
            task.payload = {**task.payload, "target_device_identity": "another-device"}
        elif mutation == "no_lease":
            task.lease_owner = None
        elif mutation == "expired_lease":
            task.leased_at = utcnow() - timedelta(days=1)
        elif mutation == "expired_task":
            task.expires_at = utcnow() - timedelta(days=1)
        elif mutation == "unsigned_task":
            task.signature = None
        else:
            session.get(EdgeAgent, edge_id).revoked_at = utcnow()
        if mutation != "unsigned_task":
            task.signature = sign_task_payload(
                task.id, task.task_type, task.environment_id, task.payload, task.expires_at.isoformat()
            )
    assert upload().status_code in (401, 403, 409)
    with session_scope() as session:
        assert session.scalar(select(SkillInstallation).where(SkillInstallation.edge_agent_id == edge_id)) is None


def test_skill_upload_complete_empty_result_is_audited(upload_case):
    body, upload, task_id, edge_id, _, env = upload_case
    body["observations"] = []
    response = upload()
    assert response.status_code == 200
    assert response.json()["observations"] == 0 and response.json()["idempotent"] is False
    assert upload().json() == {**response.json(), "idempotent": True}
    with session_scope() as session:
        assert session.get(SkillUploadReceipt, task_id) is not None
        assert session.scalar(select(SkillInstallation).where(SkillInstallation.edge_agent_id == edge_id)) is None
        assert (
            session.scalar(
                select(AuditEvent).where(AuditEvent.resource_id == env, AuditEvent.action == "skill.batch.upload")
            )
            is not None
        )


def test_skill_upload_revoked_replay_still_rejected(upload_case):
    _, upload, _, edge_id, _, _ = upload_case
    assert upload().status_code == 200
    with session_scope() as session:
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()
    assert upload().status_code in (401, 403)


def test_skill_upload_audit_failure_rolls_back(upload_case, monkeypatch):
    _, upload, task_id, edge_id, _, _ = upload_case
    from app.routers import skill_upload

    def unavailable(*args, **kwargs):
        raise RuntimeError("audit fixture unavailable")

    monkeypatch.setattr(skill_upload, "audit", unavailable)
    with pytest.raises(RuntimeError, match="audit fixture unavailable"):
        upload()
    with session_scope() as session:
        assert session.get(SkillUploadReceipt, task_id) is None
        assert session.scalar(select(SkillInstallation).where(SkillInstallation.edge_agent_id == edge_id)) is None
        assert session.get(EdgeTask, task_id).status == "pending"


def test_skill_upload_other_tenant_device_cannot_use_task(client, tenant_b, upload_case):
    _, upload, _, edge_id, _, _ = upload_case
    name = "other-skill-" + uuid.uuid4().hex
    env = client.post("/api/v1/environments", headers=tenant_b, json={"name": name}).json()["id"]
    headers, key = register_edge(client, tenant_b, env, name)
    body = copy.deepcopy(upload_case[0])
    body["signature"] = key.sign(batch_signed_bytes(body)).hex()
    assert upload(body, credentials=headers, resign=False).status_code == 409
    with session_scope() as session:
        assert session.scalar(select(SkillInstallation).where(SkillInstallation.edge_agent_id == edge_id)) is None


@pytest.mark.parametrize("empty", [False, True])
def test_skill_final_receipt_bound_to_uploaded_result(upload_case, empty):
    body, upload, task_id, _, _, _ = upload_case
    if empty:
        body["observations"] = []
    result = upload().json()
    receipt = {
        "status": "success",
        "skill_batch_digest": result["batch_digest"],
        "skill_observation_count": len(body["observations"]),
    }
    response = upload.receipt(receipt)
    assert response.status_code == 200, response.text
    assert response.json() == {"ok": True, "idempotent": False}
    assert upload.receipt(receipt).json() == {"ok": True, "idempotent": True}
    assert upload.receipt({**receipt, "skill_observation_count": 199}).status_code == 409
    assert upload.receipt({**receipt, "skill_batch_digest": "0" * 64}).status_code == 409
    with session_scope() as session:
        assert session.get(EdgeTask, task_id).status == "delivered"
        events = session.scalars(
            select(AuditEvent).where(AuditEvent.resource_id == task_id, AuditEvent.action == "skill.scan.receipt")
        ).all()
        assert len(events) == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "no_upload",
        "count",
        "digest",
        "truncated",
        "agent_evidence",
        "signature_input",
        "missing_count",
        "failed_after_upload",
        "lease",
    ],
)
def test_skill_final_receipt_rejects_false_completion(upload_case, mutation):
    _, upload, task_id, _, _, _ = upload_case
    if mutation == "no_upload":
        digest = "0" * 64
    else:
        digest = upload().json()["batch_digest"]
    receipt = {"status": "success", "skill_batch_digest": digest, "skill_observation_count": 1}
    if mutation == "count":
        receipt["skill_observation_count"] = 0
    elif mutation == "digest":
        receipt["skill_batch_digest"] = "0" * 64
    elif mutation == "truncated":
        receipt["truncated"] = True
    elif mutation == "agent_evidence":
        receipt["evidence_count"] = 1
    elif mutation == "missing_count":
        del receipt["skill_observation_count"]
    elif mutation == "failed_after_upload":
        receipt = {"status": "failed"}
    elif mutation in ("signature_input", "lease"):
        with session_scope() as session:
            if mutation == "signature_input":
                session.get(SkillUploadReceipt, task_id).signed_payload = "{}"
            else:
                session.get(EdgeTask, task_id).leased_at = utcnow() - timedelta(days=1)
    assert upload.receipt(receipt).status_code in (409, 422)
    with session_scope() as session:
        assert session.get(EdgeTask, task_id).status == ("pending" if mutation == "no_upload" else "uploaded")
        assert (
            session.scalar(
                select(AuditEvent).where(AuditEvent.resource_id == task_id, AuditEvent.action == "skill.scan.receipt")
            )
            is None
        )


def test_skill_receipt_audit_failure_preserves_uploaded_result(upload_case, monkeypatch):
    from app import skill_receipt

    _, upload, task_id, _, _, _ = upload_case
    digest = upload().json()["batch_digest"]

    def unavailable(*args, **kwargs):
        raise RuntimeError("receipt audit unavailable")

    monkeypatch.setattr(skill_receipt, "audit", unavailable)
    with pytest.raises(RuntimeError, match="receipt audit unavailable"):
        upload.receipt({"status": "success", "skill_batch_digest": digest, "skill_observation_count": 1})
    with session_scope() as session:
        assert session.get(EdgeTask, task_id).status == "uploaded"
        assert session.get(SkillUploadReceipt, task_id) is not None


def test_skill_receipt_failure_before_upload_and_normal_task_field_isolation(upload_case):
    _, upload, task_id, _, _, _ = upload_case
    assert upload.receipt({"status": "failed", "error_code": "scope_denied"}).status_code == 200
    assert upload.receipt({"status": "failed", "error_code": "scope_denied"}).json()["idempotent"] is True
    with session_scope() as session:
        session.get(EdgeTask, task_id).task_type = "scan"
    assert upload.receipt({"status": "failed", "skill_observation_count": 0}).status_code == 422
