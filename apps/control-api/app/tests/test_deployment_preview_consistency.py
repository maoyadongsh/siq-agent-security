"""CL-04-PREVIEW-CONSISTENCY-CLOSEOUT：单项/批量预览准备期间的登记身份一致性。

被测风险：
- 单项 `POST /api/v1/deployment-preview` 直接 `_snapshot(_prepare(...))`，响应全部来自
  `prepared` 的 ORM 对象；该对象在请求内是常量（`prepare_deployment` 载入绑定行时没有
  `populate_existing=True`，请求会话 `expire_on_commit=False` 且无 commit/refresh）。
- 批量 `POST /api/v1/deployment-previews/batch` 逐项 prepare+snapshot 后立即进入下一项，
  因此**后续条目的外部探测**可以吊销已经准备好的前面条目，而前面条目的预览已经生成。

两者都不是执行绕过：执行链有独立复验（`execute_deployment`）。本文件只核对预览响应的
证据一致性。所有漂移都经独立会话（`session_scope()`，独立连接）真实提交；预期值来自
持久行的独立读取，不从被测响应反推。

既有文件已覆盖 fake 后端的单项/批量成功、排序、重复稳定、重叠/重复/上限、权限顺序、
拒绝不写；本文件补充 openshell-cli（`_prepare` 内含真实外部只读探测）路径上的稳定性与
准备期漂移面，不重复上述场景。
"""

import hashlib
import json
import uuid

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    AgentAsset,
    AgentInstance,
    AuditEvent,
    Deployment,
    DeploymentSubmission,
    EdgeTask,
    Finding,
    OutboxEvent,
    RuntimeBinding,
    Tenant,
)
from app.tests.binding_helpers import assign_target_authority, make_binding
from app.tests.test_change_review import approver, change
from app.tests.test_openshell_policy_operations import StatefulRunner

SINGLE_URL = "/api/v1/deployment-preview"
BATCH_URL = "/api/v1/deployment-previews/batch"

REQUIRED_PERMISSIONS = {"policy:manage", "policy:read", "env:read"}


def _counts():
    with session_scope() as session:
        return [
            session.scalar(select(func.count()).select_from(model))
            for model in (Deployment, EdgeTask, Finding, AuditEvent, OutboxEvent)
        ]


def _reservations():
    """预留行快照（用于"预览不产生预留"的前后对比）。

    `DeploymentSubmission` 是**不可变预留记录**，没有 `state` 列；此前这里读 `row.state`
    只在表为空时不报错，导致孤立运行空通过、全量运行 AttributeError。快照取真实存在的
    标识与内容字段，行集与内容任一变化都能被前后对比发现。
    """
    with session_scope() as session:
        return [
            (row.id, row.change_request_id, row.request_key, row.request_digest, row.preview_digest)
            for row in session.scalars(select(DeploymentSubmission).order_by(DeploymentSubmission.id))
        ]


def _persisted_binding(binding_id: str) -> dict:
    """独立会话读取的持久绑定行（预期值的唯一来源）。"""
    with session_scope() as session:
        row = session.get(RuntimeBinding, binding_id)
        return {
            "id": row.id,
            "status": row.status,
            "environment_id": row.environment_id,
            "asset_id": row.asset_id,
            "agent_instance_id": row.agent_instance_id,
            "backend": row.backend,
            "backend_target_id": row.backend_target_id,
        }


def _persisted_instance_asset(instance_id: str) -> str:
    with session_scope() as session:
        return session.get(AgentInstance, instance_id).asset_id


class _TwoSandboxRunner(StatefulRunner):
    """测试替身：把第二个沙箱名映射到同一份合成输出（仅替身层面，不是生产行为）。

    批量场景需要两个解析到不同 target 的绑定（否则触发 batch_preview_target_overlap），
    而 StatefulRunner 只应答 sandbox "s1"。
    """

    def __call__(self, args):
        if tuple(args[:3]) == ("policy", "get", "s2"):
            args = ["policy", "get", "s1", *args[3:]]
        return super().__call__(args)


