"""Authenticated plan generation, controlled metadata and zero enrollment effects."""

import json
import os
import subprocess

import pytest
from jsonschema import Draft202012Validator
from sqlalchemy import func, select

from app.db import session_scope
from app.install_plan import EnterpriseInstallPlan
from app.models import AuditEvent, EdgeAgent, EnrollmentToken
from app.tests.test_enterprise_install_plan import ROOT, VALIDATOR, sample


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    plan = sample()
    value = {
        "schema_version": "enterprise-install-catalog/v1",
        "control_plane_origin": plan["control_plane_origin"],
        "allowed_service_modes": ["user"],
        "releases": [{k: plan[k] for k in ["target_arch", "release_version", "release_manifest_sha256", "connectors"]}],
    }
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    monkeypatch.setenv("SIQ_AS_INSTALL_CATALOG_FILE", str(path))
    return path


def request():
    return {
        "schema_version": "enterprise-install-request/v1",
        "target_arch": "arm64",
        "service_mode": "user",
        "connectors": ["hermes"],
    }


def test_issue_derived_identity_and_audit_no_registration(client, tenant_a, env_a, catalog):
    with session_scope() as s:
        before = [s.scalar(select(func.count(model.id))) for model in [EdgeAgent, EnrollmentToken]]
    response = client.post(f"/api/v1/environments/{env_a['id']}/install-plans", json=request(), headers=tenant_a)
    assert response.status_code == 200
    plan = response.json()
    VALIDATOR.validate(plan)
    EnterpriseInstallPlan.model_validate(plan).require_current()
    assert plan["tenant_id"] == tenant_a["X-Dev-Tenant-Id"]
    assert plan["environment_id"] == env_a["id"]
    assert response.headers["cache-control"] == "no-store"
    with session_scope() as s:
        assert before == [s.scalar(select(func.count(model.id))) for model in [EdgeAgent, EnrollmentToken]]
        audit = s.scalar(
            select(AuditEvent).where(AuditEvent.action == "install.plan.create").order_by(AuditEvent.id.desc())
        )
        assert audit is not None
        assert "~/.hermes" not in json.dumps(audit.summary)


def test_tenant_and_permission_boundaries(client, tenant_a, tenant_b, env_a, catalog):
    route = f"/api/v1/environments/{env_a['id']}/install-plans"
    assert client.post(route, json=request(), headers=tenant_b).status_code == 404
    assert client.post(route, json=request(), headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403
    assert client.post(route, json=request()).status_code in {401, 404}


@pytest.mark.parametrize(
    "field", ["tenant_id", "environment_id", "control_plane_origin", "release_manifest_sha256", "purpose", "scope"]
)
def test_no_client_authority_overrides(client, tenant_a, env_a, catalog, field):
    body = request()
    body[field] = "forged"
    assert (
        client.post(f"/api/v1/environments/{env_a['id']}/install-plans", json=body, headers=tenant_a).status_code == 422
    )


@pytest.mark.parametrize(
    "field,value", [("target_arch", "amd64"), ("service_mode", "system"), ("connectors", ["docker"])]
)
def test_unsupported_catalog_choice(client, tenant_a, env_a, catalog, field, value):
    body = {**request(), field: value}
    assert (
        client.post(f"/api/v1/environments/{env_a['id']}/install-plans", json=body, headers=tenant_a).status_code == 409
    )


@pytest.mark.parametrize("fault", ["missing", "symlink", "writable", "invalid", "http", "duplicate"])
def test_catalog_fail_closed(client, tenant_a, env_a, catalog, monkeypatch, fault):
    if fault == "missing":
        monkeypatch.delenv("SIQ_AS_INSTALL_CATALOG_FILE")
    elif fault == "symlink":
        link = catalog.parent / "link.json"
        link.symlink_to(catalog)
        monkeypatch.setenv("SIQ_AS_INSTALL_CATALOG_FILE", str(link))
    elif fault == "writable":
        catalog.chmod(0o666)
    elif fault == "invalid":
        catalog.write_text('{"private":"not-to-be-reflected"}')
    elif fault == "http":
        data = json.loads(catalog.read_text())
        data["control_plane_origin"] = "http://192.168.2.121:10082"
        catalog.write_text(json.dumps(data))
    else:
        catalog.write_text('{"schema_version":"one","schema_version":"two"}')
    response = client.post(f"/api/v1/environments/{env_a['id']}/install-plans", json=request(), headers=tenant_a)
    assert response.status_code == 503
    assert response.json() == {"detail": "install_catalog_unavailable"}


def test_audit_failure_prevents_plan_response(client, tenant_a, env_a, catalog, monkeypatch):
    from app.routers import install_plans

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(install_plans, "audit", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        client.post(f"/api/v1/environments/{env_a['id']}/install-plans", json=request(), headers=tenant_a)


def test_request_schema_rejects_overrides_and_duplicates():
    schema = json.loads((ROOT / "packages/contracts/enterprise-install-request.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(request())
    for body in [{**request(), "tenant_id": "forged"}, {**request(), "connectors": ["hermes", "hermes"]}]:
        assert list(validator.iter_errors(body))
    for key in request():
        body = request()
        body.pop(key)
        assert list(validator.iter_errors(body))


def test_actual_issued_plan_consumed_by_go(client, tenant_a, env_a, catalog, tmp_path):
    response = client.post(f"/api/v1/environments/{env_a['id']}/install-plans", json=request(), headers=tenant_a)
    assert response.status_code == 200
    plan = response.json()
    corpus, output = tmp_path / "issuer-corpus.json", tmp_path / "go-output.json"
    corpus.write_text(json.dumps([{"plan": plan, "valid": True}]))
    run = subprocess.run(
        ["go", "test", "./installplan", "-run", "^TestInstallPlanWireParity$", "-count=1"],
        cwd=ROOT / "edge/agent",
        env={**os.environ, "SIQ_INSTALL_PLAN_TEST_CORPUS": str(corpus), "SIQ_INSTALL_PLAN_TEST_OUTPUT": str(output)},
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert json.loads(output.read_text()) == [plan]
