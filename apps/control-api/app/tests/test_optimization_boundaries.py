"""OPT-04: bounded list semantics and non-sensitive backend failures."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.adapters.openshell.contracts import AdapterError, UnsupportedCapability
from app.models import DesiredPolicy
from app.routers import policies
from app.tests.binding_helpers import make_binding
from app.tests.test_deployment_verify import _make_deployment


@pytest.mark.parametrize("endpoint", ["policies", "deployments", "runtime-bindings"])
@pytest.mark.parametrize("requested,expected", [(-1, 50), (0, 50), (1, 1), (200, 200), (201, 200)])
def test_lists_use_bounded_compatible_limits(client, tenant_a, endpoint, requested, expected):
    response = client.get(f"/api/v1/{endpoint}", params={"limit": requested}, headers=tenant_a)
    assert response.status_code == 200, response.text
    assert response.headers["X-SIQ-List-Limit"] == str(expected)
    assert int(response.headers["X-SIQ-List-Returned"]) == len(response.json())
    assert len(response.json()) <= expected
    assert response.headers["X-SIQ-List-Truncated"] in {"0", "1"}


def test_lists_expose_next_page_without_cross_tenant_rows(client, tenant_a, tenant_b, env_a):
    for _ in range(3):
        make_binding(client, tenant_a, env_a["id"])
        _make_deployment(tenant_id=tenant_a["X-Dev-Tenant-Id"])
    for endpoint in ["policies", "deployments", "runtime-bindings"]:
        first = client.get(f"/api/v1/{endpoint}?limit=1", headers=tenant_a)
        assert first.status_code == 200
        assert first.headers["X-SIQ-List-Truncated"] == "1"
        second = client.get(f"/api/v1/{endpoint}", headers=tenant_a, params={
            "limit": 1, "cursor": first.headers["X-SIQ-Next-Cursor"],
        })
        assert second.status_code == 200
        assert first.json()[0]["id"] != second.json()[0]["id"]
        foreign = client.get(f"/api/v1/{endpoint}?limit=200", headers=tenant_b)
        assert foreign.status_code == 200
        assert first.json()[0]["id"] not in {row["id"] for row in foreign.json()}


@pytest.mark.parametrize("stage,status,prefix", [
    ("construct", 502, "openshell_unreachable"),
    ("compile", 422, "compile_rejected"),
    ("validate", 422, "compile_invalid"),
])
def test_compile_errors_never_echo_backend_details(monkeypatch, stage, status, prefix):
    private = "private-path=/private/operator/config synthetic-provider-token"

    class Backend:
        def __init__(self):
            if stage == "construct":
                raise AdapterError(private)

        def compile(self, desired):
            if stage == "compile":
                raise UnsupportedCapability(private)
            return object()

        def validate(self, compiled):
            return SimpleNamespace(valid=False, errors=[private])

    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    monkeypatch.setattr(policies, "OpenShellCliBackend", Backend)
    policy = DesiredPolicy(id="synthetic", tenant_id="tnt-A", selector={})
    with pytest.raises(HTTPException) as exc:
        policies._compile_for_enforcement(policy, {})
    assert exc.value.status_code == status
    category, digest = exc.value.detail.split(": ")
    assert category == prefix
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert private not in exc.value.detail
