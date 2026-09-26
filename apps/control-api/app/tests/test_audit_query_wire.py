"""ENT-019-AUDIT-WIRE：审计精确查询的真实 HTTP 响应样本导出（合成数据）。

通过隔离 TestClient + 测试 SQLite 实际执行 GET /api/v1/audit-events，
原样记录 status / body / 列表元数据响应头 / 查询参数，供前端现有客户端
（getListPage + parseListMeta）做消费者契约验证（dev/audit-query-wire.check.ts）。

边界：
- 全部记录为带唯一前缀的合成数据，样本来源标记 isolated-testclient-synthetic-data；
- 预期记录 ID 来自夹具构造，不从实际响应反推“预期答案”；
- 不导出身份头、Cookie、环境变量或任何真实身份/配置；
- 未设置 SIQ_AUDIT_QUERY_WIRE_OUTPUT 时普通 pytest 正常运行（只断言不写盘）；
  显式指定输出时独占创建（'x'），写入失败令测试失败，不静默跳过；
- 查询前后对审计 / outbox / 业务对象做行数与字段快照比较，不只凭“使用 GET”推断只读。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.db import session_scope
from app.list_meta import HDR_LIMIT, HDR_NEXT_CURSOR, HDR_RETURNED, HDR_TOTAL, HDR_TRUNCATED
from app.models import AgentAsset, AuditEvent, OutboxEvent, new_id, utcnow

MARKER = "ent019-wire"
ENDPOINT = "/api/v1/audit-events"

# 仅 dev 模式生效的合成测试身份（不导出到样本）。
AUDITOR_A = {
    "X-Dev-Tenant-Id": "tnt-A",
    "X-Dev-User-Id": "auditor-wire-a",
    "X-Dev-Roles": "auditor",
}
AUDITOR_B = {
    "X-Dev-Tenant-Id": "tnt-B",
    "X-Dev-User-Id": "auditor-wire-b",
    "X-Dev-Roles": "auditor",
}
# viewer 角色权限为 agent:read/policy:read，不含 audit:read。
VIEWER_A = {
    "X-Dev-Tenant-Id": "tnt-A",
    "X-Dev-User-Id": "viewer-wire-a",
    "X-Dev-Roles": "viewer",
}

LIST_HEADER_NAMES = (HDR_LIMIT, HDR_RETURNED, HDR_TRUNCATED, HDR_NEXT_CURSOR, HDR_TOTAL)

# 含空格、&、+、引号与中文的合法过滤值前缀；每次收集追加唯一标记并以空格结尾
# （唯一性避免同文件两次收集互相命中；尾随空格用于证明服务端不 trim）。
SPECIAL_PREFIX = "Req 加 & \"X\" + 'Y'"

OVERLONG = {
    "request_id": "x" * 65,
    "resource_id": "y" * 65,
    "actor_type": "z" * 17,
    "decision": "w" * 17,
}


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
            action=overrides.pop("action", f"audit.wire.{MARKER}"),
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


def _table_counts() -> tuple[int, int, int]:
    with session_scope() as session:
        return (
            int(session.scalar(select(func.count()).select_from(AuditEvent)) or 0),
            int(session.scalar(select(func.count()).select_from(OutboxEvent)) or 0),
            int(session.scalar(select(func.count()).select_from(AgentAsset)) or 0),
        )


def _capture(resp) -> dict:
    """原样记录状态码、JSON body 与列表元数据响应头；不记录请求身份头。"""
    headers = {"content-type": resp.headers.get("content-type", "")}
    for name in LIST_HEADER_NAMES:
        value = resp.headers.get(name)
        if value is not None:
            headers[name.lower()] = value
    return {"status": resp.status_code, "headers": headers, "body": resp.json()}


def _collect_wire_sample(client) -> dict:
    """构造夹具、执行全部场景 GET、断言后端行为并返回可导出样本（不写盘）。"""
    seeded: list[AuditEvent] = []

    # ---- 场景 A：新旧过滤条件 AND 组合 ----
    and_query = {
        "request_id": _uq("and-req"),
        "resource_id": _uq("and-res"),
        "actor_id": _uq("and-actor"),
        "actor_type": "edge",
        "action": "audit.wire.and",
        "resource_type": "change_request",
        "decision": "deny",
    }
    and_match = _seed("tnt-A", **and_query)
    seeded.append(and_match)
    # 每条诱饵恰好破坏一个条件，证明 AND 语义而非“任一命中”。
    for breaker in (
        {"request_id": _uq("and-req-x")},
        {"resource_id": _uq("and-res-x")},
        {"actor_id": _uq("and-actor-x")},
        {"actor_type": "user"},
        {"action": "audit.wire.other"},
        {"resource_type": "policy"},
        {"decision": "allow"},
    ):
        seeded.append(_seed("tnt-A", **{**and_query, **breaker}))

    # ---- 场景 B/C：相同时间戳 7 条记录，limit=2 共 4 页，每页 include_total=true ----
    paged_request_id = _uq("paged")
    same_ts = utcnow()
    paged_events = [
        _seed("tnt-A", request_id=paged_request_id, created_at=same_ts) for _ in range(7)
    ]
    seeded.extend(paged_events)
    # 排序合同：(created_at desc, id asc)；同时间戳即 id 升序，预期来自夹具 ID 排序。
    paged_expected_ids = sorted(e.id for e in paged_events)

    # ---- 场景 E：两租户同名 request_id/resource_id ----
    shared_request_id = _uq("shared-req")
    shared_resource_id = _uq("shared-res")
    shared_a = _seed("tnt-A", request_id=shared_request_id, resource_id=shared_resource_id)
    shared_b = _seed("tnt-B", request_id=shared_request_id, resource_id=shared_resource_id)
    seeded.extend([shared_a, shared_b])

    # ---- 场景 I：合法长度的未知 actor_type/decision（actor_id 限定本次收集） ----
    unknown_query = {"actor_type": "automaton-x", "decision": "quarantine", "actor_id": _uq("unknown")}
    unknown_match = _seed("tnt-A", **unknown_query)
    seeded.append(unknown_match)

    # ---- 场景 J：特殊字符原值（唯一标记 + 尾随空格证明不 trim） ----
    special_value = f"{SPECIAL_PREFIX} {_uq('special')} "
    special_match = _seed("tnt-A", request_id=special_value)
    seeded.append(special_match)

    # 夹具初始化完成后的只读基线。
    counts_before = _table_counts()

    def get(headers, **params):
        return client.get(ENDPOINT, params=params, headers=headers)

    scenarios: dict[str, dict] = {}

    # A：七条件同时满足（新 4 + 旧 3）。
    resp = get(AUDITOR_A, **and_query, include_total="true")
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in resp.json()] == [and_match.id]
    assert resp.headers.get(HDR_TOTAL) == "1"
    scenarios["and_combo"] = {
        "query": and_query,
        "expected_ids": [and_match.id],
        "response": _capture(resp),
    }

    # B/C：逐页收集，断言顺序、无重复、无遗漏、总数不随翻页递减。
    paged_pages = []
    collected: list[str] = []
    totals: list[str] = []
    returned: list[str] = []
    cursor = None
    for _ in range(10):  # 防御性上限，死循环即失败
        params = {"request_id": paged_request_id, "limit": "2", "include_total": "true"}
        if cursor:
            params["cursor"] = cursor
        resp = get(AUDITOR_A, **params)
        assert resp.status_code == 200, resp.text
        page_ids = [r["id"] for r in resp.json()]
        collected.extend(page_ids)
        totals.append(resp.headers.get(HDR_TOTAL) or "")
        returned.append(resp.headers.get(HDR_RETURNED) or "")
        paged_pages.append(_capture(resp))
        if resp.headers.get(HDR_TRUNCATED) != "1":
            break
        cursor = resp.headers.get(HDR_NEXT_CURSOR)
        assert cursor, "truncated=1 时必须给出 next cursor"
    assert len(paged_pages) == 4, f"7 条 / limit 2 应为 4 页，实际 {len(paged_pages)}"
    assert collected == paged_expected_ids, "合并顺序必须等于 (created_at desc, id asc)"
    assert len(set(collected)) == len(collected), "多页结果不得重复"
    assert totals == ["7", "7", "7", "7"], "总数不随翻页递减"
    assert returned == ["2", "2", "2", "1"]
    scenarios["paged"] = {
        "query": {"request_id": paged_request_id},
        "limit": 2,
        "total": 7,
        "expected_ids": paged_expected_ids,
        "pages": paged_pages,
    }

    # D：无匹配 → 空数组 + total=0（总数 0 是明确值，不是缺失）。
    no_match_request_id = _uq("no-match")
    resp = get(AUDITOR_A, request_id=no_match_request_id, include_total="true")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
    assert resp.headers.get(HDR_TOTAL) == "0"
    scenarios["no_match"] = {
        "query": {"request_id": no_match_request_id},
        "expected_ids": [],
        "response": _capture(resp),
    }

    # E：同名标识各自只命中本租户记录，总数各自为 1。
    shared_query = {"request_id": shared_request_id, "resource_id": shared_resource_id}
    resp_a = get(AUDITOR_A, **shared_query, include_total="true")
    assert resp_a.status_code == 200, resp_a.text
    assert [r["id"] for r in resp_a.json()] == [shared_a.id]
    assert resp_a.headers.get(HDR_TOTAL) == "1"
    scenarios["tenant_a_shared"] = {
        "query": shared_query,
        "expected_ids": [shared_a.id],
        "response": _capture(resp_a),
    }
    resp_b = get(AUDITOR_B, **shared_query, include_total="true")
    assert resp_b.status_code == 200, resp_b.text
    assert [r["id"] for r in resp_b.json()] == [shared_b.id]
    assert resp_b.headers.get(HDR_TOTAL) == "1"
    scenarios["tenant_b_shared"] = {
        "query": shared_query,
        "expected_ids": [shared_b.id],
        "response": _capture(resp_b),
    }

    # F：缺少 audit:read → 403（带不带过滤参数都拒绝）。
    forbidden = client.get(ENDPOINT, params={"request_id": shared_request_id}, headers=VIEWER_A)
    assert forbidden.status_code == 403, forbidden.text
    scenarios["forbidden"] = {
        "query": {"request_id": shared_request_id},
        "response": _capture(forbidden),
    }

    # G：新参数空字符串 → 422（四个参数逐一断言并导出）。
    for param in ("request_id", "resource_id", "actor_type", "decision"):
        resp = client.get(ENDPOINT, params={param: ""}, headers=AUDITOR_A)
        assert resp.status_code == 422, f"{param} 空字符串必须 422"
        scenarios[f"empty_{param}"] = {"query": {param: ""}, "response": _capture(resp)}

    # H：新参数超长 → 422（恰为上限时正常精确查询，由既有合同测试覆盖边界 200）。
    for param, value in OVERLONG.items():
        resp = client.get(ENDPOINT, params={param: value}, headers=AUDITOR_A)
        assert resp.status_code == 422, f"{param} 超长必须 422"
        scenarios[f"overlong_{param}"] = {"query": {param: value}, "response": _capture(resp)}

    # I：未知原值精确可查，响应原样返回未知值（不改写为已知枚举）。
    resp = get(AUDITOR_A, **unknown_query, include_total="true")
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in resp.json()] == [unknown_match.id]
    row = resp.json()[0]
    assert row["actor_type"] == "automaton-x" and row["decision"] == "quarantine"
    scenarios["unknown_values"] = {
        "query": unknown_query,
        "expected_ids": [unknown_match.id],
        "response": _capture(resp),
    }

    # J：特殊字符原值匹配；去掉尾随空格/改变大小写的变体不得命中。
    resp = get(AUDITOR_A, request_id=special_value, include_total="true")
    assert resp.status_code == 200, resp.text
    assert [r["id"] for r in resp.json()] == [special_match.id]
    assert resp.headers.get(HDR_TOTAL) == "1"
    assert resp.json()[0]["request_id"] == special_value, "响应值必须逐字等于查询原值"
    variant = get(AUDITOR_A, request_id=special_value.strip().lower())
    assert variant.status_code == 200, variant.text
    assert special_match.id not in {r["id"] for r in variant.json()}, "不得 trim 或改变大小写"
    scenarios["special_chars"] = {
        "query": {"request_id": special_value},
        "expected_ids": [special_match.id],
        "response": _capture(resp),
    }

    # 只读断言：全部场景 GET（含 403/422）之后行数不变，关键记录字段未被修改。
    assert _table_counts() == counts_before
    with session_scope() as session:
        for event in (and_match, special_match, paged_events[0]):
            row = session.get(AuditEvent, event.id)
            assert row is not None
            assert row.request_id == event.request_id
            assert row.decision == event.decision
            assert row.actor_type == event.actor_type
            assert row.summary == {"suite": MARKER}

    return {
        "scope": "isolated-testclient-synthetic-data",
        "producer": "apps/control-api/app/tests/test_audit_query_wire.py",
        "endpoint": ENDPOINT,
        "scenarios": scenarios,
    }


def test_audit_query_wire_scenarios(client):
    """不导出文件：全部场景断言在普通 pytest 运行中同样执行。"""
    sample = _collect_wire_sample(client)
    assert sample["scope"] == "isolated-testclient-synthetic-data"
    assert len(sample["scenarios"]["paged"]["pages"]) == 4


def test_export_audit_query_wire_sample(client, tmp_path):
    """显式指定 SIQ_AUDIT_QUERY_WIRE_OUTPUT 时独占创建导出；写入失败即测试失败。"""
    sample = _collect_wire_sample(client)
    output = Path(
        os.environ.get("SIQ_AUDIT_QUERY_WIRE_OUTPUT", str(tmp_path / "audit-query-wire.json"))
    )
    with output.open("x") as stream:
        json.dump(sample, stream, ensure_ascii=False, indent=2)
    assert json.loads(output.read_text(encoding="utf-8")) == sample