def _cli_scope(client, tenant_a, monkeypatch):
    """openshell-cli 隔离租户：`_prepare` 内含一次真实外部只读探测。"""
    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.operation_registry import PolicyOperationRegistry
    from app.routers import policies

    tenant_id = "preview-cons-" + uuid.uuid4().hex
    with session_scope() as session:
        session.add(Tenant(id=tenant_id, name="isolated preview consistency"))
        session.commit()
    headers = {**tenant_a, "X-Dev-Tenant-Id": tenant_id}
    created = client.post("/api/v1/environments", headers=headers, json={"name": "preview cons env", "mode": "enforce"})
    assert created.status_code == 201, created.text
    monkeypatch.setenv("SIQ_AS_ENFORCEMENT_BACKEND", "openshell-cli")
    runner = _TwoSandboxRunner()
    backend = OpenShellCliBackend(runner=runner, env_script="", operation_registry=PolicyOperationRegistry())
    monkeypatch.setattr(policies, "OpenShellCliBackend", lambda: backend)
    return headers, created.json(), backend


def _item(client, headers, env, target):
    """一个可预览目标：登记 openshell-cli 绑定 + 已批准变更 + 单项预览请求体。"""
    binding, asset, instance = make_binding(client, headers, env["id"], backend="openshell-cli", target=target)
    cr, _ = change(client, headers, agent_ids=[asset], enforcement_mode="block")
    approved = client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(headers), json={})
    assert approved.status_code == 200, approved.text
    body = {
        "schema_version": "deployment-preview-request/v1",
        "change_request_id": cr["id"],
        "environment_id": env["id"],
        "binding_id": binding["id"],
    }
    return binding, instance, body


def _assign_authorities(monkeypatch, tmp_path, binding_ids, backend):
    """为多个目标写 operator authority：先复用既有夹具，再补上其余绑定。"""
    path = assign_target_authority(monkeypatch, tmp_path, binding_ids[0], backend)
    caps = backend.probe()
    digest = hashlib.sha256(caps.handshake_gateway.encode()).hexdigest()
    catalog = json.loads(path.read_text())
    with session_scope() as session:
        for binding_id in binding_ids[1:]:
            binding = session.get(RuntimeBinding, binding_id)
            entry = {
                field: getattr(binding, field)
                for field in ("tenant_id", "environment_id", "asset_id", "agent_instance_id", "backend_target_id")
            }
            entry.update(
                id="fixture-assignment-" + binding_id,
                endpoint_fingerprint=caps.endpoint_fingerprint,
                gateway_name_sha256=digest,
            )
            catalog["assignments"].append(entry)
    path.write_text(json.dumps(catalog))
    return path


def _drift_on_probe(monkeypatch, backend, commit, *, call_index=1):
    """在探测期间提交漂移；`call_index` 选择本测试关心的那次探测（按安装后开始计数）。"""
    original = backend.probe
    calls = []

    def probe_then_commit():
        calls.append(1)
        caps = original()
        if len(calls) == call_index:
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


def _retarget_instance_asset(instance_id: str, tenant_id: str) -> None:
    """实例来源漂移：实例改指另一角色资产，绑定行本身不变。"""
    with session_scope() as session:
        other = AgentAsset(tenant_id=tenant_id, name="different role", status="confirmed")
        session.add(other)
        session.flush()
        session.get(AgentInstance, instance_id).asset_id = other.id


def _post_single(client, headers, body):
    return client.post(SINGLE_URL, headers=headers, json=body)


def _post_batch(client, headers, items):
    return client.post(
        BATCH_URL,
        headers=headers,
        json={"schema_version": "enterprise-deployment-batch-preview-request/v1", "items": items},
    )


# ------------------------------------------------------------------ 1. 稳定身份对照


def test_openshell_single_preview_is_stable_and_read_only(client, tenant_a, monkeypatch, tmp_path):
    headers, env, backend = _cli_scope(client, tenant_a, monkeypatch)
    binding, _, body = _item(client, headers, env, "s1")
    _assign_authorities(monkeypatch, tmp_path, [binding["id"]], backend)
    before, before_reservations = _counts(), _reservations()
    expected = _persisted_binding(binding["id"])

    first = _post_single(client, headers, body)
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "no-store"
    value = first.json()
    assert value["binding_id"] == expected["id"]
    assert value["environment_id"] == expected["environment_id"]
    assert value["target"] == expected["backend_target_id"]
    assert value["action"] == "dynamic_update"
    # 摘要按合同是“当前预检快照”的绑定：同状态同操作者稳定，换操作者即变
    repeat = _post_single(client, headers, body)
    assert repeat.status_code == 200 and repeat.json() == value
    other_actor = _post_single(client, {**headers, "X-Dev-User-Id": "preview-other-actor"}, body)
    assert other_actor.status_code == 200
    assert other_actor.json()["preview_digest"] != value["preview_digest"]
    assert _counts() == before and _reservations() == before_reservations
    assert _persisted_binding(binding["id"]) == expected


