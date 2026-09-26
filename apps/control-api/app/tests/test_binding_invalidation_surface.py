"""失效联动只读投影的最小验证：只读、租户/身份隔离、不把"扫不到"说成"没有"、不产出吊销动作。

本模块不是 HTTP 接口，故直接以验证身份构造 `Identity` 调用。绑定与设备走真实登记端点；
批量草稿为库内合成行——它们只是被读取的既有记录，其**来源**与投影结论无关，复用真实批量
创建会引入与本文件无关的变更请求/策略链路。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.binding_invalidation_surface import (
    BLOCKED_IF_REVOKED,
    BLOCKED_NOW,
    DEFAULT_DRAFT_SCAN_LIMIT,
    DEPENDENCY_ABSENT,
    DEPENDENCY_RECORDED,
    NOT_DETERMINABLE,
    NOT_REGISTERED,
    REASON_CODES,
    SCHEMA_VERSION,
    STATES,
    project_binding_invalidation_surface,
)
from app.db import session_scope
from app.models import (
    AuditEvent,
    Deployment,
    DeploymentBatchDraft,
    DeploymentBatchReservation,
    EdgeTask,
    OutboxEvent,
    RuntimeBinding,
    utcnow,
)
from app.tests.test_binding_evidence_readiness import _identity, _seed

COUNTED = (
    RuntimeBinding, Deployment, DeploymentBatchDraft, DeploymentBatchReservation,
    AuditEvent, OutboxEvent, EdgeTask,
)

def _hex64() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


def _actor() -> str:
    """每个用例独占的调用方身份：草稿按身份扫描，避免跨用例相互计入扫描范围。"""
    return "user-" + uuid.uuid4().hex[:12]


def _project(headers: dict, binding_id: str, actor_id: str | None = None, **kwargs) -> dict:
    """默认用租户夹具身份；草稿按身份扫，故每个用例各自指定 actor 以互不影响。"""
    with session_scope() as session:
        identity = _identity(headers)
        if actor_id is not None:
            identity = replace(identity, actor_id=actor_id)
        return project_binding_invalidation_surface(session, identity, binding_id, **kwargs)


def _counts() -> dict:
    with session_scope() as session:
        return {model.__name__: session.scalar(select(func.count()).select_from(model)) for model in COUNTED}


def _preview(*binding_ids: str) -> dict:
    """构造成立的最小批量预览：字段完整、摘要为 64 位十六进制。"""
    return {
        "schema_version": "enterprise-deployment-batch-preview/v1",
        "items": [{
            "schema_version": "deployment-preview/v1",
            "change_id": "cr-" + uuid.uuid4().hex[:12],
            "policy_id": "pol-" + uuid.uuid4().hex[:12],
            "policy_name": "focus",
            "policy_version": 1,
            "enforcement_mode": "block",
            "environment_id": "env-x",
            "environment_name": "host-x",
            "binding_id": binding_id,
            "target": "sandbox-" + uuid.uuid4().hex[:8],
            "backend": "fake",
            "action": "development_task",
            "base_revision": None,
            "preview_digest": _hex64(),
        } for binding_id in binding_ids],
        "preview_digest": _hex64(),
    }


def _draft(
    tenant_id: str,
    *,
    actor_id: str = "user-a",
    actor_type: str = "user",
    minutes_ahead: float,
    items: list,
    expires_at: datetime | None = None,
) -> str:
    draft_id = "bdraft-" + uuid.uuid4().hex[:16]
    expires = expires_at if expires_at is not None else (
        datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=minutes_ahead))
    with session_scope() as session:
        session.add(DeploymentBatchDraft(
            id=draft_id, tenant_id=tenant_id, actor_id=actor_id, actor_type=actor_type,
            request_key=str(uuid.uuid4()), request_digest=_hex64(),
            preview={"schema_version": "enterprise-deployment-batch-preview/v1",
                     "items": items, "preview_digest": _hex64()},
            created_at=utcnow(), expires_at=expires,
        ))
    return draft_id


def _deployment(seed: dict, status: str) -> str:
    deployment_id = "dep-" + uuid.uuid4().hex[:16]
    with session_scope() as session:
        session.add(Deployment(
            id=deployment_id, tenant_id=seed["tenant_id"], environment_id=seed["environment_id"],
            change_request_id="cr-" + uuid.uuid4().hex[:12], target="sandbox-x",
            runtime_binding_id=seed["binding_id"], to_revision="policy-1", status=status,
        ))
    return deployment_id


def _revoke(client, headers: dict, binding_id: str) -> None:
    response = client.post(f"/api/v1/runtime-bindings/{binding_id}/revoke", headers=headers)
    assert response.status_code == 200, response.text


def _envelope(result: dict) -> None:
    """固定结构：三值绑定态、四组联动、有限状态与原因码、原因有序、恒不产出执行结论。"""
    assert result["schema_version"] == SCHEMA_VERSION
    assert result["binding_state"] in (NOT_REGISTERED, "active", "revoked")
    assert set(result["dependents"]) == {
        "executed_deployment_records", "own_live_batch_drafts",
        "other_actor_live_batch_drafts", "runtime_occupancy",
    }
    for group in result["dependents"].values():
        assert set(group) == {"state", "reasons", "references", "must_not_infer"}
        assert group["state"] in STATES
        assert group["reasons"] == sorted(group["reasons"])
        assert set(group["reasons"]) <= REASON_CODES
        assert group["must_not_infer"], "每组必须带有不得推导结论"
    assert result["coverage"] == "recorded_dependencies_only"
    assert result["shared_runtime_occupants"] == "unknown"
    assert result["execution_confirmation_supported"] is False
    assert result["must_not_infer"]


# 一：只读——调用不写任何行，也不产生审计/事件/任务。
def test_projection_is_read_only(client, tenant_a, env_a):
    actor = _actor()
    seed = _seed(client, tenant_a, env_a["id"])
    _draft(seed["tenant_id"], actor_id=actor, minutes_ahead=4,
           items=_preview(seed["binding_id"])["items"])
    before = _counts()
    result = _project(tenant_a, seed["binding_id"], actor_id=actor)
    assert _counts() == before
    _envelope(result)


# 二：跨租户与不存在不可区分，且不回显对方标识。
def test_cross_tenant_and_absent_are_indistinguishable(client, tenant_a, tenant_b, env_a, env_b):
    foreign = _seed(client, _operator_b(tenant_b), env_b["id"])
    foreign_draft = _draft(foreign["tenant_id"], actor_id="user-b",
                           minutes_ahead=4, items=_preview(foreign["binding_id"])["items"])

    probe = _project(tenant_a, foreign["binding_id"])
    absent = _project(tenant_a, "rb-" + uuid.uuid4().hex)
    _envelope(probe)
    assert probe["binding_state"] == NOT_REGISTERED == absent["binding_state"]
    assert probe["dependents"] == absent["dependents"]
    assert probe["dependents"]["executed_deployment_records"]["reasons"] == [
        "binding_not_registered_in_tenant"]
    # 被查的 binding_id 本身由调用方给出，回显不构成泄漏；泄漏点只可能在子事实里。
    dumped = json.dumps(probe["dependents"])
    for leak in (foreign["binding_id"], foreign["asset_id"], foreign["edge_id"],
                 foreign_draft, "tnt-B"):
        assert leak not in dumped


def _operator_b(headers: dict) -> dict:
    """租户 B 需要 policy:manage 才能登记绑定；不改变既有夹具字典（与就绪度测试同一取法）。"""
    return {**headers, "X-Dev-Roles": "security_admin,agent_owner"}


# 三：历史部署记录是记录，不是当前运行状态，也不是"已回滚"。
def test_deployment_records_are_history_not_current_state(client, tenant_a, env_a):
    seed = _seed(client, tenant_a, env_a["id"])
    _deployment(seed, "effective")
    _deployment(seed, "pending")
    result = _project(tenant_a, seed["binding_id"])
    group = result["dependents"]["executed_deployment_records"]
    assert group["state"] == DEPENDENCY_RECORDED
    assert group["references"]["by_status"] == {"effective": 1, "pending": 1}
    assert group["reasons"] == ["deployment_records_are_history_not_current_state"]
    assert "deployment_record_is_not_current_runtime_state" in group["must_not_infer"]
    assert "revocation_is_not_a_deployment_rollback" in group["must_not_infer"]


# 四：本身份存活草稿引用该绑定——吊销前是"若吊销则阻断"，吊销后是"此刻已被阻断"。
def test_own_live_draft_moves_from_if_revoked_to_blocked_now(client, tenant_a, env_a):
    actor = _actor()
    seed = _seed(client, tenant_a, env_a["id"])
    draft_id = _draft(seed["tenant_id"], actor_id=actor, minutes_ahead=4,
                      items=_preview(seed["binding_id"])["items"])

    active = _project(tenant_a, seed["binding_id"], actor_id=actor)
    group = active["dependents"]["own_live_batch_drafts"]
    assert group["state"] == BLOCKED_IF_REVOKED
    assert [item["draft_id"] for item in group["references"]["matched"]] == [draft_id]
    assert group["references"]["matched"][0]["expires_at"].endswith("Z")
    assert group["references"]["scan"] == {"scanned": 1, "limit": DEFAULT_DRAFT_SCAN_LIMIT,
                                          "truncated": False}
    assert active["effect_if_revoked"]["new_preview_or_execute_on_this_binding_rejected"] == \
        "binding_revoked"

    _revoke(client, tenant_a, seed["binding_id"])
    revoked = _project(tenant_a, seed["binding_id"], actor_id=actor)
    assert revoked["binding_state"] == "revoked"
    assert revoked["dependents"]["own_live_batch_drafts"]["state"] == BLOCKED_NOW
    # 吊销不重放、不回滚、不改历史行。
    assert revoked["effect_if_revoked"]["existing_effects_are_not_reverted"] is True
    assert revoked["effect_if_revoked"]["existing_deployment_records_are_not_modified"] is True


# 五：别的身份的草稿与已过期草稿既不算作"无引用"，也不被读取回显。
def test_other_actor_and_expired_drafts_never_become_absence(client, tenant_a, env_a):
    actor = _actor()
    seed = _seed(client, tenant_a, env_a["id"])
    other = _draft(seed["tenant_id"], actor_id=_actor(), minutes_ahead=4,
                   items=_preview(seed["binding_id"])["items"])
    expired = _draft(seed["tenant_id"], actor_id=actor, minutes_ahead=-1,
                     items=_preview(seed["binding_id"])["items"])

    result = _project(tenant_a, seed["binding_id"], actor_id=actor)
    own = result["dependents"]["own_live_batch_drafts"]
    assert own["state"] == DEPENDENCY_ABSENT
    assert own["references"]["matched_count"] == 0
    assert own["reasons"] == ["expired_drafts_outside_scan_scope",
                              "no_own_live_draft_recorded_for_scope",
                              "no_own_live_draft_references_binding"]
    others = result["dependents"]["other_actor_live_batch_drafts"]
    assert others["state"] == NOT_DETERMINABLE
    assert others["reasons"] == ["draft_ownership_is_actor_scoped",
                                 "other_actor_live_drafts_not_enumerable"]
    dumped = json.dumps(result)
    assert other not in dumped and expired not in dumped


# 六：扫不完不等于没引用——截断与不可读一律降为"无法判定"。
def test_truncation_and_unreadable_previews_are_not_absence(client, tenant_a, env_a):
    other = "rb-" + uuid.uuid4().hex

    # 子例一：命中项在扫描上界之内，但仍有存活草稿没扫到 → 结论成立且如实标记截断。
    inside, actor = _seed(client, tenant_a, env_a["id"]), _actor()
    hit = _draft(inside["tenant_id"], actor_id=actor, minutes_ahead=1,
                 items=_preview(inside["binding_id"])["items"])
    _draft(inside["tenant_id"], actor_id=actor, minutes_ahead=4, items=_preview(other)["items"])
    limited = _project(tenant_a, inside["binding_id"], actor_id=actor, draft_scan_limit=1)
    group = limited["dependents"]["own_live_batch_drafts"]
    assert group["references"]["scan"] == {"scanned": 1, "limit": 1, "truncated": True}
    assert group["state"] == BLOCKED_IF_REVOKED
    assert "draft_scan_truncated" in group["reasons"]
    assert [item["draft_id"] for item in group["references"]["matched"]] == [hit]

    # 子例二：唯一命中项落在上界之外 → 既没匹配上、也没扫完，不得声明"无引用"。
    beyond, actor = _seed(client, tenant_a, env_a["id"]), _actor()
    _draft(beyond["tenant_id"], actor_id=actor, minutes_ahead=1, items=_preview(other)["items"])
    _draft(beyond["tenant_id"], actor_id=actor, minutes_ahead=4,
           items=_preview(beyond["binding_id"])["items"])
    result = _project(tenant_a, beyond["binding_id"], actor_id=actor, draft_scan_limit=1)
    group = result["dependents"]["own_live_batch_drafts"]
    assert group["state"] == NOT_DETERMINABLE
    assert "draft_scan_truncated" in group["reasons"]
    assert group["references"]["matched_count"] == 0

    # 子例三：预览损坏（摘要不成立） → 无法读取，同样不得声明"无引用"。
    corrupt, actor = _seed(client, tenant_a, env_a["id"]), _actor()
    broken = _draft(corrupt["tenant_id"], actor_id=actor, minutes_ahead=3,
                    items=_preview(other)["items"])
    with session_scope() as session:
        session.get(DeploymentBatchDraft, broken).preview = {
            "schema_version": "enterprise-deployment-batch-preview/v1",
            "items": [], "preview_digest": "not-a-digest",
        }
    group = _project(tenant_a, corrupt["binding_id"], actor_id=actor)["dependents"][
        "own_live_batch_drafts"]
    assert group["state"] == NOT_DETERMINABLE
    assert "draft_preview_unreadable" in group["reasons"]
    assert group["references"]["unreadable_draft_ids"] == [broken]


# 七：入参边界与验证身份。
def test_invalid_inputs_are_rejected(client, tenant_a, env_a):
    import pytest

    from app.security import Identity

    seed = _seed(client, tenant_a, env_a["id"])
    with session_scope() as session:
        identity = _identity(tenant_a)
        for bad in ("", None, 1):
            with pytest.raises(ValueError):
                project_binding_invalidation_surface(session, identity, bad)
        for bad_limit in (0, -1, True, "10"):
            with pytest.raises(ValueError):
                project_binding_invalidation_surface(
                    session, identity, seed["binding_id"], bad_limit)
        with pytest.raises(ValueError):
            project_binding_invalidation_surface(
                session, Identity(identity_type="user", actor_id="user-a", tenant_id=""),
                seed["binding_id"])
