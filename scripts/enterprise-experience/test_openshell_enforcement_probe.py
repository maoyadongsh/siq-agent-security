"""`scripts/enterprise-experience/openshell-enforcement-probe.py` 的合成回归守卫。

被测工具属于"本轮工具"（在 `scripts/`，不在本目录），按本轮既有约定测试放在
`scripts/enterprise-experience/`，以便被 `pytest scripts/enterprise-experience` 收走。

**本测试不接触任何网关、不新建/不删除沙箱、不发任何真实 `sandbox upload` /
`sandbox exec` / `policy set`。** 网关与沙箱边界用一个**本地替身**表示：

- `OpenShellCliBackend` 换成记录调用的替身（因此"计划模式一个字节都不许发"是
  可断言的事实，而不是承诺）；
- 探针通道换成注入式 runner（因此三臂的观测形态可被逐条翻转）；
- **唯一的真实 IO** 是可达性对照：一个本机 127.0.0.1 监听套接字。它证明的是
  "对照臂确实是对边界外发起的真连接"，不是任何生产强制点。

因此本文件的结论档只能是**隔离验证通过**——它证明检测器能区分
"被拦 / 目标已死 / 夹具撒谎"，**不构成任何真实目标的执行证据**。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "enterprise-experience" / "openshell-enforcement-probe.py"
AGENT = ROOT / "scripts" / "enterprise-experience" / "probe" / "enforcement_probe_agent.py"
sys.path.insert(0, str(ROOT / "apps" / "control-api"))

_SPEC = importlib.util.spec_from_file_location("openshell_enforcement_probe", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)

from app.adapters.openshell import cli_backend as cli_backend_module  # noqa: E402
from app.adapters.openshell import probe_channel  # noqa: E402
from app.adapters.openshell.probe_channel import (  # noqa: E402
    AGENT_REPORT_PREFIX,
    AGENT_REPORT_SCHEMA,
)

TARGET = "siq-analysis-canary-27d1289f98fa"
FINGERPRINT = "f" * 64
REVISION = "2"
ENDPOINT = "api.example.com:443"
ALLOW_PATH = "/sandbox/siq-probe-a.py"
DENY_PATH = "/sandbox/siq-probe-b.py"


@pytest.fixture(autouse=True)
def _restore_environment():
    """被测工具会 `os.environ.clear()`（隔离环境是它的正确行为）——测试负责还回去。"""
    saved = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@pytest.fixture
def loopback_listener():
    """一个真实的 127.0.0.1 监听套接字：只用来让"边界外可达性对照"真的连上。"""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(5)
    try:
        yield f"127.0.0.1:{server.getsockname()[1]}"
    finally:
        server.close()


class _StubBackend:
    """记录调用序列的替身后端。**不得**有任何真实 IO。"""

    commands: list[list[str]] = []
    probed: int = 0
    readbacks: int = 0
    snapshot: SimpleNamespace

    def __init__(self, env_script: str = ""):
        assert env_script == "", "被测工具必须以 env_script='' 构造后端（隔离环境自带目标解析）"

    def _build_command(self, parts: list[str]) -> list[str]:
        _StubBackend.commands.append(list(parts))
        return ["/stub/openshell", *parts]

    def probe(self):
        _StubBackend.probed += 1
        return SimpleNamespace(endpoint_fingerprint=FINGERPRINT)

    def read_effective_policy(self, target: str):
        _StubBackend.readbacks += 1
        return self.snapshot


def _report(outcomes: list[str]) -> str:
    payload = {
        "schema": AGENT_REPORT_SCHEMA,
        "endpoint": ENDPOINT,
        "attempts": [{"outcome": outcome, "elapsed_ms": 1} for outcome in outcomes],
    }
    return AGENT_REPORT_PREFIX + json.dumps(payload) + "\n"


#: **真正被发出去**的命令（runner 只在 dispatch 时被调用）。
#: 与 `_StubBackend.commands` 的区别很关键：计划模式**会构造** exec argv 但**不 dispatch**，
#: 所以"一个字节都没发"只能对着这张表断言。
_DISPATCHED: list[list[str]] = []


class _StubChannel(probe_channel.SandboxExecProbeChannel):
    """真通道 + 注入式 runner：argv 由替身后端构造，输出由本例给定。"""

    def __init__(self, command_builder):
        super().__init__(command_builder, runner=_stub_runner)


def _stub_runner(argv: list[str]) -> tuple[int, str, str]:
    parts = argv[1:]
    _DISPATCHED.append(list(parts))
    if "upload" in parts:
        return 0, "", ""
    path = parts[parts.index("--") + 1]
    return 0, _report(_OUTCOMES[path]), ""


#: 允许臂 / 拒绝臂的形态（每个用例只翻转它要钉住的那一条）。
_OUTCOMES = {
    ALLOW_PATH: ["connected"] * 3,
    DENY_PATH: ["connection_refused"] * 3,
}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    """装配：替身后端 + 替身通道 runner + 一份合法算子授权目录。"""
    monkeypatch.setattr(cli_backend_module, "OpenShellCliBackend", _StubBackend)
    monkeypatch.setattr(probe_channel, "SandboxExecProbeChannel", _StubChannel)

    cli_stub = tmp_path / "openshell"
    cli_stub.write_bytes(b"#!/bin/sh\nexit 0\n")
    agent = tmp_path / "enforcement_probe_agent.py"
    agent.write_bytes(AGENT.read_bytes())

    authority = tmp_path / "authority.json"
    authority.write_text(json.dumps(_authority()), encoding="utf-8")
    authority.chmod(0o600)

    xdg_root = tmp_path / "xdg"
    xdg_root.mkdir()

    _StubBackend.commands = []
    _StubBackend.probed = 0
    _StubBackend.readbacks = 0
    _DISPATCHED.clear()
    _StubBackend.snapshot = SimpleNamespace(
        revision=REVISION,
        policy_digest="a" * 64,
        enforcement_mode="unknown",
        network=[{"endpoint": ENDPOINT, "effect": "allow", "binary_paths": [ALLOW_PATH]}],
    )
    _OUTCOMES[ALLOW_PATH] = ["connected"] * 3
    _OUTCOMES[DENY_PATH] = ["connection_refused"] * 3

    out_dir = tmp_path / "evidence"
    argv = [
        "--cli", str(cli_stub),
        "--endpoint", "http://127.0.0.1:17671",
        "--xdg-root", str(xdg_root),
        "--target", TARGET,
        "--endpoint-address", ENDPOINT,
        "--allow-path", ALLOW_PATH,
        "--deny-path", DENY_PATH,
        "--operator-authority", str(authority),
        "--agent", str(agent),
        "--attempts", "3",
        "--timeout", "5.0",
        "--out-dir", str(out_dir),
    ]
    return SimpleNamespace(
        argv=argv, out_dir=out_dir, tmp_path=tmp_path, cli_stub=cli_stub, agent=agent,
    )


def _authority(target: str = TARGET, fingerprint: str = FINGERPRINT) -> dict:
    return {
        "schema_version": "enterprise-runtime-target-authority/v1",
        "issued_at": "2026-09-01T00:00:00+00:00",
        "expires_at": "2026-12-01T00:00:00+00:00",
        "assignments": [{
            "id": "assign-1",
            "tenant_id": "tenant-1",
            "environment_id": "env-1",
            "asset_id": "asset-1",
            "agent_instance_id": "agt-1",
            "endpoint_fingerprint": fingerprint,
            "gateway_name_sha256": "b" * 64,
            "backend_target_id": target,
        }],
    }


def _run(harness, monkeypatch, *extra: str):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *harness.argv, *extra])
    return tool.main()


def _report_of(harness) -> dict:
    return json.loads((harness.out_dir / "report.json").read_text(encoding="utf-8"))


def _exec_dispatched() -> list[list[str]]:
    """真正发出去的 exec（不含计划模式只构造不发送的那些）。"""
    return [parts for parts in _DISPATCHED if "exec" in parts]


def _upload_dispatched() -> list[list[str]]:
    return [parts for parts in _DISPATCHED if "upload" in parts]


# ---------------------------------------------------------------- 计划模式

def test_plan_mode_never_touches_the_gateway(harness, monkeypatch):
    """默认模式只打印计划：不发握手、不读回、不上传、不 exec。"""
    assert _run(harness, monkeypatch) == 0
    report = _report_of(harness)
    assert report["conclusion"] == "probe_plan_only"
    assert report["executed"] is False
    assert report["enforcement_verified"] is False
    assert _StubBackend.probed == 0
    assert _StubBackend.readbacks == 0
    assert _DISPATCHED == []  # 构造了 argv 但没有 dispatch 任何一条
    # 计划里的 argv 形态是可复核的（上传两条 + exec 两条）
    planned = report["planned_argv"]
    assert planned["upload_allow"][1:3] == ["sandbox", "upload"]
    assert planned["exec"][0][2:4] == ["exec", "--name"]


def test_execute_alone_still_does_not_touch_the_gateway(harness, monkeypatch):
    """只给 `--execute` 不够——必须显式确认这是一次真实行为探针。"""
    assert _run(harness, monkeypatch, "--execute") == 0
    assert _report_of(harness)["conclusion"] == "probe_plan_only"
    assert _StubBackend.probed == 0


def test_out_dir_is_exclusive_and_never_overwritten(harness, monkeypatch):
    """输出目录独占：已存在即拒绝，且**不动**里面任何既有文件。"""
    harness.out_dir.mkdir()
    keep = harness.out_dir / "keep.txt"
    keep.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    assert excinfo.value.code == 2
    assert keep.read_text(encoding="utf-8") == "existing evidence"
    assert not (harness.out_dir / "report.json").exists()


# ---------------------------------------------------------------- 参数拒绝（全部在校验之前）

@pytest.mark.parametrize("flag, value, code", [
    ("--allow-path", "relative/path.py", "probe_binary_paths_must_be_absolute"),
    ("--xdg-root", "relative/xdg", "probe_paths_must_be_absolute"),
    ("--endpoint", "http://gw.example.com:17671", "probe_endpoint_requires_https"),
    ("--endpoint", "not-a-url", "probe_endpoint_invalid"),
    ("--endpoint-address", "api.example.com", "probe_endpoint_address_invalid"),
    ("--attempts", "2", "probe_attempts_below_minimum"),
    ("--agent", "/nonexistent/probe.py", "probe_agent_missing"),
    ("--cli", "openshell", "probe_cli_must_be_absolute_file"),
])
def test_argument_refusals_are_typed(harness, monkeypatch, flag, value, code):
    """非法输入一次性拒绝（固定码），而不是半途失败。"""
    argv = list(harness.argv)
    argv[argv.index(flag) + 1] = value
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *argv, "--execute", "--confirm-behaviour-probe"])
    with pytest.raises(SystemExit) as excinfo:
        tool.main()
    assert excinfo.value.code == code
    assert _StubBackend.probed == 0


def test_identical_allow_and_deny_paths_are_refused(harness, monkeypatch):
    """两臂必须是两个不同路径——否则"差别"无从归因到策略。"""
    argv = list(harness.argv)
    argv[argv.index("--deny-path") + 1] = ALLOW_PATH
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *argv])
    with pytest.raises(SystemExit) as excinfo:
        tool.main()
    assert excinfo.value.code == "probe_binary_paths_must_differ"


# ---------------------------------------------------------------- 授权门槛

def test_authority_unusable_is_refused_with_bounded_evidence(harness, monkeypatch, tmp_path):
    harness.argv[harness.argv.index("--operator-authority") + 1] = str(tmp_path / "missing.json")
    with pytest.raises(SystemExit) as excinfo:
        _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    assert excinfo.value.code == 1
    assert _report_of(harness)["conclusion"] == "probe_authority_unusable"


def test_unauthorized_target_is_refused(harness, monkeypatch, tmp_path):
    other = tmp_path / "other-authority.json"
    other.write_text(json.dumps(_authority(target="some-other-sandbox")), encoding="utf-8")
    other.chmod(0o600)
    harness.argv[harness.argv.index("--operator-authority") + 1] = str(other)
    with pytest.raises(SystemExit) as excinfo:
        _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    assert excinfo.value.code == 1
    report = _report_of(harness)
    assert report["conclusion"] == "probe_target_not_authorized"
    assert report["match_count"] == 0
    assert _StubBackend.probed == 0


def test_endpoint_fingerprint_mismatch_is_refused(harness, monkeypatch):
    """握手观测到的目标指纹与授权目录不符 ⇒ 拒绝（授权不是"命令行说了算"）。"""
    def mismatching_probe(self):
        _StubBackend.probed += 1
        return SimpleNamespace(endpoint_fingerprint="e" * 64)

    monkeypatch.setattr(_StubBackend, "probe", mismatching_probe)
    with pytest.raises(SystemExit) as excinfo:
        _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    assert excinfo.value.code == 1
    report = _report_of(harness)
    assert report["conclusion"] == "probe_authority_endpoint_mismatch"
    assert report["observed_fingerprint"] == "e" * 64
    assert _DISPATCHED == []  # 指纹不符时连 upload 都不许发


# ---------------------------------------------------------------- 策略前提（工具不写策略）

def test_missing_allow_rule_is_refused_before_any_exec(harness, monkeypatch):
    """允许规则必须**已经**在生效策略里；工具只读回确认，绝不自己写。"""
    _StubBackend.snapshot = SimpleNamespace(
        revision=REVISION, policy_digest="a" * 64, enforcement_mode="unknown", network=[],
    )
    with pytest.raises(SystemExit) as excinfo:
        _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    assert excinfo.value.code == 1
    report = _report_of(harness)
    assert report["conclusion"] == "probe_allow_rule_absent"
    # 只读前提不成立时，**一个跨边界的动作都不许发生**（上传也不许）
    assert _DISPATCHED == []


def test_deny_path_already_allowed_is_refused(harness, monkeypatch):
    """拒绝臂的路径若也在允许集里，就不是"被策略拦住"。"""
    _StubBackend.snapshot = SimpleNamespace(
        revision=REVISION, policy_digest="a" * 64, enforcement_mode="unknown",
        network=[{"endpoint": ENDPOINT, "effect": "allow", "binary_paths": [ALLOW_PATH, DENY_PATH]}],
    )
    with pytest.raises(SystemExit) as excinfo:
        _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    assert excinfo.value.code == 1
    assert _report_of(harness)["conclusion"] == "probe_deny_path_present_in_allow_set"


# ---------------------------------------------------------------- 执行：候选证据

def test_execute_writes_candidate_evidence_and_never_claims_enforcement(harness, monkeypatch):
    """三臂成立 ⇒ 报告"判别成立"，但仍**不**声称 enforcement_verified / 生产可用。"""
    assert _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe") == 0
    report = _report_of(harness)
    assert report["conclusion"] == "probe_discriminated"
    assert report["enforcement_verified"] is False
    assert report["production_eligible"] is False
    assert report["runtime_policy_mutated"] is False
    evidence = report["evidence"]
    assert {o["outcome"] for o in evidence["allow_arm"]} == {"connected"}
    assert {o["outcome"] for o in evidence["deny_arm"]} == {"connection_refused"}
    assert evidence["differential"] == "same_endpoint_binary_path"
    assert {o["binary_path"] for o in evidence["allow_arm"]} == {ALLOW_PATH}
    # 两臂是同一份内容：摘要相同 ⇒ 唯一变量是策略按路径的归因
    assert {o["binary_sha256"] for o in evidence["allow_arm"] + evidence["deny_arm"]} == {
        hashlib.sha256(harness.agent.read_bytes()).hexdigest()
    }
    assert report["cli_sha256"] and report["agent_sha256"]


def test_reachability_control_is_an_out_of_boundary_real_connection(harness, monkeypatch,
                                                                     loopback_listener):
    """对照臂来自**边界外**且是真连接：把被观测地址换成活的回环端口即 `connected`。"""
    harness.argv[harness.argv.index("--endpoint-address") + 1] = loopback_listener
    _StubBackend.snapshot = SimpleNamespace(
        revision=REVISION, policy_digest="a" * 64, enforcement_mode="unknown",
        network=[{"endpoint": loopback_listener, "effect": "allow", "binary_paths": [ALLOW_PATH]}],
    )
    assert _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe") == 0
    control = _report_of(harness)["evidence"]["reachability_controls"][0]
    assert control["origin"] == "control_plane_host"
    assert control["outcome"] == "connected"


def test_deny_arm_connected_is_not_accepted(harness, monkeypatch):
    """拒绝臂真的连上了 ⇒ 策略没生效 ⇒ 判别不成立（退出码非 0，且写出原因）。"""
    _OUTCOMES[DENY_PATH] = ["connected"] * 3
    assert _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe") == 1
    report = _report_of(harness)
    assert report["conclusion"] == "probe_not_accepted:probe_deny_arm_not_blocked"
    assert report["validator_reason"] == "probe_deny_arm_not_blocked"
    assert report["enforcement_verified"] is False


def test_allow_arm_blocked_is_not_accepted(harness, monkeypatch):
    """允许臂没连上 ⇒ 整轮 inconclusive，绝不当成"策略生效"。"""
    _OUTCOMES[ALLOW_PATH] = ["timeout"] * 3
    assert _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe") == 1
    assert _report_of(harness)["validator_reason"] == "probe_allow_arm_not_connected"


def test_plan_argv_equals_dispatched_argv(harness, monkeypatch):
    """计划里打印的 argv **必须**就是真正发出去的那条。

    否则"计划模式可复核"只是好看：早期版本计划里写死 `--timeout 0`，而通道实际发的是
    `int(timeout*attempts)+60`，两者悄然分叉。这里断言逐字相等。
    """
    assert _run(harness, monkeypatch) == 0
    planned = _report_of(harness)["planned_argv"]

    harness.out_dir = harness.tmp_path / "evidence-executed"
    harness.argv[harness.argv.index("--out-dir") + 1] = str(harness.out_dir)
    assert _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe") == 0

    # runner 记录的是 `argv[1:]`（去掉 CLI 二进制那一项），计划里则是含它的完整 argv。
    assert planned["upload_allow"][1:] == _upload_dispatched()[0]
    assert planned["upload_deny"][1:] == _upload_dispatched()[1]
    execs = _exec_dispatched()
    assert len(execs) == 2
    for index, planned_exec in enumerate(planned["exec"]):
        assert planned_exec[1:] == execs[index], (planned_exec, execs[index])
    assert execs[0][execs[0].index("--") + 1] == ALLOW_PATH
    assert execs[1][execs[1].index("--") + 1] == DENY_PATH


def test_tool_never_writes_a_policy(harness, monkeypatch):
    """工具只读：任何被构造出来的 argv 里都不许出现 `policy set/update/delete`。"""
    _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    for parts in _StubBackend.commands:
        assert "policy" not in parts, parts
        assert parts[0] == "sandbox" and parts[1] in {"upload", "exec"}, parts


def test_report_never_contains_credentials_or_policy_body(harness, monkeypatch):
    _run(harness, monkeypatch, "--execute", "--confirm-behaviour-probe")
    raw = (harness.out_dir / "report.json").read_text(encoding="utf-8")
    for forbidden in ("password", "token", "secret", "private_key", "BEGIN "):
        assert forbidden not in raw


# ---------------------------------------------------------------- 探针脚本本身

def test_agent_reports_facts_without_expectation(loopback_listener, tmp_path):
    """探针脚本是**真子进程**：对活端口给 `connected`，且根本不接受"预期"参数。"""
    connected = subprocess.run(
        [sys.executable, str(AGENT), "--endpoint", loopback_listener, "--attempts", "3"],
        capture_output=True, text=True, timeout=30,
    )
    assert connected.returncode == 0
    lines = [line for line in connected.stdout.splitlines() if line.startswith(AGENT_REPORT_PREFIX)]
    assert len(lines) == 1
    payload = json.loads(lines[0][len(AGENT_REPORT_PREFIX):])
    assert payload["schema"] == AGENT_REPORT_SCHEMA
    assert [a["outcome"] for a in payload["attempts"]] == ["connected"] * 3

    # 没有任何"预期"输入：夹具不可能知道它"应该"被拦
    with_expectation = subprocess.run(
        [sys.executable, str(AGENT), "--endpoint", loopback_listener, "--expect", "blocked"],
        capture_output=True, text=True, timeout=30,
    )
    assert with_expectation.returncode != 0
    assert AGENT_REPORT_PREFIX not in with_expectation.stdout


def test_agent_reports_closed_port_as_a_block_like_outcome(tmp_path):
    """本机一个已关闭端口：形态落进词表（`connection_refused`），而不是含糊的失败。"""
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()

    result = subprocess.run(
        [sys.executable, str(AGENT), "--endpoint", f"127.0.0.1:{port}", "--attempts", "1"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
    payload = json.loads(
        [line for line in result.stdout.splitlines() if line.startswith(AGENT_REPORT_PREFIX)][0]
        [len(AGENT_REPORT_PREFIX):]
    )
    assert payload["attempts"][0]["outcome"] in {
        "connection_refused", "timeout", "connection_reset", "probe_error",
    }


def test_agent_rejects_malformed_endpoint(tmp_path):
    result = subprocess.run(
        [sys.executable, str(AGENT), "--endpoint", "no-port", "--attempts", "1"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2
    assert AGENT_REPORT_PREFIX not in result.stdout
