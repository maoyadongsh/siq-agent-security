"""P1 审计修复测试：P1-7 跨租户引用校验 / P1-8 制品指纹入账 / P1-10 baseline 确定性信号。

安全修复负向测试（AGENTS.md：安全修复必须带负向测试证明旧行为被拒绝）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.classification import _baseline_classify
from app.db import session_scope
from app.models import AgentAsset, System, Tenant
from app.tests.edge_helpers import candidate, create_scan_task, register_edge, signed_batch, signed_evidence


def _ensure_tenant(session, tenant_id: str) -> None:
    if session.query(Tenant).filter(Tenant.id == tenant_id).count() == 0:
        session.add(Tenant(id=tenant_id, name=f"Tenant {tenant_id}"))


def _upload_candidate(
    client,
    headers: dict,
    name: str,
    *,
    env_id: str | None = None,
    edge_identity: str | None = None,
    artifact_digest: str | None = None,
    attributes: dict | None = None,
    source_locator: str | None = None,
    evidence_id: str | None = None,
) -> dict:
    """经 Edge 批次上传一个候选（可带 artifact_digest/attributes），返回资产 JSON。"""
    if env_id is None:
        env_resp = client.post("/api/v1/environments", json={"name": f"env-p1-{name}"}, headers=headers)
        assert env_resp.status_code == 201, env_resp.text
        env_id = env_resp.json()["id"]
    identity = edge_identity or f"edge-p1-{name}"
    evidence_id = evidence_id or f"ev-p1-{name}-{datetime.now(UTC).timestamp()}"
    edge_headers, private_key = register_edge(client, headers, env_id, identity)
    task_id = create_scan_task(client, headers, env_id)
    evidence = signed_evidence(
        private_key,
        identity,
        evidence_id,
        source_locator=source_locator or f"hermes_profile://{name}",
    )
    cand = candidate(name, [evidence_id])
    if source_locator:
        cand["source_locator"] = source_locator
        cand["candidate_id"] = f"hermes_profile:{name}:{evidence_id}"
    if artifact_digest:
        cand["artifact_digest"] = artifact_digest
    if attributes:
        cand["attributes"] = attributes
    batch = signed_batch(private_key, task_id, candidates=[cand], evidence=[evidence])
    upload = client.post("/edge/v1/batches", json=batch, headers=edge_headers)
    assert upload.status_code == 200, upload.text
    assets = client.get("/api/v1/candidates", headers=headers).json()
    return next(a for a in assets if a["name"] == name)


def _get_asset_row(asset_id: str) -> AgentAsset:
    with session_scope() as session:
        return session.get(AgentAsset, asset_id)


# ------------------------------------------------------------ P1-7 跨租户引用校验


def test_confirm_rejects_cross_tenant_system_ref(client, tenant_a):
    """负向：body.system_id 指向他租户 System → 422 invalid_system_ref（旧行为直接写入）。"""
    with session_scope() as session:
        _ensure_tenant(session, "tnt-B")
        foreign = System(tenant_id="tnt-B", name="billing-b")
        session.add(foreign)
        session.flush()
        foreign_id = foreign.id
    asset = _upload_candidate(client, tenant_a, "p1-confirm-cross")
    resp = client.post(
        f"/api/v1/candidates/{asset['id']}/confirm",
        json={"system_id": foreign_id},
        headers=tenant_a,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_system_ref"
    # 状态未被改动
    refreshed = client.get(f"/api/v1/agents/{asset['id']}", headers=tenant_a).json()
    assert refreshed["status"] == "candidate"
    assert refreshed["system_id"] is None


def test_confirm_rejects_nonexistent_system_ref(client, tenant_a):
    """负向：不存在的 system_id 同样 422（请求体引用不享受 404 路径语义）。"""
    asset = _upload_candidate(client, tenant_a, "p1-confirm-missing")
    resp = client.post(
        f"/api/v1/candidates/{asset['id']}/confirm",
        json={"system_id": "sys_does_not_exist"},
        headers=tenant_a,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "invalid_system_ref"


def test_confirm_accepts_same_tenant_system_ref(client, tenant_a):
    """正向：同租户合法 system_id 正常确认并落 system_id。"""
    with session_scope() as session:
        _ensure_tenant(session, "tnt-A")
        system = System(tenant_id="tnt-A", name="finance-a")
        session.add(system)
        session.flush()
        system_id = system.id
    asset = _upload_candidate(client, tenant_a, "p1-confirm-ok")
    resp = client.post(
        f"/api/v1/candidates/{asset['id']}/confirm",
        json={"system_id": system_id, "owner_user_id": "user-a", "role": "advisor"},
        headers=tenant_a,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["system_id"] == system_id
    assert body["owner_user_id"] == "user-a"


def test_confirm_rejects_malformed_owner_user_id(client, tenant_a):
    """负向：owner_user_id 格式非法 → 422（存在性由 SIQ IAM 保证，此处只校验格式）。"""
    asset = _upload_candidate(client, tenant_a, "p1-confirm-badowner")
    resp = client.post(
        f"/api/v1/candidates/{asset['id']}/confirm",
        json={"owner_user_id": "bad owner!"},
        headers=tenant_a,
    )
    assert resp.status_code == 422


# ------------------------------------------------------------ P1-8 制品指纹入账


def test_ingest_persists_artifact_digest_and_attributes(client, tenant_a):
    asset = _upload_candidate(
        client,
        tenant_a,
        "p1-digest",
        artifact_digest="sha256:" + "1" * 64,
        attributes={"profile": "finance", "runtime": "hub"},
    )
    row = _get_asset_row(asset["id"])
    assert row.artifact_digest == "sha256:" + "1" * 64
    assert row.attributes["profile"] == "finance"
    assert row.attributes["runtime"] == "hub"


def test_redigest_on_same_source_locator_updates_with_trace(client, tenant_a):
    """重复上报同 source_locator 不同 digest：字段更新，旧值保留在 digest_observations。"""
    env_resp = client.post("/api/v1/environments", json={"name": "env-p1-redigest"}, headers=tenant_a)
    env_id = env_resp.json()["id"]
    locator = "hermes_profile://p1-redigest"
    asset = _upload_candidate(
        client,
        tenant_a,
        "p1-redigest",
        env_id=env_id,
        artifact_digest="sha256:" + "a" * 64,
        source_locator=locator,
        evidence_id="ev-p1-redigest-1",
    )
    updated = _upload_candidate(
        client,
        tenant_a,
        "p1-redigest",  # 同名同 locator：命中 uq_asset_source 去重合并路径
        env_id=env_id,
        edge_identity="edge-p1-redigest-2",
        artifact_digest="sha256:" + "b" * 64,
        source_locator=locator,
        evidence_id="ev-p1-redigest-2",
    )
    assert updated["id"] == asset["id"]  # 合并到既有资产而非新建
    row = _get_asset_row(asset["id"])
    assert row.artifact_digest == "sha256:" + "b" * 64
    observations = row.attributes["digest_observations"]
    assert observations[-1]["from"] == "sha256:" + "a" * 64
    assert observations[-1]["to"] == "sha256:" + "b" * 64


def test_ingest_digest_is_tenant_scoped(client, tenant_a, tenant_b):
    """跨租户不串：同 source_locator 在两个租户各自入账，互不影响 digest。"""
    locator = "hermes_profile://p1-shared-locator"
    asset_a = _upload_candidate(
        client,
        tenant_a,
        "p1-shared-a",
        artifact_digest="sha256:" + "a" * 64,
        source_locator=locator,
    )
    asset_b = _upload_candidate(
        client,
        tenant_b,
        "p1-shared-b",
        artifact_digest="sha256:" + "9" * 64,
        source_locator=locator,
    )
    assert asset_a["id"] != asset_b["id"]
    assert _get_asset_row(asset_a["id"]).artifact_digest == "sha256:" + "a" * 64
    assert _get_asset_row(asset_b["id"]).artifact_digest == "sha256:" + "9" * 64


# ------------------------------------------------------------ P1-10 baseline 确定性信号


def test_baseline_known_framework_marks_anonymous_name_as_candidate():
    """framework=hermes 的匿名名称资产（无关键词）也被判为候选，且给出能力提示。"""
    asset = AgentAsset(
        tenant_id="tnt-A", name="svc-x9-runner", framework="hermes", source_type="hermes_profile"
    )
    output = _baseline_classify(asset)
    assert output["is_agent_candidate"] is True
    assert "hub-runtime" in output["capability_hints"]
    assert output["confidence"] == 0.6  # 单一框架信号：低置信 → needs_review 由 classify_asset 执行


def test_baseline_capability_hints_from_source_type():
    asset = AgentAsset(tenant_id="tnt-A", name="agent-on-docker", framework="unknown", source_type="docker")
    output = _baseline_classify(asset)
    assert "containerized" in output["capability_hints"]


def test_baseline_system_candidates_from_existing_link():
    asset = AgentAsset(tenant_id="tnt-A", name="legal-advisor", framework="unknown", system_id="sys_1")
    output = _baseline_classify(asset)
    assert output["system_candidates"] == [{"system_id": "sys_1", "source": "asset_link", "confidence": 1.0}]


def test_baseline_no_signal_behavior_unchanged():
    """无 framework 信号且无名称关键词：行为与 P1-10 之前完全一致。"""
    # source_type 用无能力提示映射的 "human"（process_list 自 P1-4 起映射 host-process 提示）
    asset = AgentAsset(
        tenant_id="tnt-A", name="postgres-backup", framework="unknown", source_type="human"
    )
    output = _baseline_classify(asset)
    assert output["is_agent_candidate"] is False
    assert output["role"] is None
    assert output["confidence"] == 0.3
    assert output["capability_hints"] == []
    assert output["system_candidates"] == []
    assert output["unresolved_questions"] == ["未能从名称归纳业务角色", "未发现可验证的负责人信息"]
