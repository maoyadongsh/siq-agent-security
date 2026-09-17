"""OpenShellHttpClient 测试（httpx.MockTransport，不依赖真实网关）。

锁定：fail-closed（不可达/非 JSON → AdapterError）、未联调写路径零写入拒绝、
能力探测驱动编译、正负向验证语义。
"""

from __future__ import annotations

import httpx
import pytest

from app.adapters.openshell.client import OpenShellHttpClient
from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.policy_safety import policy_digest


def _policy(endpoint: str = "api.example.com:443") -> dict:
    host, port = endpoint.rsplit(":", 1)
    return {
        "version": 1,
        "network_policies": {
            "managed": {
                "name": "managed",
                "endpoints": [{"host": host, "port": int(port)}],
                "binaries": [{"path": "/usr/bin/curl"}],
            }
        },
    }


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


def test_apply_dynamic_is_disabled_until_full_policy_cas_is_verified():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"detail": "revision conflict"}, 409)

    client = _client(handler)
    from app.adapters.openshell.contracts import ChangePlan

    with pytest.raises(AdapterError, match="policy_fidelity_unavailable"):
        client.apply_dynamic(
            "s-1",
            ChangePlan(target="s-1", kind="dynamic", expected_revision="1", artifact_hash="h"),
            "1",
        )


def test_create_generation_is_disabled_without_verified_receipt_contract():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"revision": "2"})

    from app.adapters.openshell.contracts import CompiledPolicy

    compiled = CompiledPolicy("p1", 1, "openshell", "v1", {}, "a" * 64)
    with pytest.raises(AdapterError, match="generation_unavailable"):
        _client(handler).create_generation("s-1", compiled)
    assert calls == 0


def test_gateway_error_body_is_not_exposed():
    canary = "SYNTHETIC_SECRET_DO_NOT_EXPOSE"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=canary)

    with pytest.raises(AdapterError) as exc_info:
        _client(handler).read_effective_policy("s-1")
    assert canary not in str(exc_info.value)


def test_read_effective_policy_returns_backend_state():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "revision": "7",
                "policy": _policy(),
                "enforcement_mode": "block",
            }
        )

    snapshot = _client(handler).read_effective_policy("s-1")
    assert snapshot.revision == "7"
    assert snapshot.network[0]["endpoint"] == "api.example.com:443"


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
            "network": [{"endpoint": "x.example:443", "effect": "allow", "binary_paths": ["/usr/bin/curl"]}],
            "enforcement_mode": "block",
        }
    )
    assert compiled.needs_generation is True  # 无动态更新 → 静态路径
    assert "network.dynamic_update" in compiled.unsupported_by_backend


def test_verify_full_digest_does_not_require_an_invented_deny_probe():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "revision": "2",
                "policy": _policy("allowed.example.com:443"),
                "enforcement_mode": "block",
            }
        )

    from app.adapters.openshell.contracts import DeploymentReceipt

    client = _client(handler)
    report = client.verify(
        "s-1",
        checks={"expect_allow": ["allowed.example.com:443"], "expect_deny": []},
        receipt=DeploymentReceipt(
            backend_revision="2", applied_policy_digest=policy_digest(_policy("allowed.example.com:443"))
        ),
    )
    assert report.passed is True
    assert report.deny_checks == []

    report2 = client.verify(
        "s-1",
        checks={"expect_allow": ["allowed.example.com:443"], "expect_deny": ["evil.example.com:443"]},
        receipt=DeploymentReceipt(
            backend_revision="2", applied_policy_digest=policy_digest(_policy("allowed.example.com:443"))
        ),
    )
    assert report2.passed is True, report2.failures


def test_http_client_implements_same_contract_as_cli_backend():
    """HTTP transport 与 CLI transport 实现同一套 EnforcementAdapter 合同（签名逐一对齐）。"""
    import inspect

    from app.adapters.openshell.base import EnforcementAdapter
    from app.adapters.openshell.cli_backend import OpenShellCliBackend

    assert issubclass(OpenShellHttpClient, EnforcementAdapter)
    assert issubclass(OpenShellCliBackend, EnforcementAdapter)
    contract_methods = [
        "probe",
        "list_targets",
        "read_effective_policy",
        "compile",
        "validate",
        "plan_change",
        "apply_dynamic",
        "create_generation",
        "verify",
        "rollback",
        "stream_events",
    ]
    for name in contract_methods:
        expected = inspect.signature(getattr(EnforcementAdapter, name))
        assert inspect.signature(getattr(OpenShellHttpClient, name)) == expected, name
        assert inspect.signature(getattr(OpenShellCliBackend, name)) == expected, name


# ------------------------------------------------------------ P1-1/P1-2/P1-11：合同对齐


def test_probe_capability_document_from_gateway_response():
    """P1-1：能力文档只采纳网关如实上报的项；未报告项一律 unknown（fail-closed）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/health":
            return _json_response({"ok": True})
        if request.url.path == "/v1/capabilities":
            return _json_response(
                {
                    "schema_version": "v2",
                    "capabilities": {
                        "network_l34": {"status": "supported", "semantics": "enforce", "basis": "gw"},
                        "enforcement_mode.block": {"status": "supported", "semantics": "enforce"},
                    },
                }
            )
        return _json_response({"detail": "not found"}, 404)

    caps = _client(handler).probe()
    assert caps.capability("network_l34").status == "supported"
    assert caps.capability("enforcement_mode.block").status == "supported"
    # 未报告 → unknown，不猜 supported
    assert caps.capability("tools_mcp").status == "unknown"
    assert caps.capability("enforcement_mode.warn").status == "unknown"


def test_read_effective_policy_mode_defaults_to_unknown_when_absent():
    """P1-11：网关响应未携带 enforcement_mode 时如实 unknown，不默认编造 block。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"revision": "7", "policy": {"version": 1}})

    snapshot = _client(handler).read_effective_policy("s-1")
    assert snapshot.enforcement_mode == "unknown"


def test_verify_level_readback_on_pass_and_failed_on_failure():
    """P1-2：HTTP transport 同为配置读回——通过 readback_verified，失败 failed。"""
    from app.adapters.openshell.contracts import DeploymentReceipt

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "revision": "2",
                "policy": _policy("allowed.example.com:443"),
                "enforcement_mode": "block",
            }
        )

    client = _client(handler)
    ok = client.verify(
        "s-1",
        checks={"expect_allow": ["allowed.example.com:443"], "expect_deny": ["evil.example.com:443"]},
        receipt=DeploymentReceipt(
            backend_revision="2", applied_policy_digest=policy_digest(_policy("allowed.example.com:443"))
        ),
    )
    assert ok.passed is True
    assert ok.level == "readback_verified"
    assert ok.allow_checks[0]["expected"] == "allow"
    assert ok.allow_checks[0]["actual"] == "allow"

    bad = client.verify(
        "s-1",
        checks={"expect_allow": ["missing.example.com:443"], "expect_deny": ["evil.example.com:443"]},
        receipt=DeploymentReceipt(
            backend_revision="2", applied_policy_digest=policy_digest(_policy("allowed.example.com:443"))
        ),
    )
    assert bad.passed is False
    assert bad.level == "failed"
    assert bad.allow_checks[0]["actual"] == "not_in_allow_set"


def test_stream_events_labels_gateway_source():
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"events": [{"type": "policy.applied"}], "cursor": "c2"})

    batch = _client(handler).stream_events()
    assert batch.source == "gateway_events"
