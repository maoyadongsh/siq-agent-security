import json

import pytest

from app.adapters.openshell import enterprise_connection as module
from app.adapters.openshell.contracts import AdapterError


@pytest.fixture
def configured(monkeypatch, tmp_path):
    for name in ("SIQ_AS_OPENSHELL_ENV_SH", "SIQ_AS_OPENSHELL_GATEWAY_INSECURE"):
        monkeypatch.delenv(name, raising=False)
    binary = tmp_path / "fixture-cli"
    binary.write_text("not executed: fixture runner only")
    binary.chmod(0o700)
    monkeypatch.setenv("SIQ_AS_OPENSHELL_CLI_BIN", str(binary))
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "https://fixture.invalid:17671")
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        if argv[-2:] == ["gateway", "info"]:
            return 0, "Version: 0.0.104", ""
        if argv[-1] == "status":
            return 0, "Server Status\nGateway: private-fixture-gateway\nVersion: 0.0.104", ""
        if argv[-1] == "--version":
            return 0, "openshell 0.0.104", ""
        raise AssertionError("non-read command")

    monkeypatch.setattr(module, "run_bounded", run)
    return binary, calls


def test_frozen_connection_handshake_not_enforcement(configured, monkeypatch):
    _, calls = configured
    monkeypatch.setenv("PRIVATE_FIXTURE_TOKEN", "do-not-forward")
    result = module.inspect_connection()
    assert result["status"] == "handshake_verified"
    assert result["gateway_version"] == "0.0.104"
    assert result["ready_for_deployment"] is False and result["execution_evidence"] == "none"
    assert result["credential_scope"] == "unverified" and result["version_compatibility"] == "unverified"
    assert len(result["endpoint_fingerprint"]) == 64 and len(result["gateway_name_sha256"]) == 64
    assert "private-fixture-gateway" not in json.dumps(result) and "fixture.invalid" not in json.dumps(result)
    assert calls and all(0 < kwargs["timeout"] <= 10 for _, kwargs in calls)
    assert all("PRIVATE_FIXTURE_TOKEN" not in kwargs["environment"] for _, kwargs in calls)


@pytest.mark.parametrize("key,value", [
    ("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "http://127.0.0.1:17671"),
    ("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "https://user:private@host"),
    ("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "https://host/private"),
    ("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "https://host?token=private"),
    ("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "https://[invalid"),
    ("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "https://host:invalid"),
    ("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "1"),
    ("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "true"),
    ("SIQ_AS_OPENSHELL_ENV_SH", "/private/script"),
    ("SIQ_AS_OPENSHELL_CLI_BIN", "openshell"),
])
def test_invalid_configuration_never_executes(configured, monkeypatch, key, value):
    _, calls = configured
    monkeypatch.setenv(key, value)
    assert module.inspect_connection()["status"] == "configuration_rejected"
    assert not calls


@pytest.mark.parametrize("fault", ["missing", "writable", "symlink"])
def test_binary_safety_rejects_before_execution(configured, monkeypatch, tmp_path, fault):
    binary, calls = configured
    if fault == "missing":
        monkeypatch.setenv("SIQ_AS_OPENSHELL_CLI_BIN", str(tmp_path / "not-present"))
    elif fault == "writable":
        binary.chmod(0o777)
    else:
        link = tmp_path / "link"
        link.symlink_to(binary)
        monkeypatch.setenv("SIQ_AS_OPENSHELL_CLI_BIN", str(link))
    assert module.inspect_connection()["status"] == "configuration_rejected" and not calls


def test_missing_configuration_and_failure_never_reuse_success(configured, monkeypatch):
    assert module.inspect_connection()["status"] == "handshake_verified"

    def fail(*args, **kwargs):
        raise AdapterError("private diagnostic content")

    monkeypatch.setattr(module, "run_bounded", fail)
    result = module.inspect_connection()
    assert result["status"] == "probe_failed" and result["endpoint_fingerprint"] is None
    assert "private diagnostic" not in json.dumps(result)
    monkeypatch.delenv("SIQ_AS_OPENSHELL_CLI_BIN")
    assert module.inspect_connection()["status"] == "not_configured"


def test_frozen_target_and_context_with_readonly_allowlist(configured, monkeypatch):
    import os

    _, calls = configured
    monkeypatch.setenv("XDG_CONFIG_HOME", "/fixture/original")
    connection = module.ReadOnlyConnection(dict(os.environ))
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "http://changed.invalid")
    monkeypatch.setenv("XDG_CONFIG_HOME", "/fixture/changed")
    connection.probe()
    assert all(argv[2] == "https://fixture.invalid:17671" for argv, _ in calls)
    assert all(kwargs["environment"]["XDG_CONFIG_HOME"] == "/fixture/original" for _, kwargs in calls)
    with pytest.raises(AdapterError, match="operation_refused"):
        connection._readonly_runner(["policy", "set", "target"])


def test_route_authorization_precedes_probe(client, tenant_a, tenant_b, monkeypatch):
    from app.routers import enterprise_connection as router

    env = client.post("/api/v1/environments", headers=tenant_a, json={"name": "connection-fixture"}).json()["id"]
    calls = []
    monkeypatch.setattr(router, "inspect_connection", lambda: calls.append(True) or {"status": "not_configured"})
    url = f"/api/v1/environments/{env}/openshell-connection"
    assert client.get(url, headers=tenant_b).status_code == 404
    assert client.get(url, headers={**tenant_a, "X-Dev-Roles": "viewer"}).status_code == 403
    assert not calls
    response = client.get(url, headers=tenant_a)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["environment_id"] == env and len(calls) == 1


@pytest.mark.parametrize("status,expected", [
    ("Server Status\nGateway: fixture", "version_unknown"),
    ("unrelated server version 0.0.104", "probe_failed"),
    ("", "probe_failed"),
])
def test_status_identity_and_version_not_guessed(configured, monkeypatch, status, expected):
    def run(argv, **kwargs):
        return 0, status if argv[-1] == "status" else "openshell 0.0.104", ""

    monkeypatch.setattr(module, "run_bounded", run)
    result = module.inspect_connection()
    assert result["status"] == expected and result["ready_for_deployment"] is False
    assert result["gateway_version"] == "unknown"


def test_changed_binary_invalidates_probe(configured, monkeypatch):
    binary, _ = configured

    def run(argv, **kwargs):
        if argv[-1] == "status":
            binary.write_text("changed fixture identity during handshake")
            return 0, "Server Status\nGateway: fixture\nVersion: 0.0.104", ""
        return 0, "openshell 0.0.104", ""

    monkeypatch.setattr(module, "run_bounded", run)
    assert module.inspect_connection()["status"] == "probe_failed"


def test_total_budget_prevents_new_child(configured):
    import os

    _, calls = configured
    connection = module.ReadOnlyConnection(dict(os.environ))
    connection.deadline = 0
    with pytest.raises(AdapterError, match="command_timeout"):
        connection._readonly_runner(["status"])
    assert not calls
