"""ENT-019-AUDIT-QUERY：审计精确查询增强测试（enterprise-audit-query.v1）。

覆盖 request_id/resource_id/actor_type/decision 四个新增精确过滤参数：
- 精确匹配、新旧条件 AND 组合、空串/超长 422；
- 列表与 include_total 总数同一过滤口径，多页无重复无遗漏，总数不受 cursor 影响；
- 同名标识跨租户严格隔离、audit:read 权限保留、注入形态值只作为查询数据；
- 查询只读：多次 GET 不修改审计、outbox 或业务对象。

所有夹具值带唯一前缀，避免与共享隔离库中其他测试的记录互相影响。
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.db import session_scope
from app.list_meta import HDR_NEXT_CURSOR, HDR_RETURNED, HDR_TOTAL, HDR_TRUNCATED
from app.models import AgentAsset, AuditEvent, OutboxEvent, new_id, utcnow

AUDITOR_A = {
    "X-Dev-Tenant-Id": "tnt-A",
    "X-Dev-User-Id": "auditor-aq-a",
    "X-Dev-Roles": "auditor",
}
AUDITOR_B = {
    "X-Dev-Tenant-Id": "tnt-B",
    "X-Dev-User-Id": "auditor-aq-b",
    "X-Dev-Roles": "auditor",
}
# viewer 角色权限为 agent:read/policy:read，不含 audit:read。
VIEWER_A = {
    "X-Dev-Tenant-Id": "tnt-A",
    "X-Dev-User-Id": "viewer-aq-a",
    "X-Dev-Roles": "viewer",
}

MARKER = "ent019-aq"


def _uq(label: str) -> str:
    """本文件内唯一的合成值，避免依赖其他测试的数据。"""
    return f"{MARKER}-{label}-{uuid.uuid4().hex[:12]}"


def _seed(tenant_id: str, **overrides) -> AuditEvent:
    with session_scope() as session:
        event = AuditEvent(
            id=overrides.pop("id", new_id("aud")),
            tenant_id=tenant_id,
            actor_type=overrides.pop("actor_type", "user"),
            actor_id=overrides.pop("actor_id", f"u-{MARKER}"),
            action=overrides.pop("action", f"audit.query.{MARKER}"),
            resource_type=overrides.pop("resource_type", "test"),
            resource_id=overrides.pop("resource_id", None),
            decision=overrides.pop("decision", "allow"),
            request_id=overrides.pop("request_id", None),
            summary=overrides.pop("summary", {"suite": MARKER}),
            created_at=overrides.pop("created_at", utcnow()),
        )
        assert not overrides, f"unknown overrides: {sorted(overrides)}"
        session.add(event)
        session.commit()
        session.refresh(event)
        return event


def _get(client, headers, **params):
    resp = client.get("/api/v1/audit-events", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp


def _ids(resp) -> set[str]:
    return {row["id"] for row in resp.json()}


def test_existing_filters_unchanged_without_new_params(client):
    """不传新参数时旧过滤与响应协议保持原行为。"""
    actor_id = _uq("legacy-actor")
    match = _seed("tnt-A", actor_id=actor_id, action="audit.query.legacy", resource_type="change_request")
    _seed("tnt-A", actor_id=actor_id, action="audit.query.legacy", resource_type="policy")
    _seed("tnt-A", actor_id=_uq("legacy-other"), action="audit.query.legacy", resource_type="change_request")

    resp = _get(client, AUDITOR_A, actor_id=actor_id, action="audit.query.legacy", resource_type="change_request")
    assert _ids(resp) == {match.id}
    assert resp.headers.get(HDR_TRUNCATED) == "0"
    assert resp.headers.get(HDR_RETURNED) == "1"

    plain = _get(client, AUDITOR_A)
    assert isinstance(plain.json(), list)


def test_request_id_exact_filter(client):
    request_id = _uq("req")
    match = _seed("tnt-A", request_id=request_id)
    _seed("tnt-A", request_id=_uq("req-other"))
    _seed("tnt-A", request_id=None)

    resp = _get(client, AUDITOR_A, request_id=request_id)
    assert _ids(resp) == {match.id}
    assert resp.json()[0]["request_id"] == request_id


def test_resource_id_exact_filter(client):
    resource_id = _uq("res")
    match = _seed("tnt-A", resource_id=resource_id)
    _seed("tnt-A", resource_id=_uq("res-other"))

    resp = _get(client, AUDITOR_A, resource_id=resource_id)
    assert _ids(resp) == {match.id}


def test_actor_type_exact_filter(client):
    actor_id = _uq("actor-type")
    match = _seed("tnt-A", actor_id=actor_id, actor_type="edge")
    _seed("tnt-A", actor_id=actor_id, actor_type="service")

    resp = _get(client, AUDITOR_A, actor_id=actor_id, actor_type="edge")
    assert _ids(resp) == {match.id}


def test_decision_exact_filter(client):
    actor_id = _uq("decision")
    match = _seed("tnt-A", actor_id=actor_id, decision="deny")
    _seed("tnt-A", actor_id=actor_id, decision="allow")

    resp = _get(client, AUDITOR_A, actor_id=actor_id, decision="deny")
    assert _ids(resp) == {match.id}


def test_new_and_old_filters_combine_with_and(client):
    """新旧过滤条件 AND 组合；任一条件不满足即排除。"""
    request_id = _uq("and-req")
    resource_id = _uq("and-res")
    actor_id = _uq("and-actor")
    full = _seed(
        "tnt-A",
        actor_id=actor_id,
        actor_type="edge",
        action="audit.query.and",
        resource_type="change_request",
        resource_id=resource_id,
        request_id=request_id,
        decision="deny",
    )
    base = {
        "actor_id": actor_id,
        "actor_type": "edge",
        "action": "audit.query.and",
        "resource_type": "change_request",
        "resource_id": resource_id,
        "request_id": request_id,
        "decision": "deny",
    }
    # 每条记录恰好破坏一个条件。
    _seed("tnt-A", **{**base, "request_id": _uq("and-req-x")})
    _seed("tnt-A", **{**base, "resource_id": _uq("and-res-x")})
    _seed("tnt-A", **{**base, "actor_type": "user"})
    _seed("tnt-A", **{**base, "decision": "allow"})
    _seed("tnt-A", **{**base, "resource_type": "policy"})
    _seed("tnt-A", **{**base, "actor_id": _uq("and-actor-x")})
    _seed("tnt-A", **{**base, "action": "audit.query.other"})

    resp = _get(
        client,
        AUDITOR_A,
        actor_id=actor_id,
        action="audit.query.and",
        resource_type="change_request",
        resource_id=resource_id,
        request_id=request_id,
        actor_type="edge",
        decision="deny",
    )
    assert _ids(resp) == {full.id}


def test_exact_match_rejects_prefix_and_substring(client):
    request_id = _uq("exact")
    _seed("tnt-A", request_id=request_id)

    assert _ids(_get(client, AUDITOR_A, request_id=request_id[:6])) == set()  # 前缀
    assert _ids(_get(client, AUDITOR_A, request_id=request_id[4:])) == set()  # 子串
    assert _ids(_get(client, AUDITOR_A, request_id=f"{request_id}-extra")) == set()  # 超串


def test_unknown_actor_type_and_decision_values_queryable(client):
    """actor_type/decision 不限定为 UI 已知枚举：合法长度未知原值可查。"""
    actor_id = _uq("unknown")
    match = _seed("tnt-A", actor_id=actor_id, actor_type="automaton-x", decision="quarantine")

    resp = _get(client, AUDITOR_A, actor_type="automaton-x", decision="quarantine")
    assert match.id in _ids(resp)
    row = next(r for r in resp.json() if r["id"] == match.id)
    assert row["actor_type"] == "automaton-x"
    assert row["decision"] == "quarantine"


def test_no_match_returns_empty_and_total_zero(client):
    resp = _get(client, AUDITOR_A, request_id=_uq("no-match"), include_total="true")
    assert resp.json() == []
    assert resp.headers.get(HDR_TOTAL) == "0"
    assert resp.headers.get(HDR_TRUNCATED) == "0"
    assert resp.headers.get(HDR_NEXT_CURSOR) is None


def _seed_page_series(request_id: str, count: int, *, same_timestamp: bool = False) -> list[AuditEvent]:
    base = utcnow() - timedelta(minutes=5)
    events = []
    for i in range(count):
        events.append(
            _seed(
                "tnt-A",
                request_id=request_id,
                created_at=base if same_timestamp else base + timedelta(seconds=i),
            )
        )
    return events


def _collect_pages(client, headers, limit: int, **params) -> tuple[list[dict], list]:
    """按 cursor 翻页收集全部结果，返回 (rows, responses)。"""
    rows: list[dict] = []
    responses = []
    cursor = None
    for _ in range(20):  # 防御性上限，死循环即失败
        q = {"limit": str(limit), **params}
        if cursor:
            q["cursor"] = cursor
        resp = _get(client, headers, **q)
        responses.append(resp)
        rows.extend(resp.json())
        if resp.headers.get(HDR_TRUNCATED) != "1":
            break
        cursor = resp.headers.get(HDR_NEXT_CURSOR)
        assert cursor, "truncated=1 时必须给出 next cursor"
    return rows, responses


def test_multi_page_no_duplicates_no_gaps(client):
    request_id = _uq("paged")
    expected = {e.id for e in _seed_page_series(request_id, 5)}

    rows, responses = _collect_pages(client, AUDITOR_A, 2, request_id=request_id)
    assert len(responses) == 3
    assert {r["id"] for r in rows} == expected
    assert len(rows) == len({r["id"] for r in rows}), "多页结果不得重复"
    assert all(r["request_id"] == request_id for r in rows)


def test_total_stable_across_pages(client):
    """后续页 include_total 仍是全部匹配数，不是剩余条数，也不受 cursor 影响。"""
    request_id = _uq("total")
    _seed_page_series(request_id, 5)

    page1 = _get(client, AUDITOR_A, request_id=request_id, limit="2", include_total="true")
    assert page1.headers.get(HDR_TOTAL) == "5"
    assert page1.headers.get(HDR_TRUNCATED) == "1"

    cursor = page1.headers[HDR_NEXT_CURSOR]
    page2 = _get(client, AUDITOR_A, request_id=request_id, limit="2", include_total="true", cursor=cursor)
    assert page2.headers.get(HDR_TOTAL) == "5"
    assert page2.headers.get(HDR_RETURNED) == "2"

    cursor2 = page2.headers[HDR_NEXT_CURSOR]
    page3 = _get(client, AUDITOR_A, request_id=request_id, limit="2", include_total="true", cursor=cursor2)
    assert page3.headers.get(HDR_TOTAL) == "5"
    assert page3.headers.get(HDR_TRUNCATED) == "0"


def test_same_timestamp_pagination_stable(client):
    """同一 created_at 的多条匹配记录分页无重复、无遗漏。"""
    request_id = _uq("same-ts")
    expected = {e.id for e in _seed_page_series(request_id, 4, same_timestamp=True)}

    rows, responses = _collect_pages(client, AUDITOR_A, 3, request_id=request_id)
    assert len(responses) == 2
    assert {r["id"] for r in rows} == expected
    assert len(rows) == 4


def test_cross_tenant_same_identifiers_isolated(client):
    """两租户使用相同 request_id/resource_id，结果与总数严格隔离。"""
    request_id = _uq("shared-req")
    resource_id = _uq("shared-res")
    event_a = _seed("tnt-A", request_id=request_id, resource_id=resource_id)
    event_b = _seed("tnt-B", request_id=request_id, resource_id=resource_id)

    resp_a = _get(client, AUDITOR_A, request_id=request_id, resource_id=resource_id, include_total="true")
    assert _ids(resp_a) == {event_a.id}
    assert resp_a.headers.get(HDR_TOTAL) == "1"

    resp_b = _get(client, AUDITOR_B, request_id=request_id, resource_id=resource_id, include_total="true")
    assert _ids(resp_b) == {event_b.id}
    assert resp_b.headers.get(HDR_TOTAL) == "1"


def test_missing_audit_read_permission_forbidden(client):
    request_id = _uq("forbidden")
    _seed("tnt-A", request_id=request_id)

    plain = client.get("/api/v1/audit-events", headers=VIEWER_A)
    assert plain.status_code == 403
    filtered = client.get(
        "/api/v1/audit-events",
        params={"request_id": request_id, "include_total": "true"},
        headers=VIEWER_A,
    )
    assert filtered.status_code == 403


def test_empty_string_new_params_return_422(client):
    for param in ("request_id", "resource_id", "actor_type", "decision"):
        resp = client.get("/api/v1/audit-events", params={param: ""}, headers=AUDITOR_A)
        assert resp.status_code == 422, f"{param} 空字符串必须 422"


def test_overlong_new_params_return_422(client):
    cases = {
        "request_id": ("x" * 64, "x" * 65),
        "resource_id": ("y" * 64, "y" * 65),
        "actor_type": ("z" * 16, "z" * 17),
        "decision": ("w" * 16, "w" * 17),
    }
    for param, (ok_value, too_long) in cases.items():
        over = client.get("/api/v1/audit-events", params={param: too_long}, headers=AUDITOR_A)
        assert over.status_code == 422, f"{param} 超长必须 422"
        boundary = _get(client, AUDITOR_A, **{param: ok_value})
        assert boundary.json() == []


def test_injection_like_values_treated_as_plain_data(client):
    """含引号、SQL 片段或 HTML 的值只作为查询数据：不执行、不扩大结果。"""
    weird = "req' OR '1'='1' -- <script>alert(1)</script>"
    match = _seed("tnt-A", request_id=weird)

    # 原值精确可查。
    exact = _get(client, AUDITOR_A, request_id=weird, include_total="true")
    assert _ids(exact) == {match.id}
    assert exact.headers.get(HDR_TOTAL) == "1"

    # 截断片段（含引号 / SQL 关键字 / HTML 标签）不得扩大结果。
    for fragment in ("req' OR '1'='1", "'1'='1' -- ", "<script>alert(1)</script>", "%", "req"):
        resp = _get(client, AUDITOR_A, request_id=fragment, include_total="true")
        assert resp.json() == [], f"片段 {fragment!r} 不得匹配"
        assert resp.headers.get(HDR_TOTAL) == "0"


def test_legacy_cursor_usage_compatible(client):
    """不使用新参数的既有 cursor 翻页用法保持兼容。"""
    action = _uq("legacy-cursor")
    expected = set()
    base = utcnow() - timedelta(minutes=5)
    for i in range(3):
        expected.add(_seed("tnt-A", action=action, created_at=base + timedelta(seconds=i)).id)

    rows, _ = _collect_pages(client, AUDITOR_A, 2, action=action)
    assert {r["id"] for r in rows} == expected
    assert len(rows) == 3


def _table_counts() -> tuple[int, int, int]:
    with session_scope() as session:
        return (
            int(session.scalar(select(func.count()).select_from(AuditEvent)) or 0),
            int(session.scalar(select(func.count()).select_from(OutboxEvent)) or 0),
            int(session.scalar(select(func.count()).select_from(AgentAsset)) or 0),
        )


def test_repeated_gets_do_not_mutate_state(client):
    """多次 GET（含过滤/总数/翻页/422）不产生审计、outbox 或业务对象写入。"""
    request_id = _uq("readonly")
    event = _seed("tnt-A", request_id=request_id, decision="deny", actor_type="edge")

    before = _table_counts()
    _get(client, AUDITOR_A, request_id=request_id)
    _get(client, AUDITOR_A, request_id=request_id, include_total="true")
    _get(client, AUDITOR_A, request_id=request_id, actor_type="edge", decision="deny", limit="1")
    client.get("/api/v1/audit-events", params={"request_id": ""}, headers=AUDITOR_A)
    after = _table_counts()
    assert before == after

    with session_scope() as session:
        row = session.get(AuditEvent, event.id)
        assert row is not None
        assert row.request_id == request_id
        assert row.decision == "deny"
        assert row.actor_type == "edge"
        assert row.summary == {"suite": MARKER}
