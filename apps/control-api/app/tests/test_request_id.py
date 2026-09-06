"""DEV11-D：Request-ID 规范化与审计主键服务端生成。"""

from __future__ import annotations

from app.db import session_scope
from app.models import AuditEvent
from app.request_id import normalize_client_request_id


def test_normalize_accepts_safe_client_id():
    assert normalize_client_request_id("client-req-abc123") == "client-req-abc123"


def test_normalize_rejects_injection_and_overlength():
    injected = normalize_client_request_id("evil\ninject")
    assert injected.startswith("req-")
    assert "\n" not in injected

    spaces = normalize_client_request_id("has spaces here")
    assert spaces.startswith("req-")

    too_long = "a" * 65
    assert normalize_client_request_id(too_long).startswith("req-")

    short = normalize_client_request_id("short")
    assert short.startswith("req-")

    assert normalize_client_request_id(None).startswith("req-")
    assert normalize_client_request_id("   ").startswith("req-")


def test_middleware_echoes_sanitized_request_id(client, tenant_a):
    bad = client.post(
        "/api/v1/environments",
        json={"name": "env-reqid-bad"},
        headers={**tenant_a, "X-Request-ID": "bad\rid\ninject"},
    )
    assert bad.status_code == 201
    echoed = bad.headers.get("X-Request-ID")
    assert echoed is not None
    assert echoed.startswith("req-")
    assert "\n" not in echoed and "\r" not in echoed

    good_id = "corr-ok-12345678"
    good = client.post(
        "/api/v1/environments",
        json={"name": "env-reqid-good"},
        headers={**tenant_a, "X-Request-ID": good_id},
    )
    assert good.status_code == 201
    assert good.headers.get("X-Request-ID") == good_id


def test_enrollment_audit_uses_normalized_request_id_and_server_audit_id(
    client, tenant_a, env_a
):
    corr = "enroll-corr-abcdef01"
    resp = client.post(
        f"/api/v1/environments/{env_a['id']}/edge-enrollment",
        json={},
        headers={**tenant_a, "X-Request-ID": corr},
    )
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == corr

    with session_scope() as session:
        audits = (
            session.query(AuditEvent)
            .filter(AuditEvent.action == "edge.enrollment.create")
            .order_by(AuditEvent.created_at.desc())
            .all()
        )
        assert audits
        latest = audits[0]
        assert latest.id.startswith("aud_")
        assert latest.request_id == corr
        assert latest.actor_id == "user-a"  # 操作者仍来自身份上下文，非 Request-ID
