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
  `conclusion` 不可能是绿色；
- **消耗资源的门禁必须显式启用**：`migration_replay_postgres` 需要一次性 PostgreSQL 容器，
  默认**连探测都不做**，只有显式传 `--enable-ephemeral-postgres-gate` 才会先只读探测
  docker 与镜像、再决定是"跑"还是"记为跳过（带**实测**原因，而非泛泛的'环境不支持'）"；
  `browser_acceptance` 同理，需 `--enable-browser-smoke-gate`，会做一次**模拟身份**前端构建
  （独立临时目录、不可发布）并跑 `run-browser-smoke-suite.py`。
  两者的证据都附带**摘要级断言**（`post`）：证据必须来自本次运行、且不得声称测过生产身份/生产部署。

安全边界：只读源码 + 临时构建；**不安装依赖、不提交、不签名、不发布、不读 `.env`/私钥/种子**。
默认**不启动服务、不连数据库**；唯一例外是显式 `--enable-ephemeral-postgres-gate`：此时启动的是
**一次性回环 PostgreSQL 容器**（镜像须已存在、**不自动拉取**、无卷挂载、`--rm` + `finally` 双保险回收），
容器销毁即数据消失，且该例外需按任务书 §3.2 先取得对应许可。正式构建显式 `VITE_DEV_MODE=false`
且输出到临时目录，与模拟身份构建分离；`--enable-browser-smoke-gate` **不启动**任何控制面服务——
被测脚本各自在本机 `127.0.0.1` 起临时静态服务并用路由 mock，构建同样落在独立临时目录
（目录名自带 `NOT-RELEASABLE`）。
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
from datetime import UTC, datetime
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

# 资源消耗型门禁（默认不跑，显式启用时才探测/执行）。
POSTGRES_UNAVAILABLE_ID = "migration_replay_postgres"
POSTGRES_IMAGE = "postgres:17-alpine"
POSTGRES_CHECK_TOOL = "scripts/enterprise-experience/deployment-postgres-check.py"
POSTGRES_GATE_ID = "migration_replay_postgres_ephemeral"

# 浏览器验收（同样默认不跑）：需要带 playwright 的解释器 + 一次模拟身份前端构建。
# 实测（执行记录 R09.5）**不需要运行中的控制面**——脚本自带 127.0.0.1 静态服务与路由 mock。
BROWSER_UNAVAILABLE_ID = "browser_acceptance"
BROWSER_SUITE_TOOL = "scripts/enterprise-experience/run-browser-smoke-suite.py"
BROWSER_GATE_ID = "browser_acceptance_simulated"

