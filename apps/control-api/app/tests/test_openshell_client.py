"""OpenShellHttpClient 测试（httpx.MockTransport，不依赖真实网关）。

锁定：fail-closed（不可达/非 JSON → AdapterError）、409 → RevisionConflict、
能力探测驱动编译、正负向验证语义。
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.openshell.client import OpenShellHttpClient
from app.adapters.openshell.contracts import AdapterError, RevisionConflict


def _client(handler) -> OpenShellHttpClient:
    return OpenShellHttpClient("https://gw.test", transport=httpx.MockTransport(handler))


def _json_response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def test_probe_builds_capabilities_from_actual_response():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return _json_response({"ok": True})
        if request.url.path == "/v1/capabilities":
            return _json_response(
                {
                    "schema_version": "v2",
                    "dynamic_network_update": True,
                    "interceptor": True,
                    "landlock": True,
                    "provider_credential_injection": False,
                }
            )
        return _json_response({"detail": "not found"}, 404)

    caps = _client(handler).probe()
    assert caps.dynamic_network_update is True
    assert caps.interceptor is True
    assert caps.schema_version == "v2"


def test_probe_fail_closed_on_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(AdapterError):
        _client(handler).probe()


def test_apply_dynamic_maps_409_to_revision_conflict():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"detail": "revision conflict"}, 409)

    client = _client(handler)
    from app.adapters.openshell.contracts import ChangePlan

    with pytest.raises(RevisionConflict):
        client.apply_dynamic("s-1", ChangePlan(target="s-1", kind="dynamic", expected_revision="1", artifact_hash="h"), "1")


def test_read_effective_policy_returns_backend_state():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "revision": "7",
                "network_policies": [{"endpoint": "api.example.com", "effect": "allow"}],
                "enforcement_mode": "block",
            }
        )

    snapshot = _client(handler).read_effective_policy("s-1")
    assert snapshot.revision == "7"
    assert snapshot.network[0]["endpoint"] == "api.example.com"


def test_non_json_response_fails_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>gateway</html>")

    with pytest.raises(AdapterError):
        _client(handler).read_effective_policy("s-1")


def test_compile_uses_probed_capabilities():
    """编译必须基于探测能力（不按版本号假设）。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return _json_response({"ok": True})
        if request.url.path == "/v1/capabilities":
            return _json_response({"dynamic_network_update": False})
        return _json_response({"detail": "not found"}, 404)

    compiled = _client(handler).compile(
        {
            "policy_id": "p1",
            "version": 1,
            "selector": {"agent_ids": ["a"]},
            "network": [{"endpoint": "x", "effect": "allow"}],
            "enforcement_mode": "block",
        }
    )
    assert compiled.needs_generation is True  # 无动态更新 → 静态路径
    assert "network.dynamic_update" in compiled.unsupported_by_backend


def test_verify_requires_both_allow_and_deny():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "revision": "2",
                "network_policies": [{"endpoint": "allowed.example.com", "effect": "allow"}],
                "enforcement_mode": "block",
            }
        )

    from app.adapters.openshell.contracts import DeploymentReceipt

    client = _client(handler)
    report = client.verify(
        "s-1",
        checks={"expect_allow": ["allowed.example.com"], "expect_deny": []},
        receipt=DeploymentReceipt(backend_revision="2", evidence={}),
    )
    assert report.passed is False
    assert any("正负向" in f for f in report.failures)

    report2 = client.verify(
        "s-1",
        checks={"expect_allow": ["allowed.example.com"], "expect_deny": ["evil.example.com"]},
        receipt=DeploymentReceipt(backend_revision="2", evidence={}),
    )
    assert report2.passed is True, report2.failures
