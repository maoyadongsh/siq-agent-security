"""R03 证据拓扑内部模块的最小验证：只读、租户隔离、视角不合并、不可读原因固定、不生产行为证据。

本模块不是 HTTP 接口，故直接以验证身份构造 `Identity` 调用；夹具使用独立合成租户/环境/证据行，
不触碰共享夹具的扫描任务与资产。
"""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.evidence_topology import (
    SCHEMA_VERSION,
    project_evidence_topology,
)
from app.models import AuditEvent, Environment, Evidence, OutboxEvent, Tenant, utcnow
from app.security import Identity

COUNTED = (Tenant, Environment, Evidence, AuditEvent, OutboxEvent)


@pytest.fixture(autouse=True)
def database(client):  # noqa: ARG001
    """本文件不使用 HTTP 客户端，但需要 session 级 client 完成建表与 dev 种子初始化。"""
    return client


def _tenant_id() -> str:
    return "tnt-" + uuid.uuid4().hex[:12]


def _identity(tenant_id: str) -> Identity:
    return Identity(identity_type="user", actor_id="user-topology", tenant_id=tenant_id,
                    roles=frozenset({"agent_owner"}), permissions=frozenset({"agent:read"}))


def _counts() -> dict:
    with session_scope() as session:
        return {model.__name__: session.scalar(select(func.count()).select_from(model))
                for model in COUNTED}


def _make_environment(env_type: str = "host", *, tenant_id: str | None = None) -> tuple[str, str]:
    tenant_id = tenant_id or _tenant_id()
    with session_scope() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(Tenant(id=tenant_id, name="synthetic-topology-" + tenant_id))
            session.flush()
        environment = Environment(tenant_id=tenant_id, name="env-" + uuid.uuid4().hex[:12],
                                  env_type=env_type)
        session.add(environment)
        session.flush()
        return tenant_id, environment.id


def _add_evidence(tenant_id: str, environment_id: str, source_type: str, *,
                  payload_ref: str | None = "private://payload", expired: bool = False) -> None:
    with session_scope() as session:
        session.add(Evidence(
            evidence_id="ev-" + uuid.uuid4().hex, tenant_id=tenant_id, environment_id=environment_id,
            source_type=source_type, source_locator=f"{source_type}://synthetic",
            observed_at=utcnow(), collector_id="collector-synthetic", connector_version="0.1.0",
            content_hash=uuid.uuid4().hex + uuid.uuid4().hex, signature="0" * 128,
            payload_ref=payload_ref,
            expires_at=(utcnow() - timedelta(hours=1)) if expired else None,
        ))


def _project(tenant_id: str, environment_id: str) -> dict:
    with session_scope() as session:
        return project_evidence_topology(session, _identity(tenant_id), environment_id)


def test_topology_is_readonly_and_tenant_isolated():
    tenant_id, environment_id = _make_environment()
    _add_evidence(tenant_id, environment_id, "process")
    before = _counts()
    result = _project(tenant_id, environment_id)
    assert result["schema_version"] == SCHEMA_VERSION
    assert _counts() == before
    # 其它租户环境与不存在的环境返回完全相同结果：不构成跨租户存在性判别。
    other_tenant, other_environment = _make_environment()
    unknown = _project(other_tenant, environment_id)
    missing = _project(other_tenant, "env-" + uuid.uuid4().hex[:12])
    # 除回显的请求参数 environment_id 外，他租户环境与不存在环境结果完全相同。
    assert {k: v for k, v in unknown.items() if k != "environment_id"} == \
        {k: v for k, v in missing.items() if k != "environment_id"}
    assert unknown["reasons"] == ["environment_not_recorded_in_tenant"]
    assert unknown["observed_surfaces"] == _project(other_tenant, other_environment)["observed_surfaces"]


def test_host_environment_with_host_surface_is_observed():
    tenant_id, environment_id = _make_environment("host")
    _add_evidence(tenant_id, environment_id, "process")
    _add_evidence(tenant_id, environment_id, "systemd")
    result = _project(tenant_id, environment_id)
    assert result["declared_perspective"] == {"env_type": "host", "perspective": "host", "reason": None}
    assert result["perspective_state"] == "observed_from_records"
    assert result["reasons"] == []
    assert result["observed_surfaces"]["os"]["count"] == 2