# 用**发行版元数据**探测，而不是 `playwright.__version__`——后者不存在，会把装了
# playwright 的解释器误判成没装（"不可跑"记错的典型写法）。
PLAYWRIGHT_PROBE = "from importlib.metadata import version; print(version('playwright'))"

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
        # 2026-09-26：该门禁已在显式 opt-in 下真实执行并**通过**（一次性回环容器，见执行记录 R09.4(8)/R07.10b）。
        # 因此下面的原因是"资源要求 + 需逐次许可"，不是"不可执行"；未显式启用时它仍如实记为 skipped。
        "note": "真实 PostgreSQL 迁移回放与部署竞态需临时数据库容器；按任务书 §3.2 需先说明隔离/目标/回收并取得许可"
        "（该路径已于 2026-09-26 获批并在一次性回环容器上执行通过，需 --enable-ephemeral-postgres-gate 显式启用）",
        "tool": "scripts/enterprise-experience/deployment-postgres-check.py",
    },
    {
        "id": "browser_acceptance",
        "reason": "requires_frontend_simulated_build_and_playwright",
        # 2026-09-26 实测更正：原记为 requires_running_services，不准确。
        # 全部 30 个都自带隔离环境，**不需要任何预先运行的控制面**；但并非"全都不碰真实后端"——
        # 其中 8 个（2026-09-26 实测，非硬编码：套件按 SIQ_AS_DEV 标记逐个判定并写入 real_dev_api_scripts）
        # 会**自己起来**一个回环 dev 控制面进程（真实 socket + 真实 HTTP + 合成 X-Dev 身份，非真实 IAM），
        # 其余走路由 mock。另 2 个需原生 Edge 与框架连接器二进制（不提供即记 blocked）。
        # 实跑 25/30 通过，5 项失败**全部落在那 8 个真实后端脚本内**，且为 UI 可见性/文本断言
        # （留存证据里含服务端生成的 cr_/pol_ 等 id，说明 HTTP 往返已经成功），归因于并作者未提交的
        # apps/web 改动（本轮提交路径不含 apps/web）。见执行记录 R09.5 / R07.11。
        "note": "30 个 *-browser-smoke.py 需前端模拟身份构建 + Playwright（2 个另需原生 Edge/连接器），"
        "不需要预先运行的控制面；实测 25/30 通过，5 项失败已归因；"
        "共享夹具为 mocked browser only，但其中 8 个脚本会自起回环 dev 控制面（真实 HTTP、合成身份）；"
        "套件本身不做契约级断言（状态码/JSON 形状/隔离序），故不是契约验收证据",
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
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def docker_probe(repo: Path, runner=subprocess.run) -> dict:
    """只读探测 `migration_replay_postgres` 能否跑：docker 客户端 → 守护进程 → 镜像。

    **本函数绝不拉取镜像、绝不启动容器**（`runner` 只被喂 `version` / `image inspect`）；
    镜像缺失时返回不可跑，而不是替使用者 `docker pull`——拉取等于引入新依赖，需单独授权。
    """
    evidence = {"image": POSTGRES_IMAGE}

    def probe(argv: list[str]) -> dict:
        try:
            result = runner(argv, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "detail": f"docker_probe_error:{type(exc).__name__}"}
        if result.returncode != 0:
            return {"ok": False, "detail": (result.stderr or "").strip()[:200] or "exit_nonzero"}
        return {"ok": True, "stdout": result.stdout.strip()}

    client = probe(["docker", "version", "--format", "{{.Server.Version}}"])
    if not client["ok"]:
        return {"runnable": False, "reason": "docker_daemon_or_client_unavailable",
                "evidence": {**evidence, "detail": client["detail"]}}
    evidence["server_version"] = client["stdout"]
    image = probe(["docker", "image", "inspect", POSTGRES_IMAGE, "--format", "{{.Id}}"])
    if not image["ok"]:
        return {"runnable": False, "reason": "postgres_image_absent_and_auto_pull_forbidden",
                "evidence": {**evidence, "detail": image["detail"]}}
    evidence["image_id"] = image["stdout"]
    return {"runnable": True, "reason": None, "evidence": evidence}


def check_postgres_evidence(evidence_dir: Path, script_path: Path) -> dict:
    """断言 A1 留证确实来自**本次一次性库**，而不是"跑过一次就算过"。

    逐条要求：`passed`、`ephemeral_database` 为真、**未声称测过真实身份**、
    `checks` 非空，且 `script_sha256` 与当前脚本字节一致（防止用旧脚本的结果充当本次证据）。
    """
    result_path = evidence_dir / "result.json"
    if not result_path.is_file():
        return {"status": "blocked", "detail": "postgres_evidence_missing"}
    try:
        proof = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "blocked", "detail": "postgres_evidence_unreadable"}
    if proof.get("passed") is not True:
        return {"status": "failed", "detail": "postgres_evidence_not_passed"}
    if proof.get("ephemeral_database") is not True:
        return {"status": "failed", "detail": "postgres_evidence_not_ephemeral"}
    if proof.get("production_identity_tested") is not False:
        return {"status": "failed", "detail": "postgres_evidence_claims_production_identity"}
    checks = proof.get("checks")
    if not isinstance(checks, dict) or not checks:
        return {"status": "failed", "detail": "postgres_evidence_has_no_checks"}
    if proof.get("script_sha256") != sha256_bytes(script_path.read_bytes()):
        return {"status": "failed", "detail": "postgres_evidence_script_digest_mismatch"}
    return {"status": "passed", "evidence": {
        "checks": sorted(checks),
        "checks_count": len(checks),
        "database_image_id": proof.get("database_image_id"),
        "migrated_head": proof.get("migrated_head"),
        "script_sha256": proof["script_sha256"],
        "result_path": str(result_path),
    }}


def postgres_gate_decision(repo: Path, *, enabled: bool, runner=subprocess.run) -> dict:
    """决定本次运行里 `migration_replay_postgres` 是"跑"还是"跳过"，以及**为什么**。

    未启用时**不触碰 docker**（连只读探测都不做）——"没启用"与"探测后确实没法跑"
    是两种不同的诚实，报告必须能区分。跳过项永远留在 `skipped_gates` 里，因此
    `conclusion` 不可能因"没跑"而变绿。
    """
    declaration = next(item for item in DECLARED_UNAVAILABLE
                       if item["id"] == POSTGRES_UNAVAILABLE_ID)
    if not enabled:
        return {"action": "skipped", "reason": declaration["reason"],
                "note": declaration["note"] + "；本次未显式启用 --enable-ephemeral-postgres-gate"}
    probe = docker_probe(repo, runner)
    if not probe["runnable"]:
        return {"action": "skipped", "reason": probe["reason"],
                "note": "已启用但只读探测判定不可跑；不自动拉取镜像、不以 SQLite 代跑",
                "measured": True, "evidence": probe["evidence"]}
    return {"action": "run", "reason": None, "measured": True, "evidence": probe["evidence"]}


