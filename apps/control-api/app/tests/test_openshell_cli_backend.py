"""OpenShellCliBackend 测试：夹具为 2026-08-13 活网关（v0.0.83）实测捕获的真实输出。

锁定语义：有效策略解析、动态 policy set（静态段一致+网络段替换）、revision 校验、
版本回执解析、probe 真实版本探测（解析失败退化 unknown 不抛错）、sandbox list
解码缺陷的 docker 兜底（探测 >= v0.0.104 时退役，如实抛出 CLI 错误）、fail-closed。
"""

from __future__ import annotations

import os

import pytest
import yaml

from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError, DeploymentReceipt, RevisionConflict
from app.adapters.openshell.operation_registry import PolicyOperationRegistry
from app.adapters.openshell.policy_safety import policy_digest

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
  compatibility: hard_requirement
  abi: 6
process:
  run_as_user: sandbox
  run_as_group: sandbox
extension_guard:
  mode: "yes"
"""

# 实测捕获：policy set 成功输出
REAL_POLICY_SET_OK = "\x1b[1m\x1b[32m✓\x1b[39m\x1b[0m Policy version 2 submitted (hash: 5385cd2cf66f)\n"

# 实测捕获：静态段变更被拒
REAL_POLICY_SET_FS_REJECT = (
    'Error:   × status: InvalidArgument, message: "filesystem include_workdir cannot be '
    'changed on a live sandbox", details: [], metadata: MetadataMap { headers: {"content-type": '
    '"application/grpc", ...}}'
)

GATEWAY_INFO = "Gateway Info\n  Gateway: siq-openshell-dev\n  Gateway endpoint: https://127.0.0.1:17671\n"

# 版本探测夹具：保守解析只接受显式版本形状（"version: X.Y.Z" / "openshell … X.Y.Z"）
GATEWAY_INFO_WITH_VERSION = GATEWAY_INFO + "  Gateway version: 0.0.104\n"
VERSION_OUTPUT_V104 = "openshell version 0.0.104\n"
VERSION_OUTPUT_V083 = "openshell 0.0.83\n"
VERSION_OUTPUT_GARBAGE = "build-info: no semver here\n"


def _backend(responses: dict[tuple, tuple[int, str, str]]) -> OpenShellCliBackend:
    def runner(args: list[str]) -> tuple[int, str, str]:
        key = tuple(args)
        if key in responses:
            return responses[key]
        return 1, "", f"unexpected args: {key}"

    return OpenShellCliBackend(
        runner=runner,
        env_script="/nonexistent/env.sh",
        operation_registry=PolicyOperationRegistry(),
    )


def _policy_output(revision: int, policy: dict) -> str:
    return f"Version: {revision}\nActive: {revision}\n---\n" + yaml.safe_dump(policy, sort_keys=False)


def _policy_from_output(output: str) -> dict:
    return yaml.safe_load(output.split("---", 1)[1])


def test_read_effective_policy_parses_real_output():
    backend = _backend({("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, "")})
    snapshot = backend.read_effective_policy("s1")
    assert snapshot.revision == "1"
    assert snapshot.filesystem["read_only"][0] == "/usr"
    assert snapshot.process["run_as_user"] == "sandbox"
    assert snapshot.network == []  # 该策略无网络段
    # P1-11：policy get --full 输出无执行模式字段 → 如实 unknown，不硬编码 block
    assert snapshot.enforcement_mode == "unknown"


def test_probe_reports_measured_capabilities():
    backend = _backend({("gateway", "info"): (0, GATEWAY_INFO, "")})
    caps = backend.probe()
    assert caps.dynamic_network_update is True  # 2026-08-13 实测
    assert caps.static_filesystem is True
    assert caps.revision_support is True


def test_probe_capability_document_reflects_measured_semantics():
    """P1-1/P1-11：能力文档逐项如实映射实测结论；未实测一律 unknown/unsupported。"""
    backend = _backend({("gateway", "info"): (0, GATEWAY_INFO, "")})
    caps = backend.probe()
    doc = caps.capabilities
    assert doc, "能力文档必须非空"
    # 实测结论
    assert doc["network_l34"].status == "supported" and doc["network_l34"].semantics == "enforce"
    assert doc["filesystem"].status == "supported"
    assert doc["process"].status == "supported"
    assert doc["enforcement_mode.block"].status == "supported"
    # 实测不可用
    assert doc["network_l7"].status == "unsupported"
    assert doc["sandbox_lifecycle"].status == "unsupported"
    assert doc["enforcement_mode.warn"].status == "unsupported"
    assert doc["enforcement_mode.audit_only"].status == "unsupported"
    # 未实测 → unknown（不猜 supported），且每项都标注依据
    assert doc["tools_mcp"].status == "unknown"
    assert doc["resources"].status == "unknown"
    assert doc["audit_events"].status == "unknown"
    for name, item in doc.items():
        assert item.basis, f"{name} 必须标注判定依据"


def test_probe_schema_version_reflects_detected_gateway_version():
    """gateway info 输出携带版本时，schema_version 如实反映探测结果（不硬编码 v0.0.83）。"""
    backend = _backend({("gateway", "info"): (0, GATEWAY_INFO_WITH_VERSION, "")})
    caps = backend.probe()
    assert caps.schema_version == "v0.0.104-policy-v1"


def test_probe_version_falls_back_to_cli_version_flag():
    """gateway info 无版本信息时回退 `--version` 解析真实版本。"""
    backend = _backend(
        {
            ("gateway", "info"): (0, GATEWAY_INFO, ""),
            ("--version",): (0, VERSION_OUTPUT_V104, ""),
        }
    )
    caps = backend.probe()
    assert caps.schema_version == "v0.0.104-policy-v1"


def test_probe_version_command_failure_degrades_to_unknown_without_raising():
    """版本命令失败：schema_version 退化 unknown 前缀，probe 不抛错（可达性已由 gateway info 证明）。"""
    backend = _backend({("gateway", "info"): (0, GATEWAY_INFO, "")})  # --version 未夹具 → rc=1
    caps = backend.probe()
    assert caps.schema_version == "unknown-policy-v1"


def test_probe_unparseable_version_output_degrades_to_unknown():
    """版本输出不可解析：同样退化 unknown，绝不编造版本号。"""
    backend = _backend(
        {
            ("gateway", "info"): (0, GATEWAY_INFO, ""),
            ("--version",): (0, VERSION_OUTPUT_GARBAGE, ""),
        }
    )
    caps = backend.probe()
    assert caps.schema_version == "unknown-policy-v1"


def test_probe_gateway_info_failure_remains_fail_closed():
    """gateway info 失败仍 fail-closed（版本探测宽松化不影响可达性前提）。"""
    backend = _backend({("gateway", "info"): (1, "", "connection refused")})
    with pytest.raises(AdapterError):
        backend.probe()


def test_apply_dynamic_merges_static_and_replaces_network(tmp_path):
    active = {"output": REAL_POLICY_GET_FULL}
    set_calls: list[list[str]] = []
    merged_docs: list[dict] = []

    def runner(args):
        if tuple(args) == ("gateway", "info"):
            return 0, GATEWAY_INFO, ""
        if tuple(args[:2]) == ("policy", "set"):
            set_calls.append(args)
            merged_docs.append(yaml.safe_load(open(args[4])))  # CLI 读取期文件必须存在
            active["output"] = _policy_output(9, merged_docs[-1])
            return 0, "✓ Policy version 9 submitted (hash: 5385cd2cf66f)\n", ""
        if tuple(args) == ("policy", "get", "s1", "--full"):
            return 0, active["output"], ""
        return 1, "", f"unexpected: {args}"

    backend = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
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
    assert receipt.backend_revision == "9"  # 不推算连续 revision
    assert receipt.evidence["snapshot_hash"] == "5385cd2cf66f"
    # 合并后的 YAML 必须保留静态段 + 携带网络段
    merged = merged_docs[0]
    assert merged["filesystem_policy"]["read_only"][0] == "/usr"
    assert merged["landlock"] == {"compatibility": "hard_requirement", "abi": 6}
    assert merged["extension_guard"] == {"mode": "yes"}
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
    responses[("policy", "get", "s1", "--full")] = (0, _policy_output(2, _policy_from_output(REAL_POLICY_GET_FULL)), "")
    with pytest.raises(RevisionConflict):
        backend.apply_dynamic("s1", plan, expected_revision="1")


def test_apply_dynamic_idempotent_unchanged_policy():
    """内容未变在本地识别为 no-op，零 policy set 写入。"""
    current_policy = _policy_from_output(REAL_POLICY_GET_FULL)
    current_policy["network_policies"] = {}
    current_output = _policy_output(5, current_policy)
    set_calls = 0

    def runner(args):
        nonlocal set_calls
        if tuple(args) == ("gateway", "info"):
            return 0, GATEWAY_INFO, ""
        if tuple(args[:2]) == ("policy", "set"):
            set_calls += 1
            return 1, "", "must not write"
        if tuple(args) == ("policy", "get", "s1", "--full"):
            return 0, current_output, ""
        return 1, "", f"unexpected: {args}"

    backend = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
    compiled = backend.compile(
        {"policy_id": "p", "version": 1, "selector": {"agent_ids": ["a"]}, "network": [], "enforcement_mode": "block"}
    )
    plan = backend.plan_change("s1", compiled)
    receipt = backend.apply_dynamic("s1", plan, expected_revision="5")
    assert receipt.backend_revision == "5"
    assert receipt.result == "no_op"
    assert receipt.applied_policy_digest == policy_digest(current_policy)
    assert set_calls == 0


def test_fs_change_rejected_by_gateway_is_adapter_error():
    responses = {
        ("gateway", "info"): (0, GATEWAY_INFO, ""),
        ("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL, ""),
    }
    calls = {"n": 0}

    def runner(args):
        if tuple(args) == ("gateway", "info"):
            return 0, GATEWAY_INFO, ""
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


def test_rollback_restores_bound_snapshot_with_non_contiguous_revision():
    """回滚使用 apply 前绑定快照，不查 revision-1 历史。"""
    base_policy = _policy_from_output(REAL_POLICY_GET_FULL)
    active = {"output": _policy_output(4, base_policy)}
    set_calls: list[list[str]] = []
    submitted: list[dict] = []

    def runner(args):
        if tuple(args) == ("gateway", "info"):
            return 0, GATEWAY_INFO, ""
        if tuple(args[:2]) == ("policy", "set"):
            set_calls.append(args)
            submitted.append(yaml.safe_load(open(args[4])))
            revision = 9 if len(submitted) == 1 else 15
            active["output"] = _policy_output(revision, submitted[-1])
            return 0, f"✓ Policy version {revision} submitted (hash: 3f3f3f3f)\n", ""
        if tuple(args) == ("policy", "get", "s1", "--full"):
            return 0, active["output"], ""
        return 1, "", f"unexpected: {args}"

    backend = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
    compiled = backend.compile(
        {
            "policy_id": "p",
            "version": 1,
            "selector": {"agent_ids": ["a"]},
            "network": [{"endpoint": "api.example.com:443", "effect": "allow", "binary_paths": ["/bin/tool"]}],
            "enforcement_mode": "block",
        }
    )
    applied = backend.apply_dynamic("s1", backend.plan_change("s1", compiled), "4")
    restored = backend.rollback("s1", applied, authorizer=lambda _auth: True)
    assert applied.backend_revision == "9" and restored.restored_revision == "15"
    assert restored.restored_digest == policy_digest(base_policy)
    assert submitted[1] == base_policy
    assert not any("--rev" in call for call in set_calls)
    assert all(not os.path.exists(call[4]) for call in set_calls)
    with pytest.raises(AdapterError, match="operation_unknown"):
        backend.rollback("s1", applied, authorizer=lambda _auth: True)


def test_rollback_unknown_or_forged_receipt_is_zero_write():
    writes = 0

    def runner(args):
        nonlocal writes
        if tuple(args[:2]) == ("policy", "set"):
            writes += 1
        return 1, "", "unused"

    backend = OpenShellCliBackend(runner=runner, operation_registry=PolicyOperationRegistry())
    forged = DeploymentReceipt(
        backend_revision="9",
        operation_id="opo-forged",
        target="s1",
        base_revision="4",
        base_policy_digest="a" * 64,
        applied_policy_digest="b" * 64,
        result="applied",
    )
    with pytest.raises(AdapterError, match="operation_unknown"):
        backend.rollback("s1", forged, authorizer=lambda _auth: True)
    assert writes == 0


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
    with pytest.raises(AdapterError, match="openshell_command_failed"):
        backend.list_targets()


def test_list_targets_raises_cli_error_when_v104_retires_docker_fallback():
    """探测版本 >= v0.0.104（解码缺陷已实测修复）：sandbox list 失败如实抛出，不再静默 docker 兜底。"""
    docker_calls: list[list[str]] = []

    def runner(args):
        if tuple(args) == ("gateway", "info"):
            return 0, GATEWAY_INFO_WITH_VERSION, ""
        if tuple(args[:2]) == ("sandbox", "list"):
            return 1, "", "status: Internal, message: some real error"
        return 1, "", f"unexpected: {args}"

    def docker_runner(args):
        docker_calls.append(args)
        return 0, "openshell-siq-as-live-8515c645-1682-4814-965d-e6b330e2af2e\n", ""

    backend = OpenShellCliBackend(runner=runner, docker_runner=docker_runner)
    backend.probe()  # 探测 v0.0.104 → docker 兜底退役
    with pytest.raises(AdapterError, match="openshell_command_failed"):
        backend.list_targets()
    assert docker_calls == []  # docker 兜底不再被调用


def test_list_targets_docker_fallback_retained_below_v104():
    """探测版本 < v0.0.104：解码缺陷仍在，docker 兜底保留。"""

    def runner(args):
        if tuple(args) == ("gateway", "info"):
            return 0, GATEWAY_INFO, ""
        if tuple(args) == ("--version",):
            return 0, VERSION_OUTPUT_V083, ""
        if tuple(args[:2]) == ("sandbox", "list"):
            return 1, "", "status: Internal, message: failed to decode Protobuf message: Sandbox.id"
        return 1, "", f"unexpected: {args}"

    def docker_runner(args):
        return 0, "openshell-siq-as-live-8515c645-1682-4814-965d-e6b330e2af2e\n", ""

    backend = OpenShellCliBackend(runner=runner, docker_runner=docker_runner)
    backend.probe()  # 探测 v0.0.83 → 兜底保留
    page = backend.list_targets()
    assert page.targets == [{"id": "siq-as-live"}]


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


# ------------------------------------------------------------ P1-2：verify 分级 / 事件来源

# 实测形状：revision=2 且含网络段的 policy get --full 输出
REAL_POLICY_GET_FULL_V2_WITH_NET = """Version:      2
Hash:         5385cd2cf66f
Status:       Active
Active:       2
Created:      1786632645924 ms
Loaded:       1786632646253 ms
---
version: 1
filesystem_policy:
  include_workdir: true
  read_only:
  - /usr
  read_write:
  - /sandbox
