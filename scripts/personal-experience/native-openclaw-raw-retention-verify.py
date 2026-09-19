#!/usr/bin/env python3
"""Verify natural ciphertext expiry for records captured by the real OpenClaw host.

The matching seed is produced by r07-linux-user-journey-smoke.py with
--retain-state-dir. The daemon is stopped between the seed and this verifier;
neither this script nor its seed changes system time, timestamps, or the
product's one-hour minimum retention. Keep the seed and state in *-private/.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("native_b04_helpers", HERE / "closure-b04-expiry-seed-runner.py")
b04 = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = b04
spec.loader.exec_module(b04)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ResumeHarness(b04.B04Harness):
    """Pair the existing R07 state without rewriting its immutable config."""

    def config(self, _enforcement):
        require((self.state / "config.json").is_file(), "existing config missing")


def check(report, check_id, condition, detail):
    report["checks"].append({"id": check_id, "status": "pass" if condition else "fail", "detail": detail})
    require(condition, check_id + ": " + detail)


def group(rows, label):
    return [row for row in rows if row["label"] == label]


def file_path(state: Path, row: dict) -> Path:
    return state / "raw-task-content" / (row["record_id"] + ".json")


def verify(args):
    seed = json.loads(args.seed.read_text())
    require(seed.get("schema_version") == "linux-native-openclaw-raw-retention-seed/v1"
            and seed.get("verification_status") == "pending_real_wall_clock_expiry",
            "unexpected native retention seed")
    root, state = Path(seed["root"]), Path(seed["state_dir"])
    require(root.is_dir() and state == root / "state" and state.is_dir(),
            "retained native state missing")
    require(root.parent.name.endswith("-private") and args.seed.parent.name.endswith("-private")
            and args.out.parent.name.endswith("-private"),
            "native state and reports must remain in *-private/")
    rows = seed["records"]
    require(len(rows) == 6 and all(len(group(rows, label)) == 2 for label in ("A1", "A2", "B1")),
            "expected six native captures in A1/A2/B1 groups")
    require({row["kind"] for row in group(rows, "A1")} == {"parameters", "output"}
            and {row["kind"] for row in group(rows, "A2")} == {"parameters", "output"}
            and {row["kind"] for row in group(rows, "B1")} == {"parameters", "output"},
            "native capture kinds incomplete")
    a_tasks = {row["task_id"] for row in group(rows, "A1") + group(rows, "A2")}
    b_tasks = {row["task_id"] for row in group(rows, "B1")}
    require(len(a_tasks) == len(b_tasks) == 1 and a_tasks != b_tasks,
            "A1/A2 and B1 not bound to two independent native tasks")
    report = {
        "schema_version": "linux-native-openclaw-raw-retention-verify/v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "candidate_sha256": seed["candidate_sha256"],
        "seed_sha256": sha256(args.seed),
        "verifier_sha256": sha256(Path(__file__)),
        "native_host": "openclaw", "native_host_version": seed["native_host_version"],
        "checks": [], "passed": False,
    }
    check(report, "same_frozen_candidate",
          sha256(args.binary) == seed["candidate_sha256"]
          and sha256(root / "siq-agent-security") == seed["candidate_sha256"],
          "seed, CLI input and retained binary digest agree")

    # Stage 1: inspect encrypted envelopes while the daemon is down. Their
    # hashes must still match the native host's seed; no private key or
    # plaintext is loaded or copied into this report.
    check(report, "native_ciphertext_present_before_restart",
          all(file_path(state, row).is_file()
              and sha256(file_path(state, row)) == row["ciphertext_sha256"]
              and json.loads(file_path(state, row).read_text()).get("expires_at") == row["expires_at"]
              for row in rows),
          "six seeded envelopes unchanged while daemon stopped")
    expired_at = max(b04.parse_rfc3339(row["expires_at"]) for row in group(rows, "A1"))
    survivor_until = min(b04.parse_rfc3339(row["expires_at"])
                         for row in group(rows, "A2") + group(rows, "B1"))
    check(report, "natural_retention_window_distinct",
          survivor_until - expired_at > b04._dt.timedelta(hours=22),
          "A1=1h, A2/B1=24h server timestamps differ by over 22h")
    remaining = (expired_at - datetime.now(UTC)).total_seconds()
    if remaining > 0:
        require(args.wait, "not yet expired; re-run with --wait after the recorded expiry")
        time.sleep(remaining + 1.0)
    check(report, "real_wall_clock_expired",
          datetime.now(UTC) > expired_at and datetime.now(UTC) < survivor_until,
          "wall clock past A1 expiry and before A2/B1 expiry")

    pre = b04.state_digest_snapshot(state)
    pre_append = b04.append_only_snapshot(state)
    harness = ResumeHarness(root, argparse.Namespace(port=seed["port"]), resume=True)
    try:
        harness.start(port=seed["port"])
        check(report, "same_state_and_port_repaired",
              harness.state == state and harness.port == seed["port"]
              and sha256(harness.binary) == seed["candidate_sha256"],
              "daemon restarted and re-paired on retained state and frozen binary")
        post_start = b04.state_digest_snapshot(state)
        post_append = b04.append_only_snapshot(state)
        removed, added, modified = b04.scope_changes(pre, post_start)
        check(report, "startup_purge_scope_only_raw",
              not b04.out_of_scope_changes(removed, added, modified, pre_append, post_append),
              "startup cleanup did not delete or rewrite non-raw state")
        check(report, "expired_native_a1_deleted_on_start",
              all(not file_path(state, row).exists() for row in group(rows, "A1")),
              "A1 native ciphertext envelopes absent after real serve startup")
        check(report, "native_a2_b1_unchanged_on_start",
              all(file_path(state, row).is_file()
                  and sha256(file_path(state, row)) == row["ciphertext_sha256"]
                  for row in group(rows, "A2") + group(rows, "B1")),
              "A2/B1 24h native ciphertext byte digests unchanged")

        before_purge = b04.state_digest_snapshot(state)
        append_before = b04.append_only_snapshot(state)
        purged = harness.purge_expired()
        after_purge = b04.state_digest_snapshot(state)
        append_after = b04.append_only_snapshot(state)
        removed, added, modified = b04.scope_changes(before_purge, after_purge)
        check(report, "manual_purge_idempotent_and_scoped",
              purged.get("deleted_records") == 0
              and not b04.out_of_scope_changes(removed, added, modified,
                                               append_before, append_after),
              "manual purge after startup deletes zero and preserves unrelated state")
        a_active = harness.search_records(next(iter(a_tasks)))
        b_active = harness.search_records(next(iter(b_tasks)))
        survivor_ids = {row["record_id"] for row in group(rows, "A2") + group(rows, "B1")}
        check(report, "native_task_metadata_isolated_after_purge",
              {row["record_id"] for row in a_active + b_active} == survivor_ids
              and {row["record_id"] for row in a_active}
              == {row["record_id"] for row in group(rows, "A2")}
              and {row["record_id"] for row in b_active}
              == {row["record_id"] for row in group(rows, "B1")},
              "only unexpired A2/B1 metadata remains under its own task")
        readable = [harness.read_record(row["record_id"], row["task_id"])
                    for row in group(rows, "A2") + group(rows, "B1")]
        check(report, "native_survivors_readable_without_plaintext_report",
              all(item["record"]["plaintext_sha256"] == row["plaintext_sha256"]
                  for item, row in zip(readable, group(rows, "A2") + group(rows, "B1"), strict=True)),
              "four surviving native captures decrypt with original plaintext hashes")
        denied = harness.api(
            "/v1/raw-task-content/records/" + group(rows, "A2")[0]["record_id"] + "/read",
            {"schema_version": "local-raw-task-content-record-read/v1",
             "task_id": next(iter(b_tasks))}, expected=503)
        check(report, "cross_native_task_read_still_denied",
              denied.get("error") == "raw_task_content_unavailable" and "fields" not in denied,
              "B task cannot read A2 ciphertext after expiry cleanup")
        check(report, "grants_and_receipts_preserved",
              all((state / "raw-task-content-authority" /
                   (row["grant_id"] + ".grant.json")).is_file() for row in rows)
              and bool(harness.api("/v1/receipts")["receipts"]),
              "grant authority files and signed decision receipt chain remain")
    finally:
        harness.stop()

    verified = json.loads(harness.command([str(harness.binary), "verify"]))
    check(report, "receipt_chain_verified_after_native_cleanup",
          verified.get("verified") is True,
          "product verify accepts persisted receipt chain after cleanup")
    report["passed"] = True
    return report


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--wait", action="store_true",
                        help="wait for natural expiry if invoked before the A1 server timestamp")
    args = parser.parse_args()
    args.binary, args.seed, args.out = args.binary.resolve(), args.seed.resolve(), args.out.resolve()
    require(not args.out.exists() and not args.out.with_suffix(".failure.json").exists(),
            "refusing to overwrite a prior verifier report")
    try:
        report = verify(args)
    except Exception as error:  # noqa: BLE001 -- private failure category, no secret text
        args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        with args.out.with_suffix(".failure.json").open("x") as handle:
            json.dump({"passed": False, "error_type": type(error).__name__,
                       "seed_sha256": sha256(args.seed)}, handle, indent=2)
        raise
    args.out.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with args.out.open("x") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps({"passed": True, "checks": len(report["checks"])}))


if __name__ == "__main__":
    main()
