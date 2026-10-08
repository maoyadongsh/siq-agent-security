"""测试夹具：dev 模式 + 独立 SQLite 文件。

环境变量必须在任何 app 导入之前设置（app.config 在导入时加载）。
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path

os.environ["SIQ_AS_DEV"] = "1"
os.environ["SIQ_AS_ALLOW_SQLITE"] = "1"

_TMPDIR = tempfile.mkdtemp(prefix="siq-as-test-")
os.environ["SIQ_AS_DATABASE_URL"] = f"sqlite:///{Path(_TMPDIR) / 'test.db'}"
os.environ["SIQ_AS_SIGNING_KEY_FILE"] = str(Path(_TMPDIR) / "control-plane-signing.seed")
os.environ["SIQ_AS_ENFORCEMENT_BACKEND"] = "fake"
_RECOVERY_KEYRING = Path(_TMPDIR) / "synthetic-recovery-keys.json"
_RECOVERY_KEYRING.write_text(json.dumps({
    "active_key_id": "test-only", "keys": {"test-only": base64.b64encode(bytes(range(32))).decode()},
}))
_RECOVERY_KEYRING.chmod(0o600)
os.environ["SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE"] = str(_RECOVERY_KEYRING)

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def isolated_scan_budget(monkeypatch):
    # Each test owns a real budget; requests within a test still share limits.
    from app import scan_budget

    monkeypatch.setattr(scan_budget, "_budget", None)


@pytest.fixture(scope="session")
def client():
    # Contract-only tests do not require the API runtime or its OS dependencies.
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tenant_a():
    """租户 A：dev 身份头注入（仅 dev 模式生效）。"""
    return {
        "X-Dev-Tenant-Id": "tnt-A",
        "X-Dev-User-Id": "user-a",
        "X-Dev-Roles": "tenant_admin,security_admin,agent_owner,platform_operator",
    }


@pytest.fixture(scope="session")
def tenant_b():
    return {
        "X-Dev-Tenant-Id": "tnt-B",
        "X-Dev-User-Id": "user-b",
        "X-Dev-Roles": "tenant_admin,viewer,auditor,platform_operator",
    }


@pytest.fixture(scope="session")
def env_a(client: TestClient, tenant_a: dict):
    resp = client.post(
        "/api/v1/environments",
        json={"name": "dev-host-a", "env_type": "host", "mode": "enforce"},
        headers=tenant_a,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.fixture(scope="session")
def env_b(client: TestClient, tenant_b: dict):
    resp = client.post("/api/v1/environments", json={"name": "dev-host-b"}, headers=tenant_b)
    assert resp.status_code == 201, resp.text
    return resp.json()
