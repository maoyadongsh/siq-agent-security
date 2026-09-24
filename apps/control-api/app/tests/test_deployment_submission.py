"""Durable reservation, replay, crash windows and tenant-scoped recovery."""

import json
import os
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, Deployment, DeploymentSubmission, EdgeTask
from app.tests.test_deployment_preview import preview, setup


def prepared(client, headers, env):
    body, _ = setup(client, headers, env)
    value = preview(client, headers, body)
    return {
        **body,
        "schema_version": "deployment-submission-create/v1",
        "request_key": str(uuid.uuid4()),
        "preview_digest": value["preview_digest"],
    }


def post(client, headers, body):
    return client.post("/api/v1/deployment-submissions", headers=headers, json=body)


def read(client, headers, body):
    return client.get(
        "/api/v1/change-requests/" + body["change_request_id"] + "/deployment-submission", headers=headers
    )


def counts():
    with session_scope() as s:
        return [
            s.scalar(select(func.count()).select_from(m))
            for m in (DeploymentSubmission, Deployment, EdgeTask, AuditEvent)
        ]


def test_durable_submit_replay_and_exact_readback(client, tenant_a, env_a):
    body = prepared(client, tenant_a, env_a)
    before = counts()
    response = post(client, tenant_a, body)
    assert response.status_code == 201, response.text
    value = response.json()
    assert value["state"] == "recorded" and value["deployment_status"] == "sent"
    after = counts()
    assert [after[i] - before[i] for i in range(3)] == [1, 1, 1]
    assert after[3] - before[3] == 2
    for _ in range(2):
        replay = post(client, tenant_a, body)
        assert replay.status_code == 200 and replay.json() == value
        assert read(client, tenant_a, body).json() == value
    assert counts() == after
    assert read(client, tenant_a, body).headers["Cache-Control"] == "no-store"
    with session_scope() as s:
        event = s.scalar(
            select(AuditEvent).where(
                AuditEvent.resource_id == value["deployment_id"], AuditEvent.action == "deployment.reserve"
            )
        )
        assert event.summary == {"submission_id": value["id"], "preview_digest": body["preview_digest"]}
    root = Path(__file__).resolve().parents[4] / "packages/contracts"
    for name, payload in [("deployment-submission-create", body), ("deployment-submission", value)]:
        jsonschema.Draft202012Validator(json.loads((root / (name + ".v1.schema.json")).read_text())).validate(payload)
    conflict = post(client, tenant_a, {**body, "preview_digest": "0" * 64})
    assert conflict.status_code == 409 and conflict.json()["detail"] == "deployment_submission_key_conflict"
    another = post(client, tenant_a, {**body, "request_key": str(uuid.uuid4())})
    assert another.status_code == 409 and another.json()["detail"] == "deployment_submission_exists"
    assert counts() == after


def test_persisted_reservation_survives_unknown_execute_failure(client, tenant_a, env_a, monkeypatch):
    body = prepared(client, tenant_a, env_a)
    calls = []

    def interrupted(prepared, session, identity, **kwargs):
        with session_scope() as other:
            row = other.scalar(
                select(DeploymentSubmission).where(DeploymentSubmission.change_request_id == body["change_request_id"])
            )
            assert row is not None and other.get(Deployment, row.deployment_id).status == "pending"
            assert other.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.resource_id == row.deployment_id, AuditEvent.action == "deployment.reserve"
                )
            )
        calls.append("external-attempt")
        raise RuntimeError("simulated ambiguous process failure")

    monkeypatch.setattr("app.routers.deployment_submission.execute_deployment", interrupted)
    response = post(client, tenant_a, body)
    assert response.status_code == 502 and response.json()["detail"] == "deployment_submission_unconfirmed"
    stored = read(client, tenant_a, body).json()
    assert stored["state"] == "unconfirmed" and stored["deployment_status"] == "pending"
    assert post(client, tenant_a, body).json() == stored
    assert calls == ["external-attempt"]
    # A fresh API process reads the same durable row after the original request
    # session is gone; recovery does not depend on in-memory operation state.
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import json,sys
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
 r=client.get('/api/v1/change-requests/'+sys.argv[1]+'/deployment-submission',headers=json.loads(sys.argv[2]))
 assert r.status_code==200
 print(json.dumps(r.json()))
