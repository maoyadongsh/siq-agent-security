#!/usr/bin/env python3
"""O04-D frozen measurement protocol for native-path scenarios A-E (B1).

The protocol below is frozen BEFORE measurement: warmup, round count, sample
counts, scenario interleave order, percentile algorithm, exclusion rules and
absolute budgets. A budget miss is reported as a miss; budgets are never
widened after a run, and no sample is silently excluded.

Scope: component observations only. A/B/E run in-process fixtures with real
local crypto/state; C/D run a real subprocess fixture CLI. There is NO real
gateway, host end-to-end or sandbox in this evidence (B2/B3 stay blocked).

Rule from taskbook §15.5: scenario measurement must not run while the full
test suite or other build load is running. Run this script alone.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "apps/agentshield"

# ---- frozen protocol (do not tune after seeing results) --------------------
ROUNDS = 3
WARMUP = {  # per scenario, discarded before timed samples (mirrored in Go)
    "A": {"decide_allow": 5},
    "B": {"decide_allow_auth": 5, "decide_deny_revoked": 3},
    "C": {"probe_repeat": 3, "probe_cold": 0},  # cold sample measured first
    "D": {"timeout_fail": 3},
    "E": {"apply_rollback_cycle": 5},
}
SAMPLES = {  # required timed samples per scenario per round
    "A": {"decide_allow_ms": 200, "diagnose_unconfigured_ms": 200},
    "B": {"decide_allow_auth_ms": 200, "decide_deny_revoked_ms": 200},
    "C": {"probe_cold_ms": 1, "probe_repeat_ms": 200},
    "D": {"timeout_fail_ms": 60},  # fault injection; frozen below hot paths
    "E": {"apply_rollback_cycle_ms": 200},
}
ROUND_ORDERS = [["A", "B", "B", "A"], ["B", "A", "A", "B"], ["A", "B", "B", "A"]]
TAIL_SCENARIOS = ["C", "D", "E"]  # subprocess/fault paths appended per round
PERCENTILE_ALGORITHM = "nearest-rank on sorted samples (ceil(p/100*n))"
EXCLUSION_RULE = "none: any failed operation aborts the run; in D the timeout failure IS the measured event"
BUDGETS = {  # frozen absolute budgets (ms), dev machine, component level
    "A": {"decide_allow_ms": {"p95": 25.0}, "diagnose_unconfigured_ms": {"p95": 25.0}},
    "B": {"decide_allow_auth_ms": {"p95": 25.0}, "decide_deny_revoked_ms": {"p95": 25.0}},
    "C": {"probe_cold_ms": {"p95": 200.0}, "probe_repeat_ms": {"p95": 50.0}},
    "D": {"timeout_fail_ms": {"p95": 300.0, "max": 500.0}},
    "E": {"apply_rollback_cycle_ms": {"p95": 100.0}},
}
BUDGET_BASIS = (
    "frozen before measuring: p95 budgets sized at multiples of pre-study "
    "component magnitudes; B1-B0 relative budget is P95 increase <=10% but the "
    "B0 pre-change baseline requires a separate checkout and is not produced here"
)
EVIDENCE_LABEL = {
    "A": "component_in_process",
    "B": "component_in_process",
    "C": "component_real_subprocess_fixture",
    "D": "component_real_subprocess_fault_injection",
    "E": "component_in_process_fixture_cli",
}
NOT_MEASURED = [
    {"item": "B1_minus_B0_p95_relative", "budget": "p95_increase<=10%",
     "reason": "本组件 runner 不生成原始 B0；O04 增量 HTTP 对照由 openshell-o04-http-comparison.py 独立 archive 测量，不等价完整 B1-B0"},
    {"item": "B2_service_http_same_env", "reason": "需要真实 OpenShell 网关；缺真实后端，blocked"},
    {"item": "B3_new_integration_e2e", "reason": "需要真实后端与主机端到端旅程；blocked"},
    {"item": "host_e2e", "reason": "本轮全部为组件级证据，无主机端到端旅程"},
    {"item": "backend_process_count", "reason": "无真实后端；仅场景 A 断言 CLI 进程调用次数为 0"},
    {"item": "CPU", "reason": "未采集每场景 CPU 时间"},
    {"item": "RSS_per_scenario", "reason": "未采集每场景 RSS；perfbaseline 的 OS RSS 修复另行验证"},
    {"item": "disk_write_bytes", "reason": "未采集"},
    {"item": "network_requests", "reason": "无真实网络路径"},
    {"item": "false_rejection_rate", "reason": "误拒率需要长时间多样本真实负载，本轮 not_measured"},
]
# ----------------------------------------------------------------------------


def percentile(sorted_values: list[float], p: int) -> float:
    idx = math.ceil(p / 100 * len(sorted_values)) - 1
    return sorted_values[max(idx, 0)]


def summarize(values: list[float]) -> dict:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "min_ms": ordered[0],
        "max_ms": ordered[-1],
        **{f"p{q}_ms": percentile(ordered, q) for q in (50, 95, 99)},
    }


def run_scenario(binary: Path, scenario: str) -> dict:
    invocation = ["-test.run=^TestO04PerfScenario$", "-test.v", "-test.count=1"]
    proc = subprocess.run(
        [str(binary), *invocation], cwd=MODULE / "internal/receipt",
        timeout=300, capture_output=True, text=True,
        env={**os.environ, "SIQ_O04_PERF": "1", "SIQ_O04_SCENARIO": scenario},
    )
    if proc.returncode != 0:
        raise SystemExit(f"scenario {scenario} failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    marker = "SIQ_O04_RESULT="
    blocks = [line.split(marker, 1)[1] for line in proc.stdout.splitlines() if marker in line]
    if len(blocks) != 1:
        raise SystemExit(f"scenario {scenario} did not emit exactly one result block")
    return json.loads(blocks[0])


def validate(scenario: str, result: dict) -> None:
    for key, want in SAMPLES[scenario].items():
        got = result["samples_ms"].get(key)
        if got is None or len(got) != want:
            raise SystemExit(f"scenario {scenario}: {key} has {0 if got is None else len(got)} samples, want {want}")
        if any(not math.isfinite(v) or v < 0 for v in got):
            raise SystemExit(f"scenario {scenario}: {key} contains invalid samples")


def main() -> None:
    started = datetime.now(UTC)
    out = ROOT / "docs/evidence/personal-experience" / (
        "openshell-o04-perf-" + started.strftime("%Y%m%d-%H%M%S")
    )
    build = ["go", "test", "-trimpath", "-c", "./internal/receipt", "-o"]
    paths = sorted(p for p in MODULE.rglob("*") if p.is_file() and (
        p.suffix in {".go", ".json", ".yaml", ".yml"} or p.name in {"go.mod", "go.sum"}
    ))
    sources = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    out.mkdir(parents=True, exist_ok=False)
    (out / "protocol.md").write_text(build_protocol_md(), encoding="utf-8")
    (out / "source-hashes.json").write_text(json.dumps(sources, indent=2) + "\n")
    with tempfile.TemporaryDirectory(prefix="siq-o04-perf-") as td:
        binary = Path(td) / "o04perf.test"
        subprocess.run([*build, str(binary)], cwd=MODULE, check=True, timeout=120, capture_output=True)
        binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
        rounds: dict[str, list[dict]] = {s: [] for s in sorted(SAMPLES)}
        for index, order in enumerate(ROUND_ORDERS, start=1):
            for scenario in [*order, *TAIL_SCENARIOS]:
                result = run_scenario(binary, scenario)
                validate(scenario, result)
                result["round"] = index
                rounds[scenario].append(result)
                (out / "samples.json").write_text(json.dumps({"rounds_raw": rounds}, indent=2) + "\n")
        if any(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != sha
               for name, sha in sources.items()):
            raise SystemExit("source changed during measurement; partial evidence retained")
    pooled: dict[str, dict] = {}
    evaluation: dict[str, dict] = {}
    for scenario, entries in rounds.items():
        pooled[scenario] = {}
        evaluation[scenario] = {}
        for key in SAMPLES[scenario]:
            values = [v for entry in entries for v in entry["samples_ms"][key]]
            pooled[scenario][key] = summarize(values)
            budget = BUDGETS[scenario].get(key, {})
            checks = {}
            if "p95" in budget:
                checks["p95_within_budget"] = pooled[scenario][key]["p95_ms"] <= budget["p95"]
            if "max" in budget:
                checks["max_within_budget"] = pooled[scenario][key]["max_ms"] <= budget["max"]
            evaluation[scenario][key] = {"budget_ms": budget, **checks}
    report = {
        "format": "openshell-o04-perf-protocol/v1",
        "started_at": started.isoformat(), "finished_at": datetime.now(UTC).isoformat(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_state": "uncommitted_worktree", "source_hashes": sources,
        "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "test_binary_sha256": binary_sha,
        "environment": {"os": platform.system(), "arch": platform.machine(), "cpu_count": os.cpu_count()},
        "commands": [
            [*build, "<temporary-test-binary>"],
            ["<temporary-test-binary>", "-test.run=^TestO04PerfScenario$", "-test.v", "-test.count=1",
             "(env: SIQ_O04_PERF=1 SIQ_O04_SCENARIO=<A|B|C|D|E>, cwd=internal/receipt)"],
        ],
        "protocol": {
            "frozen_before_measurement": True,
            "rounds": ROUNDS, "round_orders": ROUND_ORDERS, "tail_scenarios": TAIL_SCENARIOS,
            "warmup": WARMUP, "samples_per_round": SAMPLES,
            "percentile_algorithm": PERCENTILE_ALGORITHM,
            "exclusion_rule": EXCLUSION_RULE,
            "concurrency": "single-threaded, no concurrent load during measurement",
        },
        "rounds_raw": rounds,
        "pooled_summary": pooled,
        "budgets": BUDGETS, "budget_basis": BUDGET_BASIS, "budget_evaluation": evaluation,
        "evidence_labels": EVIDENCE_LABEL,
        "scope": "O04-D component observations on the native decision core and OpenShell client paths; "
                 "no real gateway, no host end-to-end (B2/B3 blocked)",
        "thresholds": None,
        "not_measured": NOT_MEASURED,
        "notes": [
            "Not complete O00/O04 acceptance and not an SLA; observations only.",
            "场景测量未与全量测试并行（由执行者保证；脚本单独运行）。",
            "Scenario D measures bounded fail-return of a hung subprocess; its failure latency is the measured event, not an error to exclude.",
            "Scenario C cold sample is reported separately and never pooled with repeat probes.",
            "Scenario D uses ProbeTimeout(100ms) + min(200ms, ProbeTimeout) pipe drainage; "
            "the original p95<=300ms and max<=500ms budgets are unchanged.",
        ],
    }
    samples_bytes = (json.dumps({"rounds_raw": rounds}, ensure_ascii=False, indent=2) + "\n").encode()
    (out / "samples.json").write_bytes(samples_bytes)
    report.pop("rounds_raw")
    raw = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    (out / "report.json").write_bytes(raw)
    (out / "protocol.md").write_text(build_protocol_md(), encoding="utf-8")
    sums = "".join(
        f"{hashlib.sha256((out / name).read_bytes()).hexdigest()}  {name}\n"
        for name in ("report.json", "samples.json", "protocol.md", "source-hashes.json")
    )
    (out / "SHA256SUMS").write_text(sums)
    worst = [f"{s}:{k}" for s, keys in evaluation.items() for k, v in keys.items()
             if not all(v[x] for x in v if x.endswith("_within_budget"))]
    print(json.dumps({"path": str(out.relative_to(ROOT)), "budget_misses": worst}, ensure_ascii=False))


def build_protocol_md() -> str:
    lines = [
        "# O04-D 冻结测量协议（B1：改造后 native 组件）",
        "",
        "本协议在测量前冻结；不得因结果调整。冻结项：",
        "",
        f"- 轮数：{ROUNDS}；A/B 交错顺序：{ROUND_ORDERS}；C/D/E 每轮各测一次",
        f"- 预热（丢弃）：{json.dumps(WARMUP, ensure_ascii=False)}",
        f"- 每轮样本量：{json.dumps(SAMPLES, ensure_ascii=False)}（D 故障注入路径冻结为 60，非热路径）",
        f"- 百分位算法：{PERCENTILE_ALGORITHM}",
        f"- 剔除规则：{EXCLUSION_RULE}",
        f"- 冻结预算（ms）：{json.dumps(BUDGETS, ensure_ascii=False)}",
        f"- 预算依据：{BUDGET_BASIS}",
        "- B1−B0 相对预算：P95 增幅 ≤10%（B0 对照本轮不可测，见 report.json not_measured）",
        "- B2/B3：blocked，缺真实后端",
        "",
        "## 证据分级",
        "",
        *[f"- 场景 {s}：{label}" for s, label in EVIDENCE_LABEL.items()],
        "",
        "全部为组件级证据：无真实网关、无主机端到端。测量期间不运行全量测试或构建负载。",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
