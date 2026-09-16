#!/usr/bin/env python3
"""Frozen B2 doctor measurements plus auxiliary control-plane restoration.

The Go test driver is NOT the candidate executable and cannot close B3, O05
session binding or enforcement. No shared target: confirm a disposable target
created and owned by this run. Never run concurrently with builds/benchmarks.
Prior v1 measurements remain historical; v2 results require a fresh run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import resource
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "apps/agentshield"
ROUNDS, WARMUP, SAMPLES, CYCLE_SAMPLES = 3, 2, 15, 5
ROUND_ORDERS = [["old", "new", "new", "old"], ["new", "old", "old", "new"], ["old", "new", "new", "old"]]
SCENARIOS = ["doctor_readback", "doctor_unreachable"]
RELATIVE_SCENARIOS = ["doctor_readback"]
RELATIVE_BUDGET_RATIO = 1.30
BUDGETS = {"doctor_readback": 15000.0, "doctor_unreachable": 15000.0, "aux_control_plane_restore": 60000.0}
MARKER = "SIQ_AUX_CONTROL_PLANE_RESTORE_VERIFIED"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, doc):
    with Path(path).open("x", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")


def source_binding():
    paths = sorted(p for p in MODULE.rglob("*.go") if ".git" not in p.parts)
    paths += [MODULE / "go.mod"]
    paths += sorted(p for p in (MODULE / "internal/ui/embedded").rglob("*") if p.is_file())
    files = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    return {"files": files, "sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}


def percentile(values, p):
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty sample set")
    return ordered[math.ceil(p / 100 * len(ordered)) - 1]


def validate_doctor(stdout, target, unreachable=False):
    try:
        d = json.loads(stdout)
    except (ValueError, TypeError):
        raise ValueError("invalid doctor JSON") from None
    if not isinstance(d, dict) or d.get("started_gateway") is not False:
        raise ValueError("invalid doctor report")
    if unreachable:
        if d.get("state") != "configured_unreachable" or d.get("probe_ok") is not False or d.get("identity_ok") is not False:
            raise ValueError("unreachable diagnostic not proven")
        return {"state": d["state"], "probe_ok": False, "identity_ok": False}
    if (d.get("state") != "policy_readable" or d.get("probe_ok") is not True
            or d.get("identity_ok") is not True or d.get("target") != target
            or not re.fullmatch(r"[1-9][0-9]*", str(d.get("revision", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(d.get("policy_digest", "")))):
        raise ValueError("target policy readback not proven")
    try:
        observed = datetime.fromisoformat(d["observed_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(d["expires_at"].replace("Z", "+00:00"))
        now = datetime.now(UTC)
        if not observed <= now < expires:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError("fresh doctor evidence required") from None
    return {k: d[k] for k in ("state", "target", "revision", "policy_digest", "observed_at", "expires_at")}


def validate_driver(stdout):
    if ("--- PASS: TestO05LiveRollbackRestore " not in stdout or MARKER not in stdout
            or "--- SKIP:" in stdout or "--- FAIL:" in stdout):
        raise ValueError("auxiliary changed apply/refusal/restore not proven")
    return {"scope": "auxiliary_control_plane", "changed_restore_verified": True}


def run_once(argv, env, validator, cwd=None):
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    c0 = cpu.ru_utime + cpu.ru_stime
    start = time.perf_counter()
    try:
        proc = subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise RuntimeError("sample timeout; run invalid") from None
    wall = (time.perf_counter() - start) * 1000
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    if proc.returncode:
        # Never expose argv/stderr: they can contain private paths or credentials.
        raise RuntimeError("sample nonzero exit; run invalid")
    evidence = validator(proc.stdout)  # validation outside timed window
    return {"wall_ms": wall, "child_cpu_ms": (cpu.ru_utime + cpu.ru_stime - c0) * 1000,
            "rc": proc.returncode, "evidence": evidence}


def summarize(samples):
    verdicts = {}
    for key, runs in sorted(samples.items()):
        name = key.split(":", 1)[1]
        walls = [r["wall_ms"] for r in runs]
        stat = {"n": len(walls), **{f"p{p}_ms": percentile(walls, p) for p in (50, 95, 99)},
                "max_ms": max(walls), "absolute_budget_p95_ms": BUDGETS[name]}
        stat["absolute_verdict"] = "pass" if stat["p95_ms"] <= BUDGETS[name] else "MISS"
        verdicts[key] = stat
    for name in RELATIVE_SCENARIOS:
        old, new = (verdicts[f"{leg}:{name}"]["p95_ms"] for leg in ("old", "new"))
        verdicts[f"relative:{name}"] = {
            "ratio": new / old if old else None, "budget_ratio": RELATIVE_BUDGET_RATIO,
            "verdict": "pass" if new <= old * RELATIVE_BUDGET_RATIO else "MISS"}
    return verdicts


def budget_misses(verdicts):
    return [k for k, v in verdicts.items()
            if v.get("absolute_verdict") == "MISS" or v.get("verdict") == "MISS"]


def main():
    old, new, cli = (Path(os.environ[k]).resolve(strict=True)
                     for k in ("B2B3_OLD_BIN", "B2B3_NEW_BIN", "B2B3_CLI_BIN"))
    target = os.environ["B2B3_SANDBOX"]
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", target):
        raise ValueError("invalid dedicated target")
    if os.environ.get("B2B3_CONFIRM_OWNED_TARGET") != target:
        raise ValueError("confirm exact disposable target ownership")
    endpoint = os.environ["SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT"]
    u = urlsplit(endpoint)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.query or u.fragment or u.path not in ("", "/"):
        raise ValueError("explicit credential-free HTTPS endpoint required")
    out = Path(os.environ["B2B3_OUT"])
    out.parent.mkdir(parents=True, exist_ok=True)
    # Claim before any backend access/build; leave failed run records intact.
    claim = out.with_suffix(".claim")
    with claim.open("x") as f:
        f.write("exclusive run; never overwrite or reuse\n")
    for p in (out, out.with_suffix(".protocol.json"), out.with_suffix(".samples.jsonl")):
        if p.exists():
            raise ValueError("evidence output already exists")
    env = dict(os.environ)
    for k in list(env):
        if k.startswith(("B2B3_", "SIQ_O05_")):
            del env[k]
    env.pop("SIQ_AS_OPENSHELL_ENV_SH", None)
    env["SIQ_AS_OPENSHELL_CLI_BIN"] = str(cli)
    sources = source_binding()
    bindings = {"old_sha256": sha(old), "new_sha256": sha(new), "cli_sha256": sha(cli),
                "endpoint_sha256": hashlib.sha256(endpoint.encode()).hexdigest(),
                "target": target, "driver_source": sources}
    protocol = {"schema": "openshell-service-perf/v2", "protocol_sha256": sha(__file__),
                "bindings": bindings, "rounds": ROUNDS, "warmup": WARMUP, "samples": SAMPLES,
                "cycle_samples": CYCLE_SAMPLES, "round_orders": ROUND_ORDERS,
                "scenario_order": SCENARIOS + ["aux_control_plane_restore"],
                "percentile_algorithm": "nearest-rank ceil(p*n/100), all samples",
                "budgets": BUDGETS, "relative_ratio": RELATIVE_BUDGET_RATIO,
                "budget_basis": "retained v1 frozen budgets; no post-measurement tuning",
                "exclusions": "none; failed sample invalidates run",
                "B3": "not_measured: auxiliary Go driver is not candidate executable",
                "scope": "B2 CLI diagnostic wall time; no enforcement/session claim",
                "host": {"platform": platform.platform(), "machine": platform.machine()},
                "started_utc": datetime.now(UTC).isoformat()}
    dump(out.with_suffix(".protocol.json"), protocol)
    samples = {}
    # Raw validated samples are flushed as they arrive; errors do not erase them.
    with out.with_suffix(".samples.jsonl").open("x", encoding="utf-8") as raw:
        try:
            with tempfile.TemporaryDirectory(prefix="siq-b2-aux-") as td:
                driver = Path(td) / "live.test"
                build = subprocess.run(["go", "test", "-c", "-o", str(driver), "./internal/openshell"],
                                       cwd=MODULE, env=env, capture_output=True, timeout=180)
                if build.returncode:
                    raise RuntimeError("auxiliary driver build failed")
                if source_binding() != sources:
                    raise RuntimeError("source drift during build")
                driver_hash = sha(driver)
                dump(out.with_suffix(".driver.json"), {"sha256": driver_hash, "source_sha256": sources["sha256"]})

                def measure(leg, name):
                    e = dict(env)
                    if name == "aux_control_plane_restore":
                        e.update(SIQ_O05_LIVE="1", SIQ_O05_TARGET=target, SIQ_O05_CONFIRM_TARGET=target)
                        return run_once([str(driver), "-test.run", "^TestO05LiveRollbackRestore$", "-test.v", "-test.count=1"],
                                        e, validate_driver, str(MODULE))
                    unreachable = name == "doctor_unreachable"
                    if unreachable:
                        e["SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT"] = "https://127.0.0.1:1"
                    return run_once([str(old if leg == "old" else new), "openshell", "doctor", "--target", target],
                                    e, lambda s: validate_doctor(s, target, unreachable))

                for leg in ("old", "new"):
                    for name in SCENARIOS:
                        for _ in range(WARMUP):
                            measure(leg, name)
                def collect(leg, name):
                    sample = measure(leg, name)
                    samples.setdefault(f"{leg}:{name}", []).append(sample)
                    raw.write(json.dumps({"leg": leg, "scenario": name, **sample}) + "\n")
                    raw.flush()
                for order in ROUND_ORDERS:
                    for leg in order:
                        for name in SCENARIOS:
                            for _ in range(SAMPLES):
                                collect(leg, name)
                        print(f"B2 leg {leg} done", flush=True)
                for _ in range(CYCLE_SAMPLES):
                    collect("auxiliary", "aux_control_plane_restore")
                if (sha(old) != bindings["old_sha256"] or sha(new) != bindings["new_sha256"]
                        or sha(cli) != bindings["cli_sha256"] or sha(driver) != driver_hash
                        or source_binding() != sources):
                    raise RuntimeError("bound inputs drifted")
            verdicts = summarize(samples)
            misses = budget_misses(verdicts)
            dump(out, {"valid": True, "budget_passed": not misses, "B3": "not_measured",
                       "protocol_sha256": sha(out.with_suffix(".protocol.json")),
                       "budget_verdicts": verdicts, "misses": misses,
                       "finished_utc": datetime.now(UTC).isoformat()})
            return 1 if misses else 0
        except Exception as exc:
            dump(out, {"valid": False, "budget_passed": False, "B3": "not_measured",
                       "error_category": type(exc).__name__, "raw_samples_retained": True})
            print("Measurement invalid; raw samples retained. Inspect the owned target.", file=sys.stderr)
            return 2


if __name__ == "__main__":
    sys.exit(main())
