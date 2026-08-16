"""OpenShellCliBackend 测试：夹具为 2026-08-13 活网关（v0.0.83）实测捕获的真实输出。

锁定语义：有效策略解析、动态 policy set（静态段一致+网络段替换）、revision 校验、
版本回执解析、sandbox list 解码缺陷的 docker 兜底、fail-closed。
"""

from __future__ import annotations

import os

import pytest

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError, DeploymentReceipt, RevisionConflict

# 实测捕获：openshell policy get siq-as-live --full（截取）
REAL_POLICY_GET_FULL = """Version:      1
Hash:         21ca0b7c8c0ee3fe71660bb18960bdb2d572b6904f6a22338eba727ca26add43
Status:       Loaded
Active:       1
Created:      1786632645924 ms
Loaded:       1786632646253 ms
---
version: 1
filesystem_policy:
  include_workdir: true
  read_only:
  - /usr
  - /lib
  - /proc
  - /dev/urandom
  - /app
  - /etc
  - /var/log
  read_write:
  - /sandbox
  - /tmp
  - /dev/null
landlock:
  compatibility: best_effort
process:
  run_as_user: sandbox
  run_as_group: sandbox
"""

# 实测捕获：policy set 成功输出
REAL_POLICY_SET_OK = "\x1b[1m\x1b[32m✓\x1b[39m\x1b[0m Policy version 2 submitted (hash: 5385cd2cf66f)\n"

# 实测捕获：静态段变更被拒
REAL_POLICY_SET_FS_REJECT = (
    "Error:   × status: InvalidArgument, message: \"filesystem include_workdir cannot be "
    "changed on a live sandbox\", details: [], metadata: MetadataMap { headers: {\"content-type\": "
    "\"application/grpc\", ...}}"
)

GATEWAY_INFO = "Gateway Info\n  Gateway: siq-openshell-dev\n  Gateway endpoint: https://127.0.0.1:17671\n"


def _backend(responses: dict[tuple, tuple[int, str, str]]) -> OpenShellCliBackend:
    def runner(args: list[str]) -> tuple[int, str, str]:
        key = tuple(args)
        if key in responses:
            return responses[key]
        return 1, "", f"unexpected args: {key}"

    return OpenShellCliBackend(runner=runner, env_script="/nonexistent/env.sh")


