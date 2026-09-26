"""Focused negative boundaries for change-execution correlation and evidence projection.

Reproduces only the gaps not covered by test_change_execution.py: reserved-vs-real
verification levels, malformed attestations, per-permission gating, deterministic
window ordering and read-only GET behaviour.
"""

from datetime import timedelta

from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, Deployment, OutboxEvent, utcnow
from app.tests.test_change_execution import get_execution, seed_deployment
from app.tests.test_change_review import change


def test_reserved_behavior_verified_level_is_not_upgraded(client, tenant_a, env_a):
    """`behavior_verified` 属于 OpenShell 诊断合同且无生产者，不得升级为行为证据。"""
    cr, _ = change(client, tenant_a)
    seed_deployment(cr, env_a["id"], verification={"level": "behavior_verified"})
    row = get_execution(client, tenant_a, cr)["deployments"][0]
    assert row["verification_level"] == "unknown"


def test_present_but_unreadable_attestation_is_unknown_not_absent(client, tenant_a, env_a):
    """非对象 independent_attestation 存在时必须报 unknown，不能冒充“没有记录”。"""
    cr, _ = change(client, tenant_a)
    seed_deployment(
        cr,
        env_a["id"],
        verification={"level": "readback_verified", "independent_attestation": "verified"},
    )
    row = get_execution(client, tenant_a, cr)["deployments"][0]
    assert row["independent_result"] == "unknown"


def test_env_name_and_audit_are_gated_by_independent_permissions(client, tenant_a, env_a):
    """env:read 与 audit:read 各自独立生效，不能用“都缺权限”的身份代替。"""
    cr, _ = change(client, tenant_a)
    seed_deployment(cr, env_a["id"])
    # policy:read + audit:read，无 env:read（auditor）
    audited = get_execution(client, {**tenant_a, "X-Dev-Roles": "auditor"}, cr)
    assert audited["audit_access"] == "allowed" and audited["audit_events"]
    assert audited["deployments"][0]["environment_name"] is None
    # policy:read + env:read，无 audit:read（security_admin）
    env_only = get_execution(client, {**tenant_a, "X-Dev-Roles": "security_admin"}, cr)
    assert env_only["deployments"][0]["environment_name"] == env_a["name"]
    assert env_only["audit_access"] == "denied"
    assert env_only["audit_events"] == [] and env_only["audit_truncated"] is False


def test_denied_audit_does_not_leak_count_or_truncation(client, tenant_a, env_a):
    """缺 audit:read 时，即便存在大量精确关联审计，也不得借正文、计数或截断标志披露。"""
    cr, _ = change(client, tenant_a)
    ids = [seed_deployment(cr, env_a["id"]) for _ in range(3)]
    with session_scope() as s:
        for _ in range(60):
            s.add(
                AuditEvent(
                    tenant_id="tnt-A",
                    actor_type="user",
                    actor_id="fixture-leak",
                    action="deployment.verify",
                    resource_type="deployment",
                    resource_id=ids[0],
                    decision="allow",
                )
            )
        s.commit()
    viewer = {**tenant_a, "X-Dev-Roles": "viewer"}
    for suffix in ("", "?expanded=true"):
        result = get_execution(client, viewer, cr, suffix)
        assert result["audit_access"] == "denied"
        assert result["audit_events"] == [] and result["audit_truncated"] is False


def test_audit_requires_matching_resource_type_object_and_tenant(client, tenant_a, env_a):
    """同租户其他变更、错误 resource_type、其他租户同名标识都不得混入。"""
    cr, _ = change(client, tenant_a)
    other, _ = change(client, tenant_a)
    seed_deployment(cr, env_a["id"])
    with session_scope() as s:
        for tenant, rtype, rid in [
            ("tnt-A", "agent_asset", cr["id"]),
            ("tnt-A", "change_request", other["id"]),
            ("tnt-B", "change_request", cr["id"]),
        ]:
            s.add(
                AuditEvent(
                    tenant_id=tenant,
                    actor_type="user",
                    actor_id="fixture-excluded",
                    action="change.approve",
                    resource_type=rtype,
                    resource_id=rid,
                    decision="allow",
                )
            )
        s.commit()
    result = get_execution(client, {**tenant_a, "X-Dev-Roles": "auditor"}, cr)
    assert all(e["actor_id"] != "fixture-excluded" for e in result["audit_events"])


def test_same_timestamp_window_is_stable_and_bounded(client, tenant_a, env_a):
    """同时间戳按 id 稳定排序；default 20 条截断、expanded 不再声称全量。"""
    cr, _ = change(client, tenant_a)
    stamp = utcnow() - timedelta(days=1)
    ids = sorted(seed_deployment(cr, env_a["id"], created_at=stamp) for _ in range(25))
    page = get_execution(client, tenant_a, cr)
    assert [d["id"] for d in page["deployments"]] == ids[:20]
    assert page["deployments_truncated"] is True
    full = get_execution(client, tenant_a, cr, "?expanded=true")
    assert [d["id"] for d in full["deployments"]] == ids
    assert full["deployments_truncated"] is False


def test_get_execution_writes_no_deployment_audit_or_outbox(client, tenant_a, env_a):
    """GET 不产生部署、审计、outbox 或状态写入。"""
    cr, _ = change(client, tenant_a)
    seed_deployment(cr, env_a["id"])
    with session_scope() as s:
        before = (
            s.scalar(select(func.count()).select_from(Deployment)),
            s.scalar(select(func.count()).select_from(AuditEvent)),
            s.scalar(select(func.count()).select_from(OutboxEvent)),
            s.get(ChangeRequest, cr["id"]).status,
        )
    headers = {**tenant_a, "X-Dev-Roles": "auditor"}
    get_execution(client, headers, cr)
    get_execution(client, headers, cr, "?expanded=true")
    with session_scope() as s:
        after = (
            s.scalar(select(func.count()).select_from(Deployment)),
            s.scalar(select(func.count()).select_from(AuditEvent)),
            s.scalar(select(func.count()).select_from(OutboxEvent)),
            s.get(ChangeRequest, cr["id"]).status,
        )
    assert before == after