def test_openshell_batch_preview_is_sorted_stable_and_read_only(client, tenant_a, monkeypatch, tmp_path):
    headers, env, backend = _cli_scope(client, tenant_a, monkeypatch)
    first, _, first_body = _item(client, headers, env, "s1")
    second, _, second_body = _item(client, headers, env, "s2")
    _assign_authorities(monkeypatch, tmp_path, [first["id"], second["id"]], backend)
    ordered = sorted([first_body, second_body], key=lambda item: item["binding_id"])
    before, before_reservations = _counts(), _reservations()

    response = _post_batch(client, headers, [second_body, first_body])
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    value = response.json()
    assert value["schema_version"] == "enterprise-deployment-batch-preview/v1"
    assert value["batch_submission_supported"] is False
    # 合同：请求按 binding_id 排序处理，结果同序，客户端顺序不影响摘要
    assert [item["binding_id"] for item in value["items"]] == [item["binding_id"] for item in ordered]
    assert value == _post_batch(client, headers, ordered).json()
    assert len(value["preview_digest"]) == 64
    assert _counts() == before and _reservations() == before_reservations


# --------------------------------------------------- 2. 单项：准备期探测期间的漂移


@pytest.mark.parametrize("drift", ["revoked", "binding_asset", "instance_asset"])
def test_single_preview_drift_during_prepare_probe_is_refused(client, tenant_a, monkeypatch, tmp_path, drift):
    """探测期间提交吊销/身份漂移/实例来源漂移：不得返回漂移前的旧预览。"""
    headers, env, backend = _cli_scope(client, tenant_a, monkeypatch)
    tenant_id = headers["X-Dev-Tenant-Id"]
    binding, instance_id, body = _item(client, headers, env, "s1")
    _assign_authorities(monkeypatch, tmp_path, [binding["id"]], backend)
    before_binding = _persisted_binding(binding["id"])
    before_instance_asset = _persisted_instance_asset(instance_id)
    before, before_reservations = _counts(), _reservations()

    def commit():
        if drift == "revoked":
            _revoke(binding["id"])
        elif drift == "binding_asset":
            _repoint_binding_asset(binding["id"], tenant_id)
        else:
            _retarget_instance_asset(instance_id, tenant_id)

    calls = _drift_on_probe(monkeypatch, backend, commit)
    result = _post_single(client, headers, body)

    assert calls == [1]  # 漂移确实落在本次请求的探测期间
    if drift == "instance_asset":
        assert _persisted_binding(binding["id"]) == before_binding
        assert _persisted_instance_asset(instance_id) != before_instance_asset
    else:
        assert _persisted_binding(binding["id"]) != before_binding
    expected_detail = "binding_revoked" if drift == "revoked" else "binding_source_identity_changed"
    assert result.status_code == 409, result.text
    assert result.json() == {"detail": expected_detail}
    assert binding["asset_id"] not in result.text
    assert "preview_digest" not in result.text
    assert _counts() == before and _reservations() == before_reservations


# ------------------------------------------- 3./4. 批量：跨条目窗口与末项自身漂移


def _batch_scope(client, tenant_a, monkeypatch, tmp_path):
    """批量目标：两个不同 target 的绑定，处理顺序由 binding_id 排序决定。"""
    headers, env, backend = _cli_scope(client, tenant_a, monkeypatch)
    first, first_instance, first_body = _item(client, headers, env, "s1")
    second, second_instance, second_body = _item(client, headers, env, "s2")
    _assign_authorities(monkeypatch, tmp_path, [first["id"], second["id"]], backend)
    pair = sorted(
        [(first_body, first, first_instance), (second_body, second, second_instance)],
        key=lambda entry: entry[1]["id"],
    )
    return headers, [entry[0] for entry in pair], pair, backend


