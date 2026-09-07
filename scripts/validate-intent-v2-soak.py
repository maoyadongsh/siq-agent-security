#!/usr/bin/env python3
"""Bounded real-daemon soak: multiple authorities, in-flight kills, post replay.

Synthetic HTTP clients and temporary state only; no platform/model calls. A pass
describes the measured duration and faults, not an uptime or durability SLA.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import math
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location(
    "native_fixture", ROOT / "scripts/validate-intent-v2-hermes.py"
)
fixture = importlib.util.module_from_spec(loader)
loader.loader.exec_module(fixture)


class Soak:
    def __init__(self, harness, args):
        self.h, self.args = harness, args
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.restarting = threading.Event()
        self.generation = 0
        self.serial = 0
        self.attempted_new = 0
        self.known = []
        self.counts = Counter()
        self.latencies = {kind: deque(maxlen=10000) for kind in ("decide", "observe")}
        self.errors = []
        self.sessions = []
        self.restarts = []
        self.resources = []

    def setup(self):
        self.h.build()
        self.h.start()
        self.h.setup_authority()
        self.token = (self.h.state / "token").read_text().strip()
        base = self.h.api("/v1/intents/int-native-fixture")
        base.pop("signature")
        base.pop("digest")
        for index in range(self.args.sessions):
            sid = f"soak-session-{index}"
            company = "company-a" if index % 2 == 0 else "company-b"
            intent = self.h.api(
                "/v1/intents",
                {
                    **base,
                    "intent_id": f"int-soak-{index}",
                    "task_id": f"task-soak-{index}",
                    "resource_constraints": [
                        {
                            "domain": "filesystem",
                            "operator": "prefix",
                            "value": str(self.h.workspace / company),
                        }
                    ],
                },
                expected=201,
            )
            self.h.api(
                "/v1/intent-bindings",
                {
                    "platform": "hermes",
                    "session_id": sid,
                    "agent_id": fixture.AGENT,
                    "intent_id": intent["intent_id"],
                },
                expected=201,
            )
            self.sessions.append(
                {
                    "session_id": sid,
                    "intent_id": intent["intent_id"],
                    "digest": intent["digest"],
                    "task_id": intent["task_id"],
                    "path": str(self.h.workspace / company / "report.txt"),
                }
            )
        for session in self.sessions:
            self.new_action(session)

    def request(self, kind, body):
        started = time.perf_counter()
        response = self.h.api("/v1/" + kind, body, token=self.token)
        with self.lock:
            self.counts[kind + "_success"] += 1
            self.latencies[kind].append((time.perf_counter() - started) * 1000)
        return response

    def new_action(self, session):
        with self.lock:
            if self.attempted_new >= self.args.max_new_actions:
                return
            self.attempted_new += 1
            serial = self.attempted_new
        request = {
            "platform": "hermes",
            "session_id": session["session_id"],
            "agent_id": fixture.AGENT,
            "tool": "read_file",
            "tool_call_id": f"soak-call-{serial}",
            "params": {"path": session["path"]},
        }
        decision = self.request("decide", request)
        fixture.require(decision["action"] == "allow", "valid soak action denied")
        observation = {
            **request,
            "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"],
            "result": "synthetic soak result " + str(serial),
        }
        item = {"request": observation, "response": None}
        # Save acknowledged authority before sending post; a lost response must
        # never cause us to invent an action ID or replay an unacknowledged tool.
        with self.lock:
            self.known.append(item)
        self.observe(item)

    def observe(self, item):
        response = self.request("observe", item["request"])
        with self.lock:
            if item["response"] is not None:
                fixture.require(
                    response == item["response"], "replay changed observation identity"
                )
            item["response"] = response

    def worker(self, worker_index):
        while not self.stop.is_set():
            with self.lock:
                self.serial += 1
                serial = self.serial
                generation = self.generation
                was_restarting = self.restarting.is_set()
                create = (
                    serial % 10 == 0 and self.attempted_new < self.args.max_new_actions
                )
                session = self.sessions[(serial + worker_index) % len(self.sessions)]
                item = self.known[(serial + worker_index) % len(self.known)]
            try:
                if create:
                    self.new_action(session)
                else:
                    self.observe(item)
            except (
                urllib.error.URLError,
                OSError,
                http.client.HTTPException,
                json.JSONDecodeError,
            ) as exc:
                with self.lock:
                    if (
                        was_restarting
                        or self.restarting.is_set()
                        or generation != self.generation
                    ):
                        self.counts["transport_errors_during_restart"] += 1
                    else:
                        self.errors.append(
                            "unexpected transport failure: " + type(exc).__name__
                        )
                        self.stop.set()
            except (RuntimeError, ValueError, KeyError) as exc:
                with self.lock:
                    self.errors.append(str(exc))
                self.stop.set()
            self.stop.wait(self.args.workers / self.args.rate)

    def snapshot(self, elapsed):
        row = {"elapsed_seconds": round(elapsed, 3), "generation": self.generation}
        try:
            proc = Path(f"/proc/{self.h.proc.pid}")
            for line in (proc / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    row["daemon_rss_kib"] = int(line.split()[1])
                elif line.startswith("Threads:"):
                    row["daemon_threads"] = int(line.split()[1])
            row["daemon_open_fds"] = len(list((proc / "fd").iterdir()))
        except (OSError, AttributeError):
            row["proc_metrics_unavailable"] = True
        row["state_bytes_approx"] = 0
        for path in self.h.state.rglob("*"):
            try:
                if path.is_file():
                    row["state_bytes_approx"] += path.stat().st_size
            except FileNotFoundError:
                pass  # Concurrent publication may rename a temporary file.
        with self.lock:
            row["known_actions"] = len(self.known)
            row["counts"] = dict(self.counts)
        self.resources.append(row)
        print(json.dumps({"progress": row}), flush=True)

    def restart(self, elapsed):
        self.restarting.set()
        with self.lock:
            self.generation += 1
        started = time.monotonic()
        self.h.stop(kill=True)
        # Keep a real unavailable interval while workers continue issuing HTTP.
        self.stop.wait(0.5)
        self.h.start()
        self.restarting.clear()
        self.restarts.append(
            {"elapsed_seconds": elapsed, "recovery_seconds": time.monotonic() - started}
        )

    def verify(self):
        fixture.require(not self.errors, "; ".join(self.errors[:3]))
        for item in self.known:
            self.observe(item)
        records = self.h.receipts()
        decisions = {
            r["action_id"]: r for r in records if r.get("record_type") == "decision"
        }
        observations = [r for r in records if r.get("record_type") == "observation"]
        fixture.require(
            len(decisions)
            == len([r for r in records if r.get("record_type") == "decision"]),
            "duplicate decision action ID",
        )
        fixture.require(
            len(observations) == len({r["action_id"] for r in observations}),
            "duplicate observation",
        )
        authority = {s["session_id"]: s for s in self.sessions}
        for record in records:
            session = authority[record["session_id"]]
            fixture.require(
                record["intent_binding"] == "bound"
                and record["intent_id"] == session["intent_id"]
                and record["intent_digest"] == session["digest"]
                and record["task_id"] == session["task_id"],
                "authority crossed session boundary",
            )
        for observed in observations:
            before = decisions[observed["action_id"]]
            fixture.require(
                observed["decision_receipt_id"] == before["receipt_id"],
                "observation detached",
            )
        for session in self.sessions:
            own = [
                r
                for r in decisions.values()
                if r["session_id"] == session["session_id"]
            ]
            own.sort(key=lambda r: r["seq"])
            for index, record in enumerate(own):
                fixture.require(
                    record["task_seq"] == index + 1,
                    "task sequence broke across restart",
                )
                fixture.require(
                    record.get("parent_action_id", "")
                    == (own[index - 1]["action_id"] if index else ""),
                    "task parent changed across restart",
                )
        for item in self.known:
            fixture.require(
                sum(
                    r["action_id"] == item["request"]["action_id"] for r in observations
                )
                == 1,
                "acknowledged decision lost its observation",
            )
        sample = self.known[0]["request"]
        self.h.api(
            "/v1/observe",
            {**sample, "session_id": self.sessions[1]["session_id"]},
            token=self.token,
            expected=400,
        )
        self.h.api(
            "/v1/observe",
            {**sample, "result": "conflicting result"},
            token=self.token,
            expected=409,
        )
        self.h.stop()
        verified = json.loads(self.h.command([str(self.h.binary), "verify"]))
        fixture.require(verified["verified"], "offline chain verification failed")
        return {
            "receipts": len(records),
            "decisions": len(decisions),
            "observations": len(observations),
            "unacknowledged_or_unobserved_decisions": len(decisions)
            - len(observations),
            "checks": [
                "all_acknowledged_actions_observed_once",
                "post_replay_same_receipt",
                "per_session_intent_authority",
                "task_sequence_and_parent_recovery",
                "cross_session_observe_denied",
                "conflicting_result_denied",
                "offline_chain_verified",
            ],
        }

    def run(self):
        self.setup()
        self.counts.clear()
        for values in self.latencies.values():
            values.clear()
        started = time.monotonic()
        next_restart = self.args.restart_every
        next_snapshot = 0
        with ThreadPoolExecutor(max_workers=self.args.workers) as pool:
            futures = [pool.submit(self.worker, i) for i in range(self.args.workers)]
            try:
                while not self.stop.is_set():
                    elapsed = time.monotonic() - started
                    if elapsed >= self.args.duration_seconds:
                        break
                    if elapsed >= next_restart:
                        self.restart(elapsed)
                        next_restart += self.args.restart_every
                    if elapsed >= next_snapshot:
                        self.snapshot(elapsed)
                        next_snapshot += 30
                    self.stop.wait(0.2)
            finally:
                self.stop.set()
                for future in futures:
                    future.result(timeout=15)
        elapsed = time.monotonic() - started
        self.snapshot(elapsed)
        fixture.require(
            elapsed >= self.args.duration_seconds,
            "soak stopped before requested duration",
        )
        measured_counts = dict(self.counts)
        measured_latencies = {
            kind: list(values) for kind, values in self.latencies.items()
        }
        verification = self.verify()

        def percentile(values):
            ordered = sorted(values)
            return {
                f"p{p}_ms": ordered[max(0, math.ceil(len(ordered) * p / 100) - 1)]
                for p in (50, 95, 99)
            }

        return {
            "schema": "intent-v2-soak/v1",
            "passed": True,
            "recorded_at": fixture.datetime.now(fixture.timezone.utc).isoformat(),
            "siq_commit": self.h.command(
                ["git", "rev-parse", "HEAD"], cwd=ROOT
            ).strip(),
            "siq_dirty": bool(
                self.h.command(["git", "status", "--porcelain"], cwd=ROOT).strip()
            ),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "fixture_sha256": hashlib.sha256(
                (ROOT / "scripts/validate-intent-v2-hermes.py").read_bytes()
            ).hexdigest(),
            "binary_sha256": hashlib.sha256(self.h.binary.read_bytes()).hexdigest(),
            "duration_seconds": elapsed,
            "sessions": len(self.sessions),
            "workers": self.args.workers,
            "requested_operation_rate_ceiling": self.args.rate,
            "counts_before_final_reconciliation": measured_counts,
            "restart_measurements": self.restarts,
            "resource_samples": self.resources,
            "latency_last_10000_successful_requests": {
                k: percentile(v) if v else None for k, v in measured_latencies.items()
            },
            "verification": verification,
            "thresholds": None,
            "limitations": [
                "synthetic HTTP and tool results, not native Agent sessions",
                "observed duration only; no 24-hour uptime or power-loss claim",
                "transport failures accepted only during tracked kill/restart generations",
                "lost Decide responses never authorize tool execution or invented Observe references",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-seconds", type=int, default=600)
    parser.add_argument("--restart-every", type=int, default=90)
    parser.add_argument("--sessions", type=int, default=32)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--rate", type=float, default=24)
    parser.add_argument("--max-new-actions", type=int, default=2000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    fixture.require(
        5 <= args.duration_seconds <= 1800, "duration must be 5..1800 seconds"
    )
    fixture.require(
        1 <= args.restart_every < args.duration_seconds,
        "restart interval must be shorter than duration",
    )
    fixture.require(
        2 <= args.sessions <= 64 and 1 <= args.workers <= 32,
        "sessions/workers outside limits",
    )
    fixture.require(
        1 <= args.rate <= 100 and args.sessions <= args.max_new_actions <= 4000,
        "rate/action budget outside limits",
    )
    with tempfile.TemporaryDirectory(prefix="siq-intent-soak-") as tmp:
        harness = fixture.Harness(Path(tmp), args)
        try:
            report = Soak(harness, args).run()
        finally:
            harness.stop()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": True,
                "duration_seconds": report["duration_seconds"],
                "verification": report["verification"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"soak failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
