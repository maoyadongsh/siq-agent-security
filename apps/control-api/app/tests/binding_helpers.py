"""测试夹具：RuntimeBinding 登记（P0-1 部署前置）。

asset/instance 无独立写入 API，库内直插；binding 走真实管理端点（含审计/outbox）。
"""

from __future__ import annotations

import uuid


def assign_target_authority(monkeypatch, tmp_path, binding_id, adapter):
    """Explicit synthetic operator assignment; exercises the real file authorizer."""
    import hashlib
    import json
    from datetime import UTC, datetime, timedelta

    from app.db import session_scope
    from app.models import RuntimeBinding

    caps = adapter.probe()
    with session_scope() as session:
        binding = session.get(RuntimeBinding, binding_id)
        item = {field: getattr(binding, field) for field in (
            "tenant_id", "environment_id", "asset_id", "agent_instance_id", "backend_target_id",
        )}
    item.update(id="fixture-assignment", endpoint_fingerprint=caps.endpoint_fingerprint,
                gateway_name_sha256=hashlib.sha256(caps.handshake_gateway.encode()).hexdigest())
    now = datetime.now(UTC)
    catalog = {"schema_version": "enterprise-runtime-target-authority/v1",
               "issued_at": (now - timedelta(minutes=1)).isoformat(),
               "expires_at": (now + timedelta(hours=1)).isoformat(), "assignments": [item]}
    path = tmp_path / "target-authority.json"
    path.write_text(json.dumps(catalog))
    path.chmod(0o600)
    monkeypatch.setenv("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE", str(path))
    return path


def make_instance(
    tenant_id: str,
    env_id: str,
    *,
    asset_name: str | None = None,
    owner_user_id: str | None = None,
):
    """库内直插 confirmed 资产 + 实例，返回 (asset_id, instance_id)。"""
    from app.db import session_scope
    from app.models import AgentAsset, AgentInstance

    with session_scope() as session:
        asset = AgentAsset(
            tenant_id=tenant_id,
            name=asset_name or f"asset-{uuid.uuid4().hex[:8]}",
            status="confirmed",
            owner_user_id=owner_user_id,
        )
        session.add(asset)
        session.flush()
        instance = AgentInstance(
            tenant_id=tenant_id, asset_id=asset.id, environment_id=env_id, runtime="hermes"
        )
        session.add(instance)
        session.flush()
        asset_id, instance_id = asset.id, instance.id
        session.commit()
    return asset_id, instance_id


def make_binding(client, headers, env_id, *, backend="fake", target=None, tenant_id=None):
    """造 asset/instance + 经 API 登记 active RuntimeBinding，返回 (binding, asset_id, instance_id)。"""
    tid = tenant_id or headers["X-Dev-Tenant-Id"]
    target = target or f"sandbox-{uuid.uuid4().hex[:8]}"
    asset_id, instance_id = make_instance(tid, env_id)
    resp = client.post(
        "/api/v1/runtime-bindings",
        json={
            "agent_instance_id": instance_id,
            "environment_id": env_id,
            "backend": backend,
            "backend_target_id": target,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json(), asset_id, instance_id
