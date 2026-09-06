"""DEV13-D：列表截断元数据（响应头），禁止本页条数冒充全量。"""

from __future__ import annotations

from app.db import session_scope
from app.list_meta import HDR_LIMIT, HDR_NEXT_CURSOR, HDR_RETURNED, HDR_TOTAL, HDR_TRUNCATED
from app.models import AgentAsset, AuditEvent, ChangeRequest, DesiredPolicy, Finding, PermissionFact, new_id, utcnow

AUDITOR_A = {
    "X-Dev-Tenant-Id": "tnt-A",
    "X-Dev-User-Id": "auditor-a",
    "X-Dev-Roles": "auditor",
}


def _seed_policy(session, tenant_id: str) -> DesiredPolicy:
    p = DesiredPolicy(
        id=new_id("pol"),
        tenant_id=tenant_id,
        name="list-meta",
        selector={"agent_ids": []},
        version=1,
        status="approved",
        enforcement_mode="audit_only",
        unsupported_by_backend=[],
    )
    session.add(p)
    session.commit()
    return p


def test_audit_list_headers_mark_truncation(client):
    with session_scope() as session:
        for i in range(5):
            session.add(
                AuditEvent(
                    id=new_id("aud"),
                    tenant_id="tnt-A",
                    actor_type="user",
                    actor_id="u1",
                    action=f"act.{i}",
                    resource_type="test",
                    resource_id=None,
                    decision="allow",
                    request_id=None,
                    summary={"i": i},
                    created_at=utcnow(),
                )
            )
        session.commit()

    resp = client.get("/api/v1/audit-events?limit=2", headers=AUDITOR_A)
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert resp.headers.get(HDR_LIMIT) == "2"
    assert resp.headers.get(HDR_RETURNED) == "2"
    assert resp.headers.get(HDR_TRUNCATED) == "1"
    assert resp.headers.get(HDR_NEXT_CURSOR)
    assert resp.headers.get(HDR_TOTAL) is None

    resp2 = client.get(
        f"/api/v1/audit-events?limit=2&cursor={resp.headers[HDR_NEXT_CURSOR]}",
        headers=AUDITOR_A,
    )
    assert resp2.status_code == 200
    assert len(resp2.json()) == 2
    assert {r["id"] for r in body}.isdisjoint({r["id"] for r in resp2.json()})


def test_audit_include_total_sets_header(client):
    with session_scope() as session:
        for i in range(3):
            session.add(
                AuditEvent(
                    id=new_id("aud"),
                    tenant_id="tnt-A",
                    actor_type="user",
                    actor_id="u1",
                    action=f"tot.{i}",
                    resource_type="test",
                    resource_id=None,
                    decision="allow",
                    request_id=None,
                    summary={},
                    created_at=utcnow(),
                )
            )
        session.commit()

    resp = client.get("/api/v1/audit-events?limit=2&include_total=true", headers=AUDITOR_A)
    assert resp.status_code == 200
    assert resp.headers.get(HDR_TRUNCATED) == "1"
    total = int(resp.headers.get(HDR_TOTAL, "0"))
    assert total >= 3
    assert len(resp.json()) == 2
    assert total != len(resp.json())


def test_change_requests_list_truncation_headers(client, tenant_a):
    with session_scope() as session:
        pol = _seed_policy(session, "tnt-A")
        for i in range(4):
            session.add(
                ChangeRequest(
                    id=new_id("cr"),
                    tenant_id="tnt-A",
                    policy_id=pol.id,
                    proposer_user_id="u-proposer",
                    approver_user_id=None,
                    approval_policy="sod",
                    status="proposed",
                    idempotency_key=f"ik-{i}-{new_id('k')}",
                    created_at=utcnow(),
                )
            )
        session.commit()

    resp = client.get("/api/v1/change-requests?limit=2", headers=tenant_a)
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    assert resp.headers.get(HDR_TRUNCATED) == "1"
    assert resp.headers.get(HDR_NEXT_CURSOR)
    assert resp.headers.get(HDR_RETURNED) == "2"


def test_agents_list_truncation_headers(client, tenant_a):
    """DEV13-E：/agents 截断头 + 游标翻页。"""
    with session_scope() as session:
        for i in range(4):
            session.add(
                AgentAsset(
                    id=new_id("agt"),
                    tenant_id="tnt-A",
                    name=f"agent-{i}",
                    framework="hermes",
                    status="managed",
                    source_type="test",
                    source_locator=f"test://agent-{i}",
                    updated_at=utcnow(),
                )
            )
        session.commit()

    resp = client.get("/api/v1/agents?limit=2", headers=tenant_a)
    assert resp.status_code == 200
    page1 = resp.json()
    assert len(page1) == 2
    assert resp.headers.get(HDR_TRUNCATED) == "1"
    assert resp.headers.get(HDR_NEXT_CURSOR)
    assert resp.headers.get(HDR_RETURNED) == "2"

    resp2 = client.get(
        f"/api/v1/agents?limit=2&cursor={resp.headers[HDR_NEXT_CURSOR]}",
        headers=tenant_a,
    )
    assert resp2.status_code == 200
    page2 = resp2.json()
    assert len(page2) >= 1
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})


def test_findings_list_truncation_headers(client, tenant_a):
    """DEV13-E：/findings 截断头 + 游标翻页。"""
    with session_scope() as session:
        for i in range(4):
            session.add(
                Finding(
                    id=new_id("fnd"),
                    tenant_id="tnt-A",
                    rule_id=f"R-TEST-{i}",
                    severity="medium",
                    status="open",
                    first_seen_at=utcnow(),
                    last_seen_at=utcnow(),
                )
            )
        session.commit()

    resp = client.get("/api/v1/findings?limit=2", headers=tenant_a)
    assert resp.status_code == 200
    page1 = resp.json()
    assert len(page1) == 2
    assert resp.headers.get(HDR_TRUNCATED) == "1"
    assert resp.headers.get(HDR_NEXT_CURSOR)

    resp2 = client.get(
        f"/api/v1/findings?limit=2&cursor={resp.headers[HDR_NEXT_CURSOR]}",
        headers=tenant_a,
    )
    assert resp2.status_code == 200
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in resp2.json()})


def test_permissions_list_truncation_headers(client, tenant_a):
    """DEV13-E：/permissions 截断头 + 游标翻页。"""
    with session_scope() as session:
        for i in range(4):
            session.add(
                PermissionFact(
                    id=new_id("pf"),
                    tenant_id="tnt-A",
                    subject_type="agent_asset",
                    subject_id=f"agt-{i}",
                    domain="tool",
                    action="invoke",
                    resource_type="tool",
                    resource_value=f"tool://t{i}",
                    effect="allow",
                    state="declared",
                    authority="edge",
                    created_at=utcnow(),
                )
            )
        session.commit()

    resp = client.get("/api/v1/permissions?limit=2", headers=tenant_a)
    assert resp.status_code == 200
    page1 = resp.json()
    assert len(page1) == 2
    assert resp.headers.get(HDR_TRUNCATED) == "1"
    assert resp.headers.get(HDR_NEXT_CURSOR)

    resp2 = client.get(
        f"/api/v1/permissions?limit=2&cursor={resp.headers[HDR_NEXT_CURSOR]}",
        headers=tenant_a,
    )
    assert resp2.status_code == 200
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in resp2.json()})
