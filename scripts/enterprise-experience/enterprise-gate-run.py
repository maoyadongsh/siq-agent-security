"""R07 统一防御门禁执行器：在**同一工作树**上按固定顺序跑全部可离线门禁，并如实登记不可跑项。

本工具把 R07.1 盘点出的门禁从"口头清单"变成可重复、可留证的单次运行：

- **固定顺序**，不随机化后端测试（`-p no:randomly`），因为 `-p randomly` 会把跨文件夹具污染
  变成不可复现的间歇失败；
- **只跑全量后端**：R07.3 已实证"单独运行测试文件"会产生**空通过（vacuous pass）**——
  `test_deployment_preview_consistency.py` 孤立运行 15 passed，全量运行同一文件抛 `AttributeError`；
- **`gofmt` 只对 Git 跟踪文件判定**：`gofmt -l .` 会被已忽略的 `.tmp/` 临时目录误报
  （`apps/agentshield/.tmp/fx01/refcalc.go` 未跟踪）；
- **不带自定义 vitest reporter**：`--reporter=basic` 在 vitest 4 已被移除，直接崩溃并掩盖真实结果；
- **不可跑项一律记为 skipped/blocked 并带原因，绝不计入通过**；任何 skipped 存在时
  `conclusion` 不可能是绿色。

安全边界：只读源码 + 临时构建；**不安装依赖、不提交、不签名、不发布、不启动服务、不连数据库、
不读 `.env`/私钥/种子**。正式构建显式 `VITE_DEV_MODE=false` 且输出到临时目录，与模拟身份构建分离。
报告 `conclusion` 只描述**本机这一份工作树**的门禁状态：不是生产效果证据，不是已签候选，
也不是源码冻结结论。退出码 0 只表示"本次运行中没有 failed 且没有 skipped/blocked"。
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

TOOL_VERSION = "enterprise-gate-run/0.1.0"
SCHEMA_VERSION = "siq-enterprise-gate-run/v1"

EXIT_PASS = 0
EXIT_NOT_GREEN = 1
EXIT_USAGE = 2
EXIT_REPORT_WRITE_FAILED = 3

DEFAULT_TIMEOUT_SECONDS = 1800
MAX_TAIL_CHARS = 4000

GO_MODULES = (
    ("go_edge", "edge/agent"),
    ("go_connectors_dify", "connectors/dify"),
    ("go_connectors_directory", "connectors/directory"),
    ("go_connectors_docker", "connectors/docker"),
    ("go_connectors_hermes", "connectors/hermes"),
    ("go_connectors_kubernetes", "connectors/kubernetes"),
    ("go_connectors_mcp", "connectors/mcp"),
    ("go_connectors_openclaw", "connectors/openclaw"),
    ("go_connectors_piagent", "connectors/piagent"),
    ("go_connectors_process", "connectors/process"),
    ("go_connectors_siq", "connectors/siq"),
    ("go_connectors_systemd", "connectors/systemd"),
    ("go_connectors_workbuddy", "connectors/workbuddy"),
    ("go_agentshield", "apps/agentshield"),
)

RULEPACK_PYTHON = "apps/control-api/app/data/threat_rules.v1.json"
RULEPACK_GO = "apps/agentshield/internal/rulepack/data/threat_rules.v1.json"

# 正式产物中**不得**出现的开发身份字面量。命中即失败（这是断言，不是观察）。
DEV_IDENTITY_LITERALS = ("X-Dev-Tenant-Id", "X-Dev-User-Id", "X-Dev-Roles", "VITE_DEV_MODE")

# 报告固定声明：本工具不是这些结论。
NOT_EVIDENCE_OF = (
    "green_gates_are_not_production_effect",
    "gate_run_is_not_a_signed_candidate",
    "gate_run_is_not_a_source_freeze",
    "local_run_is_not_a_ci_attestation",
    "skipped_gate_is_never_a_pass",
)

# 本环境不可执行的门禁：必须显式登记，绝不静默省略。
DECLARED_UNAVAILABLE = (
    {
        "id": "migration_replay_postgres",
        "reason": "requires_database_container",
        "note": "真实 PostgreSQL 迁移回放与部署竞态需临时数据库容器；按任务书 §3.2 需先说明隔离/目标/回收并取得许可",
        "tool": "scripts/enterprise-experience/deployment-postgres-check.py",
    },
    {
        "id": "browser_acceptance",
        "reason": "requires_running_services",
        "note": "30 个 *-browser-smoke.py 需要运行中的控制面与浏览器环境；属 R09 资源门槛",
        "tool": "scripts/enterprise-experience/*-browser-smoke.py",
    },
    {
        "id": "real_device_native_evidence",
        "reason": "requires_real_device_and_identity",
        "note": "真实设备/原生平台/真实身份证据；属 R09 资源门槛，且不得在本轮制造 effective 事实",
        "tool": None,
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "--no-optional-locks", *args], cwd=str(repo),
                          capture_output=True, check=False)
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", "replace").strip()


def tracked_paths(repo: Path, subdir: str) -> set[str]:
    out = git(repo, "ls-files", "-z", "--", subdir)
    return {p for p in out.split("\0") if p}


def tail(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_TAIL_CHARS:
        return text, False
    return text[-MAX_TAIL_CHARS:], True


def _tally(data: bytes) -> dict:
    text = data.decode("utf-8", "replace")
    kept, truncated = tail(text)
    return {"bytes": len(data), "tail": kept, "tail_truncated": truncated}


def run_command(repo: Path, spec: dict) -> dict:
    """执行一条命令门禁。返回不含时间戳的结果字典。"""
    cwd = repo / spec["cwd"] if spec.get("cwd") else repo
    argv = list(spec["argv"])
    executable = shutil.which(argv[0]) if not argv[0].startswith((".", "/")) else None
    if executable is None and not (cwd / argv[0]).exists():
        return {"status": "blocked", "detail": f"executable_not_found:{argv[0]}"}
    if not cwd.is_dir():
        return {"status": "blocked", "detail": f"cwd_not_found:{spec['cwd']}"}
    env = dict(os.environ)
    env.update(spec.get("env") or {})
    env.pop("PYTHONPATH", None)
    started = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True,
                              timeout=spec.get("timeout", DEFAULT_TIMEOUT_SECONDS), check=False)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "detail": "timeout",
                "duration_seconds": round(time.monotonic() - started, 3)}
    except OSError as exc:
        return {"status": "blocked", "detail": f"os_error:{exc.errno or 'unknown'}"}
    result = {
        "exit_code": proc.returncode,
        "stdout": _tally(proc.stdout),
        "stderr": _tally(proc.stderr),
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    if proc.returncode == 0:
        result["status"] = "passed"
    else:
        result["status"] = "failed"
        result["detail"] = f"exit_code={proc.returncode}"
    return result


def _repo_relative(subdir: str, reported: str) -> str:
    relative = reported.removeprefix("./")
    return str(Path(subdir) / relative)


def check_gofmt(repo: Path, subdir: str) -> dict:
    """gofmt 只对 Git 跟踪文件判定：未跟踪的忽略目录不得制造失败。"""
    cwd = repo / subdir
    if not cwd.is_dir():
        return {"status": "blocked", "detail": f"module_not_found:{subdir}"}
    proc = subprocess.run(["gofmt", "-l", "."], cwd=str(cwd), capture_output=True, check=False)
    if proc.returncode != 0:
        return {"status": "failed", "detail": f"gofmt_exit={proc.returncode}",
                "stderr": _tally(proc.stderr)}
    reported = [line.strip() for line in proc.stdout.decode("utf-8", "replace").splitlines()
                if line.strip()]
    tracked = tracked_paths(repo, subdir)
    untracked_ignored, offenders = [], []
    for item in reported:
        target = _repo_relative(subdir, item)
        if target in tracked:
            offenders.append(item)
        else:
            untracked_ignored.append(item)
    if offenders:
        return {"status": "failed", "detail": "unformatted_tracked_files",
                "evidence": {"offenders": sorted(offenders)}}
    return {"status": "passed",
            "evidence": {"tracked_scanned": len(tracked),
                         "reported_untracked_ignored": sorted(untracked_ignored)}}


def check_contract_version_chain(repo: Path, build_dir: Path) -> dict:
    """版本链审计：本门禁只要求"闭合与否可被判定"；是否可接受由 R06 结论裁决。

    工具在链未闭合时按设计退出 1，故退出码 1 **不是**本门禁的失败条件；能产出可解析报告才是。
    """
    out = build_dir / "contract-version-chain.json"
    tool = repo / "scripts/enterprise-experience/contract-version-chain-audit.py"
    aliases = repo / "scripts/enterprise-experience/contract-version-aliases.json"
    if not tool.is_file():
        return {"status": "blocked", "detail": "tool_missing"}
    argv = [sys.executable or "python3", str(tool), "--repo", str(repo), "--out", str(out)]
    if aliases.is_file():
        argv += ["--aliases", str(aliases)]
    proc = subprocess.run(argv, cwd=str(repo), capture_output=True, check=False)
    if proc.returncode not in (0, 1) or not out.is_file():
        return {"status": "failed", "detail": f"tool_exit={proc.returncode}",
                "stdout": _tally(proc.stdout), "stderr": _tally(proc.stderr)}
    try:
        report = json.loads(out.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "failed", "detail": "report_unparsable"}
    return {"status": "passed",
            "evidence": {"tool_exit": proc.returncode,
                         "undocumented_versions": len(report.get("undocumented_versions") or []),
                         "broken_navigation_links": len(report.get("broken_navigation_links") or []),
                         "closed_version_chain": report.get("closed_version_chain")}}


def check_rulepack_identity(repo: Path) -> dict:
    """共享威胁规则包 Python/Go 双份必须字节相同，否则同一规则在两处解释不同。"""
    paths = [repo / RULEPACK_PYTHON, repo / RULEPACK_GO]
    for path in paths:
        if not path.is_file():
            return {"status": "blocked", "detail": f"missing:{path.relative_to(repo)}"}
    digests = {str(p.relative_to(repo)): sha256_bytes(p.read_bytes()) for p in paths}
    sizes = {str(p.relative_to(repo)): p.stat().st_size for p in paths}
    if len(set(digests.values())) != 1:
        return {"status": "failed", "detail": "rulepack_copies_differ",
                "evidence": {"sha256": digests, "bytes": sizes}}
    return {"status": "passed", "evidence": {"sha256": digests, "bytes": sizes}}


def check_prod_bundle_has_no_dev_identity(out_dir: Path) -> dict:
    """正式构建产物内**不得**出现开发身份字面量（断言；命中即失败）。"""
    if not out_dir.is_dir():
        return {"status": "blocked", "detail": "build_output_missing"}
    hits = {}
    files = 0
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        files += 1
        try:
            blob = path.read_bytes()
        except OSError:
            return {"status": "blocked", "detail": "build_output_unreadable"}
        for literal in DEV_IDENTITY_LITERALS:
            if literal.encode() in blob:
                hits.setdefault(literal, []).append(str(path.relative_to(out_dir)))
    if hits:
        return {"status": "failed", "detail": "dev_identity_in_production_bundle",
                "evidence": {"files_scanned": files, "hits": hits}}
    return {"status": "passed",
            "evidence": {"files_scanned": files, "literals_absent": list(DEV_IDENTITY_LITERALS)}}


def build_gates(repo: Path, build_dir: Path) -> list[dict]:
    """固定顺序的门禁清单。`post` 为命令之后必须成立的断言。"""
    python = str(repo / "apps/control-api/.venv/bin/python")
    gates = [
        {"id": "backend_full_suite", "kind": "command", "cwd": "apps/control-api",
         "argv": [python, "-m", "pytest", "app/tests", "-p", "no:randomly"],
         "why": "全量且固定顺序；单独运行测试文件会产生空通过"},
        {"id": "web_unit_suite", "kind": "command", "cwd": "apps/web",
         "argv": ["npx", "vitest", "run"],
         "why": "不带自定义 reporter（vitest 4 已移除 basic）"},
        {"id": "web_prod_build", "kind": "command", "cwd": "apps/web",
         "argv": ["npx", "tsc", "-b"], "env": {"VITE_DEV_MODE": "false"},
         "why": "正式构建前先做类型检查"},
        {"id": "web_prod_build_bundle", "kind": "command", "cwd": "apps/web",
         "argv": ["npx", "vite", "build", "--outDir", str(build_dir), "--emptyOutDir"],
         "env": {"VITE_DEV_MODE": "false"},
         "post": lambda _outcome: check_prod_bundle_has_no_dev_identity(build_dir),
         "why": "正式模式产物输出到临时独立目录，且不得含开发身份"},
        {"id": "rulepack_python_go_identity", "kind": "check",
         "fn": lambda: check_rulepack_identity(repo),
         "why": "共享规则包双份一致性"},
    ]
    for gate_id, subdir in GO_MODULES:
        gates.append({"id": f"{gate_id}_gofmt", "kind": "check",
                      "fn": lambda subdir=subdir: check_gofmt(repo, subdir),
                      "why": "gofmt 只对跟踪文件判定"})
        gates.append({"id": f"{gate_id}_vet", "kind": "command", "cwd": subdir,
                      "argv": ["go", "vet", "./..."]})
        # -count=1 强制重跑：Go 测试缓存按输入内容寻址，命中时 stdout 为 "ok … (cached)"。
        # 那等价于"同一份输入此前通过"，但**不是本次执行证据**，而任务书要求把历史结果与
        # 本次结果分开。详见执行记录 R07.6 门禁设计缺陷 4。
        gates.append({"id": f"{gate_id}_race", "kind": "command", "cwd": subdir,
                      "argv": ["go", "test", "-race", "-count=1", "./..."],
                      "post": check_go_output_is_fresh,
                      "why": "-count=1 禁缓存；否则 (cached) 会把'没跑'呈现为'通过'"})
    gates.append({"id": "contract_version_chain", "kind": "check",
                  "fn": lambda: check_contract_version_chain(repo, build_dir),
                  "why": "链未闭合时工具退出 1；本门禁只要求闭合与否可被判定，可接受性由 R06 裁决"})
    return gates


def check_go_output_is_fresh(outcome: dict) -> dict:
    """Go 测试缓存命中会把"没跑"呈现为"通过"，本断言把它降级为失败。

    `-count=1` 应当消除缓存；本断言存在的意义是**防止该参数被误删后门禁悄悄变成"历史通过"**。
    只检查输出尾部（工具本身只保留尾部），`ok … (cached)` 由 go test 输出在末尾。
    """
    stdout = outcome.get("stdout")
    tail = stdout.get("tail") if isinstance(stdout, dict) else ""
    cached = [line for line in (tail or "").splitlines() if "(cached)" in line]
    if cached:
        return {"status": "failed", "detail": f"go_test_cache_hit_is_not_fresh_execution:{len(cached)}"}
    return {"status": "passed", "detail": "no_cached_packages_in_output_tail"}


def run_gate(repo: Path, gate: dict) -> dict:
    record = {"id": gate["id"], "kind": gate["kind"]}
    if gate.get("why"):
        record["why"] = gate["why"]
    if gate["kind"] == "check":
        record["command"] = None
        try:
            outcome = gate["fn"]()
        except (OSError, ValueError) as exc:
            outcome = {"status": "blocked", "detail": f"check_error:{type(exc).__name__}"}
    else:
        record["command"] = " ".join(gate["argv"])
        record["cwd"] = gate.get("cwd") or "."
        outcome = run_command(repo, gate)
        if outcome.get("status") == "passed" and gate.get("post"):
            outcome = dict(outcome)
            outcome["post_check"] = gate["post"](outcome)
            if outcome["post_check"]["status"] != "passed":
                outcome["status"] = outcome["post_check"]["status"]
                outcome["detail"] = outcome["post_check"].get("detail")
    record.update(outcome)
    record.setdefault("status", "blocked")
    record.setdefault("detail", None)
    return record


def run_gates(repo: Path, gates: list[dict], build_dir: Path) -> dict:
    started = utc_now()
    records = [run_gate(repo, gate) for gate in gates]
    skipped = [dict(item, status="skipped") for item in DECLARED_UNAVAILABLE]
    statuses = [r["status"] for r in records]
    if "failed" in statuses:
        conclusion = "gates_failed"
    elif any(s in statuses for s in ("blocked",)) or skipped:
        conclusion = "gates_incomplete"
    else:
        conclusion = "gates_green"
    return {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "started_at": started,
        "finished_at": utc_now(),
        "repo": str(repo),
        "head_sha": git(repo, "rev-parse", "HEAD"),
        "branch": git(repo, "rev-parse", "--abbrev-ref", "HEAD"),
        "worktree_modified_count": len([line for line in
                                        git(repo, "status", "--porcelain").splitlines() if line.strip()]),
        "gates": records,
        "skipped_gates": skipped,
        "failed_gate_ids": [r["id"] for r in records if r["status"] == "failed"],
        "blocked_gate_ids": [r["id"] for r in records if r["status"] == "blocked"],
        "skipped_gate_ids": [item["id"] for item in skipped],
        "conclusion": conclusion,
        "not_evidence_of": list(NOT_EVIDENCE_OF),
    }


def write_report_exclusive(out_path: Path, report: dict) -> None:
    parent_fd = None
    try:
        absolute = out_path.absolute()
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent_fd = os.open(absolute.anchor, flags)
        for part in absolute.parts[1:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, flags, dir_fd=parent_fd)
            os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(absolute.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent_fd)
    except FileExistsError:
        raise RuntimeError(f"report path already exists; refusing to overwrite: {out_path}") from None
    except (OSError, AttributeError) as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"report path already exists: {out_path}") from None
        raise RuntimeError("report directory unavailable or unsafe") from None
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=True, indent=2, sort_keys=True)
    except OSError:
        raise RuntimeError("report write failed") from None


def main(argv: list[str] | None = None, gate_builder=None) -> int:
    """`gate_builder` 仅供测试注入合成门禁；生产调用不传，恒用 `build_gates`。"""
    parser = argparse.ArgumentParser(description="R07 统一防御门禁执行器（只读 + 临时构建）")
    parser.add_argument("--repo", required=True, help="仓库根路径")
    parser.add_argument("--out", required=True, help="报告 JSON 输出路径（必须位于仓库外，独占创建）")
    parser.add_argument("--only", help="只跑指定 id（逗号分隔）；使用后结论恒为 partial_run_not_a_gate")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="单门禁超时秒数")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_path = Path(args.out)
    if not repo.is_dir():
        return EXIT_USAGE
    if out_path.absolute().is_relative_to(repo):
        parser.exit(EXIT_USAGE, "report must be written outside the repository\n")
    if not git(repo, "rev-parse", "HEAD"):
        return EXIT_USAGE

    build_dir = Path(tempfile.mkdtemp(prefix="siq-gate-build-"))
    gates = (gate_builder or build_gates)(repo, build_dir)
    for gate in gates:
        gate["timeout"] = args.timeout
    selected = None
    if args.only:
        selected = {part.strip() for part in args.only.split(",") if part.strip()}
        gates = [gate for gate in gates if gate["id"] in selected]
        if not gates:
            parser.exit(EXIT_USAGE, "no gate matched --only\n")

    try:
        report = run_gates(repo, gates, build_dir)
    except KeyboardInterrupt:
        return EXIT_NOT_GREEN
    if selected is not None:
        # 子集运行不得被读作"门禁通过"：结论与通过集合都明确标注为部分运行。
        report["conclusion"] = "partial_run_not_a_gate"
        report["selected_only"] = sorted(selected)
    report["build_dir"] = str(build_dir)
    try:
        write_report_exclusive(out_path, report)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_REPORT_WRITE_FAILED

    for record in report["gates"]:
        sys.stderr.write(f"{record['status']:>7}  {record['id']}\n")
    sys.stderr.write(f"conclusion={report['conclusion']} report={out_path}\n")
    return EXIT_PASS if report["conclusion"] == "gates_green" else EXIT_NOT_GREEN


if __name__ == "__main__":
    raise SystemExit(main())