def postgres_gate(repo: Path, evidence_dir: Path) -> dict:
    """A1 门禁本体：一次性回环 PostgreSQL 的迁移回放 + 部署竞态，附证据断言。"""
    return {
        "id": POSTGRES_GATE_ID,
        "kind": "command",
        "cwd": ".",
        "argv": [str(repo / "apps/control-api/.venv/bin/python"),
                 str(repo / POSTGRES_CHECK_TOOL), str(evidence_dir)],
        "post": lambda _outcome: check_postgres_evidence(evidence_dir, repo / POSTGRES_CHECK_TOOL),
        "why": "SQLite 不能替代 PostgreSQL 的行锁/迁移语义；留证须来自本次一次性库",
    }


def browser_probe(repo: Path, python: Path, runner=subprocess.run) -> dict:
    """只读探测：这个解释器能不能跑浏览器验收、仓库里有没有可跑的脚本。**不安装任何依赖**。"""
    evidence: dict = {"python": str(python)}
    evidence["scripts"] = len(sorted((repo / "scripts/enterprise-experience").glob("*-browser-smoke.py")))
    if evidence["scripts"] == 0:
        return {"runnable": False, "reason": "no_browser_smoke_scripts_found", "evidence": evidence}
    if not python.is_file():
        return {"runnable": False, "reason": "browser_python_not_found", "evidence": evidence}
    try:
        result = runner([str(python), "-c", PLAYWRIGHT_PROBE],
                        capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"runnable": False, "reason": "playwright_probe_failed",
                "evidence": {**evidence, "detail": type(exc).__name__}}
    if result.returncode != 0:
        # 缺 playwright 的解释器**不能**代跑：装依赖不在本工具边界内，如实记为不可跑。
        return {"runnable": False, "reason": "playwright_not_importable",
                "evidence": {**evidence, "detail": (result.stderr or "").strip()[:200]}}
    evidence["playwright_version"] = (result.stdout or "").strip()
    return {"runnable": True, "reason": None, "evidence": evidence}


def check_browser_evidence(evidence_dir: Path, suite_path: Path) -> dict:
    """断言浏览器验收留证确实来自**本次模拟身份套件**，且没有冒充生产结论。"""
    result_path = evidence_dir / "result.json"
    if not result_path.is_file():
        return {"status": "blocked", "detail": "browser_evidence_missing"}
    try:
        proof = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "blocked", "detail": "browser_evidence_unreadable"}
    if proof.get("passed") is not True:
        return {"status": "failed", "detail": "browser_evidence_not_passed"}
    if proof.get("simulated_build") is not True:
        return {"status": "failed", "detail": "browser_evidence_not_a_simulated_build"}
    if proof.get("production_deployed") is not False:
        return {"status": "failed", "detail": "browser_evidence_claims_production_deploy"}
    if proof.get("production_identity_tested") is not False:
        return {"status": "failed", "detail": "browser_evidence_claims_production_identity"}
    counts = proof.get("counts")
    if not isinstance(counts, dict) or not counts.get("total"):
        return {"status": "failed", "detail": "browser_evidence_has_no_scripts"}
    if proof.get("suite_sha256") != sha256_bytes(suite_path.read_bytes()):
        return {"status": "failed", "detail": "browser_evidence_suite_digest_mismatch"}
    # 新增自述字段的类型必须核对：套件把"哪些脚本起了真实后端"作为证据的一部分度量输出，
    # 门禁只有真的读到它，报告里的范围描述才算有据（而不是读一句范围声明）。
    if not isinstance(proof.get("real_dev_api_scripts"), list):
        return {"status": "failed", "detail": "browser_evidence_missing_real_dev_api_measurement"}
    return {"status": "passed", "evidence": {
        "counts": counts,
        "failed_scripts": proof.get("failed_scripts"),
        "blocked_scripts": proof.get("blocked_scripts"),
        "real_dev_api_scripts": proof.get("real_dev_api_scripts"),
        "failed_are_subset_of_real_dev_api": proof.get("failed_are_subset_of_real_dev_api"),
        "playwright_version": proof.get("playwright_version"),
        "scope_note": proof.get("scope_note"),
        "suite_sha256": proof["suite_sha256"],
        "result_path": str(result_path),
    }}


