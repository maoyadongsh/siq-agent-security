"""OpenShell 版本兼容矩阵检查脚本（P2）。

用法（在 apps/control-api 目录下运行）：

    # 探测真实版本与能力，与 scripts/openshell_compat_matrix.json 比对
    uv run python ../../scripts/openshell_compat_check.py

    # 追加真实部署闭环 fixture（policy set → 读回验证 → 回滚），需存在的沙箱名
    uv run python ../../scripts/openshell_compat_check.py --live --sandbox <sandbox-name>

环境变量约定与 app.adapters.openshell.cli_backend 完全一致：
    - SIQ_AS_OPENSHELL_CLI_BIN + SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT
      （回环开发网关可加 SIQ_AS_OPENSHELL_GATEWAY_INSECURE=1）；或
    - SIQ_AS_OPENSHELL_ENV_SH（绝对路径）。
两种方式都未配置时打印 "SKIP: 未配置网关" 并以 0 退出（CI 无可达网关时不红）。

退出码：
    0 — 跳过（未配置网关）或全部期望一致；
    1 — 存在不一致项（差异逐项打印）或 --live 闭环失败；
    2 — 探测失败（网关不可达/CLI 报错）或探测到的版本不在矩阵中。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 本脚本位于 <repo>/scripts/，被测代码位于 <repo>/apps/control-api/app/。
# 以脚本位置推导仓库根，把 control-api 加入 sys.path（不依赖调用方 cwd）。
_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONTROL_API = _REPO_ROOT / "apps" / "control-api"
if str(_CONTROL_API) not in sys.path:
    sys.path.insert(0, str(_CONTROL_API))

_DEFAULT_MATRIX = Path(__file__).resolve().with_name("openshell_compat_matrix.json")

# probe() 可探测的布尔能力 + 直接 CLI 探测的 sandbox list 可解码性，
# 与 scripts/openshell_compat_matrix.json 的 expect 键一一对应。
_PROBE_BOOL_FIELDS = (
    "dynamic_network_update",
    "static_filesystem",
    "static_process",
    "landlock",
    "interceptor",
    "provider_credential_injection",
    "revision_support",
)


def _gateway_configured() -> bool:
    cli_bin = os.getenv("SIQ_AS_OPENSHELL_CLI_BIN")
    endpoint = os.getenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT")
    env_sh = os.getenv("SIQ_AS_OPENSHELL_ENV_SH")
    return bool((cli_bin and endpoint) or env_sh)


def _probe_actual(backend) -> tuple[str, dict]:
    """probe() + sandbox list 直接探测，返回 (版本号, 实际能力字典)。

    版本号取自 probe 的 schema_version（真实探测结果，不编造）；
    sandbox_list_decodable 直接调 CLI `sandbox list`（SandboxResponse 解码路径），
    不走 list_targets 的 docker 兜底，以如实反映解码缺陷是否修复。
    """
    from app.adapters.openshell.contracts import AdapterError

    caps = backend.probe()  # 网关不可达 → AdapterError（fail-closed）
    version = "unknown"
    if caps.schema_version.endswith("-policy-v1") and not caps.schema_version.startswith("unknown"):
        version = caps.schema_version[: -len("-policy-v1")]

    actual = {field: bool(getattr(caps, field)) for field in _PROBE_BOOL_FIELDS}
    try:
        backend._cli("sandbox", "list")  # noqa: SLF001 兼容检查需绕过 docker 兜底直测解码路径
        actual["sandbox_list_decodable"] = True
    except AdapterError:
        actual["sandbox_list_decodable"] = False
    return version, actual


def _compare(version: str, actual: dict, matrix: list[dict]) -> list[str]:
    entry = next((e for e in matrix if e.get("version") == version), None)
    if entry is None:
        known = ", ".join(e.get("version", "?") for e in matrix)
        raise KeyError(f"探测版本 {version} 不在兼容矩阵中（已知: {known}）")
    diffs = []
    for key, expected in entry["expect"].items():
        got = actual.get(key)
        mark = "OK  " if got == expected else "DIFF"
        print(f"  [{mark}] {key}: 期望 {expected} / 实际 {got}")
        if got != expected:
            diffs.append(f"{key}: 期望 {expected} / 实际 {got}")
    # 实际多出而矩阵未记录的键不判错（矩阵是期望子集），但打印提示
    extra = sorted(set(actual) - set(entry["expect"]))
    if extra:
        print(f"  [INFO] 矩阵未记录的实测键: {extra}")
    return diffs


def _live_check(backend, sandbox: str) -> bool:
    """真实部署闭环 fixture：compile → plan → apply_dynamic → verify → rollback。

    语义 fixture 只含网络 allow 规则（动态段），不触碰静态边界；
    任何一步失败仍尽力回滚到上一 revision。
    """
    desired = {
        "policy_id": "siq-openshell-compat-live",
        "enforcement_mode": "block",
        "network": [
            {
                "endpoint": "example.com:443",
                "effect": "allow",
                "rule_name": "siq-compat-live-check",
            }
        ],
    }
    checks = {
        "expect_allow": ["example.com:443"],
        "expect_deny": ["denied.invalid:443"],
    }
    compiled = backend.compile(desired)
    if compiled.unsupported_by_backend:
        print(f"  [LIVE] 编译含 unsupported 项: {compiled.unsupported_by_backend}")
    plan = backend.plan_change(sandbox, compiled)
    if plan.kind != "dynamic":
        print(f"  [LIVE] FAIL: 期望 dynamic 变更，实际 {plan.kind}")
        return False
    receipt = backend.apply_dynamic(sandbox, plan, plan.expected_revision)
    print(f"  [LIVE] policy set 提交成功: revision {receipt.backend_revision}")
    report = backend.verify(sandbox, checks, receipt)
    ok = report.passed
    if ok:
        print(f"  [LIVE] 读回验证通过（level={report.level}）")
    else:
        print(f"  [LIVE] FAIL: 读回验证失败: {report.failures}")
    try:
        rolled = backend.rollback(sandbox, receipt)
        print(f"  [LIVE] 已回滚到 revision {rolled.restored_revision}")
    except Exception as exc:  # 回滚失败必须显式报告，不吞掉
        print(f"  [LIVE] FAIL: 回滚失败: {exc}")
        ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenShell 版本兼容矩阵检查")
    parser.add_argument("--matrix", default=str(_DEFAULT_MATRIX), help="兼容矩阵 JSON 路径")
    parser.add_argument("--live", action="store_true", help="追加真实 policy set/读回/回滚闭环 fixture")
    parser.add_argument("--sandbox", help="--live 使用的已存在沙箱名")
    args = parser.parse_args()

    if not _gateway_configured():
        print("SKIP: 未配置网关")
        return 0

    from app.adapters.openshell.cli_backend import OpenShellCliBackend
    from app.adapters.openshell.contracts import AdapterError

    matrix = json.loads(Path(args.matrix).read_text(encoding="utf-8"))
    backend = OpenShellCliBackend()

    try:
        version, actual = _probe_actual(backend)
    except AdapterError as exc:
        print(f"FAIL: 网关探测失败（fail-closed）: {exc}")
        return 2
    print(f"探测版本: {version}")
    print("能力比对:")

    try:
        diffs = _compare(version, actual, matrix)
    except KeyError as exc:
        print(f"FAIL: {exc}")
        return 2

    if args.live:
        if not args.sandbox:
            print("FAIL: --live 需要 --sandbox <已存在沙箱名>")
            return 2
        print(f"真实部署闭环 fixture（沙箱 {args.sandbox}）:")
        try:
            if not _live_check(backend, args.sandbox):
                return 1
        except AdapterError as exc:
            print(f"FAIL: live 闭环异常（fail-closed）: {exc}")
            return 1

    if diffs:
        print(f"FAIL: {len(diffs)} 项不一致")
        for diff in diffs:
            print(f"  - {diff}")
        return 1
    print("PASS: 全部期望一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
