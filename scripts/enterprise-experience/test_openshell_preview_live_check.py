"""`scripts/enterprise-experience/openshell-preview-live-check.py` 的合成回归守卫。

**不接触任何真实网关、不发任何真实 CLI 调用。** `--cli` 指向一个合成可执行文件（只打印固定的
`gateway info` / `status` / `policy get` 文本），`--endpoint` 虽为回环 HTTPS 但从不被连接。

被测的是「身份 id 只能来自算子授权目录」这条改造。要点：

1. 目录里的 tenant 与 environment/asset/agent_instance id 必须真的被用上——否则
   `require_target_authority` 的精确元组判定不可能相等，预览必 409（README §五）；
2. 指纹/网关名对不上时，必须在**任何控制面写入之前**以有界判别码失败，并把两个观测摘要
   带出来（算子一次就能补齐目录，不必反复试）；
3. 目录不安全、不合法（重复 JSON 键）→ 有界失败码；
4. 目录缺该目标条目、同一目标多条 → 有界失败码；
5. 结果 JSON 不得出现本机路径（授权目录、CLI、XDG 根都不落盘）；
6. 上下文变化被拒的**断面**：算子授权闸先于摘要比对失败，所以观测码是
   `deployment_target_authority_unverified` 而不是 `deployment_preview_changed`——
   E149 记录的「目录变化拒绝旧预览」性质仍在，机制已不是旧的那一处。这条也钉住。

「合成 CLI 下全绿」只说明这条链路在替身上可达，**不构成任何真实执行或行为验证**：
`enforcement_verified` 恒为 False。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "enterprise-experience" / "openshell-preview-live-check.py"
SANDBOX = "siq-synthetic-preview-target"
OTHER_SANDBOX = "siq-synthetic-other-target"
ENDPOINT = "https://127.0.0.1:18443"
GATEWAY_NAME = "siq-synthetic-preview-gw"
ZERO = "0" * 64
ASSIGNMENT = "iso-preview-assignment"

_FAKE_CLI = '''#!{python}
"""Synthetic openshell CLI: fixed read-only outputs, no network, no writes."""
import sys

POLICY = """version: 1
filesystem_policy:
  include_workdir: true
  read_only:
  - /usr
  read_write:
  - /sandbox
landlock:
  compatibility: hard_requirement
  abi: 6
process:
  run_as_user: sandbox
  run_as_group: sandbox
extension_guard:
  mode: strict