def browser_gate_decision(repo: Path, *, enabled: bool, python: Path | None,
                          runner=subprocess.run) -> dict:
    """决定本次运行里 `browser_acceptance` 是"跑"还是"跳过"，以及**为什么**。

    未启用时**不触碰任何东西**（不探解释器、不构建前端）。
    """
    declaration = next(item for item in DECLARED_UNAVAILABLE
                       if item["id"] == BROWSER_UNAVAILABLE_ID)
    if not enabled:
        return {"action": "skipped", "reason": declaration["reason"],
                "note": declaration["note"] + "；本次未显式启用 --enable-browser-smoke-gate"}
    resolved = python or Path(sys.executable)
    probe = browser_probe(repo, resolved, runner)
    if not probe["runnable"]:
        return {"action": "skipped", "reason": probe["reason"],
                "note": ("已启用但只读探测判定不可跑；不安装依赖、不用缺 playwright 的解释器代跑"
                         "（可用 --browser-smoke-python 指定）"),
                "measured": True, "evidence": probe["evidence"]}
    return {"action": "run", "reason": None, "measured": True,
            "python": str(resolved), "evidence": probe["evidence"]}


def browser_gate(repo: Path, evidence_dir: Path, python: Path, *,
                 edge: Path | None = None, connector_dir: Path | None = None) -> dict:
    """浏览器验收门禁本体：模拟身份构建 + 全部 `*-browser-smoke.py`，附证据断言。

    需要原生 Edge/连接器的脚本由 `--browser-smoke-edge` / `--browser-smoke-connector-dir` 提供；
    **不提供时它们记为 `blocked`**（套件不会替它们造假参数），套件因此不可能"通过"。
    """
    argv = [str(python), str(repo / BROWSER_SUITE_TOOL), "--repo", str(repo), "--out", str(evidence_dir)]
    if edge is not None:
        argv += ["--edge", str(edge)]
    if connector_dir is not None:
        argv += ["--connector-dir", str(connector_dir)]
    return {
        "id": BROWSER_GATE_ID,
        "kind": "command",
        "cwd": ".",
        "argv": argv,
        "post": lambda _outcome: check_browser_evidence(evidence_dir, repo / BROWSER_SUITE_TOOL),
        # 范围措辞必须与实测一致：不是"全都不碰真实后端"（8/30 会自起回环 dev 控制面），
        # 也不是"真实 HTTP 契约验收"（套件只断言脚本通过/失败，不核对状态码/JSON 形状/隔离序）。
        "why": "共享夹具为模拟身份构建 + 路由 mock，其中部分脚本自起回环 dev 控制面（真实 HTTP、"
               "合成 X-Dev 身份）；套件只断言脚本通过/失败，不做契约级断言，故不构成契约验收证据",
    }


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


