"""R07.11 浏览器验收套件：`enterprise-gate-run.py --enable-browser-smoke-gate` 的探测/执行体。

**为什么需要单独一个文件**：30 个 `*-browser-smoke.py` 的参数家族不一致（实测 4 个只接受
`--output`、18 个 `--out-dir`、8 个 `--out`，其中 2 个另外需要原生 Edge 与框架连接器二进制），
且都需要一个**不存在**的新输出目录（脚本内部 `mkdir(exist_ok=False)`，正是为了不可能覆盖上一次留证）。
把这些拼装逻辑写进门禁执行器会让门禁本身变成"参数拼装器"，所以拆出来，并让它的产物可被断言。

**这个套件证明什么、不证明什么**（写进 `result.json` 的硬字段，不是注释）：
脚本自述 `scope: mocked browser only`、`production_deployed: false`——它们跑的是
**模拟身份（`VITE_DEV_MODE=true`）构建 + `127.0.0.1` 静态服务 + Playwright 路由 mock**。
因此本套件只证明"前端在模拟条件下的交互行为"，**不是真实后端 HTTP 契约证据、不是真实 IAM 证据**。

安全边界：不启动任何共享服务、不连数据库、不读 `.env`/私钥/种子、不安装依赖；
模拟身份构建输出到**独立临时目录**且目录名自带 `NOT-RELEASABLE`，
不覆盖也不等同于正式构建（正式构建统一由 `enterprise-gate-run.py` 以 `VITE_DEV_MODE=false` 产生）。
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

TOOL_VERSION = "run-browser-smoke-suite/0.1.0"
SCHEMA_VERSION = "siq-browser-smoke-suite/v1"

EXIT_PASS = 0
EXIT_NOT_PASS = 1
EXIT_USAGE = 2
EXIT_BUILD_FAILED = 3

DEFAULT_TIMEOUT_SECONDS = 600
MAX_TAIL_CHARS = 2000

SMOKE_GLOB = "*-browser-smoke.py"
WEB_APP_DIR = "apps/web"

# 探测用的是**发行版元数据**而不是 `playwright.__version__`——后者根本不存在，
# 会让"装了 playwright 的解释器"被误判为没装（这是把"不可跑"记错的典型写法）。
PLAYWRIGHT_PROBE = "from importlib.metadata import version; print(version('playwright'))"
# 哪些脚本会自起**真实**回环控制面进程？判据是 dev 开关 `SIQ_AS_DEV`——只有它置位，
# X-Dev-* 合成身份头才会被 app/security.py 采纳。**这是运行时度量，不是写死的数字**：
# 30 个脚本里 8 个属于这一类（2026-09-26 实测），硬编码会随脚本增删腐坏。
REAL_DEV_API_MARKER = "SIQ_AS_DEV"
SCOPE_NOTE = ("scope: mocked browser only —— 共享夹具是模拟身份构建 + 本地静态服务 + Playwright 路由 mock；"
              "**但按 real_dev_api_scripts 列出的脚本会额外自起回环 dev 控制面**"
              "（真实 socket、真实 HTTP、合成 X-Dev 身份，非真实 IAM）；"
              "套件本身只断言各脚本通过/失败，**不做契约级断言**（状态码/JSON 形状/隔离序不做独立核对）；"
              "构建产物为模拟身份构建，不可发布")


def real_dev_api_scripts(script_paths) -> list[str]:
    """列出会自起回环 dev 控制面的脚本名（按内容判定，读不到就跳过，不猜）。

    结果进 result.json，让"这批脚本证明什么"**由证据自述**，而不是靠读者相信一句范围声明。
    """
    names: list[str] = []
    for path in script_paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if REAL_DEV_API_MARKER in text:
            names.append(Path(path).stem)
    return sorted(names)


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def tail(text: str | None) -> str:
    if not text:
        return ""
    return text[-MAX_TAIL_CHARS:]


def playwright_version(python: Path, runner=subprocess.run) -> str | None:
    """只读探测：解释器里有没有 playwright、版本是多少。不安装任何依赖。"""
    try:
        result = runner([str(python), "-c", PLAYWRIGHT_PROBE],
                        capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip() or None


def script_option_sets(repo: Path, python: Path, script_paths: list[Path],
                       runner=subprocess.run) -> dict[str, set[str]]:
    """用 `--help` 读出每个脚本**实际**接受的选项，而不是猜参数家族。

    `--help` 由 argparse 在处理参数时立即退出，不会执行验收逻辑，因此是只读的。
    """
    options: dict[str, set[str]] = {}
    for path in script_paths:
        try:
            result = runner([str(python), str(path), "--help"],
                            capture_output=True, text=True, timeout=60, cwd=str(repo))
        except (OSError, subprocess.SubprocessError):
            # 读不出选项就不猜：该脚本会以 `no_known_output_option` 记为 blocked，而不是被硬塞参数。
            options[path.stem] = set()
            continue
        found: set[str] = set()
        for line in (result.stdout or "").splitlines():
            stripped = line.strip()
            # argparse 把短选项与长选项打印在同一行（`-h, --help`），所以逐行取**所有** `--xxx`，
            # 而不是只取行首那一个词——否则会漏掉 `--help` 这类同行的长选项。
            if stripped.startswith("-"):
                found.update(re.findall(r"--[a-z0-9][a-z0-9-]*", stripped))
        options[path.stem] = found
    return options


def build_argv(python: Path, script_path: Path, options: set[str], *,
               web_build: Path | None, evidence_root: Path,
               edge: Path | None, connector_dir: Path | None) -> tuple[list[str], str | None]:
    """按脚本**实际**接受的选项拼参数；缺必需的原生二进制时返回 blocked 原因而不是假装能跑。"""
    argv = [str(python), str(script_path)]
    if "--web" in options:
        if web_build is None:
            return argv, "simulated_web_build_unavailable"
        argv += ["--web", str(web_build)]
    if "--edge" in options:
        if edge is None:
            return argv, "native_edge_binary_not_provided"
        argv += ["--edge", str(edge)]
    if "--connector-dir" in options:
        if connector_dir is None:
            return argv, "native_connector_dir_not_provided"
        argv += ["--connector-dir", str(connector_dir)]
    # 三种输出选项**都是目录**（实测脚本内部一律 `mkdir(exist_ok=False)`），
    # 因此这里只给出一个**尚未存在**的路径，**不预建**——预建会让脚本抛 FileExistsError，
    # 把"我的调用方式错"伪装成"验收失败"（同一坑见执行记录 R07.10 缺陷 1）。
    for flag in ("--out-dir", "--out", "--output"):
        if flag in options:
            argv += [flag, str(evidence_root / script_path.stem)]
            break
    else:
        return argv, "no_known_output_option"
    return argv, None


def build_web_simulated(repo: Path, *, runner=subprocess.run, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """模拟身份前端构建到独立临时目录；目录名自带 NOT-RELEASABLE，避免被误当正式产物。"""
    build_dir = Path(tempfile.mkdtemp(prefix="siq-browser-suite-web-SIMULATED-NOT-RELEASABLE-"))
    command = ["npx", "vite", "build", "--outDir", str(build_dir), "--emptyOutDir"]
    try:
        result = runner(command, cwd=str(repo / WEB_APP_DIR), capture_output=True, text=True,
                        timeout=timeout, env={**os.environ, "VITE_DEV_MODE": "true"})
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "web_build_dir": str(build_dir),
                "detail": f"web_build_error:{type(exc).__name__}"}
    if result.returncode != 0:
        return {"ok": False, "web_build_dir": str(build_dir), "command": " ".join(command),
                "detail": "web_build_exit_nonzero", "stderr_tail": tail(result.stderr)}
    return {"ok": True, "web_build_dir": str(build_dir), "command": " ".join(command),
            "env": {"VITE_DEV_MODE": "true"},
            "note": "模拟身份构建，独立临时目录，不可发布；与正式构建（VITE_DEV_MODE=false）分离"}


def run_suite(repo: Path, evidence_root: Path, *, python: Path, edge: Path | None,
              connector_dir: Path | None, only: set[str] | None,
              timeout: int, runner=subprocess.run, build_result: dict | None = None,
              keep_build: bool = False) -> dict:
    started = utc_now()
    if build_result is None:
        build_result = build_web_simulated(repo, runner=runner, timeout=timeout)
    web_build = Path(build_result["web_build_dir"]) if build_result.get("ok") else None

    script_paths = sorted((repo / "scripts/enterprise-experience").glob(SMOKE_GLOB))
    if only:
        script_paths = [p for p in script_paths if p.stem in only]
    options = script_option_sets(repo, python, script_paths, runner=runner)
    if playwright_version(python, runner) is None:
        # 没有 playwright 就没有浏览器验收可言；如实降级为 blocked，绝不把"没跑"记成通过。
        build_result = {**build_result, "ok": False, "playwright_missing": True,
                        "detail": build_result.get("detail") or "playwright_not_importable_in_interpreter"}
    records: dict[str, dict] = {}
    for path in script_paths:
        argv, blocked_reason = build_argv(python, path, options.get(path.stem, set()),
                                          web_build=web_build, evidence_root=evidence_root,
                                          edge=edge, connector_dir=connector_dir)
        if blocked_reason or not build_result.get("ok"):
            records[path.stem] = {"status": "blocked",
                                  "detail": blocked_reason or build_result.get("detail"),
                                  "command": " ".join(argv),
                                  "evidence_dir": None, "seconds": None, "exit_code": None}
            continue
        record = {"command": " ".join(argv), "evidence_dir": str(evidence_root / path.stem)}
        began = time.monotonic()
        try:
            result = runner(argv, cwd=str(repo), capture_output=True, text=True, timeout=timeout)
            record["exit_code"] = result.returncode
            record["seconds"] = round(time.monotonic() - began, 3)
            record["status"] = "passed" if result.returncode == 0 else "failed"
            record["stdout_tail"] = tail(result.stdout)
            record["stderr_tail"] = tail(result.stderr)
        except subprocess.TimeoutExpired:
            record.update({"status": "failed", "detail": f"timeout_after_{timeout}s",
                           "seconds": round(time.monotonic() - began, 3), "exit_code": None})
        except (OSError, subprocess.SubprocessError) as exc:
            record.update({"status": "blocked", "detail": f"runner_error:{type(exc).__name__}",
                           "seconds": round(time.monotonic() - began, 3), "exit_code": None})
        records[path.stem] = record

    counts = {name: sum(1 for r in records.values() if r["status"] == name)
              for name in ("passed", "failed", "blocked")}
    counts["total"] = len(records)
    passed = bool(records) and counts["failed"] == 0 and counts["blocked"] == 0
    real_api = real_dev_api_scripts(script_paths)
    failed_names = sorted(n for n, r in records.items() if r["status"] == "failed")
    result = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "started_at": started,
        "finished_at": utc_now(),
        "repo": str(repo),
        "passed": passed,
        "simulated_build": True,
        "production_deployed": False,
        "production_identity_tested": False,
        "web_build": build_result,
        "python": str(python),
        "playwright_version": playwright_version(python, runner),
        "edge_binary": str(edge) if edge else None,
        "connector_dir": str(connector_dir) if connector_dir else None,
        "scripts": records,
        "counts": counts,
        "failed_scripts": failed_names,
        "blocked_scripts": sorted(n for n, r in records.items() if r["status"] == "blocked"),
        # 度量而非声明：哪些脚本真的起了回环控制面进程（真实 socket + 真实 HTTP），
        # 以及失败项是否**全部**落在该子集内——后者是"失败发生在真实往返之后吗"的可核对线索。
        "real_dev_api_scripts": real_api,
        "failed_are_subset_of_real_dev_api": set(failed_names) <= set(real_api),
        "suite_sha256": sha256_file(Path(__file__)),
        "scope_note": SCOPE_NOTE,
    }
    if web_build is not None and not keep_build:
        shutil.rmtree(web_build, ignore_errors=True)
        result["web_build_removed"] = not web_build.exists()
    return result


def claim_evidence_dir(out_dir: Path) -> None:
    """**开跑之前**就独占占位：已存在即拒绝，绝不覆盖上一次留证。

    必须在跑脚本**之前**占位，而不是等写结果时才创建——每个脚本会用
    `mkdir(parents=True, exist_ok=False)` 建自己的输出目录，**顺手会把本目录也建出来**，
    于是"最后才独占创建"必然失败，而且是在整批跑完之后才失败（见执行记录 R07.11 缺陷 1）。
    """
    try:
        os.mkdir(out_dir, 0o700)
    except FileExistsError:
        raise RuntimeError(f"evidence dir already exists; refusing to overwrite: {out_dir}") from None
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"evidence dir already exists: {out_dir}") from None
        raise RuntimeError("evidence dir unavailable") from None


def write_result(out_dir: Path, result: dict) -> Path:
    """结果文件同样独占创建（`O_EXCL`），并落回本工具已占位的证据目录。"""
    result_path = out_dir / "result.json"
    try:
        fd = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"result already exists; refusing to overwrite: {result_path}") from None
        raise RuntimeError("result write unavailable") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=True, indent=2, sort_keys=True)
    return result_path


def main(argv: list[str] | None = None, *, runner=subprocess.run, build_web=None) -> int:
    """`runner` / `build_web` 仅供测试注入；生产调用不传。"""
    parser = argparse.ArgumentParser(description="R07.11 浏览器验收套件（模拟身份，只读源码 + 临时构建）")
    parser.add_argument("--repo", required=True, help="仓库根路径")
    parser.add_argument("--out", required=True, help="证据目录（必须**不存在**，由本工具独占创建）")
    parser.add_argument("--python", help="带 playwright 的解释器；默认用当前解释器")
    parser.add_argument("--edge", help="原生 Edge 二进制路径（仅需要它的脚本用得到）")
    parser.add_argument("--connector-dir", help="框架连接器二进制目录")
    parser.add_argument("--only", help="只跑指定脚本名（逗号分隔，不含 .py）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="单脚本超时秒数")
    parser.add_argument("--keep-build", action="store_true", help="保留模拟身份构建目录（默认删除）")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    out_dir = Path(args.out)
    if not repo.is_dir() or not (repo / "scripts/enterprise-experience").is_dir():
        parser.exit(EXIT_USAGE, "--repo must be a repository root\n")
    if out_dir.exists():
        parser.exit(EXIT_USAGE, "--out must not exist (evidence dirs are created exclusively)\n")
    python = Path(args.python).resolve() if args.python else Path(sys.executable)
    try:
        claim_evidence_dir(out_dir)  # 先占位，再跑（脚本会连带创建父目录）
    except RuntimeError as exc:
        parser.exit(EXIT_USAGE, f"{exc}\n")
    build_result = None
    if build_web is not None:
        build_result = build_web(repo)
    try:
        result = run_suite(repo, out_dir, python=python,
                           edge=Path(args.edge).resolve() if args.edge else None,
                           connector_dir=(Path(args.connector_dir).resolve()
                                          if args.connector_dir else None),
                           only=({part.strip() for part in args.only.split(",") if part.strip()}
                                 if args.only else None),
                           timeout=args.timeout, runner=runner, build_result=build_result,
                           keep_build=args.keep_build)
    except Exception as exc:  # 任何意外都要留下结果文件，否则证据目录会空着
        result = {"schema_version": SCHEMA_VERSION, "tool_version": TOOL_VERSION,
                  "started_at": utc_now(), "finished_at": utc_now(), "repo": str(repo),
                  "passed": False, "simulated_build": True, "production_deployed": False,
                  "production_identity_tested": False, "counts": {"total": 0},
                  "detail": f"suite_error:{type(exc).__name__}",
                  "scope_note": SCOPE_NOTE,
                  "suite_sha256": sha256_file(Path(__file__))}
    try:
        result_path = write_result(out_dir, result)
    except RuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_USAGE
    counts = result.get("counts") or {}
    sys.stderr.write(
        f"browser-smoke suite: {counts.get('passed', 0)} passed / {counts.get('failed', 0)} failed / "
        f"{counts.get('blocked', 0)} blocked (of {counts.get('total', 0)}); result={result_path}\n")
    # 失败/阻塞的脚本名也打到 stderr：门禁报告只保留输出尾部，没有这一行就只能看到计数。
    for label in ("failed", "blocked"):
        names = result.get(f"{label}_scripts") or []
        if names:
            sys.stderr.write(f"  {label}: {', '.join(names)}\n")
    if not (result.get("web_build") or {}).get("ok"):
        return EXIT_BUILD_FAILED
    return EXIT_PASS if result["passed"] else EXIT_NOT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