def test_declared_only_when_no_evidence():
    tenant_id, environment_id = _make_environment("container")
    result = _project(tenant_id, environment_id)
    assert result["perspective_state"] == "declared_only"
    assert result["reasons"] == ["no_evidence_in_environment_scope"]
    assert result["evidence_readability"]["total"] == 0


def test_container_surface_in_host_environment_is_conflict_not_merged():
    tenant_id, environment_id = _make_environment("host")
    _add_evidence(tenant_id, environment_id, "process")
    _add_evidence(tenant_id, environment_id, "docker")
    result = _project(tenant_id, environment_id)
    # 同时存在相容与冲突表面时不降级为一致。
    assert result["perspective_state"] == "declared_and_observed_conflict"
    assert "declared_and_observed_perspective_conflict" in result["reasons"]


def test_unmapped_connector_is_reported_not_silently_bucketed():
    tenant_id, environment_id = _make_environment("host")
    _add_evidence(tenant_id, environment_id, "synthetic-unknown-connector")
    result = _project(tenant_id, environment_id)
    assert result["observed_surfaces"]["unmapped"] == {
        "count": 1, "connectors": ["synthetic-unknown-connector"]}
    assert "connector_perspective_unmapped" in result["reasons"]
    # 未归类采集器不得被计入宿主表面。
    assert result["observed_surfaces"]["os"]["count"] == 0
    assert result["perspective_state"] == "declared_and_observed_conflict"


def test_account_environment_remote_perspective_has_no_surface_source():
    tenant_id, environment_id = _make_environment("account")
    result = _project(tenant_id, environment_id)
    assert result["declared_perspective"]["perspective"] == "remote"
    assert result["perspective_state"] == "not_established"
    assert "account_perspective_source_absent" in result["reasons"]
    # 远程视角不借用宿主/容器表面顶替。
    assert result["observed_surfaces"]["os"]["count"] == 0


def test_unknown_environment_type_does_not_guess_perspective():
    tenant_id, environment_id = _make_environment("synthetic-type")
    result = _project(tenant_id, environment_id)
    assert result["declared_perspective"] == {
        "env_type": "synthetic-type", "perspective": "not_established",
        "reason": "declared_environment_type_unknown"}
    assert result["perspective_state"] == "not_established"


def test_unreadable_reasons_are_recorded_facts_not_inferences():
    tenant_id, environment_id = _make_environment("host")
    _add_evidence(tenant_id, environment_id, "process", payload_ref=None)
    _add_evidence(tenant_id, environment_id, "process", expired=True)
    result = _project(tenant_id, environment_id)
    readability = result["evidence_readability"]
    assert readability["total"] == 2
    assert readability["metadata_only"] == 1
    assert readability["expired"] == 1
    assert sorted(readability["reasons"]) == ["evidence_expired", "payload_not_retained"]
    # 只判断可读性事实，绝不读取 payload 正文。
    assert "private://payload" not in str(result)


def test_enforcement_verified_is_never_produced():
    tenant_id, environment_id = _make_environment("host")
    _add_evidence(tenant_id, environment_id, "docker")
    result = _project(tenant_id, environment_id)
    assert result["enforcement_verified"] is False
    assert result["behavioral_evidence"] == {
        "state": "not_established", "reason": "behavioral_fixture_source_absent"}
    assert result["coverage"] == "recorded_evidence_in_environment_only"
    for code in ("host_name_is_not_model_identification", "dmi_product_name_is_not_device_model",
                 "devicetree_model_is_not_device_model",
                 "declared_environment_type_is_not_observed_perspective",
                 "topology_projection_is_not_enforcement_proof"):
        assert code in result["must_not_infer"]


def test_verified_tenant_identity_is_required():
    with session_scope() as session:
        with pytest.raises(ValueError, match="^verified_tenant_identity_required$"):
            project_evidence_topology(session, _identity(""), "env-synthetic")
        with pytest.raises(ValueError, match="^environment_id_required$"):
            project_evidence_topology(session, _identity(_tenant_id()), "")