landlock:
  compatibility: best_effort
process:
  run_as_user: sandbox
  run_as_group: sandbox
network_policies:
  siq_as_rule_0:
    name: siq-as-rule-0
    endpoints:
    - host: api.example.com
      port: 443
    binaries:
    - path: /usr/bin/curl
"""


def test_verify_pass_level_is_readback_verified_not_enforcement():
    """P1-2：CLI verify 是配置读回——通过时 level=readback_verified，绝不 enforcement_verified。"""
    backend = _backend({("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL_V2_WITH_NET, "")})
    expected_digest = policy_digest(_policy_from_output(REAL_POLICY_GET_FULL_V2_WITH_NET))
    report = backend.verify(
        "s1",
        checks={"expect_allow": ["api.example.com:443"], "expect_deny": ["10.255.255.255:1"]},
        receipt=DeploymentReceipt(backend_revision="2", applied_policy_digest=expected_digest, evidence={}),
    )
    assert report.passed is True, report.failures
    assert report.level == "readback_verified"
    # checks 携带 request/expected/actual/revision 供审计复核
    allow = report.allow_checks[0]
    assert allow["request"] == "config_readback"
    assert allow["expected"] == "allow" and allow["actual"] == "allow"
    assert allow["revision"] == "2"
    deny = report.deny_checks[0]
    assert deny["expected"] == "deny" and deny["actual"] == "deny"


def test_verify_failure_level_is_failed(monkeypatch):
    """P1-2：revision 读回不一致 → passed=False 且 level=failed（不伪装通过）。"""
    monkeypatch.setattr("time.sleep", lambda _s: None)  # 跳过轮询等待
    backend = _backend({("policy", "get", "s1", "--full"): (0, REAL_POLICY_GET_FULL_V2_WITH_NET, "")})
    report = backend.verify(
        "s1",
        checks={"expect_allow": ["api.example.com:443"], "expect_deny": ["10.255.255.255:1"]},
        receipt=DeploymentReceipt(backend_revision="3", evidence={}),
    )
    assert report.passed is False
    assert report.level == "failed"
    assert any("revision mismatch" in f for f in report.failures)


def test_stream_events_labels_real_source_not_behavioral():
    """P1-2：stream_events 是 policy list 回读，事件 type/source 如实标注，非行为事件流。"""
    backend = _backend({("policy", "list"): (0, "siq-as-live  version 2\n", "")})
    batch = backend.stream_events()
    assert batch.source == "cli_policy_list_readback"
    assert batch.events[0]["type"] == "policy_history"

    failing = _backend({("policy", "list"): (1, "", "connection refused")})
    batch2 = failing.stream_events(cursor="c1")
    assert batch2.source == "cli_policy_list_readback"
    assert batch2.events[0]["type"] == "backend_unavailable"