""",
            body["change_request_id"],
            json.dumps(tenant_a),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        env={k: v for k, v in os.environ.items() if k.startswith("SIQ_AS_") or k in ("PATH", "HOME", "LANG")},
    )
    assert child.returncode == 0
    assert json.loads(child.stdout) == stored
    for path, request in [
        ("/api/v1/deployments", {k: body[k] for k in ("change_request_id", "environment_id", "binding_id")}),
        (
            "/api/v1/deployment-preview/submit",
            {k: v for k, v in {**body, "schema_version": "deployment-preview-submit/v1"}.items() if k != "request_key"},
        ),
    ]:
        assert client.post(path, headers=tenant_a, json=request).status_code == 409
    assert calls == ["external-attempt"]


def test_concurrent_delivery_reads_claim_without_second_execution(client, tenant_a, env_a, monkeypatch):
    body = prepared(client, tenant_a, env_a)
    entered, release = threading.Event(), threading.Event()
    from app.routers.deployment_submission import execute_deployment

    calls = []

    def paused(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return execute_deployment(*args, **kwargs)

    monkeypatch.setattr("app.routers.deployment_submission.execute_deployment", paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, client, tenant_a, body)
        try:
            assert entered.wait(10)
            second = post(client, tenant_a, body)
            assert second.status_code == 200 and second.json()["state"] == "unconfirmed"
            assert post(client, tenant_a, {**body, "request_key": str(uuid.uuid4())}).status_code == 409
        finally:
            release.set()
        completed = first.result(timeout=10)
    assert completed.status_code == 201
    assert completed.json()["deployment_id"] == second.json()["deployment_id"]
    assert calls == [1]


def test_reservation_audit_failure_never_calls_execute(client, tenant_a, env_a, monkeypatch):
    body = prepared(client, tenant_a, env_a)
    before = counts()

    def fail(*args, **kwargs):
        raise RuntimeError("audit storage failed")

    def never(*args, **kwargs):
        pytest.fail("must not execute without committed audit")

    monkeypatch.setattr("app.routers.deployment_submission.audit", fail)
    monkeypatch.setattr("app.routers.deployment_submission.execute_deployment", never)
    with pytest.raises(RuntimeError, match="audit storage failed"):
        post(client, tenant_a, body)
    assert counts() == before


def test_submission_tenant_access_and_bad_requests_no_write(client, tenant_a, tenant_b, env_a):
    body = prepared(client, tenant_a, env_a)
    before = counts()
    assert read(client, tenant_b, body).status_code == 404
    denied = {**tenant_a, "X-Dev-Roles": "reviewer"}
    assert read(client, denied, body).status_code == 403
    assert post(client, denied, body).status_code == 403
    assert post(client, tenant_b, body).status_code == 404
    assert post(client, tenant_a, {**body, "target": "injected"}).status_code == 422
    assert post(client, tenant_a, {**body, "preview_digest": "0" * 64}).status_code == 409
    assert counts() == before
    assert post(client, tenant_a, body).status_code == 201
    assert read(client, {**tenant_a, "X-Dev-Roles": "viewer"}, body).status_code == 200
    assert post(client, {**tenant_a, "X-Dev-User-Id": "different-actor"}, body).status_code == 409


def test_simultaneous_preflight_unique_constraint_selects_one_executor(client, tenant_a, env_a, monkeypatch):
    body = prepared(client, tenant_a, env_a)
    from app.routers import deployment_submission as route

    snapshot, execute = route._snapshot, route.execute_deployment
    barrier = threading.Barrier(2)
    snapshot_lock = threading.Lock()
    snapshot_calls = 0
    calls = []

    def synchronized(*args):
        nonlocal snapshot_calls
        result = snapshot(*args)
        with snapshot_lock:
            snapshot_calls += 1
            initial = snapshot_calls <= 2
        if initial:
            barrier.wait(timeout=10)
        return result

    def counted(*args, **kwargs):
        calls.append(1)
        return execute(*args, **kwargs)

    monkeypatch.setattr(route, "_snapshot", synchronized)
    monkeypatch.setattr(route, "execute_deployment", counted)
    before = counts()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(post, client, tenant_a, body) for _ in range(2)]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json()["deployment_id"] == results[1].json()["deployment_id"]
    assert calls == [1]
    after = counts()
    assert [after[i] - before[i] for i in range(3)] == [1, 1, 1]


def test_binding_revoked_during_reservation_is_rechecked_before_execute(client, tenant_a, env_a, monkeypatch):
    body = prepared(client, tenant_a, env_a)
    from app.models import RuntimeBinding
    from app.routers.deployment_submission import audit

    def revoke(session, *args, **kwargs):
        result = audit(session, *args, **kwargs)
        session.get(RuntimeBinding, body["binding_id"]).status = "revoked"
        return result

    def never(*args, **kwargs):
        pytest.fail("revoked binding must never execute")

    monkeypatch.setattr("app.routers.deployment_submission.audit", revoke)
    monkeypatch.setattr("app.routers.deployment_submission.execute_deployment", never)
    response = post(client, tenant_a, body)
    assert response.status_code == 201
    assert response.json()["state"] == "needs_attention"
    with session_scope() as s:
        deployment = s.get(Deployment, response.json()["deployment_id"])
        assert deployment.status == "failed" and deployment.verification["backend_mutated"] is False


@pytest.mark.parametrize("outcome", ["success", "adapter_failure", "audit_failure_after_apply"])
def test_openshell_execution_is_never_replayed_after_effect(client, tenant_a, env_a, monkeypatch, outcome):
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.operation_registry import PolicyOperationRegistry
    from app.routers import policies
    from app.tests.test_openshell_policy_operations import StatefulRunner

    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()

    def run(args):
        if args[:2] == ["policy", "get"]:
            args = [*args[:2], "s1", *args[3:]]
        result = runner(args)
        if args[:2] == ["policy", "set"] and outcome == "adapter_failure":
            return 1, "", "simulated lost acknowledgement after effect"
        return result

    backend = OpenShellCliBackend(runner=run, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr(policies, "OpenShellCliBackend", lambda: backend)
    body, _ = setup(client, tenant_a, env_a, backend="openshell-cli")
    value = preview(client, tenant_a, body)
    request = {
        **body,
        "schema_version": "deployment-submission-create/v1",
        "request_key": str(uuid.uuid4()),
        "preview_digest": value["preview_digest"],
    }
    original_audit = policies.audit

    def audit_after_effect(*args, **kwargs):
        if args[4] == "deployment.verify" and outcome == "audit_failure_after_apply":
            raise RuntimeError("simulated audit failure after external effect")
        return original_audit(*args, **kwargs)

    monkeypatch.setattr(policies, "audit", audit_after_effect)
    response = post(client, tenant_a, request)
    assert response.status_code == (502 if outcome == "audit_failure_after_apply" else 201)
    assert runner.set_calls == 1
    record = read(client, tenant_a, request).json()
    expected = {"success": "recorded", "adapter_failure": "needs_attention", "audit_failure_after_apply": "unconfirmed"}
    assert record["state"] == expected[outcome]
    for _ in range(2):
        assert post(client, tenant_a, request).json() == record
    assert runner.set_calls == 1
