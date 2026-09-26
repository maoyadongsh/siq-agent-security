"""OCSF 导出收口测试（CL-06-OCSF-EXPORT-CLOSEOUT）。

只补 `test_ocsf_export.py` 未覆盖的收口面（映射纯函数、基础 NDJSON、基础租户隔离、403/422、
limit 计数、审计摘要键集已在原文件覆盖，本文件不重复）：

1. 同名标识 + 相同时间戳的跨租户严格隔离（两个 class 各查一次，用集合相等而非"包含"断言）；
2. 拒绝路径（无权限 / 非法 class / 非法 since / limit 越界）在导出前拒绝，且不写导出审计；
3. since 时区换算与包含边界；极端非法日期（时区换算溢出）必须受控 4xx，不得 500 或回显输入；
4. NDJSON 字节级行完整性（含换行/回车/引号/中文/行分隔符）、空结果、顺序与 limit 独立对照；
5. 审计失败 / 提交失败时客户端拿不到 200 内容，且审计与 outbox 无残留；
6. 导出审计摘要只含既有受控元信息，不含导出正文与 canary；
7. 敏感导出的缓存控制（no-store），且不改变媒体类型与业务输出；
8. 导出不改业务状态、不写 outbox；响应不包含本次请求自己刚写的审计行。

每个用例组用自己的独立租户，因此可以用集合相等断言"只看得到自己的行"，且不受其他文件/用例顺序影响。
期望值由本文件独立构造（种子数据 + 独立排序），不复制路由实现。失败注入用例用
`raise_server_exceptions=False` 的客户端观察**真实 HTTP 状态**，不把测试客户端抛出的异常当成验收成功。
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import AuditEvent, Finding, OutboxEvent, Tenant

EXPORT_URL = "/api/v1/export/ocsf"

# 每个用例组一个独立租户（与其他测试文件、以及本文件其他用例互相隔离）
CLO_ISO_A, CLO_ISO_B = "tnt-ocsf-clo-iso-a", "tnt-ocsf-clo-iso-b"
CLO_REJ, CLO_SINCE, CLO_EXTREME = "tnt-ocsf-clo-rej", "tnt-ocsf-clo-since", "tnt-ocsf-clo-extreme"
CLO_TEXT, CLO_EMPTY, CLO_ORDER = "tnt-ocsf-clo-text", "tnt-ocsf-clo-empty", "tnt-ocsf-clo-order"
CLO_FAIL, CLO_SUM, CLO_CACHE = "tnt-ocsf-clo-fail", "tnt-ocsf-clo-sum", "tnt-ocsf-clo-cache"
CLO_RO, CLO_SELF = "tnt-ocsf-clo-ro", "tnt-ocsf-clo-self"

T0 = datetime(2024, 6, 1, 11, 59, 59)  # 边界前 1 秒（naive UTC）
T1 = datetime(2024, 6, 1, 12, 0, 0)
T2 = datetime(2024, 6, 1, 12, 0, 0)  # 与 T1 同值：用于时间并列时的稳定排序
T3 = datetime(2024, 6, 1, 12, 0, 1)

# 合成 canary（不是真实秘密）：只用来断言它不出现在导出审计摘要里
CANARY = "CANARY-OCSF-CLO-9f2c"


def _auditor(tenant_id: str, user: str) -> dict:
    return {"X-Dev-Tenant-Id": tenant_id, "X-Dev-User-Id": user, "X-Dev-Roles": "auditor"}


HEAD_ISO_A = _auditor(CLO_ISO_A, "auditor-iso-a")
HEAD_ISO_B = _auditor(CLO_ISO_B, "auditor-iso-b")
HEAD_REJ = _auditor(CLO_REJ, "auditor-rej")
HEAD_SINCE = _auditor(CLO_SINCE, "auditor-since")
HEAD_EXTREME = _auditor(CLO_EXTREME, "auditor-extreme")
HEAD_TEXT = _auditor(CLO_TEXT, "auditor-text")
HEAD_EMPTY = _auditor(CLO_EMPTY, "auditor-empty")
HEAD_ORDER = _auditor(CLO_ORDER, "auditor-order")
HEAD_FAIL = _auditor(CLO_FAIL, "auditor-fail")
HEAD_SUM = _auditor(CLO_SUM, "auditor-sum")
HEAD_CACHE = _auditor(CLO_CACHE, "auditor-cache")
HEAD_RO = _auditor(CLO_RO, "auditor-ro")
HEAD_SELF = _auditor(CLO_SELF, "auditor-self")
# 同租户、无 audit:read 角色（与 test_ocsf_export.py 的 403 用例同构，租户独立）
HEAD_REJ_NO_PERM = {"X-Dev-Tenant-Id": CLO_REJ, "X-Dev-User-Id": "owner-rej", "X-Dev-Roles": "agent_owner"}


@pytest.fixture(scope="module")
def status_client():
    """观察真实 HTTP 状态的客户端（服务器异常呈现为 5xx，而不是抛回测试）。

    与 conftest 的 session 级 `client` 指向同一个 app 实例与同一个 SQLite 文件；
    lifespan 可重复进入（dev 模式 create_all 幂等，且仅空表才写 dev-tenant 种子）。
    """
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ------------------------------------------------------------------ 独立夹具


def _ensure_tenant(tenant_id: str) -> None:
    with session_scope() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))


def _seed_finding(tenant_id: str, rule_id: str, when: datetime, **overrides) -> str:
    _ensure_tenant(tenant_id)
    params = {
        "tenant_id": tenant_id,
        "rule_id": rule_id,
        "rule_version": 1,
        "severity": "medium",
        "status": "open",
        "first_seen_at": when,
        "last_seen_at": when,
    }
    params.update(overrides)
    with session_scope() as session:
        finding = Finding(**params)
        session.add(finding)
        session.commit()
        return finding.id


def _seed_audit(tenant_id: str, action: str, when: datetime, **overrides) -> str:
    _ensure_tenant(tenant_id)
    params = {
        "tenant_id": tenant_id,
        "actor_type": "user",
        "actor_id": "seeder",
        "action": action,
        "resource_type": "finding",
        "resource_id": "fnd_clo_seed",
        "decision": "allow",
        "summary": {"seed": action},
        "created_at": when,
    }
    params.update(overrides)
    with session_scope() as session:
        event = AuditEvent(**params)
        session.add(event)
        session.commit()
        return event.id


def _lines(resp) -> list[dict]:
    """NDJSON 的线级合同是"以 \\n 分隔的 JSON 文本"：按字节切分，逐行独立解析。"""
    assert resp.headers["content-type"].startswith("application/x-ndjson"), resp.headers
    return [json.loads(raw) for raw in resp.content.split(b"\n") if raw.strip()]


def _finding_uids(resp) -> set[str]:
    return {e["finding_info"]["uid"] for e in _lines(resp)}


def _export_audits(tenant_id: str) -> list[AuditEvent]:
    """该租户的导出审计（按主键排序，便于稳定比对新增项）。"""
    with session_scope() as session:
        return list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == tenant_id, AuditEvent.action == "export.ocsf")
                .order_by(AuditEvent.id)
            )
        )


def _new_export_audits(tenant_id: str, known_ids: set[str]) -> list[AuditEvent]:
    return [row for row in _export_audits(tenant_id) if row.id not in known_ids]


def _outbox_count() -> int:
    with session_scope() as session:
        return len(list(session.scalars(select(OutboxEvent))))


def _finding_count(tenant_id: str) -> int:
    with session_scope() as session:
        return len(list(session.scalars(select(Finding.id).where(Finding.tenant_id == tenant_id))))


# ------------------------------------------------------- 1. 跨租户严格隔离


def test_interleaved_tenants_with_identical_identifier_and_timestamp(client):
    """两个租户用同名标识、同时间戳导出，彼此看不到对方的行（集合相等，而非"包含"）。"""
    a1 = _seed_finding(CLO_ISO_A, "clo-same-rule", T1)
    a2 = _seed_finding(CLO_ISO_A, "clo-same-rule", T2)
    b1 = _seed_finding(CLO_ISO_B, "clo-same-rule", T1)
    a_audit = _seed_audit(CLO_ISO_A, "clo.same.action", T1, resource_id="fnd_clo_iso_a")
    b_audit = _seed_audit(CLO_ISO_B, "clo.same.action", T2, resource_id="fnd_clo_iso_b")

    resp_a = client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_ISO_A)
    resp_b = client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_ISO_B)
    assert resp_a.status_code == 200 and resp_b.status_code == 200
    assert _finding_uids(resp_a) == {a1, a2}
    assert _finding_uids(resp_b) == {b1}
    # 同名标识在两租户都存在，导出内容仍只来自请求方租户
    assert all(e["finding_info"]["title"] == "clo-same-rule" for e in _lines(resp_a))

    audit_a = client.get(f"{EXPORT_URL}?class=api_activity", headers=HEAD_ISO_A)
    audit_b = client.get(f"{EXPORT_URL}?class=api_activity", headers=HEAD_ISO_B)
    uids_a = {e["resources"][0]["uid"] for e in _lines(audit_a) if e["activity_name"] == "clo.same.action"}
    uids_b = {e["resources"][0]["uid"] for e in _lines(audit_b) if e["activity_name"] == "clo.same.action"}
    assert a_audit and b_audit  # 两条同名审计都已落库，只是看不到对方
    assert uids_a == {"fnd_clo_iso_a"}
    assert uids_b == {"fnd_clo_iso_b"}


# ------------------------------------------------- 2. 拒绝路径不写导出审计


@pytest.mark.parametrize(
    ("label", "query", "headers", "expected_status"),
    [
        ("invalid_class", "?class=nope", "HEAD_REJ", 422),
        ("missing_class", "", "HEAD_REJ", 422),
        ("invalid_since", "?class=detection_finding&since=not-a-date", "HEAD_REJ", 422),
        ("limit_above_max", "?class=detection_finding&limit=2001", "HEAD_REJ", 422),
        ("limit_below_min", "?class=detection_finding&limit=0", "HEAD_REJ", 422),
        ("no_permission", "?class=detection_finding", "HEAD_REJ_NO_PERM", 403),
    ],
)
def test_rejected_request_is_refused_without_export_audit(client, label, query, headers, expected_status):
    headers = {"HEAD_REJ": HEAD_REJ, "HEAD_REJ_NO_PERM": HEAD_REJ_NO_PERM}[headers]
    _seed_finding(CLO_REJ, f"clo-reject-{label}", T1)
    before = {row.id for row in _export_audits(CLO_REJ)}

    resp = client.get(f"{EXPORT_URL}{query}", headers=headers)

    assert resp.status_code == expected_status, (label, resp.status_code, resp.text)
    assert b'"class_uid"' not in resp.content  # 拒绝时不得返回任何导出内容
    assert _new_export_audits(CLO_REJ, before) == []  # 拒绝不产生"成功导出"审计


# --------------------------------------------- 3. since 时区与极端非法日期


def test_since_offset_conversion_and_inclusive_boundary(client):
    """偏移时间换算成 UTC 后按既有包含边界（>=）过滤：等于边界包含，晚 1µs 排除。"""
    early = _seed_finding(CLO_SINCE, "clo-since-early", T0)
    edge = _seed_finding(CLO_SINCE, "clo-since-edge", T1)

    def uids(since: str) -> set[str]:
        resp = client.get(f"{EXPORT_URL}?class=detection_finding&since={since}", headers=HEAD_SINCE)
        assert resp.status_code == 200, resp.text
        return _finding_uids(resp)

    # 14:00+02:00 与 15:00+03:00 都是 12:00Z：等于边界 → 包含（URL 中 + 必须百分号编码）
    assert uids("2024-06-01T14:00:00%2B02:00") == {edge}
    assert uids("2024-06-01T15:00:00%2B03:00") == {edge}
    # 边界后 1µs → 排除
    assert uids("2024-06-01T12:00:00.000001Z") == set()
    # 朴素日期（无时区）按既有语义当 UTC 零点
    assert uids("2024-06-01T00:00:00") == {early, edge}


@pytest.mark.parametrize(
    "raw_since",
    [
        "9999-12-31T23:59:59-14:00",  # 换算到 UTC 越过 datetime 上限
        "0001-01-01T00:00:00%2B14:00",  # 百分号编码的 +14:00，换算越过下限
    ],
)
def test_extreme_since_is_controlled_rejection(status_client, raw_since):
    """极端非法日期必须受控 4xx：不得 500、不得回显输入、不得泄漏内部路径或异常名。"""
    _seed_finding(CLO_EXTREME, "clo-extreme", T1)
    before = {row.id for row in _export_audits(CLO_EXTREME)}

    resp = status_client.get(
        f"{EXPORT_URL}?class=detection_finding&since={raw_since}", headers=HEAD_EXTREME
    )

    assert resp.status_code == 422, (raw_since, resp.status_code, resp.text[:200])
    assert json.loads(resp.text) == {"detail": "invalid_since"}
    assert raw_since.replace("%2B", "+") not in resp.text
    for leak in ("Traceback", "site-packages", "OverflowError", "/home/"):
        assert leak not in resp.text
    assert _new_export_audits(CLO_EXTREME, before) == []


# ------------------------------------------------------- 4. NDJSON 行完整性


def test_ndjson_lines_are_independently_parseable_with_hostile_text(client):
    """正文含换行/回车/引号/中文/行分隔符时，每行仍是独立可解析的 JSON。"""
    hostile_impact = '第一名\n第二行\r\n引号"结尾" 空格   行分隔符'
    fid = _seed_finding(CLO_TEXT, "clo-hostile", T1, impact=hostile_impact, remediation="a\rb")

    resp = client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_TEXT)
    assert resp.status_code == 200

    raw_lines = [raw for raw in resp.content.split(b"\n") if raw.strip()]
    parsed = [json.loads(raw) for raw in raw_lines]  # 每一行都能独立解析
    assert len(parsed) == len(raw_lines)
    # \n / \r 被 JSON 转义，不额外断行；U+2028 保持字面量，不参与字节级分行（见交付文档边界说明）
    assert len(raw_lines) == 1
    mine = [e for e in parsed if e["finding_info"]["uid"] == fid]
    assert len(mine) == 1
    assert mine[0]["impact"] == hostile_impact  # 往返一致，未做二次加工
    assert mine[0]["remediation"] == {"desc": "a\rb"}


def test_empty_export_is_empty_body_and_still_audited(client):
    _ensure_tenant(CLO_EMPTY)
    before = {row.id for row in _export_audits(CLO_EMPTY)}

    resp = client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_EMPTY)

    assert resp.status_code == 200
    assert resp.content == b""
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    new = _new_export_audits(CLO_EMPTY, before)
    assert len(new) == 1
    assert new[0].summary["count"] == 0


def test_limit_applies_after_time_then_id_ordering(client):
    """顺序 = (时间升序, id 升序)；limit 取该顺序的前 N 条（期望值由本文件独立排序得出）。"""
    pairs = [
        (T1, _seed_finding(CLO_ORDER, "clo-order-1", T1)),
        (T2, _seed_finding(CLO_ORDER, "clo-order-2", T2)),
        (T3, _seed_finding(CLO_ORDER, "clo-order-3", T3)),
    ]
    expected = [fid for _, fid in sorted(pairs)]

    full = client.get(f"{EXPORT_URL}?class=detection_finding&limit=3", headers=HEAD_ORDER)
    assert [e["finding_info"]["uid"] for e in _lines(full)] == expected

    limited = client.get(f"{EXPORT_URL}?class=detection_finding&limit=2", headers=HEAD_ORDER)
    assert [e["finding_info"]["uid"] for e in _lines(limited)] == expected[:2]


# --------------------------------------------- 5. 失败关闭：审计 / 提交失败


def test_audit_failure_delivers_no_content_and_persists_nothing(status_client, monkeypatch):
    """审计写入失败 → 5xx、无导出内容、无审计/outbox 残留（fail-closed）。"""
    import app.routers.export as export_module

    _seed_finding(CLO_FAIL, "clo-audit-fail", T1, impact=CANARY)
    before_audits = {row.id for row in _export_audits(CLO_FAIL)}
    before_outbox = _outbox_count()

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(export_module, "audit", boom)
    try:
        resp = status_client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_FAIL)
    finally:
        monkeypatch.undo()

    assert resp.status_code >= 500, (resp.status_code, resp.text[:200])
    assert CANARY not in resp.text
    assert b'"class_uid"' not in resp.content
    assert _new_export_audits(CLO_FAIL, before_audits) == []
    assert _outbox_count() == before_outbox


def test_commit_failure_delivers_no_content_and_persists_no_audit(status_client, monkeypatch):
    """审计已 flush 后提交前失败 → 5xx、无导出内容，且请求关闭后回滚。"""
    _seed_finding(CLO_FAIL, "clo-commit-fail", T1, impact=CANARY)
    before_audits = {row.id for row in _export_audits(CLO_FAIL)}
    before_outbox = _outbox_count()
    flushed_audit_ids = []

    def bad_commit(self, *args, **kwargs):
        self.flush()
        flushed_audit_ids.extend(
            self.scalars(select(AuditEvent.id).where(
                AuditEvent.tenant_id == CLO_FAIL,
                AuditEvent.action == "export.ocsf",
            ))
        )
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(Session, "commit", bad_commit)
    try:
        resp = status_client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_FAIL)
    finally:
        monkeypatch.undo()

    assert resp.status_code >= 500, (resp.status_code, resp.text[:200])
    assert len(set(flushed_audit_ids) - before_audits) == 1
    assert CANARY not in resp.text
    assert b'"class_uid"' not in resp.content
    assert _new_export_audits(CLO_FAIL, before_audits) == []
    assert _outbox_count() == before_outbox


# ------------------------------------------------------- 6. 审计摘要受控


def test_export_audit_summary_keeps_only_controlled_metadata(client):
    """导出审计摘要仍是 {class,count,since}，不含导出正文 / canary / 跨租户内容。"""
    _seed_finding(CLO_SUM, f"clo-canary-{CANARY}", T1, impact=CANARY, remediation=CANARY)
    _seed_audit(CLO_SUM, "clo.canary.action", T1, summary={"leak": CANARY})
    before = {row.id for row in _export_audits(CLO_SUM)}

    resp = client.get(
        f"{EXPORT_URL}?class=api_activity&since=2024-06-01T00:00:00Z&limit=2000", headers=HEAD_SUM
    )

    assert resp.status_code == 200
    assert CANARY in resp.text  # 导出正文按设计包含已入库的脱敏摘要；本断言只用于与审计摘要对照
    new = _new_export_audits(CLO_SUM, before)
    assert len(new) == 1
    summary = new[0].summary
    assert set(summary) == {"class", "count", "since"}
    assert CANARY not in json.dumps(summary, ensure_ascii=False)
    assert summary["class"] == "api_activity"
    assert isinstance(summary["count"], int) and 0 <= summary["count"] <= 2000
    assert summary["since"] == "2024-06-01T00:00:00Z"


# --------------------------------------------- 7. 缓存控制与媒体类型


def test_sensitive_export_is_not_cacheable_and_media_type_unchanged(client):
    _seed_finding(CLO_CACHE, "clo-cache", T1)
    resp = client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_CACHE)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    assert _lines(resp)  # 正文仍按原合同输出


# --------------------------------------------- 8. 只读性与响应自排除


def test_export_does_not_change_business_state_or_write_outbox(client):
    fid = _seed_finding(CLO_RO, "clo-readonly", T1, impact="unchanged", severity="high")
    with session_scope() as session:
        row = session.get(Finding, fid)
        before = (row.status, row.severity, row.first_seen_at, row.last_seen_at, row.impact, row.owner_user_id)
    before_findings = _finding_count(CLO_RO)
    before_outbox = _outbox_count()
    before_audits = {row.id for row in _export_audits(CLO_RO)}

    for _ in range(2):
        resp = client.get(f"{EXPORT_URL}?class=detection_finding", headers=HEAD_RO)
        assert resp.status_code == 200

    with session_scope() as session:
        row = session.get(Finding, fid)
        after = (row.status, row.severity, row.first_seen_at, row.last_seen_at, row.impact, row.owner_user_id)
    assert after == before  # 含 last_seen_at：导出不碰业务状态
    assert _finding_count(CLO_RO) == before_findings
    assert _outbox_count() == before_outbox
    assert len(_new_export_audits(CLO_RO, before_audits)) == 2


def test_export_response_excludes_its_own_audit_row(client):
    """本次导出自己写的审计在查询之后追加：不出现在本次响应里（读在前、写在后）。"""
    _seed_audit(CLO_SELF, "clo.self.action", T1)
    before = len(_export_audits(CLO_SELF))

    resp = client.get(f"{EXPORT_URL}?class=api_activity", headers=HEAD_SELF)

    assert resp.status_code == 200
    events = _lines(resp)
    assert any(e["activity_name"] == "clo.self.action" for e in events)
    assert sum(1 for e in events if e["activity_name"] == "export.ocsf") == before