def test_batch_revocation_during_second_probe_refuses_the_whole_batch(client, tenant_a, monkeypatch, tmp_path):
    """A 已在 B 探测之前准备好；在 B 的探测期间吊销 A，整批必须拒绝且不返回 A 的旧预览。"""
    headers, items, pair, backend = _batch_scope(client, tenant_a, monkeypatch, tmp_path)
    first_binding = pair[0][1]
    before, before_reservations = _counts(), _reservations()

    # 探测 1 = A 的准备，探测 2 = B 的准备；A 的预览在探测 2 之前就已生成。
    calls = _drift_on_probe(monkeypatch, backend, lambda: _revoke(first_binding["id"]), call_index=2)
    result = _post_batch(client, headers, items)

    assert calls == [1, 1]
    assert _persisted_binding(first_binding["id"])["status"] == "revoked"
    assert result.status_code == 409, result.text
    assert result.json() == {"detail": "binding_revoked"}
    assert "items" not in result.json()
    assert first_binding["asset_id"] not in result.text
    assert _counts() == before and _reservations() == before_reservations


def test_batch_last_item_drift_refuses_without_partial_items(client, tenant_a, monkeypatch, tmp_path):
    """末项自身在探测期间漂移：整批拒绝，不回传任何 items。"""
    headers, items, pair, backend = _batch_scope(client, tenant_a, monkeypatch, tmp_path)
    last_binding = pair[-1][1]
    before, before_reservations = _counts(), _reservations()
    calls = _drift_on_probe(monkeypatch, backend, lambda: _revoke(last_binding["id"]), call_index=2)
    result = _post_batch(client, headers, items)

    assert calls == [1, 1]
    assert _persisted_binding(last_binding["id"])["status"] == "revoked"
    assert result.status_code == 409, result.text
    assert result.json() == {"detail": "binding_revoked"}
    assert "items" not in result.json()
    assert _counts() == before and _reservations() == before_reservations


# ------------------------------------------------------------- 5. 权限、租户与零探测


def test_denials_precede_any_external_probe(client, tenant_a, monkeypatch, tmp_path):
    """无权限 403、跨租户 404 都在任何外部探测之前，且不回显对象字段。"""
    from app import security

    headers, env, backend = _cli_scope(client, tenant_a, monkeypatch)
    binding, _, body = _item(client, headers, env, "s1")
    _assign_authorities(monkeypatch, tmp_path, [binding["id"]], backend)
    before, before_reservations = _counts(), _reservations()

    original = backend.probe
    probes = []
    monkeypatch.setattr(backend, "probe", lambda: (probes.append(1), original())[1])

    # 被测角色必须真的缺少所需权限：viewer 有 agent:read/policy:read 但没有 policy:manage/env:read；
    # agent_owner 拥有 agent:read（本接口也不以 agent:read 为门禁），不能当作“缺权限”的替身。
    viewer = security.ROLE_PERMISSIONS["viewer"]
    assert not REQUIRED_PERMISSIONS <= viewer
    assert "agent:read" in security.ROLE_PERMISSIONS["agent_owner"]

    denied_single = _post_single(client, {**headers, "X-Dev-Roles": "viewer"}, body)
    denied_batch = _post_batch(client, {**headers, "X-Dev-Roles": "viewer"}, [body])
    assert denied_single.status_code == 403, denied_single.text
    assert denied_batch.status_code == 403, denied_batch.text
    assert probes == []

    foreign_single = _post_single(client, {**headers, "X-Dev-Tenant-Id": "tnt-B"}, body)
    foreign_batch = _post_batch(client, {**headers, "X-Dev-Tenant-Id": "tnt-B"}, [body])
    assert foreign_single.status_code == 404 and foreign_batch.status_code == 404
    for response in (foreign_single, foreign_batch):
        assert response.json() == {"detail": "not_found"}
        for leaked in (binding["id"], binding["asset_id"], binding["agent_instance_id"]):
            assert leaked not in response.text
    assert probes == []
    assert _counts() == before and _reservations() == before_reservations
