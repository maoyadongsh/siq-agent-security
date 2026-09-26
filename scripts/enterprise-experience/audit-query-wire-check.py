#!/usr/bin/env python3
"""ENT-019-AUDIT-WIRE 一键验收：后端真实响应样本 → 前端消费者契约检查。

流程：
1. 创建独立临时证据目录（或 --out-dir 指定尚不存在的目录，绝不覆盖已有证据）；
2. 运行后端聚焦测试 app/tests/test_audit_query_wire.py，
   通过 SIQ_AUDIT_QUERY_WIRE_OUTPUT 导出隔离 TestClient 真实响应样本；
3. 校验样本存在、来源标记正确并计算 SHA-256；
4. 将同一样本路径传给前端独立消费者检查 dev/audit-query-wire.config.ts
   （真实 getListPage + parseListMeta，fetch 层回放样本）；
5. 任一步非零退出，脚本最终非零退出；缺少工具或样本时明确失败，不以跳过冒充通过。

只使用标准库与项目已有工具（uv / node_modules 内 vitest），不安装依赖、
不启动生产服务、不连接真实控制面或数据库、不输出进程环境或秘密。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTROL_API = REPO / "apps" / "control-api"
WEB = REPO / "apps" / "web"
VITEST = WEB / "node_modules" / ".bin" / "vitest"
ENV_VAR = "SIQ_AUDIT_QUERY_WIRE_OUTPUT"
SCOPE = "isolated-testclient-synthetic-data"

BACKEND_CMD = [
    "uv", "run", "pytest", "-o", "addopts=", "-q",
    "app/tests/test_audit_query_wire.py", "--tb=short",
]
FRONTEND_CMD = [str(VITEST), "run", "--config", "dev/audit-query-wire.config.ts"]


def run_step(name: str, cmd: list[str], cwd: Path, sample: Path, evidence: Path) -> dict:
    """以参数数组运行一步；输出同时上屏并落证据目录日志。"""
    env = dict(os.environ)
    env[ENV_VAR] = str(sample)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    log_path = evidence / f"{name}.log"
    # 独占创建日志，避免覆盖已有证据。
    with log_path.open("x", encoding="utf-8") as stream:
        stream.write(proc.stdout)
        if proc.stderr:
            stream.write("\n--- stderr ---\n")
            stream.write(proc.stderr)
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stdout.write(proc.stderr)
    return {
        "step": name,
        "cmd": cmd,
        "cwd": str(cwd),
        "exit_code": proc.returncode,
        "log": str(log_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="证据目录（默认新建唯一临时目录；指定目录必须尚不存在）",
    )
    args = parser.parse_args()

    if args.out_dir is None:
        evidence = Path(tempfile.mkdtemp(prefix="siq-audit-query-wire-"))
    else:
        # Child processes run in different repositories; keep one absolute
        # artifact path rooted in the invoking user's working directory.
        evidence = args.out_dir.resolve()
        if evidence.exists():
            print(f"拒绝覆盖已有目录: {evidence}", file=sys.stderr)
            return 2
        evidence.mkdir(parents=True)

    sample = evidence / "audit-query-wire-sample.json"
    steps: list[dict] = []
    failures: list[str] = []

    # 前置工具检查：缺失即明确失败。
    if shutil.which("uv") is None:
        failures.append("缺少 uv，无法运行后端聚焦测试")
    if not VITEST.exists():
        failures.append(f"缺少前端 vitest（{VITEST}），请先完成已有依赖安装")
    if failures:
        report = {"passed": False, "failures": failures, "evidence_dir": str(evidence)}
        with (evidence / "report.json").open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False))
        return 2

    # 1. 后端聚焦测试 + 真实响应样本导出。
    steps.append(run_step("backend-pytest", BACKEND_CMD, CONTROL_API, sample, evidence))
    if steps[-1]["exit_code"] != 0:
        failures.append("后端聚焦测试失败")

    # 2. 样本校验与摘要。
    sample_sha256 = None
    if steps[-1]["exit_code"] == 0:
        if not sample.exists():
            failures.append(f"后端未导出样本: {sample}")
        else:
            raw = sample.read_bytes()
            sample_sha256 = hashlib.sha256(raw).hexdigest()
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError as exc:
                failures.append(f"样本不是合法 JSON: {exc}")
            else:
                if parsed.get("scope") != SCOPE:
                    failures.append(f"样本来源标记不符: {parsed.get('scope')!r}")

    # 3. 前端消费者契约检查（仅在样本有效时运行；样本缺失本身是失败而非跳过）。
    if sample_sha256 is not None and not failures:
        steps.append(run_step("frontend-vitest", FRONTEND_CMD, WEB, sample, evidence))
        if steps[-1]["exit_code"] != 0:
            failures.append("前端消费者契约检查失败")

    report = {
        "passed": not failures,
        "failures": failures,
        "evidence_dir": str(evidence),
        "sample": str(sample),
        "sample_sha256": sample_sha256,
        "steps": steps,
        "note": "隔离合成样本的前后端契约兼容性验证；不证明真实 IAM、网关或 PostgreSQL 已验收。",
    }
    with (evidence / "report.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
