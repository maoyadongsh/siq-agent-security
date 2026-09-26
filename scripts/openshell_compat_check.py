"""OpenShell 版本兼容矩阵检查脚本（P2）。

用法（在 apps/control-api 目录下运行）：

    # 探测真实版本与能力，与 scripts/openshell_compat_matrix.json 比对
    uv run python ../../scripts/openshell_compat_check.py

    # 追加真实部署闭环 fixture（policy set → 读回验证 → 回滚），需存在的沙箱名
    uv run python ../../scripts/openshell_compat_check.py --live --sandbox <sandbox-name>

⚠️ `--live` 的真实写面（2026-09-26 实测更正，别照旧印象用）：
    1. `apply_dynamic` 对 `network_policies` 是**整段替换**（`cli_backend.apply_dynamic`），
       本 fixture 只含 1 条 `example.com:443` 规则，因此**目标沙箱原有的全部网络策略
       在写入与回滚之间会整体缺席**。请只用专用/一次性沙箱。
    2. 回滚**必须**由本脚本提供 authorizer（绑定 `receipt.operation_id` 与目标，从私有
       操作记录取值）；早期版本不传 authorizer，在 `cli_backend.rollback` 处必然抛
       `openshell_rollback_authorizer_required`，导致"写成功但回不去"。
    3. 写入后无论成功失败都会尝试回滚，并在回滚后再读回核对 `policy_digest` 与写入前一致。

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

# `--live` 的语义 fixture 里的网络规则**必须**带非空 `binary_paths`
# （`policy_safety.validate_network_rules`：缺失即 `openshell_network_binary_required`，
# 在 `compile()` 阶段就抛错、**一个字节都不会写**）。这里用目标沙箱内既有的解释器路径，
# 与 `scripts/openshell_compat_matrix.json` 所针对的那套网关一致。
_LIVE_FIXTURE_BINARY = "/opt/siq/hermes/venv/bin/python"

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


def _live_check(backend, sandbox: str, receipt_out: dict | None = None) -> bool:
    """真实部署闭环 fixture：compile → plan → apply_dynamic → verify → rollback。

    语义 fixture 只含网络 allow 规则（动态段），不触碰静态边界；
    **写入前先读回 BEFORE 快照**，写入后无论成功与否都必须回滚，并在回滚后
    再次读回、逐字段核对内容已还原（`policy_digest` 相等）。回滚作者由本函数
    依据**私有操作记录**（`receipt.operation_id` + BEFORE 快照）构造，不接受任何
    外部请求正文；**不传作者时后端必然拒绝回滚**（`openshell_rollback_authorizer_required`），
    因此作者是"写后能回收"的硬前提，不是可选项。

    ⚠️ 写面提醒：`apply_dynamic` 对 `network_policies` 是**整段替换**，不是追加。
    本 fixture 只含 1 条规则，故目标沙箱原有的全部网络策略在写入与回滚之间会
    **整体缺席**。只应对**专用/一次性**沙箱执行；对生产性 canary 执行前必须先
    确认该窗口可接受。
    """
    from app.adapters.openshell.contracts import RollbackAuthorization

    before = backend.read_effective_policy(sandbox)
    if receipt_out is not None:
        receipt_out["before_revision"] = before.revision
        receipt_out["before_policy_digest"] = before.policy_digest
    print(f"  [LIVE] BEFORE: revision={before.revision} 网络规则 {len(before.network)} 条")

    desired = {
        "policy_id": "siq-openshell-compat-live",
        "enforcement_mode": "block",
        "network": [
            {
                "endpoint": "example.com:443",
                "effect": "allow",
                "rule_name": "siq-compat-live-check",
                # 缺 binary_paths 会在 compile() 阶段抛 openshell_network_binary_required；
                # 早期版本缺这一段，`--live` 其实从未真正写入过（也从未被验证过）。
                "binary_paths": [_LIVE_FIXTURE_BINARY],
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
    if receipt_out is not None:
        receipt_out["applied_revision"] = receipt.backend_revision
    observed: dict = {}

    def _authorize(auth: RollbackAuthorization) -> bool:
        """只认这一次操作：操作 id 与目标必须对上。

        恢复目标（`auth.restore`）是后端从**私有操作记录**里取的写入时基线，
        这里只**记录**它与我们写入前读到的 BEFORE 是否一致、并如实报告差异，
        **不**据它拒绝回滚——拒绝就没人把沙箱改回去了，那比不一致更糟。
        """
        observed["restore_revision"] = auth.restore.revision
        observed["restore_digest"] = auth.restore.policy_digest
        return auth.operation_id == receipt.operation_id and auth.target == sandbox

    ok = True
    try:
        report = backend.verify(sandbox, checks, receipt)
        if report.passed:
            print(f"  [LIVE] 读回验证通过（level={report.level}）")
        else:
            print(f"  [LIVE] FAIL: 读回验证失败: {report.failures}")
            ok = False
    finally:
        # 已经写入就必须尝试回收；异常路径不得跳过回滚。
        rolled = None
        try:
            rolled = backend.rollback(sandbox, receipt, authorizer=_authorize)
            print(f"  [LIVE] 已回滚: revision {rolled.restored_revision}（result={rolled.result}）")
        except Exception as exc:  # 回滚失败必须显式报告，不吞掉
            print(f"  [LIVE] FAIL: 回滚失败: {exc}")
            ok = False
        if rolled is not None:
            after = backend.read_effective_policy(sandbox)
            if after.policy_digest != before.policy_digest:
                print(
                    "  [LIVE] FAIL: 回滚后内容与 BEFORE 不一致"
                    f"（{after.policy_digest} != {before.policy_digest}）"
                )
                ok = False
            else:
                print(f"  [LIVE] 回滚后读回一致: 网络规则 {len(after.network)} 条，digest 与 BEFORE 相同")
                if receipt_out is not None:
                    receipt_out["restored_revision"] = rolled.restored_revision
                    receipt_out["restored_digest_matches_before"] = True
            if observed.get("restore_digest") not in (None, before.policy_digest):
                print(
                    "  [LIVE] WARN: 后端记录的写入时基线与本函数写入前读到的 BEFORE 不一致"
                    f"（记录 {observed.get('restore_revision')} / 本函数 {before.revision}）"
                    " —— 说明读与写之间目标被外部改动；已按私有记录的基线恢复，请人工复核"
                )
        if receipt_out is not None:
            receipt_out["rollback_attempted"] = True
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenShell 版本兼容矩阵检查")
    parser.add_argument("--matrix", default=str(_DEFAULT_MATRIX), help="兼容矩阵 JSON 路径")
    parser.add_argument(
        "--live",
        action="store_true",
        help="追加真实 policy set/读回/回滚闭环 fixture（注意：会整段替换目标沙箱的 network_policies，仅供专用沙箱）",
    )
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
        print(
            "  注意：apply_dynamic 对 network_policies 是整段替换，"
            "写入与回滚之间该沙箱原有网络策略会整体缺席；仅用于专用/一次性沙箱。"
        )
        receipt_out: dict = {}
        try:
            if not _live_check(backend, args.sandbox, receipt_out):
                print(f"  [LIVE] 摘要: {json.dumps(receipt_out, ensure_ascii=False)}")
                return 1
        except AdapterError as exc:
            print(f"FAIL: live 闭环异常（fail-closed）: {exc}")
            if receipt_out.get("applied_revision"):
                print(f"  [LIVE] 已写入 revision {receipt_out['applied_revision']}，请人工确认是否已回滚")
            return 1
        print(f"  [LIVE] 摘要: {json.dumps(receipt_out, ensure_ascii=False)}")

    if diffs:
        print(f"FAIL: {len(diffs)} 项不一致")
        for diff in diffs:
            print(f"  - {diff}")
        return 1
    print("PASS: 全部期望一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
