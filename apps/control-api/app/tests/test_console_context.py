"""Console identity projection and truthful overview checks against real API/DB."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema
import jwt
import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, DesiredPolicy, EdgeAgent, Environment, Tenant, utcnow
from app.security import settings


@pytest.mark.parametrize(
    "role,visible",
    [
        ("viewer", {"agents", "permissions", "findings", "policies", "changes", "runtime_bindings"}),
        ("auditor", {"agents", "permissions", "findings", "policies", "changes", "runtime_bindings", "audit"}),
        ("platform_operator", {"environments"}),
        ("agent_owner", {"agents", "permissions", "findings"}),
        ("reviewer", set()),
        ("tenant_admin", {"environments"}),
    ],
)
def test_console_role_access_matches_existing_backend(client, tenant_a, role, visible):
    headers = {**tenant_a, "X-Dev-Roles": role}
    response = client.get("/api/v1/console-context", headers=headers)
    assert response.status_code == 200
    value = response.json()
    assert {k for k, v in value["access"].items() if v} == visible | {"workspace", "settings"}
    assert value["roles"][0]["code"] == role
    assert value["authentication"] == "development_headers"
    assert value["actor"]["id"] == tenant_a["X-Dev-User-Id"]
    schema = Path(__file__).resolve().parents[4] / "packages/contracts/console-context.v1.schema.json"
    jsonschema.validate(value, json.loads(schema.read_text()), format_checker=jsonschema.FormatChecker())
    routes = {
        "agents": "/agents",
        "environments": "/environments",
        "policies": "/policies",
        "changes": "/change-requests",
        "audit": "/audit-events",
    }
    for key, route in routes.items():
        result = client.get("/api/v1" + route, headers=headers)
        assert result.status_code == (200 if key in visible else 403), (role, route, result.status_code)


def test_console_tenant_is_verified_and_get_does_not_write(client):
    with session_scope() as session:
        session.add_all(
            [Tenant(id="console-own", name="自己的组织"), Tenant(id="console-other", name="OTHER-PRIVATE-ORG")]
        )
    headers = {"X-Dev-Tenant-Id": "console-own", "X-Dev-User-Id": "console-user", "X-Dev-Roles": "viewer"}
    with session_scope() as session:
        before = (session.scalar(select(func.count(Tenant.id))), session.scalar(select(func.count(AuditEvent.id))))
    got = client.get("/api/v1/console-context?tenant_id=console-other", headers=headers)
    assert got.json()["tenant"] == {"id": "console-own", "name": "自己的组织"}
    assert "OTHER-PRIVATE" not in got.text
    missing = client.get("/api/v1/console-context", headers={**headers, "X-Dev-Tenant-Id": "console-unseeded"})
    assert missing.json()["tenant"] == {"id": "console-unseeded", "name": None}
    assert client.get("/api/v1/console-context").status_code == 401
    with session_scope() as session:
        assert before == (
            session.scalar(select(func.count(Tenant.id))),
            session.scalar(select(func.count(AuditEvent.id))),
        )


def test_console_verified_token_permissions_not_role_label(client, monkeypatch):
    signing_key = "console-context-fixture-key-" * 3
    monkeypatch.setattr("app.security._dev_secret", lambda: signing_key)
    def request(roles, permissions, identity_type="user"):
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": "console-token-user",
                "tenant_id": "console-own",
                "type": identity_type,
                "role_codes": roles,
                "permissions": permissions,
                "aud": settings.jwt_audience,
                "iat": now,
                "exp": now + timedelta(minutes=2),
            },
            signing_key,
            algorithm="HS256",
        )
        result = client.get("/api/v1/console-context", headers={"Authorization": "Bearer " + token})
        assert result.status_code == 200
        assert token not in result.text and "permissions" not in result.json()
        return result.json()

    value = request(["custom-finance-role"], ["agent:read"], "service")
    assert value["roles"] == [] and value["custom_role_count"] == 1
    assert value["actor"]["type"] == "service" and value["authentication"] == "verified_token"
    assert value["access"]["agents"] and not value["access"]["policies"]
    admin = request(["admin"], ["*"])
    assert all(admin["access"].values()) and all(admin["actions"].values())
    reviewer = request(["reviewer"], [])
    assert reviewer["actions"]["approve_change"] and not reviewer["access"]["changes"]


def test_overview_permissions_online_heartbeat_and_policy_count(client):
    headers = {"X-Dev-Tenant-Id": "console-stats", "X-Dev-User-Id": "user", "X-Dev-Roles": "security_admin"}
    now = utcnow()
    with session_scope() as session:
        session.add_all(
            [Tenant(id="console-stats", name="统计组织"), Tenant(id="console-stats-other", name="其他统计组织")]
        )
        session.flush()
        session.add_all(
            [
                Environment(id="console-env", tenant_id="console-stats", name="one"),
                Environment(id="console-other-env", tenant_id="console-stats-other", name="other"),
            ]
        )
        session.flush()
        for suffix, seen, revoked, env in [
            ("online", now, None, "console-env"),
            ("waiting", None, None, "console-env"),
            ("stale", now - timedelta(days=1), None, "console-env"),
            ("future", now + timedelta(days=1), None, "console-env"),
            ("revoked", now, now, "console-env"),
            ("foreign", now, None, "console-other-env"),
        ]:
            session.add(
                EdgeAgent(
                    environment_id=env,
                    device_identity="console-" + suffix,
                    secret_hash="fixture",
                    public_key_pem="fixture",
                    version="1",
                    last_seen_at=seen,
                    revoked_at=revoked,
                )
            )
        session.add_all(
            [
                DesiredPolicy(tenant_id="console-stats", name="one", selector={}),
                DesiredPolicy(tenant_id="console-stats-other", name="other", selector={}),
            ]
        )
    got = client.get("/api/v1/overview", headers=headers)
    assert got.status_code == 200
    assert got.json()["edges_online"] == 1 and got.json()["policies"] == 1 and got.json()["environments"] == 1
    for role in ["viewer", "platform_operator", "reviewer"]:
        assert client.get("/api/v1/overview", headers={**headers, "X-Dev-Roles": role}).status_code == 403
