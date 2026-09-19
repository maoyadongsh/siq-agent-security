#!/usr/bin/env python3
"""OpenShell task-execution performance driver (independent scope).

Scope `task_execution`: this driver is the only one in this batch that measures
a REAL command executed through the production executor
`POST /v1/openshell/task-executions`. The pre-existing
`openshell-b2b3-perf-protocol.py` measures doctor read-back and an auxiliary
control-plane restore and has never submitted a task execution -- its
`"B3": "not_measured"` is accurate and is not renamed or extended here. The two
drivers' results must never be merged into one statistic.

The protocol is frozen on disk before any sample is taken:
`<out>/protocol.md`, schema `openshell-taskexec-perf-protocol/v1`. This driver
re-hashes that file and refuses to run if it no longer matches
PROTOCOL_SHA256, so a post-measurement budget edit cannot be laundered through
a fresh run.

Prior measurements must not be overwritten: `--out` must be an empty (or
non-existent) directory, and this driver refuses to write into one that already
holds a `report.json`.

Only resources created by this batch are touched: one owned sandbox, one
daemon started here, one isolated HOME/state root. The shared gateway is used
as-is and is never restarted or reconfigured.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import re
import resource
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE_DRIVER = HERE / "openshell-o05v6-taskexec-journey.py"
B2B3_DRIVER = HERE / "openshell-b2b3-perf-protocol.py"
DEPENDENCY_SHA256 = {
    "base_driver": "4073dec7f1e811a1a65fd7eda6bf2c5a468e19ffdb7db7f30547971193247af9",
    "b2b3_helper": "761ae1868f781d68f0018effd5d19a2087367cd09cec40adf4cf1c46cc515dd6",
}
DEPENDENCY_PATHS = {
    "base_driver": BASE_DRIVER,
    "b2b3_helper": B2B3_DRIVER,
}

PERF_SCHEMA = "openshell-taskexec-perf/v1"
PROTOCOL_SCHEMA = "openshell-taskexec-perf-protocol/v1"
PROTOCOL_NAME = "protocol.md"

# Frozen before any measurement (protocol §4 R1). Changing a budget in
# protocol.md after this point makes this constant stop matching and the run
# refuses to start -- which is the point.
PROTOCOL_SHA256 = "32246f7b3a3d8e137aade9a1fbe45c408fb9f42aaedd1db33136c4b40b537288"

ROUNDS = 3
WARMUP = 2
SAMPLES = 15
CYCLE_SAMPLES = 5

# Protocol §1.6. (p95 budget ms, max ceiling ms). Frozen before measurement.
BUDGETS = {
    "S1": (15000.0, 30000.0),
    "S2": (60000.0, 60000.0),
    "S3": (2000.0, 15000.0),
    "S4": (1500.0, 15000.0),
}
SCENARIO_TITLES = {
    "S1": "doctor_readback",
    "S2": "policy_load_roundtrip",
    "S3": "taskexec_read_only",
    "S4": "taskexec_status_read",
}
# Protocol §1.3 R1. `cond` is the untimed readiness conditioning step; it is
# not a scenario and carries no budget.
ROUND_ORDER = {
    1: ["S2", "cond", "S1", "S3", "S4"],
    2: ["S2", "cond", "S3", "S1", "S4"],
    3: ["S2", "cond", "S1", "S3", "S4"],
}
EVIDENCE_LEVEL = {
    "S1": "integration_real_gateway_control_plane",
    "S2": "integration_real_gateway_policy_write",
    "S3": "integration_real_gateway_real_sandbox_real_execution",
    "S4": "integration_real_daemon_state_projection",
}
# Protocol §1.1: every scenario's relative-to-old-candidate value.
RELATIVE = {
    "S1": ("not_measured", "本轮未按相同协议独占重测 main 基点的 doctor 读回"),
    "S2": ("not_measured", "本轮未按相同协议独占重测 main 基点的策略加载"),
    "S3": ("not_comparable", "集成基点 9b8c09af 无任务执行路由；不能把 policy_apply 冒充任务执行"),
    "S4": ("not_comparable", "集成基点 9b8c09af 无任务执行状态读回路由"),
}

_FRAC = re.compile(r"\.(\d+)")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bind_driver_dependencies(paths=None, expected=None):
    """Fail before any live access when an imported measurement helper drifts."""
    paths = DEPENDENCY_PATHS if paths is None else paths
    expected = DEPENDENCY_SHA256 if expected is None else expected
    if set(paths) != set(expected):
        raise SystemExit("measurement dependency names do not match the frozen set")
    bound = {}
    for name in sorted(paths):
        path = Path(paths[name])
        if not path.is_file():
            raise SystemExit(f"measurement dependency is missing: {name}")
        actual = sha256_file(path)
        wanted = expected[name]
        if actual != wanted:
            raise SystemExit(
                f"measurement dependency drifted: {name} {actual} != frozen {wanted}"
            )
        bound[name] = {
            "file": path.name,
            "sha256": actual,
        }
    return bound


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


DRIVER_DEPENDENCIES = bind_driver_dependencies()
BASE = load_module("o05v6_taskexec_journey", BASE_DRIVER)
B2B3 = load_module("b2b3_perf_protocol", B2B3_DRIVER)
check = BASE.check
StepFailure = BASE.StepFailure
CliStall = BASE.CliStall


def percentile(values, p):
    """nearest-rank on sorted samples: ceil(p/100 * n). Protocol §1.5, frozen."""
    if not values:
        return None
    ordered = sorted(values)
    rank = math.ceil(p / 100 * len(ordered))
    return ordered[min(max(rank, 1), len(ordered)) - 1]


def stats(values):
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
        "max": max(values),
        "mean": round(sum(values) / len(values), 3),
    }


def parse_ts(text):
    """Parse the product's RFC3339Nano timestamps.

    Python's fromisoformat takes at most 6 fractional digits, so nanoseconds
    are truncated to microseconds. The truncation is bounded by 1 microsecond,
    i.e. three orders of magnitude below the millisecond granularity every
    budget and percentile in this protocol is expressed in.
    """
    if not text:
        return None
    match = _FRAC.search(text)
    if match and len(match.group(1)) > 6:
        text = _FRAC.sub("." + match.group(1)[:6], text, count=1)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


# Protocol §1.4. A *competing build, regression run or benchmark* voids the
# round. A long-running dev server that is already up when the run starts is a
# different thing: it is part of the host as measured, it is not something this
# batch started, and killing it is forbidden. The two are therefore classified
# apart and only the first is fatal -- recorded honestly, not silently dropped.
_FATAL_TOKENS = (
    "go build", "go test", "go vet", "pytest", "npm test", "npm run build",
    "build:local", "vite build", "tsc ", "webpack", " -race",
    "perf-protocol", "openshell-o05v6-taskexec-perf",
)
_AMSERVICE_TOKENS = ("vite", "npm", "node", "uvicorn", "webpack", "esbuild")


def host_load():
    """Host load snapshot. The host is shared with unrelated tenants, so this is
    recorded as an environment condition rather than treated as something this
    batch could clear; it is never used to discard a round."""
    snap = {"nproc": os.cpu_count(), "loadavg": None, "top_cpu": []}
    try:
        snap["loadavg"] = [float(x) for x in
                           Path("/proc/loadavg").read_text().split()[:3]]
    except OSError:
        pass
    try:
        out = subprocess.run(["ps", "-eo", "pid,pcpu,etimes,comm", "--sort=-pcpu"],
                             capture_output=True, text=True, timeout=20).stdout
        lines = [ln.rstrip() for ln in out.splitlines()[1:9] if ln.strip()]
        for ln in lines:
            parts = ln.split(None, 3)
            if len(parts) == 4:
                snap["top_cpu"].append({"pid": int(parts[0]), "pcpu": float(parts[1]),
                                        "etimes": int(parts[2]), "comm": parts[3]})
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return snap


def host_load_delta(pre, post):
    """Compare two host_load() snapshots without asserting anything about them."""
    if not pre or not post:
        return None
    delta = {}
    if pre.get("loadavg") and post.get("loadavg"):
        delta["loadavg_1min"] = round(post["loadavg"][0] - pre["loadavg"][0], 2)
    pre_pids = {p["pid"] for p in pre.get("top_cpu", [])}
    post_pids = {p["pid"] for p in post.get("top_cpu", [])}
    delta["new_top_consumers"] = sorted(post_pids - pre_pids)
    delta["note"] = "informational; the empty case means the pre-check snapshot's top " \
                    "consumers were unchanged"
    return delta


def exclusivity_scan(root: Path, exclude_pids):
    """Read-only /proc scan; nothing is signalled.

    Returns {"fatal": [...], "observed": [...]}. `fatal` is a competing
    build/test/benchmark that must stop the run; `observed` is other load seen
    at the same instant and reported as an environment condition.
    """
    fatal, observed = [], []
    proc = Path("/proc")
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in exclude_pids:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        cmd = raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()
        if not cmd:
            continue
        low = cmd.lower()
        try:
            cwd = str((entry / "cwd").resolve())
        except OSError:
            cwd = ""
        in_worktree = cwd.startswith(str(root))
        if in_worktree or any(t in low for t in _FATAL_TOKENS):
            fatal.append({"pid": pid, "cmd": cmd[:300], "cwd": cwd,
                          "reason": "this worktree" if in_worktree
                                    else "competing build/test/benchmark"})
        elif any(t in low for t in _AMSERVICE_TOKENS):
            observed.append({"pid": pid, "cmd": cmd[:300], "cwd": cwd})
    return {"fatal": fatal, "observed": observed}


class PerfJourney(BASE.Journey):
    """The D02/D05 journey's preflight, driven by this batch's frozen protocol."""

    def __init__(self, args):
        super().__init__(args)
        # The base driver's raw dir is named for the D02 journey; this run's
        # private traffic belongs to the perf batch and gets its own 0700 tree.
        self.raw_dir = self.out / "d06-private" / "d06-raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.raw_dir.parent, 0o700)
        os.chmod(self.raw_dir, 0o700)
        self.protocol_path = self.out / PROTOCOL_NAME
        self.protocol_sha256 = args.expected_protocol_sha256 or PROTOCOL_SHA256
        self.source_binding = B2B3.source_binding()
        self.samples = []
        # Set before any measurement so a failure outside the loop still has a
        # scenario/round to attribute itself to instead of masking the real
        # error with an AttributeError.
        self.current_round = 0
        self.current_scenario = "?"
        self.current_leg = "?"
        self.abort_reason = None
        self.aborted_round = None
        self.conditioning = []
        self.resources = []
        self.interference = []
        self.pristine_body = None
        self.last_task = None
        self.s3_revision = self.s3_digest = None
        self.relative = dict(RELATIVE)
        if args.baseline_has_taskexec:
            # The original F05 baseline predates the task routes. A newer main
            # may contain them, but this driver still measures only one binary.
            # Never carry the old "not_comparable" claim into that new run.
            reason = ("baseline " + args.baseline_commit +
                      " has the task route; an equivalent baseline run was not measured")
            for scenario in ("S3", "S4"):
                self.relative[scenario] = ("not_measured", reason)
        self.evidence_level = EVIDENCE_LEVEL

    # ---------- protocol binding ----------
    def bind_protocol(self):
        check(self.protocol_path.is_file(),
              f"the frozen protocol is missing: {self.protocol_path}")
        actual = sha256_file(self.protocol_path)
        check(actual == self.protocol_sha256,
              f"protocol.md drifted: {actual} != frozen {self.protocol_sha256}; "
              f"a post-freeze edit must be a new protocol version, not a rerun")
        head = self.protocol_path.read_text().splitlines()[:12]
        check(any(PROTOCOL_SCHEMA in line for line in head),
              f"protocol.md does not declare schema {PROTOCOL_SCHEMA}")
        self.record({
            "id": "P00", "title": "protocol hash bound (budgets frozen before measurement)",
            "kind": "derived", "status": "pass",
            "protocol_file": PROTOCOL_NAME, "protocol_sha256": actual,
            "driver_dependencies": DRIVER_DEPENDENCIES,
            "rounds": ROUNDS, "warmup": WARMUP, "samples": SAMPLES,
            "cycle_samples": CYCLE_SAMPLES,
            "budgets_ms": {k: {"p95": v[0], "max": v[1]} for k, v in BUDGETS.items()},
        })

    def exclusivity(self):
        exclude = {os.getpid(), os.getppid()}
        if self.proc is not None:
            exclude.add(self.proc.pid)
        if self.lost_proc is not None:
            exclude.add(self.lost_proc.pid)
        scan = exclusivity_scan(BASE.REPO, exclude)
        load = host_load()
        self.interference = {"scan": scan, "host_load_pre": load}
        self.record({
            "id": "P01", "title": "exclusivity pre-check (no competing build/regression/benchmark)",
            "kind": "derived", "status": "pass" if not scan["fatal"] else "fail",
            "scanned_root": str(BASE.REPO),
            "fatal": scan["fatal"],
            "observed_background_services": scan["observed"],
            "host_load_pre": load,
            "note": "read-only /proc scan; nothing signalled. Protocol §1.4 forbids "
                    "competing builds/regressions/benchmarks and requires stopping the "
                    "round rather than selecting data. Pre-existing services on a shared "
                    "host are recorded as environment conditions, not treated as "
                    "exclusivity failures -- killing them is forbidden, and a condition "
                    "that can never be cleared would make any measurement impossible.",
        })
        if scan["fatal"]:
            raise StepFailure(
                "competing build/test/benchmark present before measurement; "
                "stopping per protocol §1.4")

    # ---------- conditioning (untimed, protocol §1.3 R1) ----------
    def await_exec_ready(self, deadline=420, interval=5):
        """Poll `sandbox exec` until it stops stalling.

        A `policy set/update --wait` is followed by a 1-3 minute stall in
        `sandbox exec` (reproduced three times during D05 recon). The stall is
        not a denial and must not be read as one, so this waits it out rather
        than concluding anything from a slow first attempt. Copied from the D05
        acceptance driver so the two batches condition identically.
        """
        argv = [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                "sandbox", "exec", "-n", self.target, "--no-tty", "--",
                "/bin/echo", "ready"]
        started = time.time()
        attempts = 0
        while time.time() - started < deadline:
            attempts += 1
            try:
                proc = subprocess.run(argv, cwd=self.workspace, env=self.env,
                                      capture_output=True, text=True, timeout=45,
                                      check=False)
            except subprocess.TimeoutExpired:
                continue
            if proc.returncode == 0 and "ready" in proc.stdout:
                return {"ready": True, "attempts": attempts,
                        "elapsed_s": round(time.time() - started, 1)}
            time.sleep(interval)
        return {"ready": False, "attempts": attempts,
                "elapsed_s": round(time.time() - started, 1)}

    def conditioning_step(self, rnd):
        started = time.time()
        ready = self.await_exec_ready()
        # The reload must not have changed the document: content-identical is
        # what makes S2 a load-confirmation cost and not a policy change.
        after = self.policy_read(f"C{rnd}b", note="content-identical reload must not "
                                                  "change the policy document")
        check(after["hash"] == self.base_hash,
              f"the pristine reload changed the policy document: {after['hash']} "
              f"!= {self.base_hash}; S2 is not content-neutral and the round is void")
        preview = self.http(f"C{rnd}c", "refresh executor-space binding after the reload "
                                        "(untimed conditioning)",
                            "POST", "/v1/openshell/task-executions/preview",
                            {"target": self.target})
        live = preview.get("live") or {}
        check(preview.get("scope") == "task_execution" and bool(live.get("revision"))
              and bool(live.get("policy_digest")),
              f"conditioning preview did not expose the live executor binding: {list(preview)}")
        self.s3_revision, self.s3_digest = live["revision"], live["policy_digest"]
        entry = {
            "round": rnd, "ready": ready["ready"], "attempts": ready["attempts"],
            "elapsed_s": ready["elapsed_s"],
            "total_s": round(time.time() - started, 1),
            "sandbox_revision_after_reload": after["revision"],
            "executor_revision": self.s3_revision,
            "executor_policy_digest": self.s3_digest,
        }
        self.conditioning.append(entry)
        self.record({
            "id": f"C{rnd}a", "title": "conditioning: wait out the post-reload exec stall "
                                       "(untimed, no budget)",
            "kind": "derived", "status": "pass" if ready["ready"] else "fail",
            "conditioning": entry,
            "note": "not a scenario sample: excluded from every percentile and budget; "
                    "recorded so the environment condition stays visible in the evidence",
        })
        if not ready["ready"]:
            raise StepFailure(
                f"round {rnd}: sandbox exec did not become ready within 420s; "
                f"protocol §1.3 treats this as a run-stopping environment failure")

    # ---------- sampling helpers ----------
    def rss_now(self):
        if self.proc is None:
            return None, None
        try:
            status = Path(f"/proc/{self.proc.pid}/status").read_text()
        except OSError:
            return None, None
        vals = {}
        for line in status.splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                parts = line.split()
                vals[parts[0].rstrip(":")] = int(parts[1])
        return vals.get("VmRSS"), vals.get("VmHWM")

    def client_cpu_ms(self):
        me = resource.getrusage(resource.RUSAGE_SELF)
        ch = resource.getrusage(resource.RUSAGE_CHILDREN)
        return {
            "self_ms": round((me.ru_utime + me.ru_stime) * 1000, 1),
            "children_ms": round((ch.ru_utime + ch.ru_stime) * 1000, 1),
        }

    def last_entry(self, step_id):
        for entry in reversed(self.steps):
            if entry.get("id") == step_id:
                return entry
        return None

    def timed(self, step_id, fn):
        """Run one measured sample.

        On any failure the sample is recorded **invalid** in full, the round is
        voided and the whole run stops (protocol §1.5). Nothing is retried.
        """
        started = time.perf_counter()
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 -- any failure is a result, not a crash
            entry = self.last_entry(step_id) or {}
            sample = {
                "round": self.current_round, "scenario": self.current_scenario,
                "step": step_id, "valid": False,
                "error": str(exc), "error_type": type(exc).__name__,
                "http_status": entry.get("http_status"),
                "wall_ms": entry.get("duration_ms"),
                "wall_ms_independent": round(
                    (time.perf_counter() - started) * 1000, 3),
                "detail": traceback.format_exc()[-800:],
            }
            self.samples.append(sample)
            self.abort_reason = (f"{self.current_scenario} sample {step_id} failed: {exc}")
            self.aborted_round = self.current_round
            self.record({
                "id": f"ABORT-{step_id}", "title": "measured sample invalid: run stops, "
                                                   "round voided, no retry",
                "kind": "derived", "status": "fail",
                "scenario": self.current_scenario, "round": self.current_round,
                "detail": str(exc),
            })
            return None
        entry = self.last_entry(step_id) or {}
        wall = entry.get("duration_ms")
        sample = {
            "round": self.current_round, "scenario": self.current_scenario,
            "step": step_id, "valid": True, "wall_ms": wall,
            # Independent cross-check: measured by this driver's own
            # perf_counter around the call, not read back from the product's
            # duration_ms. The two differ only by whatever local work the
            # callable does after the product responds (for S3, the executor
            # assertion and the digest proof); a divergence much larger than
            # that would mean the product's own timing does not cover the work
            # being claimed.
            "wall_ms_independent": round((time.perf_counter() - started) * 1000, 3),
            "http_status": entry.get("http_status"),
        }
        return wall, value, sample

    # ---------- scenarios ----------
    def s1_sample(self, rnd, idx):
        sid = f"S1r{rnd}.{idx}"
        return self.timed(sid, lambda: self.http(
            sid, "S1 doctor read-back (real CLI + real gateway via the daemon)",
            "GET", "/v1/openshell/doctor"))

    def s2_sample(self, rnd, idx):
        sid = f"S2r{rnd}.{idx}"
        argv = [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                "policy", "set", "--policy", str(self.pristine_body), self.target, "--wait"]
        return self.timed(sid, lambda: self.cli(
            sid, "S2 content-identical policy reload with --wait load confirmation",
            argv, timeout=180,
            note="the document is byte-identical to the loaded one; this measures the "
                 "submit + --wait load-confirmation round trip, not a policy change"))

    def s3_sample(self, rnd, idx, warm):
        """One real, human-approved, bounded command through the production executor.

        Timed region = the submit HTTP round trip only. Every approval step
        before it runs outside the timed region.
        """
        token = f"o05v6perf-{self.run_id}-{rnd}-{idx}"
        # printf %s emits the token with no trailing newline and no network use.
        argv = ["/bin/sh", "-c", f"printf %s {token}"]
        tag = f"S3{'w' if warm else 'r'}{rnd}.{idx}"
        params = self.canonical_task_params(
            self.target, argv, "", 60, 65536, self.s3_revision, self.s3_digest, [])
        decision = self.decide(f"{tag}a", f"o05v6-perf-{self.run_id}-{rnd}-{idx}", params)
        self.hold_resolve(f"{tag}b", decision, approve=True,
                          note="human approves this exact bounded read-only command")
        body = self.task_body(f"o05v6-perf-{self.run_id}-{rnd}-{idx}", params, self.target,
                              argv, "", 60, 65536, self.s3_revision, self.s3_digest,
                              [], decision)
        # Anti-replay / anti-cache proof: the stdout digest must derive from
        # *this* sample's unique token, so a cached or replayed response cannot
        # match. A trailing newline is tolerated because the transport may add
        # one; both accepted variants remain unique to this sample.
        variants = {
            "exact": hashlib.sha256(token.encode()).hexdigest(),
            "trailing_newline": hashlib.sha256((token + "\n").encode()).hexdigest(),
        }

        def run():
            # The executor assertion and the digest proof run INSIDE the timed
            # region so that a sample which fails either of them is recorded as
            # an invalid sample under the uniform §1.5 rule, rather than
            # escaping as an uncaught exception.
            resp = self.submit_task(
                tag, "S3 production executor runs one real approved command",
                body, expect=200,
                note="must be 200 with outcome.task_executed=yes; 502 would mean an "
                     "unknown outcome and would never be read as success or as a block")
            outcome = self.assert_task_executed(tag, resp)
            digest = outcome.get("stdout_digest")
            matched = next((k for k, v in variants.items() if v == digest), None)
            check(matched is not None,
                  f"{tag}: stdout digest {digest!r} does not correspond to this "
                  f"sample's own token; the response cannot be a real execution of "
                  f"this command")
            return resp, outcome, matched

        result = self.timed(tag, run)
        if result is None:
            return None
        wall, (resp, outcome, matched), sample = result
        sample["stdout_matched"] = matched
        sample["exit_code"] = outcome.get("exit_code")
        sample["stdout_bytes"] = outcome.get("stdout_bytes")
        started, finished = parse_ts(outcome.get("started_at")), parse_ts(outcome.get("finished_at"))
        if started and finished and wall is not None:
            remote = round((finished - started).total_seconds() * 1000, 3)
            sample["remote_exec_ms"] = remote
            sample["pre_remote_ms"] = round(wall - remote, 3)
            sample["phase_note"] = (
                "remote_exec_ms is the product's own measure: outcome.started_at is "
                "stamped immediately before the runner is invoked and finished_at "
                "immediately after it returns, so it includes the local CLI transport. "
                "pre_remote_ms is DERIVED (wall - remote) and covers request handling, "
                "binding validation, the reservation write and the pre-spawn recheck; "
                "result recording is not separable from it and is reported as null.")
        else:
            sample["remote_exec_ms"] = None
            sample["remote_exec_ms_reason"] = (
                "the product did not return parsable outcome timestamps for this sample")
            sample["pre_remote_ms"] = None
            sample["pre_remote_ms_reason"] = "derived from remote_exec_ms, which is unavailable"
        self.last_task = {
            "reservation_receipt_id": resp["reservation"]["reservation_receipt_id"],
            "decision_receipt_id": decision["receipt_id"],
            "action_id": decision["action_id"],
            "task_id": decision.get("task_id"),
        }
        return wall, resp, sample

    def s4_sample(self, rnd, idx):
        sid = f"S4r{rnd}.{idx}"
        check(self.last_task is not None,
              "S4 needs a previously persisted execution record; none exists")
        payload = {
            "schema_version": "openshell-task-execution-status-request/v1",
            "platform": "openclaw",
            "session_id": self.session,
            "agent_id": self.target,
            "tool": BASE.TASK_TOOL,
            "action_id": self.last_task["action_id"],
            "decision_receipt_id": self.last_task["decision_receipt_id"],
            "reservation_receipt_id": self.last_task["reservation_receipt_id"],
        }
        if self.last_task.get("task_id"):
            payload["task_id"] = self.last_task["task_id"]
        expected = self.last_task["reservation_receipt_id"]

        def run():
            # /read is capAdmin: the admin session, not the daemon token.
            resp = self.http(sid, "S4 read the persisted execution record projection",
                             "POST", "/v1/openshell/task-executions/read", payload)
            check(resp.get("reservation_receipt_id") == expected,
                  f"{sid}: projection names a different reservation: "
                  f"{resp.get('reservation_receipt_id')!r}")
            return resp

        result = self.timed(sid, run)
        if result is None:
            return None
        wall, resp, sample = result
        sample["projection_state"] = resp.get("state")
        return wall, resp, sample

    # ---------- the measurement loop ----------
    def sample_once(self, stage, rnd, idx, warm):
        """Dispatch one sample and, when measured, append it to self.samples."""
        if stage == "S1":
            result = self.s1_sample(rnd, idx)
        elif stage == "S2":
            result = self.s2_sample(rnd, idx)
        elif stage == "S3":
            result = self.s3_sample(rnd, idx, warm)
        elif stage == "S4":
            result = self.s4_sample(rnd, idx)
        else:
            raise StepFailure(f"unknown scenario {stage}")
        if result is None or warm:
            return
        wall, _resp, sample = result
        sample["wall_ms"] = wall
        self.samples.append(sample)

    def measure(self):
        self.samples = []
        for rnd in range(1, ROUNDS + 1):
            self.current_leg = f"perf-round-{rnd}"
            for stage in ROUND_ORDER[rnd]:
                self.current_scenario = "cond" if stage == "cond" else stage
                self.current_round = rnd
                if self.abort_reason:
                    break
                if stage == "cond":
                    self.conditioning_step(rnd)
                    continue
                self.current_scenario = stage
                count = CYCLE_SAMPLES if stage == "S2" else SAMPLES
                before_steps, before_cpu = len(self.steps), self.client_cpu_ms()
                cpu0 = before_cpu
                for i in range(WARMUP):
                    if self.abort_reason:
                        break
                    self.sample_once(stage, rnd, f"w{i}", warm=True)
                for i in range(count):
                    if self.abort_reason:
                        break
                    # Warmups are numbered "w<i>" and never reach self.samples;
                    # measured samples are numbered from 0. Both carry the
                    # round, so every per-sample token stays unique, which is
                    # what the S3 digest proof relies on.
                    self.sample_once(stage, rnd, str(i), warm=False)
                rss, hwm = self.rss_now()
                cpu1 = self.client_cpu_ms()
                self.resources.append({
                    "round": rnd, "scenario": stage,
                    "daemon_rss_kb": rss, "daemon_hwm_kb": hwm,
                    "client_cpu": cpu1,
                    "cpu_delta_ms": {k: round(cpu1[k] - cpu0[k], 1)
                                     for k in ("self_ms", "children_ms")},
                    "steps_recorded": len(self.steps) - before_steps,
                    "valid_samples": sum(1 for s in self.samples
                                         if s["round"] == rnd and s["scenario"] == stage
                                         and s["valid"]),
                    "invalid_samples": sum(1 for s in self.samples
                                           if s["round"] == rnd and s["scenario"] == stage
                                           and not s["valid"]),
                })
            if self.abort_reason:
                break

    def run(self):
        self.bind_protocol()
        self.leg_k00()
        self.leg_k01()
        try:
            self.leg_k02()
            self.leg_k03()
            self.exclusivity()
            self.leg_k10()
            self.leg_k20()
            self.leg_k30()
            self.perf_prepare()
            self.measure()
            self.after = self.policy_read("P90a")
            # Same snapshot, taken after the last sample, so a load change
            # during the run is visible in the report instead of being assumed
            # away.
            if isinstance(self.interference, dict):
                self.interference["host_load_post"] = host_load()
                self.interference["host_load_delta"] = host_load_delta(
                    self.interference.get("host_load_pre"),
                    self.interference.get("host_load_post"))
        finally:
            self.leg_k90()
        return self.perf_report()

    def perf_prepare(self):
        # Pristine inner policy document, taken from the CLI's own --base output.
        # `policy get --base -o json` emits an envelope; the CLI's `policy set
        # --policy` wants the inner document, so the envelope key is unwrapped
        # here rather than handed to the CLI (which rejects it with
        # "unknown field 'active_version'").
        base_json = self.cli(
            "P02a", "read the pristine policy document (--base)",
            [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
             "policy", "get", self.target, "--base", "-o", "json"], timeout=180)
        doc = json.loads(base_json.stdout)
        inner = doc.get("policy")
        check(isinstance(inner, dict) and inner,
              f"policy get --base did not expose the inner policy document: {list(doc)}")
        raw = self.raw_dir / "o05v6-perf-pristine-policy.json"
        raw.write_text(json.dumps(inner, indent=2, sort_keys=True))
        os.chmod(raw, 0o600)
        self.pristine_body = raw
        live = self.policy_read("P02b")
        self.base_revision, self.base_hash = live["revision"], live["hash"]
        self.record({
            "id": "P02c", "title": "pristine reload body and baseline revision bound",
            "kind": "derived", "status": "pass",
            "pristine_body": str(raw.relative_to(self.out)),
            "pristine_body_sha256": sha256_file(raw),
            "sandbox_revision": self.base_revision,
            "sandbox_policy_sha256": self.base_hash,
            "note": "S2 reloads exactly this document, unchanged, so the write has no "
                    "content effect; only the load-confirmation cost is measured",
        })

    def leg_k90(self):
        # Same teardown as the base journey, with one deliberate difference: the
        # base asserts the sandbox *revision* is unchanged, and S2 invalidates
        # that assertion by construction. S2 measures policy-load cost by
        # reloading the pristine document byte-for-byte (protocol §1.2), and a
        # `policy set` advances the revision even when the content is identical.
        # The invariant that actually matters is that this journey never changed
        # the policy *content*, so that is what is asserted. The revision delta
        # is recorded rather than swallowed, so a silent content change still
        # shows up as a hash mismatch instead of hiding behind a revision bump.
        self.serve_stop("K90a", self.proc, self.serve_log)
        self.serve_stop("K90b", self.lost_proc, self.lost_log)
        after = self.policy_read("K90c")
        check(after["hash"] == self.base_hash,
              f"the perf journey changed the sandbox policy content: "
              f"{self.base_hash} -> {after['hash']}")
        self.record({
            "id": "K90d",
            "title": "sandbox policy content untouched by the whole perf journey",
            "kind": "derived", "status": "pass",
            "sandbox_revision_before": self.base_revision,
            "sandbox_revision_after": after["revision"],
            "sandbox_policy_sha256_before": self.base_hash,
            "sandbox_policy_sha256_after": after["hash"],
            "revision_delta_reason": "S2's measured operation is a byte-for-byte reload "
                                     "of the pristine document; a policy set advances "
                                     "the revision even when the content is unchanged",
        })

    # ---------- report ----------
    def summarize_scenario(self, key):
        vals = [s["wall_ms"] for s in self.samples
                if s["scenario"] == key and s["valid"] and s["wall_ms"] is not None]
        invalid = [s for s in self.samples if s["scenario"] == key and not s["valid"]]
        p95_budget, max_ceiling = BUDGETS[key]
        doc = {
            "scenario": SCENARIO_TITLES[key],
            "scope": "task_execution" if key in ("S3", "S4") else "control_plane",
            "evidence_level": EVIDENCE_LEVEL[key],
            "relative_to_old_candidate": self.relative[key][0],
            "relative_reason": self.relative[key][1],
            "wall_ms": stats(vals),
            "invalid_samples": len(invalid),
            "budget_p95_ms": p95_budget,
            "max_ceiling_ms": max_ceiling,
            "per_round": {
                str(r): stats([s["wall_ms"] for s in self.samples
                               if s["scenario"] == key and s["valid"] and s["round"] == r
                               and s["wall_ms"] is not None])
                for r in range(1, ROUNDS + 1)
            },
            "phases": {
                "user_visible_total_ms": "measured (wall_ms above)",
                "policy_load_ms": "measured only for S2 (wall_ms above)",
                "remote_exec_ms": "product-measured (outcome.started_at/finished_at); see samples.json",
                "client_api_and_recording_ms": "DERIVED (wall - remote); recording is not "
                                               "separable from it and is reported as null",
                "per_phase_write_counts": None,
                "per_phase_write_counts_reason": "the product exposes no per-phase "
                                                 "write/fsync/signature counters; adding them "
                                                 "would change the candidate under measurement",
            },
        }
        if key == "S3":
            remote = [s["remote_exec_ms"] for s in self.samples
                      if s["scenario"] == "S3" and s["valid"]
                      and s.get("remote_exec_ms") is not None]
            pre = [s["pre_remote_ms"] for s in self.samples
                   if s["scenario"] == "S3" and s["valid"]
                   and s.get("pre_remote_ms") is not None]
            doc["phases"]["remote_exec_ms_stats"] = stats(remote)
            doc["phases"]["client_api_and_recording_ms_stats"] = dict(
                stats(pre), derived=True)
            doc["anti_replay"] = {
                "method": "each sample's stdout digest must derive from that sample's own "
                          "unique token",
                "matched": {v: sum(1 for s in self.samples if s.get("stdout_matched") == v)
                            for v in ("exact", "trailing_newline")},
            }
        if vals:
            doc["verdict"] = "within_budget" if (
                percentile(vals, 95) <= p95_budget and max(vals) <= max_ceiling
            ) else "budget_missed"
        else:
            doc["verdict"] = "no_valid_samples"
        return doc

    def scatter(self, key, field):
        out = []
        for s in self.samples:
            if s["scenario"] == key and s["valid"]:
                out.append({"round": s["round"], "step": s["step"],
                            "value": s.get(field)})
        return out

    def public(self, value):
        if isinstance(value, str):
            for secret, label in self.secrets.items():
                if secret and secret in value:
                    value = value.replace(secret, f"<{label}>")
            # The lost-backend root is a private absolute path, not a secret;
            # the base driver's report() collapses it the same way.
            if self.lost_root:
                value = value.replace(str(self.lost_root), "<lost-backend-root>")
            # Longest path first: this repo, then the home directory. Other
            # projects' paths appear only in the exclusivity scan's *observed*
            # list, which is host context, not this batch's data.
            value = value.replace(str(BASE.REPO), "<repo>")
            return value.replace(str(Path.home()), "<home>")
        if isinstance(value, dict):
            return {k: self.public(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.public(v) for v in value]
        return value

    def perf_report(self):
        source_at_report = B2B3.source_binding()
        source_stable = source_at_report["sha256"] == self.source_binding["sha256"]
        if not source_stable:
            self.record({"id": "P99", "title": "source files changed during measurement",
                         "kind": "derived", "status": "fail",
                         "before_sha256": self.source_binding["sha256"],
                         "after_sha256": source_at_report["sha256"]})
        scenarios = {k: self.summarize_scenario(k) for k in ("S1", "S2", "S3", "S4")}
        misses = [k for k, v in scenarios.items() if v["verdict"] == "budget_missed"]
        doc = {
            "schema": PERF_SCHEMA,
            "scope": "task_execution",
            "scope_note": "independent of openshell-b2b3-perf-protocol.py; the two drivers' "
                          "results must never be merged",
            "protocol": {"file": PROTOCOL_NAME, "schema": PROTOCOL_SCHEMA,
                         "sha256": self.protocol_sha256,
                         "amendment": "R1 (pre-measurement): conditioning step between S2 "
                                      "and S3; R2 (pre-measurement): teardown invariant is "
                                      "policy content, not revision; no frozen parameter "
                                      "changed by either"},
            "driver_dependencies": DRIVER_DEPENDENCIES,
            "candidate": {
                "binary": str(self.binary),
                "binary_sha256": self.binary_sha,
                "source_binding_procedure": "B / source_binding-family; measured at run start, not independently captured at build time",
                "source_binding_sha256": self.source_binding["sha256"],
                "source_file_count": len(self.source_binding["files"]),
                "source_stable_during_run": source_stable,
            },
            "meta": self.meta,
            "frozen": {
                "rounds": ROUNDS, "warmup": WARMUP, "samples": SAMPLES,
                "cycle_samples": CYCLE_SAMPLES, "order": ROUND_ORDER,
                "budgets_ms": {k: {"p95": v[0], "max": v[1]} for k, v in BUDGETS.items()},
                "percentile": "nearest-rank ceil(p/100*n) on sorted samples",
                "exclusion_rule": "none",
                "failure_rule": "any invalid measured sample voids its round and stops the "
                                "run; no retry, no cherry-picking",
            },
            "rounds_completed": self.rounds_completed(),
            "aborted": bool(self.abort_reason),
            "abort_reason": self.abort_reason,
            "aborted_round": self.aborted_round,
            "scenarios": scenarios,
            "budget_misses": misses,
            "conditioning": self.conditioning,
            "conditioning_role": "untimed environment conditioning; excluded from all "
                                 "percentiles and budgets",
            "resources": self.resources,
            "resource_notes": {
                "daemon_rss_kb": "VmRSS of this batch's own daemon, read from "
                                 "/proc/<pid>/status",
                "client_cpu": "resource.getrusage; children_ms only accounts reaped "
                              "children, so per-sample daemon CPU is not obtainable and "
                              "is reported as null",
                "per_sample_daemon_cpu_ms": None,
                "per_sample_daemon_cpu_reason": "a running daemon's CPU is only reaped at "
                                                "exit, so it is a whole-run figure, not a "
                                                "per-sample one",
            },
            "relative_to_old_candidate": {
                k: {"value": v[0], "reason": v[1]} for k, v in self.relative.items()},
            "interference_precheck": self.interference,
            "environment_conditions": {
                "sandbox_exec_stall": "intermittent; bounded by the conditioning step "
                                      "(protocol §1.3 R1) and, for measured samples, by the "
                                      "§1.5 stop rule",
                "shared_gateway": "pid 4009810 used as-is; not restarted by this batch",
                "sandbox": self.target,
                "host": platform.platform(),
            },
            "finished_at": BASE.now_iso(),
            "steps": self.steps,
        }
        out = self.out / "report.json"
        out.write_text(json.dumps(self.public(doc), indent=2, ensure_ascii=False, default=str))
        samples_path = self.out / "samples.json"
        samples_path.write_text(json.dumps(
            self.public({"schema": PERF_SCHEMA + "/samples",
                         "warmup_discarded_per_scenario": WARMUP,
                         "samples": self.samples}),
            indent=2, ensure_ascii=False, default=str))
        src = self.out / "source-hashes.json"
        src.write_text(json.dumps(self.public({
            "procedure": "B / source_binding-family",
            "files": len(self.source_binding["files"]),
            "sha256": self.source_binding["sha256"],
            "stable_during_run": source_stable,
            "note": "computed by reusing the frozen bookkeeping procedure from "
                    "openshell-b2b3-perf-protocol.py rather than reimplementing it",
        }), indent=2, ensure_ascii=False))
        failed = sum(1 for s in self.steps if s.get("status") == "fail")
        print(f"\nwrote {out} ({len(self.samples)} samples, {failed} failed steps, "
              f"budget misses: {misses or 'none'})")
        return 0 if failed == 0 else 1

    def rounds_completed(self):
        done = set()
        for s in self.samples:
            done.add(s["round"])
        return sorted(done)


def main():
    os.umask(0o077)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--expected-sha256", required=True, help="candidate SHA256")
    ap.add_argument("--expected-protocol-sha256", default=None,
                    help="pre-measurement SHA256 of this run's protocol.md; "
                         "omission keeps the original frozen protocol hash")
    ap.add_argument("--baseline-commit", default=None,
                    help="source commit of an explicitly declared baseline")
    ap.add_argument("--baseline-has-taskexec", action="store_true",
                    help="baseline has task routes, but this run does not measure it")
    ap.add_argument("--env-script", required=True,
                    help="private env script exporting SIQ_OPENSHELL_BIN + XDG dirs")
    ap.add_argument("--gateway-endpoint", default="https://127.0.0.1:17671")
    ap.add_argument("--lost-endpoint", default="https://127.0.0.1:1")
    ap.add_argument("--target", required=True, help="explicitly owned writable test target")
    ap.add_argument("--fact-endpoint", required=True,
                    help="the sandbox's own egress gateway:port, declared as policy content only")
    ap.add_argument("--out", required=True, help="evidence directory (must not already "
                                                 "contain a report.json)")
    args = ap.parse_args()
    if args.baseline_has_taskexec and not args.baseline_commit:
        ap.error("--baseline-has-taskexec requires --baseline-commit")
    if args.expected_protocol_sha256 is not None and not re.fullmatch(
        r"[0-9a-f]{64}", args.expected_protocol_sha256
    ):
        ap.error("--expected-protocol-sha256 must be a lowercase SHA256")

    out = Path(args.out).resolve()
    if (out / "report.json").exists():
        raise SystemExit(f"refusing to overwrite an existing measurement: {out}/report.json")

    j = PerfJourney(args)
    rc = 1
    try:
        rc = j.run()
    except Exception as exc:  # noqa: BLE001 -- record failed evidence, then exit nonzero
        trace = traceback.format_exc()
        print(f"PERF RUN FAILED: {j.redact(exc)}\n{j.redact(trace)}", file=sys.stderr)
        j.record({"id": "ABORT", "title": "performance run aborted", "kind": "derived",
                  "status": "fail", "detail": str(exc),
                  "leg": getattr(j, "current_leg", "?"), "traceback": trace})
        try:
            j.perf_report()
        except Exception:  # noqa: BLE001 -- reporting must not mask the original failure
            print("report generation also failed", file=sys.stderr)
        rc = 1
    finally:
        for proc in (j.proc, j.lost_proc):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
        shutil.rmtree(j.root, ignore_errors=True)
        if j.lost_root:
            shutil.rmtree(j.lost_root, ignore_errors=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
