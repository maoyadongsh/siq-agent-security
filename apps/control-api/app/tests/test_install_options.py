import json

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, EdgeAgent, EnrollmentToken
from app.tests import test_install_plan_issuer as issuer

catalog = issuer.catalog


def test_options_are_scoped_read_only_configuration(client, tenant_a, env_a, catalog):
    def counts():
        with session_scope() as session:
            return [session.scalar(select(func.count(model.id))) for model in (AuditEvent, EdgeAgent, EnrollmentToken)]

    before = counts()
    response = client.get(f"/api/v1/environments/{env_a['id']}/install-options", headers=tenant_a)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    value = response.json()
    assert value["schema_version"] == "enterprise-install-options/v1"
    assert value["environment_id"] == env_a["id"]
    assert value["purpose"] == "discovery_only"
    assert value["release_signature_verified"] is False
    assert value["allowed_service_modes"] == ["user"]
    assert value["releases"][0]["connectors"][0]["scope"]["include"]
    assert "plan_id" not in value and "code" not in value
    assert counts() == before


def test_options_cross_tenant_and_permission_denial(client, tenant_a, tenant_b, env_a, catalog):
    path = f"/api/v1/environments/{env_a['id']}/install-options"
    assert client.get(path, headers=tenant_b).status_code == 404
    assert client.get(path, headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403


@pytest.mark.parametrize("kind", ["missing", "unsafe_origin", "system_only", "unknown_field"])
def test_options_unavailable_is_not_secret_disclosure(client, tenant_a, env_a, catalog, monkeypatch, kind):
    value = json.loads(catalog.read_text())
    if kind == "missing":
        monkeypatch.delenv("SIQ_AS_INSTALL_CATALOG_FILE")
    elif kind == "unsafe_origin":
        value["control_plane_origin"] = "https://credential:secret@example.test"
    elif kind == "system_only":
        value["allowed_service_modes"] = ["system"]
    else:
        value["private_fixture"] = "must-not-appear"
    catalog.write_text(json.dumps(value))
    response = client.get(f"/api/v1/environments/{env_a['id']}/install-options", headers=tenant_a)
    assert response.status_code == 503
    assert response.json() == {"detail": "install_options_unavailable"}
