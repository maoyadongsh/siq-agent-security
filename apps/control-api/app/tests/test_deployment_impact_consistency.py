"""CL-04-IMPACT-SNAPSHOT-CLOSEOUT：影响报告生成时的证据一致性。

被测风险：`POST /api/v1/deployment-preview/impact` 在 `_prepare` 期间做外部只读探测
（openshell-cli 的 `probe()`），探测期间别的事务可能提交绑定吊销或来源身份漂移。请求会话的
ORM identity map 仍持有准备阶段读到的旧值，`_snapshot` 的 preview_digest 与 `registered_subject`
都从这份旧值产出，因此客户端提交的原 digest 仍然匹配，报告会描述一个已经失效的身份。

本文件只覆盖 `test_deployment_impact.py` 未覆盖的“准备期漂移”面（既有文件已覆盖：正常报告
与摘要重算、重复只读、无 agent:read 先于探测、跨租户 404、无权限 403、非法字段 422、拒绝不写）。
所有漂移都经独立会话（`session_scope()`，独立连接）真实提交；预期身份来自变更前后独立读取的
持久行，不从被测响应反推。
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    AgentAsset,
    AgentInstance,
    AuditEvent,
    Deployment,
    EdgeTask,
    Finding,
    OutboxEvent,
    RuntimeBinding,
    Tenant,
)
from app.tests.binding_helpers import assign_target_authority, make_binding
from app.tests.test_change_review import approver, change

IMPACT_URL = "/api/v1/deployment-preview/impact"
PREVIEW_URL = "/api/v1/deployment-preview"

SNAPSHOT_FIELDS = ("status", "environment_id", "asset_id", "agent_instance_id", "backend", "backend_target_id")


def _counts():
    with session_scope() as session:
        return [
            session.scalar(select(func.count()).select_from(model))
            for model in (Deployment, EdgeTask, Finding, AuditEvent, OutboxEvent)
        ]


def _persisted_binding(binding_id: str) -> dict:
    """独立会话读取的持久绑定行（预期值的唯一来源）。"""
    with session_scope() as session:
        row = session.get(RuntimeBinding, binding_id)
        return {"id": row.id, **{field: getattr(row, field) for field in SNAPSHOT_FIELDS}}


def _persisted_instance_asset(instance_id: str) -> str:
    with session_scope() as session:
        return session.get(AgentInstance, instance_id).asset_id


def _impact(client, headers, body, digest):
    return client.post(
        IMPACT_URL,
        headers=headers,
        json={
            **body,
            "schema_version": "enterprise-deployment-impact-request/v1",
            "preview_digest": digest,
        },
    )


def _preview(client, headers, body):
    response = client.post(PREVIEW_URL, headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _fake_scope(client, tenant_a, env_a):
    """默认后端（fake）的隔离租户预检目标。"""
    tenant_id = "impact-cons-" + uuid.uuid4().hex
    with session_scope() as session:
        session.add(Tenant(id=tenant_id, name="isolated impact consistency"))
        session.commit()
    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant_id}
    created = client.post("/api/v1/environments", headers=headers, json={"name": "impact env", "mode": "enforce"})
    assert created.status_code == 201, created.text
    env = created.json()
    binding, asset, _ = make_binding(client, headers, env["id"])
    cr, _ = change(client, headers, agent_ids=[asset], enforcement_mode="block")
    approved = client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(headers), json={})
    assert approved.status_code == 200, approved.text
    body = {
        "schema_version": "deployment-preview-request/v1",
        "change_request_id": cr["id"],
        "environment_id": env["id"],
        "binding_id": binding["id"],
    }
    return headers, env, binding, body


def _openshell_scope(client, tenant_a, monkeypatch, tmp_path):
    """openshell-cli 预检目标：`_prepare` 内含一次真实外部只读探测。"""
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.operation_registry import PolicyOperationRegistry
    from app.routers import policies
    from app.tests.test_openshell_policy_operations import StatefulRunner

    tenant_id = "impact-cons-cli-" + uuid.uuid4().hex
    with session_scope() as session:
        session.add(Tenant(id=tenant_id, name="isolated impact consistency cli"))
        session.commit()
    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant_id}
    created = client.post("/api/v1/environments", headers=headers, json={"name": "impact cli env", "mode": "enforce"})
    assert created.status_code == 201, created.text
    env = created.json()
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr(policies, "OpenShellCliBackend", lambda: backend)
    binding, _, _, cr = _setup_cli(client, headers, env, backend, monkeypatch, tmp_path)
    body = {
        "schema_version": "deployment-preview-request/v1",
        "change_request_id": cr["id"],
        "environment_id": env["id"],
        "binding_id": binding["id"],
    }
    return headers, env, binding, body, backend


def _setup_cli(client, headers, env, backend, monkeypatch, tmp_path):
    """openshell-cli 目标的登记 + 审批 + operator target authority。"""
    from app.tests.test_change_review import change as make_change

    binding, asset, instance = make_binding(client, headers, env["id"], backend="openshell-cli", target="s1")
    cr, _ = make_change(client, headers, agent_ids=[asset], enforcement_mode="block")
    approved = client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(headers), json={})
    assert approved.status_code == 200, approved.text
    assign_target_authority(monkeypatch, tmp_path, binding["id"], backend)
    return binding, asset, instance, cr


def _drift_on_first_probe(monkeypatch, backend, commit):
    """在探测期间提交漂移：本测试安装后紧接着的那次 probe 代表本次请求的探测。

    先取 preview 值再安装，因此计数不依赖前面的请求。
    """
    original_probe = backend.probe
    calls = []

    def probe_then_commit():
        calls.append(1)
        caps = original_probe()
        if len(calls) == 1:
            commit()
        return caps

    monkeypatch.setattr(backend, "probe", probe_then_commit)
    return calls


# ------------------------------------------------------------ 漂移提交（带外、独立会话）


def _revoke(binding_id: str) -> None:
    with session_scope() as session:
        session.get(RuntimeBinding, binding_id).status = "revoked"


def _repoint_binding_asset(binding_id: str, tenant_id: str) -> None:
    with session_scope() as session:
        asset = AgentAsset(tenant_id=tenant_id, name="drifted role", status="confirmed")
        session.add(asset)
        session.flush()
        session.get(RuntimeBinding, binding_id).asset_id = asset.id


def _repoint_binding_instance(binding_id: str, tenant_id: str, environment_id: str) -> None:
    with session_scope() as session:
        asset = AgentAsset(tenant_id=tenant_id, name="drifted role", status="confirmed")
        session.add(asset)
        session.flush()
        instance = AgentInstance(
            tenant_id=tenant_id, asset_id=asset.id, environment_id=environment_id, runtime="hermes"
        )
        session.add(instance)
        session.flush()
        session.get(RuntimeBinding, binding_id).agent_instance_id = instance.id


def _retarget_instance_asset(instance_id: str, tenant_id: str, environment_id: str) -> None:
    """实例来源漂移：实例改指向另一个角色资产，绑定行本身不变。"""
    with session_scope() as session:
        other = AgentAsset(tenant_id=tenant_id, name="different role", status="confirmed")
        session.add(other)
        session.flush()
        session.get(AgentInstance, instance_id).asset_id = other.id


def _change_attestation(binding_id: str) -> None:
    """两个复验字段集都不含的漂移，只能由 preview_digest 发现。"""
    with session_scope() as session:
        session.get(RuntimeBinding, binding_id).attestation = {"declared_by": "out-of-band"}


# ------------------------------------------------------------------------ 1. 稳定身份


def test_stable_identity_report_matches_persisted_row_without_writes(client, tenant_a, monkeypatch, tmp_path):
    """对照用例：无漂移时报告与独立读取的持久行一致，且只读。"""
    headers, env, binding, body, backend = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    value = _preview(client, headers, body)
    before = _counts()
    expected = _persisted_binding(binding["id"])

    result = _impact(client, headers, body, value["preview_digest"])
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["registered_subject"] == {
        "binding_id": expected["id"],
        "environment_id": expected["environment_id"],
        "asset_id": expected["asset_id"],
        "agent_instance_id": expected["agent_instance_id"],
    }
    assert data["preview"] == value
    assert data["coverage"] == "registered_binding_only"
    assert data["shared_runtime_occupants"] == "unknown"
    assert data["skill_isolation"] == "not_established"
    assert data["execution_confirmation_supported"] is False
    assert _counts() == before
    assert _persisted_binding(binding["id"]) == expected
    repeated = _impact(client, headers, body, value["preview_digest"])
    assert repeated.status_code == 200
    assert repeated.json() == data


# ------------------------------------------------------- 2. 准备期探测期间提交的漂移


def test_revocation_during_prepare_probe_refuses_stale_impact_report(client, tenant_a, monkeypatch, tmp_path):
    """探测期间提交绑定吊销：报告必须拒绝，不得描述已吊销的登记身份。"""
    headers, env, binding, body, backend = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    value = _preview(client, headers, body)
    before = _counts()

    calls = _drift_on_first_probe(monkeypatch, backend, lambda: _revoke(binding["id"]))
    result = _impact(client, headers, body, value["preview_digest"])

    assert calls == [1]  # 漂移确实落在本次请求的探测期间
    assert _persisted_binding(binding["id"])["status"] == "revoked"
    assert result.status_code == 409, result.text
    assert result.json() == {"detail": "binding_revoked"}
    assert binding["asset_id"] not in result.text
    assert "registered_subject" not in result.text
    assert _counts() == before


@pytest.mark.parametrize("drift", ["binding_asset", "binding_instance", "instance_asset"])
def test_identity_drift_during_prepare_probe_refuses_stale_impact_report(
    client, tenant_a, monkeypatch, tmp_path, drift
):
    """探测期间提交身份/来源漂移：报告不得把漂移前的身份当作当前登记身份返回。"""
    headers, env, binding, body, backend = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    tenant_id = headers["X-Dev-Tenant-Id"]
    with session_scope() as session:
        instance_id = session.get(RuntimeBinding, binding["id"]).agent_instance_id
    before_binding = _persisted_binding(binding["id"])
    before_instance_asset = _persisted_instance_asset(instance_id)
    value = _preview(client, headers, body)
    before = _counts()

    def commit():
        if drift == "binding_asset":
            _repoint_binding_asset(binding["id"], tenant_id)
        elif drift == "binding_instance":
            _repoint_binding_instance(binding["id"], tenant_id, env["id"])
        else:
            _retarget_instance_asset(instance_id, tenant_id, env["id"])

    _drift_on_first_probe(monkeypatch, backend, commit)
    result = _impact(client, headers, body, value["preview_digest"])

    # 独立的“漂移确实已持久化”证据：绑定行漂移看绑定行，实例来源漂移看实例行
    # （后者绑定行本身不变，只有复验里的来源核对能看到）。
    if drift == "instance_asset":
        assert _persisted_binding(binding["id"]) == before_binding
        assert _persisted_instance_asset(instance_id) != before_instance_asset
    else:
        assert _persisted_binding(binding["id"]) != before_binding
    assert result.status_code == 409, result.text
    assert result.json() == {"detail": "binding_source_identity_changed"}
    assert binding["asset_id"] not in result.text
    assert instance_id not in result.text
    assert _counts() == before


def test_identity_drift_between_prepare_and_report_refuses_on_default_backend(
    client, tenant_a, env_a, monkeypatch
):
    """默认 fake 后端：`_prepare` 之后、报告生成之前的窗口同样按持久状态复验。

    该窗口在此由 prepare 结束后立即提交的带外事务代表（fake 路径没有网络探测，
    窗口来自预检内部的本地读取）；这不是真实外部调用。
    """
    from app.routers import deployment_impact

    headers, env, binding, body = _fake_scope(client, tenant_a, env_a)
    value = _preview(client, headers, body)
    before = _counts()
    original_prepare = deployment_impact._prepare
    seen = []

    def prepare_then_drift(*args, **kwargs):
        prepared = original_prepare(*args, **kwargs)
        seen.append(1)
        _revoke(binding["id"])
        return prepared

    monkeypatch.setattr(deployment_impact, "_prepare", prepare_then_drift)
    result = _impact(client, headers, body, value["preview_digest"])

    assert seen == [1]
    assert _persisted_binding(binding["id"])["status"] == "revoked"
    assert result.status_code == 409, result.text
    assert result.json() == {"detail": "binding_revoked"}
    assert _counts() == before


# --------------------------------------------------- 3. 原 digest 仍被提交时的既有语义


def test_digest_remains_fail_closed_for_drift_outside_recheck_fields(client, tenant_a, monkeypatch, tmp_path):
    """复验字段集之外的漂移仍由 preview_digest 失败关闭，顺序与错误码不变。"""
    headers, env, binding, body, backend = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    value = _preview(client, headers, body)
    before = _counts()
    _change_attestation(binding["id"])

    result = _impact(client, headers, body, value["preview_digest"])

    assert result.status_code == 409, result.text
    assert result.json() == {"detail": "deployment_preview_changed"}
    assert _counts() == before


# ------------------------------------------------------------- 4. 权限、租户与零探测


def test_rejection_happens_before_any_external_probe(client, tenant_a, monkeypatch, tmp_path):
    """无 agent:read 403、跨租户 404 均发生在外部探测之前，且不回显对象字段。"""
    from app import security

    headers, env, binding, body, backend = _openshell_scope(client, tenant_a, monkeypatch, tmp_path)
    value = _preview(client, headers, body)
    before = _counts()

    original_probe = backend.probe
    probes = []
    monkeypatch.setattr(backend, "probe", lambda: (probes.append(1), original_probe())[1])

    role = "impact_consistency_without_inventory"
    monkeypatch.setitem(security.ROLE_PERMISSIONS, role, {"policy:manage", "policy:read", "env:read"})
    no_inventory = _impact(client, {**headers, "X-Dev-Roles": role}, body, value["preview_digest"])
    assert no_inventory.status_code == 403, no_inventory.text
    assert probes == []

    other_tenant = _impact(client, {**headers, "X-Dev-Tenant-Id": "tnt-B"}, body, value["preview_digest"])
    assert other_tenant.status_code == 404, other_tenant.text
    assert other_tenant.json() == {"detail": "not_found"}
    for leaked in (binding["id"], binding["asset_id"], binding["agent_instance_id"], env["id"]):
        assert leaked not in other_tenant.text
    assert probes == []
    assert _counts() == before
