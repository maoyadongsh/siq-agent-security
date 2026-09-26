"""证据就绪度内部模块的最小验证：只读、租户/设备隔离、无秘密外泄、不产出执行结论。

本模块不是 HTTP 接口，故直接以验证身份构造 `Identity` 调用。夹具尽量走真实写入路径
（真实绑定登记端点、真实签名技能上传）；仅“显式配置声明”记录使用库内合成行——复用 openclaw
签名批次夹具会给共享租户增加扫描任务与资产，与本文件无关。每个场景使用独立合成对象，
避免共享环境任务污染。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.binding_evidence_readiness import (
    DIMENSIONS,
    REASON_CODES,
    SCHEMA_VERSION,
    STATES,
    _declared_selection,
    assess_binding_evidence,
)
from app.db import session_scope
from app.models import (
    AgentAsset,
    AgentInstance,
    AuditEvent,
    Deployment,
    EdgeAgent,
    EdgeTask,
    Environment,
    Evidence,
    Finding,
    OutboxEvent,
    RoleSkillSelectionObservation,
    RuntimeBinding,
    SkillInstallation,
    SkillManifestObservation,
    Tenant,
    utcnow,
)
from app.security import Identity
from app.tests import test_skill_upload as uploads

# 真实签名上传夹具（租户 A，真实注册设备 + 真实入库安装观察），仅依赖 client/tenant_a。
upload_case = uploads.upload_case

CANARY_NAME = "canary-skill-" + uuid.uuid4().hex
CANARY_ATTESTATION = "canary-attestation-" + uuid.uuid4().hex
CANARY_SCOPE = "canary-scope-" + uuid.uuid4().hex

COUNTED = (
    RuntimeBinding, AgentAsset, AgentInstance, EdgeAgent, Environment, Evidence,
    SkillInstallation, SkillManifestObservation, RoleSkillSelectionObservation,
    Deployment, EdgeTask, Finding, AuditEvent, OutboxEvent, Tenant,
)

FORBIDDEN_KEY_PARTS = ("execut", "authoriz", "approved", "allow", "grant", "permit")


def _hex64() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex


def _operator(headers: dict, roles: str) -> dict:
    """带 policy:manage 的 dev 身份头（登记绑定需要）；不改变既有夹具字典。"""
    return {**headers, "X-Dev-Roles": roles}


def _identity(headers: dict) -> Identity:
    return Identity(
        identity_type="user",
        actor_id=headers["X-Dev-User-Id"],
        tenant_id=headers["X-Dev-Tenant-Id"],
        roles=frozenset({"agent_owner"}),
        permissions=frozenset({"agent:read"}),
    )


def _assess(headers: dict, binding_id: str) -> dict:
    with session_scope() as session:
        return assess_binding_evidence(session, _identity(headers), binding_id)


def _counts() -> dict:
    with session_scope() as session:
        return {model.__name__: session.scalar(select(func.count()).select_from(model)) for model in COUNTED}


def _keys(value) -> list:
    if isinstance(value, dict):
        found = []
        for key, item in value.items():
            found.append(key)
            found.extend(_keys(item))
        return found
    if isinstance(value, list):
        return [key for item in value for key in _keys(item)]
    return []


def _make_device(environment_id: str, *, revoked: bool = False):
    device_identity = "dev-" + uuid.uuid4().hex[:12]
    with session_scope() as session:
        edge = EdgeAgent(
            environment_id=environment_id,
            device_identity=device_identity,
            secret_hash="0" * 64,
            public_key_pem="fixture",
            version="1",
            revoked_at=utcnow() if revoked else None,
        )
        session.add(edge)
        session.flush()
        return edge.id, device_identity


def _seed(
    client,
    headers: dict,
    environment_id: str,
    *,
    edge_id: str | None = None,
    device_identity: str | None = None,
    with_device: bool = True,
    with_source: bool = True,
    source_raw: str | None = None,
    attestation: dict | None = None,
    target: str | None = None,
) -> dict:
    """库内直插资产/实例（+设备、框架来源证据），经真实端点登记绑定。"""
    tenant_id = headers["X-Dev-Tenant-Id"]
    if edge_id is None and with_device:
        edge_id, device_identity = _make_device(environment_id)
    instance_key, config_sha256 = _hex64(), _hex64()
    evidence_id = "ev-" + uuid.uuid4().hex[:12]
    source = None
    if with_source or source_raw is not None:
        source = {
            "schema_version": "enterprise-framework-source/v2",
            "framework": "hermes",
            "instance_key": instance_key,
            "config_sha256": config_sha256,
            "evidence_id": evidence_id,
        }
    raw = source_raw if source_raw is not None else (json.dumps(source) if source else None)
    with session_scope() as session:
        asset = AgentAsset(
            tenant_id=tenant_id,
            name="asset-" + uuid.uuid4().hex[:8],
            status="confirmed",
            framework="hermes" if source else "unknown",
            source_type="hermes_profile" if source else None,
            source_locator=f"hermes://profiles/v2/{instance_key}" if source else None,
            discovery_scope=edge_id or "legacy",
            attributes={"framework_source": raw} if raw is not None else {},
            evidence_ids=[evidence_id] if source else [],
        )
        session.add(asset)
        session.flush()
        instance = AgentInstance(
            tenant_id=tenant_id, asset_id=asset.id, environment_id=environment_id, runtime="hermes"
        )
        session.add(instance)
        session.flush()
        if source is not None and edge_id and device_identity:
            session.add(Evidence(
                tenant_id=tenant_id,
                environment_id=environment_id,
                source_type="manifest",
                source_locator=instance_key + "/config.yaml",
                subject_ref="hermes:v2:" + instance_key,
                observed_at=utcnow(),
                collector_id=device_identity,
                connector_version="1",
                content_hash=config_sha256,
                signature="fixture",
                evidence_id=evidence_id,
            ))
        asset_id, instance_id = asset.id, instance.id
    body = {
        "agent_instance_id": instance_id,
        "environment_id": environment_id,
        "backend": "fake",
        "backend_target_id": target or f"sandbox-{uuid.uuid4().hex[:8]}",
        "attestation": attestation or {},
    }
    response = client.post("/api/v1/runtime-bindings", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return {
        "binding_id": response.json()["id"],
        "asset_id": asset_id,
        "instance_id": instance_id,
        "edge_id": edge_id,
        "device_identity": device_identity,
        "environment_id": environment_id,
        "tenant_id": tenant_id,
        "instance_key": instance_key,
        "evidence_id": evidence_id,
    }


def _register(client, headers: dict, seed: dict, *, target: str) -> str:
    response = client.post("/api/v1/runtime-bindings", headers=headers, json={
        "agent_instance_id": seed["instance_id"],
        "environment_id": seed["environment_id"],
        "backend": "fake",
        "backend_target_id": target,
        "attestation": {},
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _revoke_device(edge_id: str) -> None:
    with session_scope() as session:
        session.get(EdgeAgent, edge_id).revoked_at = utcnow()


def _repoint(asset_id: str, scope: str) -> None:
    with session_scope() as session:
        session.get(AgentAsset, asset_id).discovery_scope = scope


def _relocate_device(edge_id: str, environment_id: str, evidence_id: str) -> None:
    """把设备与其同源证据一起搬到另一个环境（设备来源仍然可核对，但与绑定环境不一致）。"""
    with session_scope() as session:
        session.get(EdgeAgent, edge_id).environment_id = environment_id
        row = session.scalar(select(Evidence).where(Evidence.evidence_id == evidence_id))
        row.environment_id = environment_id


def _declaration(seed: dict, names, *, edge_agent_id: str | None = None) -> None:
    with session_scope() as session:
        task = EdgeTask(
            environment_id=seed["environment_id"],
            task_type="scan",
            expires_at=utcnow() + timedelta(minutes=10),
            payload={},
        )
        session.add(task)
        session.flush()
        session.add(RoleSkillSelectionObservation(
            tenant_id=seed["tenant_id"],
            asset_id=seed["asset_id"],
            edge_agent_id=edge_agent_id or seed["edge_id"],
            task_id=task.id,
            batch_digest=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
            selection={
                "schema_version": "enterprise-openclaw-skill-selection/v1",
                "source": "agent",
                "status": "declared_list",
                "names": list(names),
            },
            source_evidence=[],
            observed_at=utcnow(),
            received_at=utcnow(),
        ))


def _subfacts(result: dict, dimension: str) -> dict:
    return result["dimensions"][dimension]["references"]["subfacts"]


def _envelope(result: dict) -> None:
    """固定结构：五维度、四键、有限状态与原因码、原因有序。"""
    assert result["schema_version"] == SCHEMA_VERSION
    assert set(result["dimensions"]) == set(DIMENSIONS)
    for dimension in result["dimensions"].values():
        assert set(dimension) == {"state", "reasons", "references", "must_not_infer"}
        assert dimension["state"] in STATES
        assert dimension["reasons"] == sorted(dimension["reasons"])
        assert set(dimension["reasons"]) <= REASON_CODES
        assert dimension["must_not_infer"], "每个维度必须带有不得推导结论"
    assert result["coverage"] == "registered_binding_only"
    assert result["shared_runtime_occupants"] == "unknown"
    assert result["skill_isolation"] == "not_established"
    assert result["execution_confirmation_supported"] is False


# 一：登记身份一致 —— 可核对的身份不使其它维度自动可核对。
def test_registered_identity_is_verified_without_claiming_runtime(client, tenant_a, env_a):
    seed = _seed(client, tenant_a, env_a["id"])
    result = _assess(tenant_a, seed["binding_id"])
    _envelope(result)

    registered = result["dimensions"]["registered_identity"]
    assert registered["state"] == "verified_from_records" and registered["reasons"] == []
    assert registered["references"]["asset_id"] == seed["asset_id"]
    assert registered["references"]["agent_instance_id"] == seed["instance_id"]
    assert set(registered["must_not_infer"]) == {
        "active_registration_is_not_runtime_attestation",
        "attestation_is_not_independent_verification",
    }

    device = result["dimensions"]["device_origin"]
    assert device["state"] == "verified_from_records"
    assert device["references"]["asset_device_id"] == seed["edge_id"]
    assert device["references"]["device_revoked"] is False
    assert device["references"]["device_scoped_evidence_count"] == 1
    assert "asset_device_link_is_not_binding_device_origin" in device["must_not_infer"]

    # 记录自洽不等于证据齐全：其余三维度均不可核对，且不返回总体通过结论。
    assert result["dimensions"]["role_skill_version"]["state"] == "evidence_missing"
    assert result["dimensions"]["execution_identity"]["state"] == "evidence_missing"
    assert result["dimensions"]["shared_impact"]["state"] == "capability_not_established"
    assert "verified" not in json.dumps(result["dimensions"]["shared_impact"])


# 二：同名跨租户/跨设备不串联。
def test_same_name_never_merges_across_tenants_or_devices(client, tenant_a, tenant_b, env_a, env_b):
    # 租户 B 需要 policy:manage 才能登记绑定；这里只用于造夹具对象。
    foreign = _seed(client, _operator(tenant_b, "security_admin,agent_owner"), env_b["id"])

    # 跨租户：与“完全不存在”逐维度完全一致，且不泄漏对方标识。
    probe = _assess(tenant_a, foreign["binding_id"])
    absent = _assess(tenant_a, "rb-" + uuid.uuid4().hex)
    _envelope(probe)
    assert probe["dimensions"] == absent["dimensions"]
    assert probe["dimensions"]["registered_identity"]["state"] == "evidence_missing"
    assert probe["dimensions"]["registered_identity"]["reasons"] == ["binding_not_registered_in_tenant"]
    dumped = json.dumps(probe)
    for leak in (foreign["asset_id"], foreign["instance_id"], foreign["edge_id"],
                 foreign["device_identity"], "tnt-B"):
        assert leak not in dumped

    # 跨设备：另一设备上的声明与安装观察不属于本资产。
    device_b = _make_device(env_a["id"])
    first = _seed(client, tenant_a, env_a["id"])
    second = _seed(client, tenant_a, env_a["id"], edge_id=device_b[0], device_identity=device_b[1])
    assert first["edge_id"] != second["edge_id"]
    _declaration(first, [CANARY_NAME])
    with session_scope() as session:
        session.add(SkillInstallation(tenant_id=tenant_a["X-Dev-Tenant-Id"], edge_agent_id=first["edge_id"],
                                      locator_sha256=_hex64()))
    isolated = _subfacts(_assess(tenant_a, second["binding_id"]), "role_skill_version")
    assert isolated["declared_selection"] == {"state": "evidence_missing", "reason": "no_recorded_declaration"}
    assert isolated["installation_observation"]["state"] == "evidence_missing"
    assert isolated["installation_observation"]["installation_count"] == 0
    assert CANARY_NAME not in json.dumps(_assess(tenant_a, second["binding_id"]))

    # 同一资产出现来自其它设备的声明 → 记录不一致，不合并归属。
    _declaration(second, [CANARY_NAME], edge_agent_id=first["edge_id"])
    merged = _assess(tenant_a, second["binding_id"])
    declared = _subfacts(merged, "role_skill_version")["declared_selection"]
    assert declared["state"] == "records_inconsistent"
    assert declared["reason"] == "declaration_device_mismatch"
    assert merged["dimensions"]["role_skill_version"]["state"] == "records_inconsistent"
    assert CANARY_NAME not in json.dumps(merged)


# 三：来源损坏或悬挂引用 —— 一律 fail-closed，不从环境里“任选一台”。
def test_damaged_and_dangling_sources_are_not_papered_over(client, tenant_a, tenant_b, env_a, env_b):
    dangling = _seed(client, tenant_a, env_a["id"], edge_id="edge-" + uuid.uuid4().hex)
    result = _assess(tenant_a, dangling["binding_id"])
    assert result["dimensions"]["device_origin"]["state"] == "source_unavailable"
    assert result["dimensions"]["device_origin"]["reasons"] == ["framework_source_unverifiable"]
    assert "no_device_evidence_must_not_select_any_device" in result["dimensions"]["device_origin"]["must_not_infer"]

    # 其它租户的设备：本层不做跨租户读取，按不可核对处理且不回显对方标识。
    foreign_device = _make_device(env_b["id"])
    cross = _seed(client, tenant_a, env_a["id"])
    _repoint(cross["asset_id"], foreign_device[0])
    cross_result = _assess(tenant_a, cross["binding_id"])
    assert cross_result["dimensions"]["device_origin"]["state"] == "source_unavailable"
    assert cross_result["dimensions"]["device_origin"]["reasons"] == ["framework_source_unverifiable"]
    assert foreign_device[0] not in json.dumps(cross_result)
    assert foreign_device[1] not in json.dumps(cross_result)

    # 设备已吊销。
    revoked = _seed(client, tenant_a, env_a["id"])
    _revoke_device(revoked["edge_id"])
    revoked_result = _assess(tenant_a, revoked["binding_id"])
    assert revoked_result["dimensions"]["device_origin"]["state"] == "source_unavailable"
    assert revoked_result["dimensions"]["device_origin"]["reasons"] == ["device_revoked"]
    assert revoked_result["dimensions"]["device_origin"]["references"]["device_revoked"] is True

    # 设备与同源证据在其它环境：来源本身可核对，但与绑定环境不一致。
    other_env = client.post("/api/v1/environments", headers=tenant_a, json={"name": "readiness-other"}).json()["id"]
    elsewhere = _seed(client, tenant_a, env_a["id"])
    _relocate_device(elsewhere["edge_id"], other_env, elsewhere["evidence_id"])
    moved_result = _assess(tenant_a, elsewhere["binding_id"])
    assert moved_result["dimensions"]["device_origin"]["state"] == "source_unavailable"
    assert moved_result["dimensions"]["device_origin"]["reasons"] == [
        "device_environment_outside_binding_environment"]

    # 来源记录损坏（非法 JSON）与完全无来源记录。
    broken = _seed(client, tenant_a, env_a["id"], source_raw="{not-json")
    assert _assess(tenant_a, broken["binding_id"])["dimensions"]["device_origin"]["reasons"] == [
        "framework_source_unverifiable"]
    absent = _seed(client, tenant_a, env_a["id"], with_source=False)
    assert _assess(tenant_a, absent["binding_id"])["dimensions"]["device_origin"]["state"] == "evidence_missing"
    assert _assess(tenant_a, absent["binding_id"])["dimensions"]["device_origin"]["reasons"] == [
        "no_recorded_framework_source"]


# 四：只有 active / attestation 不能通过运行归属。
def test_active_and_attestation_do_not_prove_runtime_identity(client, tenant_a, env_a):
    seed = _seed(client, tenant_a, env_a["id"], attestation={"boot_proof": CANARY_ATTESTATION})
    result = _assess(tenant_a, seed["binding_id"])

    assert result["dimensions"]["registered_identity"]["state"] == "verified_from_records"
    execution = result["dimensions"]["execution_identity"]
    assert execution["state"] != "verified_from_records"
    attestation = execution["references"]["subfacts"]["operator_attestation"]
    assert attestation == {
        "state": "source_unavailable",
        "reason": "attestation_not_independently_verified",
        "present": True,
    }
    assert execution["references"]["subfacts"]["revision_history"]["state"] == "evidence_missing"
    assert "attestation_is_not_independent_verification" in execution["must_not_infer"]
    assert "historical_revision_is_not_current_revision" in execution["must_not_infer"]
    assert CANARY_ATTESTATION not in json.dumps(result)
    _envelope(result)


# 五：有安装观察不等于真实加载（观察走真实签名上传路径）。
def test_installation_observation_is_recorded_but_not_a_runtime_load(client, tenant_a, upload_case):
    body, upload, _, edge_id, device_identity, env = upload_case
    canary_body = json.loads(json.dumps(body))
    canary_body["observations"][0]["name"] = CANARY_NAME
    assert upload(canary_body).status_code == 200
    seed = _seed(client, tenant_a, env, edge_id=edge_id, device_identity=device_identity)

    result = _assess(tenant_a, seed["binding_id"])
    subfacts = _subfacts(result, "role_skill_version")
    observation = subfacts["installation_observation"]
    assert observation["state"] == "verified_from_records"
    assert observation["installation_count"] == 1
    assert observation["observed_installation_count"] == 1
    assert observation["latest_observation"]["manifest_sha256"] == "b" * 64
    assert observation["latest_observation"]["parse_status"] == "parsed"
    assert subfacts["runtime_load"] == {
        "state": "capability_not_established", "reason": "runtime_load_source_absent"}
    # 有安装观察，但目录候选与显式声明仍无记录：维度为缺失证据，绝不升格为“已验证加载”。
    assert result["dimensions"]["role_skill_version"]["state"] == "evidence_missing"
    assert set(result["dimensions"]["role_skill_version"]["reasons"]) == {
        "no_layout_candidate_recorded", "no_recorded_declaration", "runtime_load_source_absent"}

    must_not_infer = set(result["dimensions"]["role_skill_version"]["must_not_infer"])
    assert {"installation_observation_is_not_runtime_load", "manifest_sha256_is_not_package_version",
            "no_load_record_is_not_no_skill"} <= must_not_infer
    dumped = json.dumps(result)
    assert CANARY_NAME not in dumped and "sample" not in dumped
    assert "locator_sha256" not in dumped and "a" * 64 not in dumped


# 六：只有一条绑定不等于独占（登记数量不是独占判据）。
def test_single_registration_is_not_exclusive_occupancy(client, tenant_a, env_a):
    seed = _seed(client, tenant_a, env_a["id"])
    one = _assess(tenant_a, seed["binding_id"])["dimensions"]["shared_impact"]
    assert one["state"] == "capability_not_established"
    assert one["references"]["registered_active_targets_for_subject"] == 1
    assert set(one["reasons"]) == {
        "runtime_occupancy_source_absent",
        "target_registration_is_unique_per_tenant_backend_target",
        "subject_may_hold_multiple_target_registrations",
    }
    assert "runtime_occupancy_source_absent" in one["reasons"]
    assert "single_registration_is_not_exclusive_occupancy" in one["must_not_infer"]
    assert "user_confirmation_is_not_evidence" in one["must_not_infer"]

    second = _register(client, tenant_a, seed, target="sandbox-" + uuid.uuid4().hex[:8])
    assert second != seed["binding_id"]
    two = _assess(tenant_a, seed["binding_id"])["dimensions"]["shared_impact"]
    assert two["references"]["registered_active_targets_for_subject"] == 2
    assert two["state"] == one["state"] and two["reasons"] == one["reasons"]
    assert two["must_not_infer"] == one["must_not_infer"]


# 七：任何场景都不返回可执行结论。
def test_no_scenario_returns_an_execution_verdict(client, tenant_a, env_a):
    seed = _seed(client, tenant_a, env_a["id"])
    dangling = _seed(client, tenant_a, env_a["id"], edge_id="edge-" + uuid.uuid4().hex)
    revoked = _seed(client, tenant_a, env_a["id"], attestation={"boot_proof": CANARY_ATTESTATION})
    _revoke_device(revoked["edge_id"])
    results = [
        _assess(tenant_a, seed["binding_id"]),
        _assess(tenant_a, dangling["binding_id"]),
        _assess(tenant_a, revoked["binding_id"]),
        _assess(tenant_a, "rb-" + uuid.uuid4().hex),
    ]
    for result in results:
        _envelope(result)
        assert result["execution_confirmation_supported"] is False
        keys = _keys(result)
        assert [key for key in keys
                if any(part in key for part in FORBIDDEN_KEY_PARTS) and key not in DIMENSIONS] == [
            "execution_confirmation_supported"]
        assert "execution_confirmation_supported" in keys
        assert set(result["dimensions"]) == set(DIMENSIONS)


# 八：读取前后无写入，且输出不含合成秘密 canary。
def test_reading_is_write_free_and_leaks_no_synthetic_secrets(
        client, tenant_a, tenant_b, env_a, env_b, upload_case):
    body, upload, _, edge_id, device_identity, env = upload_case
    canary_body = json.loads(json.dumps(body))
    canary_body["observations"][0]["name"] = CANARY_NAME
    assert upload(canary_body).status_code == 200
    seed = _seed(client, tenant_a, env, edge_id=edge_id, device_identity=device_identity,
                 attestation={"boot_proof": CANARY_ATTESTATION})
    _declaration(seed, [CANARY_NAME])
    foreign = _seed(client, _operator(tenant_b, "security_admin,agent_owner"), env_b["id"])

    dangling = _seed(client, tenant_a, env_a["id"], edge_id="edge-" + CANARY_SCOPE,
                     device_identity=CANARY_SCOPE)
    cases = [seed["binding_id"], dangling["binding_id"], foreign["binding_id"], "rb-" + uuid.uuid4().hex]

    before = _counts()
    results = [_assess(tenant_a, binding_id) for binding_id in cases]
    after = _counts()
    assert before == after, "只读检查不得产生任何写入"

    dumped = json.dumps([result["dimensions"] for result in results])
    for canary in (CANARY_NAME, CANARY_ATTESTATION, CANARY_SCOPE,
                   foreign["asset_id"], foreign["instance_id"], foreign["edge_id"],
                   foreign["device_identity"], "tnt-B"):
        assert canary not in dumped


def test_missing_tenant_identity_is_refused_before_any_read(client, tenant_a, env_a):
    seed = _seed(client, tenant_a, env_a["id"])
    with session_scope() as session:
        for identity in (Identity("anon", "anon", ""), Identity("user", "u", None)):
            with pytest.raises(ValueError, match="verified_tenant_identity_required"):
                assess_binding_evidence(session, identity, seed["binding_id"])
        with pytest.raises(ValueError, match="binding_id_required"):
            assess_binding_evidence(session, _identity(tenant_a), "")


@pytest.mark.parametrize("selection", [[], {}, {
    "schema_version": "enterprise-openclaw-skill-selection/v1",
    "source": "agent", "status": "private-canary-invalid-state", "names": [],
}])
def test_invalid_declaration_is_not_verified_or_echoed(client, tenant_a, env_a, selection):
    seed = _seed(client, tenant_a, env_a["id"])
    _declaration(seed, [])
    with session_scope() as session:
        row = session.scalar(select(RoleSkillSelectionObservation).where(
            RoleSkillSelectionObservation.asset_id == seed["asset_id"]))
        row.selection = selection
    # 单独核对声明模型，避免框架不匹配先拒绝而遮蔽损坏结构负例。
    with session_scope() as session:
        declared = _declared_selection(session, seed["tenant_id"], SimpleNamespace(
            id=seed["asset_id"], framework="openclaw", source_type="openclaw_agent"), seed["edge_id"])
        assert declared == {"state": "records_inconsistent", "reason": "declaration_record_invalid"}
    before = _counts()
    result = _assess(tenant_a, seed["binding_id"])
    declared = _subfacts(result, "role_skill_version")["declared_selection"]
    assert declared["state"] == "records_inconsistent"
    assert "private-canary" not in json.dumps(result)
    assert _counts() == before
    _envelope(result)


def test_valid_declaration_is_not_applied_to_another_framework(client, tenant_a, env_a):
    seed = _seed(client, tenant_a, env_a["id"])
    _declaration(seed, [])
    with session_scope() as session:
        declared = _declared_selection(session, seed["tenant_id"], SimpleNamespace(
            id=seed["asset_id"], framework="openclaw", source_type="openclaw_agent"), seed["edge_id"])
    assert declared["state"] == "verified_from_records"
    assert declared["declaration_name_count"] == 0
    assert declared["declaration_status"] == "declared_list"
    result = _assess(tenant_a, seed["binding_id"])
    assert _subfacts(result, "role_skill_version")["declared_selection"] == {
        "state": "records_inconsistent", "reason": "declaration_record_invalid"}


@pytest.mark.parametrize("version,expected", [
    ("v1", "records_inconsistent"), ("v2", "verified_from_records"),
])
def test_directory_candidate_requires_matching_framework(client, tenant_a, env_a, version, expected):
    seed = _seed(client, tenant_a, env_a["id"])
    roots = ({"schema_version": "enterprise-role-skill-roots/v1", "basis": "none",
              "status": "unresolved", "roots": []} if version == "v1" else {
        "schema_version": "enterprise-role-skill-roots/v2", "basis": "hermes_profile_layout",
        "status": "layout_candidate", "roots": [{"kind": "profile_skills", "locator_sha256": "a" * 64}],
    })
    with session_scope() as session:
        asset = session.get(AgentAsset, seed["asset_id"])
        asset.attributes = {**asset.attributes, "skill_source_roots": json.dumps(roots)}
    result = _assess(tenant_a, seed["binding_id"])
    assert _subfacts(result, "role_skill_version")["directory_candidate"]["state"] == expected
    _envelope(result)