def test_read_effective_policy_parses_real_output():
    backend = _backend({("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, "")})
    snapshot = backend.read_effective_policy("s1")
    assert snapshot.revision == "1"
    assert snapshot.filesystem["read_only"][0] == "/usr"
    assert snapshot.process["run_as_user"] == "sandbox"
    assert snapshot.network == []  # 该策略无网络段


def test_probe_reports_measured_capabilities():
    backend = _backend({("gateway", "info"): (0, GATEWAY_INFO, "")})
    caps = backend.probe()
    assert caps.dynamic_network_update is True  # 2026-08-13 实测
    assert caps.static_filesystem is True
    assert caps.revision_support is True


def test_apply_dynamic_merges_static_and_replaces_network(tmp_path):
    responses = {
        ("gateway", "info"): (0, GATEWAY_INFO, ""),
        ("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    set_calls: list[list[str]] = []
    merged_docs: list[dict] = []

    def runner(args):
        if tuple(args[:2]) == ("policy", "set"):
            set_calls.append(args)
            import yaml as _yaml

            merged_docs.append(_yaml.safe_load(open(args[4])))  # CLI 读取期文件必须存在
            return 0, REAL_POLICY_SET_OK, ""
        return responses.get(tuple(args), (1, "", f"unexpected: {args}"))

    backend = OpenShellCliBackend(runner=runner)
    compiled = backend.compile(
        {
            "policy_id": "p1",
            "version": 1,
            "selector": {"agent_ids": ["a"]},
            "network": [{"endpoint": "api.example.com:443", "effect": "allow", "binary_paths": ["/usr/bin/curl"]}],
            "enforcement_mode": "block",
        }
    )
    plan = backend.plan_change("s1", compiled)
    assert plan.kind == "dynamic"  # 无静态段变化 → 动态路径
    receipt = backend.apply_dynamic("s1", plan, expected_revision="1")
    assert receipt.backend_revision == "2"
    assert receipt.evidence["snapshot_hash"] == "5385cd2cf66f"
    # 合并后的 YAML 必须保留静态段 + 携带网络段
    merged = merged_docs[0]
    assert merged["filesystem_policy"]["read_only"][0] == "/usr"
    assert "demo_allowed_api" not in merged["network_policies"]  # 名称按编译制品生成
    assert len(merged["network_policies"]) == 1
    # 临时策略文件在 CLI 读取完成后立即删除（不泄漏）
    assert not os.path.exists(set_calls[0][4])


def test_apply_dynamic_tempfile_cleaned_on_cli_error():
    """CLI 失败路径：临时策略文件同样删除（try/finally 清理点）。"""
    responses = {
        ("gateway", "info"): (0, GATEWAY_INFO, ""),
        ("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    set_calls: list[list[str]] = []

    def runner(args):
        if tuple(args[:2]) == ("policy", "set"):
            set_calls.append(args)
            return 1, "", "gateway rejected"
        return responses.get(tuple(args), (1, "", f"unexpected: {args}"))

    backend = OpenShellCliBackend(runner=runner)
    compiled = backend.compile(
        {"policy_id": "p", "version": 1, "selector": {"agent_ids": ["a"]}, "network": [], "enforcement_mode": "block"}
    )
    plan = backend.plan_change("s1", compiled)
    with pytest.raises(AdapterError):
        backend.apply_dynamic("s1", plan, expected_revision="1")
    assert set_calls and not os.path.exists(set_calls[0][4])


def test_apply_dynamic_revision_conflict():
    responses = {
        ("gateway", "info"): (0, GATEWAY_INFO, ""),
        ("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    backend = _backend(responses)
    compiled = backend.compile(
        {"policy_id": "p", "version": 1, "selector": {"agent_ids": ["a"]}, "network": [], "enforcement_mode": "block"}
    )
    plan = backend.plan_change("s1", compiled)
    with pytest.raises(RevisionConflict):
        backend.apply_dynamic("s1", plan, expected_revision="0")  # 实际是 1


def test_apply_dynamic_idempotent_unchanged_policy():
    """实测网关语义：内容未变 → 'Policy unchanged (version N)'，视为成功（幂等重放）。"""
    responses = {
        ("gateway", "info"): (0, GATEWAY_INFO, ""),
        ("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    unchanged = "· Policy unchanged (version 5, hash: 12f756c6915d)\n"

    def runner(args):
        if tuple(args[:2]) == ("policy", "set"):
            return 0, unchanged, ""
        return responses.get(tuple(args), (1, "", f"unexpected: {args}"))

    backend = OpenShellCliBackend(runner=runner)
    compiled = backend.compile(
        {"policy_id": "p", "version": 1, "selector": {"agent_ids": ["a"]}, "network": [], "enforcement_mode": "block"}
    )
    plan = backend.plan_change("s1", compiled)
    receipt = backend.apply_dynamic("s1", plan, expected_revision="1")
    assert receipt.backend_revision == "5"
    assert receipt.evidence["snapshot_hash"] == "12f756c6915d"


def test_fs_change_rejected_by_gateway_is_adapter_error():
    responses = {
        ("gateway", "info"): (0, GATEWAY_INFO, ""),
        ("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    calls = {"n": 0}

    def runner(args):
        if tuple(args[:2]) == ("policy", "set"):
            calls["n"] += 1
            return 1, REAL_POLICY_SET_FS_REJECT, ""
        return responses.get(tuple(args), (1, "", f"unexpected: {args}"))

    backend = OpenShellCliBackend(runner=runner)
    compiled = backend.compile(
        {"policy_id": "p", "version": 1, "selector": {"agent_ids": ["a"]}, "network": [], "enforcement_mode": "block"}
    )
    plan = backend.plan_change("s1", compiled)
    with pytest.raises(AdapterError):
        backend.apply_dynamic("s1", plan, expected_revision="1")


def test_rollback_reports_gateway_reported_revision_and_cleans_tempfile():
    """回滚成功：restored_revision 如实采用网关回执版本号；临时策略文件在 CLI 读取后删除。"""
    responses = {
        ("policy", "get", "s1", "--rev", "1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    set_calls: list[list[str]] = []

    def runner(args):
        if tuple(args[:2]) == ("policy", "set"):
            set_calls.append(args)
            return 0, "✓ Policy version 3 submitted (hash: 3f3f3f3f)\n", ""
        return responses.get(tuple(args), (1, "", f"unexpected: {args}"))

    backend = OpenShellCliBackend(runner=runner)
    receipt = backend.rollback("s1", DeploymentReceipt(backend_revision="2", evidence={}))
    assert receipt.restored_revision == "3"  # 网关如实上报的版本号，而非推算的 prev_rev
    assert set_calls and not os.path.exists(set_calls[0][4])


def test_rollback_unparseable_set_receipt_fails_closed():
    """policy set 成功但回执不可解析：如实报失败（不伪造 restored_revision=prev_rev）。"""
    responses = {
        ("policy", "get", "s1", "--rev", "1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    set_calls: list[list[str]] = []

    def runner(args):
        if tuple(args[:2]) == ("policy", "set"):
            set_calls.append(args)
            return 0, "unexpected output without version receipt\n", ""
        return responses.get(tuple(args), (1, "", f"unexpected: {args}"))

    backend = OpenShellCliBackend(runner=runner)
    with pytest.raises(AdapterError, match="回执"):
        backend.rollback("s1", DeploymentReceipt(backend_revision="2", evidence={}))
    assert set_calls and not os.path.exists(set_calls[0][4])


def test_rollback_missing_backend_revision_fails_structured():
    """空 backend_revision：结构化 AdapterError（此前 int('') 抛未捕获 ValueError → 500）。"""
    backend = OpenShellCliBackend(runner=lambda a: (1, "", "unused"))
    with pytest.raises(AdapterError, match="backend_revision"):
        backend.rollback("s1", DeploymentReceipt(backend_revision="", evidence={}))


def test_rollback_invalid_backend_revision_fails_structured():
    """非法 backend_revision：结构化 AdapterError，不伪造恢复。"""
    backend = OpenShellCliBackend(runner=lambda a: (1, "", "unused"))
    with pytest.raises(AdapterError, match="backend_revision"):
        backend.rollback("s1", DeploymentReceipt(backend_revision="12abc", evidence={}))


def test_rollback_whitespace_revision_accepted():
    """带空白的 revision 可解析（与路由端 str() 直传保持一致）。"""
    responses = {
        ("policy", "get", "s1", "--rev", "1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }

    def runner(args):
        if tuple(args[:2]) == ("policy", "set"):
            return 0, "✓ Policy version 3 submitted (hash: 3f3f3f3f)\n", ""
        return responses.get(tuple(args), (1, "", f"unexpected: {args}"))

    backend = OpenShellCliBackend(runner=runner)
    receipt = backend.rollback("s1", DeploymentReceipt(backend_revision=" 2 ", evidence={}))
    assert receipt.restored_revision == "3"


def test_sandbox_list_decode_bug_falls_back_to_docker():
    def runner(args):
        if tuple(args[:2]) == ("sandbox", "list"):
            return 1, "", "status: Internal, message: failed to decode Protobuf message: Sandbox.id"
        return 1, "", f"unexpected: {args}"

    def docker_runner(args):
        return 0, "openshell-siq-as-live-8515c645-1682-4814-965d-e6b330e2af2e\n", ""

    backend = OpenShellCliBackend(runner=runner, docker_runner=docker_runner)
    page = backend.list_targets()
    assert page.targets == [{"id": "siq-as-live"}]


def test_sandbox_list_docker_fallback_failure_is_fail_closed():
    def runner(args):
        return 1, "", "protobuf decode error"

    def docker_runner(args):
        return 1, "", "docker daemon unavailable"

    backend = OpenShellCliBackend(runner=runner, docker_runner=docker_runner)
    with pytest.raises(AdapterError, match="docker"):
        backend.list_targets()


def test_cli_failure_is_fail_closed():
    def runner(args):
        return 1, "", "boom"

    backend = OpenShellCliBackend(runner=runner)
    with pytest.raises(AdapterError):
        backend.read_effective_policy("x")


def test_cli_backend_targets_v104_gateway_via_env(monkeypatch):
    """v0.0.104 直连：SIQ_AS_OPENSHELL_CLI_BIN + ENDPOINT 绕过 env.sh（canary 隔离不破坏）。"""
    monkeypatch.setenv("SIQ_AS_OPENSHELL_CLI_BIN", "/opt/os104/openshell")
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "http://127.0.0.1:17673")
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "1")

    captured: list[list[str]] = []

    def runner(args):
        captured.append(args)
        return 1, "", "unexpected in test"

    backend = OpenShellCliBackend(runner=runner)
    cmd = backend._build_command(["sandbox", "list"])
    assert cmd[0] == "/opt/os104/openshell"
    assert "--gateway-endpoint" in cmd and "http://127.0.0.1:17673" in cmd
    assert "--gateway-insecure" in cmd
    # 显式 env.sh 时通过位置参数传路径，不做 shell 字符串拼接。
    monkeypatch.delenv("SIQ_AS_OPENSHELL_CLI_BIN")
    monkeypatch.delenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT")
    explicit_env_backend = OpenShellCliBackend(runner=runner, env_script="/opt/siq/openshell-env.sh")
    default_cmd = explicit_env_backend._build_command(["sandbox", "list"])
    assert default_cmd[:4] == [
        "bash",
        "-c",
        'source "$1" && shift && exec openshell "$@"',
        "openshell-env",
    ]
    assert default_cmd[4] == "/opt/siq/openshell-env.sh"


def test_cli_backend_requires_explicit_secure_gateway_configuration(monkeypatch):
    monkeypatch.delenv("SIQ_AS_OPENSHELL_CLI_BIN", raising=False)
    monkeypatch.delenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", raising=False)
    monkeypatch.delenv("SIQ_AS_OPENSHELL_ENV_SH", raising=False)
    with pytest.raises(AdapterError, match="未配置"):
        OpenShellCliBackend()._build_command(["gateway", "info"])

    monkeypatch.setenv("SIQ_AS_OPENSHELL_CLI_BIN", "/usr/bin/openshell")
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "http://gateway.example.com:17671")
    with pytest.raises(AdapterError, match="HTTPS"):
        OpenShellCliBackend()._build_command(["gateway", "info"])

    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "https://gateway.example.com:17671")
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "1")
    with pytest.raises(AdapterError, match="回环"):
        OpenShellCliBackend()._build_command(["gateway", "info"])

    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "0")
    for endpoint in (
        "https://user:secret@gateway.example.com:17671",
        "https://gateway.example.com:17671/admin",
        "https://gateway.example.com:17671?tenant=other",
        "https://gateway.example.com:17671#fragment",
        "https://gateway.example.com:invalid",
    ):
        monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", endpoint)
        with pytest.raises(AdapterError, match="无效"):
            OpenShellCliBackend()._build_command(["gateway", "info"])