def run_gates(repo: Path, gates: list[dict], build_dir: Path, *,
              postgres_decision: dict | None = None,
              browser_decision: dict | None = None) -> dict:
    started = utc_now()
    records = [run_gate(repo, gate) for gate in gates]
    attempted_ids = {r["id"] for r in records}
    # 每条声明只可能被一个可选门禁覆盖；覆盖时用**本次实测**的原因替换静态原因。
    overrides = {
        POSTGRES_UNAVAILABLE_ID: (POSTGRES_GATE_ID, postgres_decision),
        BROWSER_UNAVAILABLE_ID: (BROWSER_GATE_ID, browser_decision),
    }
    skipped = []
    for item in DECLARED_UNAVAILABLE:
        gate_id, decision = overrides.get(item["id"], (None, None))
        if decision is not None:
            if decision["action"] == "run" and gate_id in attempted_ids:
                # 真的跑了就不该再登记为"不可跑"；跑成什么样由门禁记录本身说明。
                continue
            item = {**item, "reason": decision["reason"],
                    "note": decision.get("note") or item["note"],
                    "measured": bool(decision.get("measured"))}
        skipped.append(dict(item, status="skipped"))
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
    parser.add_argument("--enable-ephemeral-postgres-gate", action="store_true",
                        help="显式启用一次性回环 PostgreSQL 门禁（会启动容器）；按 §3.2 需先取得许可")
    parser.add_argument("--enable-browser-smoke-gate", action="store_true",
                        help="显式启用浏览器验收门禁（会做一次模拟身份前端构建并跑 30 个脚本）")
    parser.add_argument("--browser-smoke-python",
                        help="带 playwright 的解释器路径；默认用当前解释器（缺 playwright 时记为不可跑）")
    parser.add_argument("--browser-smoke-edge", help="原生 Edge 二进制（仅需要它的脚本用得到）")
    parser.add_argument("--browser-smoke-connector-dir", help="框架连接器二进制目录")
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

    # 只有本次**确实要跑**它时才探测 docker：`--only` 把它排除掉时连只读探测都不做。
    # 顺序上必须先判定"是否被选中"、再把门禁**追加到过滤之前**，否则 `--only <本门禁 id>`
    # 会得到 "no gate matched"——门禁永远无法被单独选中（见执行记录 R07.10 缺陷 2）。
    postgres_enabled = args.enable_ephemeral_postgres_gate and (
        selected is None or POSTGRES_GATE_ID in selected)
    postgres_decision = postgres_gate_decision(repo, enabled=postgres_enabled)
    if args.enable_ephemeral_postgres_gate and not postgres_enabled:
        # 说清是"本次没轮到它"，不是"没启用"，更不是"探测后不可跑"。
        postgres_decision["note"] = ("已显式启用，但本次被 --only 排除，"
                                     "未探测 docker、未启动容器；仍登记为不可跑")
        postgres_decision["excluded_by_only"] = True
    browser_enabled = args.enable_browser_smoke_gate and (
        selected is None or BROWSER_GATE_ID in selected)
    browser_python = Path(args.browser_smoke_python).resolve() if args.browser_smoke_python else None
    browser_edge = Path(args.browser_smoke_edge).resolve() if args.browser_smoke_edge else None
    browser_connector_dir = (Path(args.browser_smoke_connector_dir).resolve()
                             if args.browser_smoke_connector_dir else None)
    for flag, path in (("--browser-smoke-edge", browser_edge),
                       ("--browser-smoke-connector-dir", browser_connector_dir)):
        # 路径给错了就当用法错误处理：不让"文件不存在"变成一条看不懂的 blocked 记录。
        if path is not None and not path.exists():
            parser.exit(EXIT_USAGE, f"{flag}: no such path: {path}\n")
    browser_decision = browser_gate_decision(repo, enabled=browser_enabled, python=browser_python)
    if args.enable_browser_smoke_gate and not browser_enabled:
        browser_decision["note"] = ("已显式启用，但本次被 --only 排除，"
                                    "未探测解释器、未构建前端；仍登记为不可跑")
        browser_decision["excluded_by_only"] = True

    if postgres_decision["action"] == "run":
        # **不预建**该目录：A1 脚本要求传入一个**不存在**的新目录（`mkdir(exist_ok=False)`），
        # 正是为了不可能覆盖上一次的留证。`mkdtemp` 只为取一个不会撞名的路径，随后立即移除；
        # 曾经预建导致 `FileExistsError`、门禁假失败（见执行记录 R07.10 缺陷 1）。
        evidence_dir = Path(tempfile.mkdtemp(prefix="siq-gate-postgres-evidence-"))
        os.rmdir(evidence_dir)
        postgres_decision["evidence_dir"] = str(evidence_dir)
        gates = gates + [postgres_gate(repo, evidence_dir)]
        gates[-1]["timeout"] = args.timeout
    if browser_decision["action"] == "run":
        # 同样**不预建**：套件自己 `mkdir(0o700)` 独占创建证据目录，已存在即拒绝。
        browser_evidence_dir = Path(tempfile.mkdtemp(prefix="siq-gate-browser-evidence-"))
        os.rmdir(browser_evidence_dir)
        browser_decision["evidence_dir"] = str(browser_evidence_dir)
        gates = gates + [browser_gate(repo, browser_evidence_dir,
                                      Path(browser_decision["python"]),
                                      edge=browser_edge, connector_dir=browser_connector_dir)]
        gates[-1]["timeout"] = args.timeout
    if selected is not None:
        gates = [gate for gate in gates if gate["id"] in selected]
        if not gates:
            parser.exit(EXIT_USAGE, "no gate matched --only\n")

    try:
        report = run_gates(repo, gates, build_dir, postgres_decision=postgres_decision,
                           browser_decision=browser_decision)
    except KeyboardInterrupt:
        return EXIT_NOT_GREEN
    report["optional_gate_decisions"] = [
        {"id": POSTGRES_UNAVAILABLE_ID, **postgres_decision},
        {"id": BROWSER_UNAVAILABLE_ID, **browser_decision}]
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
