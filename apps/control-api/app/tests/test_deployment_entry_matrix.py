"""Same authorization and static-intent counterexamples at every HTTP writer."""

import uuid

import pytest
from sqlalchemy import func, select

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.operation_registry import PolicyOperationRegistry
from app.db import session_scope
from app.models import ChangeRequest, Deployment, DesiredPolicy, EdgeTask, OpenShellOperation, RuntimeBinding
from app.tests.binding_helpers import assign_target_authority
from app.tests.test_deployment_preview import preview, setup
from app.tests.test_openshell_policy_operations import StatefulRunner


def _counts():
    with session_scope() as session:
        return [session.scalar(select(func.count()).select_from(model))
                for model in (Deployment, EdgeTask, OpenShellOperation)]


def _request(client, headers, body, entry):
    value = preview(client, headers, body)
    if entry == "legacy":
        return "/api/v1/deployments", {k: v for k, v in body.items() if k != "schema_version"}
    if entry == "preview":
        return "/api/v1/deployment-preview/submit", {
            **body, "schema_version": "deployment-preview-submit/v1", "preview_digest": value["preview_digest"],
        }
    if entry == "submission":
        return "/api/v1/deployment-submissions", {
            **body, "schema_version": "deployment-submission-create/v1",
            "preview_digest": value["preview_digest"], "request_key": str(uuid.uuid4()),
        }
    result = client.post("/api/v1/deployment-batch-drafts", headers=headers, json={
        "schema_version": "enterprise-batch-draft-create/v1", "items": [body], "request_key": str(uuid.uuid4()),
    })
    assert result.status_code == 201, result.text
    draft = result.json()
    return f"/api/v1/deployment-batch-drafts/{draft['id']}/execute", {
        "schema_version": "enterprise-batch-execute/v1", "confirm_execution": True,
        "preview_digest": draft["preview"]["preview_digest"],
    }


@pytest.mark.parametrize("entry", ["legacy", "preview", "submission", "batch"])
@pytest.mark.parametrize("fault", [
    "none", "permission", "tenant", "approval", "revoked_binding", "target_drift",
    "static_narrowing", "unknown_filesystem",
])
def test_all_writers_refuse_invalid_authority_or_lost_static_intent(
    client, tenant_a, tenant_b, env_a, monkeypatch, tmp_path, entry, fault,
):
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()

    def run(args):
        if args[:2] == ["policy", "get"]:
            args = [*args[:2], "s1", *args[3:]]
        return runner(args)

    backend = OpenShellCliBackend(runner=run, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr("app.routers.policies.OpenShellCliBackend", lambda: backend)
    body, policy = setup(client, tenant_a, env_a, backend="openshell-cli")
    assign_target_authority(monkeypatch, tmp_path, body["binding_id"], backend)
    url, request = _request(client, tenant_a, body, entry)
    headers = tenant_a
    with session_scope() as session:
        if fault == "permission":
            headers = {**tenant_a, "X-Dev-Roles": "viewer"}
        elif fault == "tenant":
            headers = tenant_b
        elif fault == "approval":
            session.get(ChangeRequest, body["change_request_id"]).status = "pending"
        elif fault == "revoked_binding":
            session.get(RuntimeBinding, body["binding_id"]).status = "revoked"
        elif fault == "target_drift":
            session.get(RuntimeBinding, body["binding_id"]).backend_target_id = "unassigned-" + uuid.uuid4().hex
        elif fault == "static_narrowing":
            session.get(DesiredPolicy, policy["id"]).filesystem = {"read_only": [], "read_write": []}
        elif fault == "unknown_filesystem":
            session.get(DesiredPolicy, policy["id"]).filesystem = {"include_workdir": False}
    before = _counts()
    response = client.post(url, headers=headers, json=request)
    if fault == "none":
        assert response.status_code in {200, 201}, response.text
        assert runner.set_calls == 1
        after = _counts()
        assert after[0] == before[0] + 1 and after[2] == before[2] + 1
        replay = client.post(url, headers=headers, json=request)
        assert replay.status_code in ({200} if entry in {"submission", "batch"} else {409})
        assert runner.set_calls == 1 and _counts() == after
    else:
        expected = {"permission": 403, "tenant": 404, "approval": 409, "revoked_binding": 409,
                    "target_drift": 409, "static_narrowing": 422, "unknown_filesystem": 422}
        assert response.status_code == expected[fault], response.text
        assert runner.set_calls == 0 and _counts() == before