"""

args = sys.argv[3:]  # 跳过 --gateway-endpoint <url>
if args == ["gateway", "info"]:
    print("Gateway Info")
    print("  Gateway version: 0.0.104")
elif args == ["status"]:
    print("Server Status")
    print("  Gateway: {gateway}")
    print("  Gateway version: 0.0.104")
elif args == ["--version"]:
    print("openshell 0.0.104")
elif len(args) == 4 and args[:2] == ["policy", "get"] and args[3] == "--full":
    print("Version: 4")
    print("Active: 4")
    print("---")
    sys.stdout.write(POLICY)
else:
    print("unexpected command", file=sys.stderr)
    sys.exit(1)
'''


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    """共享的工作台：CLI 与 XDG 根必须在各次运行间保持同一身份，指纹才可比。"""
    base = tmp_path_factory.mktemp("preview-iso")
    cli = base / "openshell"
    cli.write_text(_FAKE_CLI.format(python=sys.executable, gateway=GATEWAY_NAME))
    cli.chmod(0o755)
    xdg = base / "xdg"
    for name in ("config", "state", "data", "cache"):
        (xdg / name).mkdir(parents=True)
    return base, cli, xdg


def _catalog(assignments):
    return json.dumps({
        "schema_version": "enterprise-runtime-target-authority/v1",
        "issued_at": "2026-09-01T00:00:00Z",
        "expires_at": "2027-09-01T00:00:00Z",
        "assignments": assignments,
    })


def _assignment(fingerprint, gateway, *, target=SANDBOX, identifier=ASSIGNMENT):
    return {"id": identifier, "tenant_id": "iso-preview-tenant", "environment_id": "env-iso-preview",
            "asset_id": "agt-iso-preview", "agent_instance_id": "inst-iso-preview",
            "endpoint_fingerprint": fingerprint, "gateway_name_sha256": gateway,
            "backend_target_id": target}


def _run(bench, name, text, *, mode=0o600, assignment_id=None):
    base, cli, xdg = bench
    authority = base / f"authority-{name}.json"
    authority.write_text(text)
    authority.chmod(mode)
    out = base / f"out-{name}"
    argv = [sys.executable, str(TOOL), "--cli", str(cli), "--endpoint", ENDPOINT, "--xdg-root", str(xdg),
            "--target", SANDBOX, "--target-authority", str(authority), "--out-dir", str(out)]
    if assignment_id is not None:
        argv += ["--assignment-id", assignment_id]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=600, check=False)
    record = json.loads((out / "result.json").read_text()) if (out / "result.json").exists() else None
    return proc, record


def test_wrong_authority_tuple_fails_before_any_control_plane_write(bench):
    """目录里指纹/网关名对不上：带观测摘要的有界失败，且不产生结果。"""
    proc, record = _run(bench, "mismatch", _catalog([_assignment(ZERO, ZERO)]))
    assert proc.returncode == 1, proc.stderr
    assert record["reason"] == "authority_endpoint_mismatch"
    assert record["passed"] is False and record["enforcement_verified"] is False
    assert record["runtime_policy_mutated"] is False
    observed = record["observed_endpoint_fingerprint"]
    assert len(observed) == 64 and observed != ZERO
    assert len(record["observed_gateway_name_sha256"]) == 64
    assert str(bench[0]) not in json.dumps(record)


def test_operator_declared_identity_reaches_the_preview(bench):
    """先拿观测摘要补全目录，再跑：整条预览链路在合成 CLI 上应全绿。"""
    _, probe = _run(bench, "observe", _catalog([_assignment(ZERO, ZERO)]))
    fingerprint = probe["observed_endpoint_fingerprint"]
    gateway = probe["observed_gateway_name_sha256"]
    proc, record = _run(bench, "green", _catalog([_assignment(fingerprint, gateway)]))
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {"passed": True, "checks": 10, "runtime_policy_mutated": False}
    assert record["passed"] is True and all(record["checks"].values())
    assert record["identity"] == "operator_declared_authority"
    assert record["assignment_id"] == ASSIGNMENT
    assert record["authority_sha256"] == hashlib.sha256(
        (bench[0] / "authority-green.json").read_bytes()).hexdigest()
    # 身份 id 只有目录一个来源：门禁的精确元组判定成立，才可能拿到预览值。
    assert record["gateway_version"] == "0.0.104" and record["command_count"] >= 3
    assert (record["before_revision"], record["after_revision"]) == ("4", "4")
    assert record["before_policy_digest"] == record["after_policy_digest"]
    assert record["cli_sha256"] == hashlib.sha256(bench[1].read_bytes()).hexdigest()
    # 上下文变化被拒的**确切断面**：算子授权闸在前，摘要比对不可达。钉住这一层，
    # 否则以后闸的顺序一变，E149 记录的"目录变化拒绝旧预览"会静默变成另一条分支。
    assert record["changed_context_detail"] == "deployment_target_authority_unverified"
    assert "changed_context_refuses_old_digest_without_writes" not in record["checks"]
    # 天花板与"未生产"声明不得随绿灯一起消失。
    assert record["enforcement_verified"] is False
    assert record["production_eligible"] is False and record["tls_insecure"] is False
    # 不得回显本机路径（授权目录、CLI、XDG 根）。
    assert str(bench[0]) not in json.dumps(record)


def test_absence_and_ambiguity_are_bounded_failures(bench):
    """缺该目标条目 → absent；同一目标两条条目（不同上下文）→ ambiguous。"""
    _, probe = _run(bench, "observe2", _catalog([_assignment(ZERO, ZERO)]))
    fingerprint = probe["observed_endpoint_fingerprint"]
    gateway = probe["observed_gateway_name_sha256"]
    proc, record = _run(bench, "absent", _catalog([_assignment(fingerprint, gateway, target=OTHER_SANDBOX)]))
    assert proc.returncode == 1 and record["reason"] == "authority_target_absent"
    # 同一沙箱目标在不同上下文各有一条授权：目录本身合法（(指纹, 目标) 互不相同），
    # 但按 --target 选中不唯一——这正是同一目标被两个 XDG 上下文授权的真实形态。
    ambiguous = _catalog([
        _assignment(fingerprint, gateway, identifier="iso-preview-a"),
        _assignment(ZERO, gateway, identifier="iso-preview-b"),
    ])
    proc, record = _run(bench, "ambiguous", ambiguous)
    assert proc.returncode == 1 and record["reason"] == "authority_target_ambiguous"
    assert record["matching_assignments"] == 2
    # --assignment-id 是这种目录下的正解。
    proc, record = _run(bench, "picked", ambiguous, assignment_id="iso-preview-a")
    assert proc.returncode == 0, proc.stderr
    assert record["assignment_id"] == "iso-preview-a" and record["passed"] is True


def test_unsafe_and_malformed_catalogs_are_rejected(bench):
    """组/其他可写的目录、重复 JSON 键：与门禁同一套判定，失败码有界且不回显路径。"""
    proc, record = _run(bench, "unsafe", _catalog([_assignment(ZERO, ZERO)]), mode=0o666)
    assert proc.returncode == 1 and record["reason"] == "authority_unusable"
    assert record["authority_error"] == "target_authority_unsafe"
    assert str(bench[0]) not in json.dumps(record)
    duplicated = _catalog([_assignment(ZERO, ZERO)]).replace(
        '"schema_version"', '"schema_version": "x", "schema_version"', 1)
    proc, record = _run(bench, "duplicate", duplicated)
    assert proc.returncode == 1 and record["reason"] == "authority_invalid"


def test_authority_catalog_is_required(bench):
    """没有算子授权目录就没有身份 id 来源：缺参数必须直接拒绝，不进任何运行期后续。"""
    base, cli, xdg = bench
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--cli", str(cli), "--endpoint", ENDPOINT, "--xdg-root", str(xdg),
         "--target", SANDBOX, "--out-dir", str(base / "out-no-authority")],
        capture_output=True, text=True, timeout=120, check=False)
    assert proc.returncode == 2
    assert "--target-authority" in proc.stderr
    assert not (base / "out-no-authority").exists()
