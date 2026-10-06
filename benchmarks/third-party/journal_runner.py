"""Registered in-process marker calibration for the canonical journal.

This validates evaluation infrastructure only, not SIQ protection. No subprocess,
network, daemon, customer file or model is dispatched by the registered operation.
"""
import hashlib
import json
import os
import time
from pathlib import Path

from common import canonical, safe_path, sha256, utc_now, write_json
from lifecycle import Journal, process_identity, process_state, project, summarize


def preflight(path):
    p = json.loads(path.read_text())
    if p["schema_version"] != "siq-evaluation-protocol/v2" or p["operation"] != "marker_calibration":
        raise ValueError("unregistered journal operation")
    if p["track"] != "B" or p["max_attempts"] != 2 or p["measurement_kind"] != "harness_calibration":
        raise ValueError("unsupported journal calibration scope")
    if p["model_calls_enabled"] is not False or p["pause_seconds"] not in range(1, 61):
        raise ValueError("invalid calibration budget")
    ids = [u["unit_id"] for u in p["allocation"]]
    if ids != ["interrupted-write", "independent-write"]:
        raise ValueError("unknown calibration allocation")
    if [u["forbid_write"] for u in p["allocation"]] != [True, False] or any(u["group"] != "CALIBRATION" for u in p["allocation"]):
        raise ValueError("calibration semantics changed")
    if set(p["harness_sources"]) != {"run.py", "common.py", "lifecycle.py", "journal_runner.py", "schemas/case.v1.schema.json"}:
        raise ValueError("incomplete harness identity")
    if p["candidate_digest"] != hashlib.sha256(canonical(p["harness_sources"])).hexdigest():
        raise ValueError("harness candidate digest differs")
    for name, digest in p["harness_sources"].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError("run the frozen harness snapshot")
    return p


def run(path, out, *, resume=False, retry=None, seal=False):
    p = preflight(path)
    if out.name != p["run_id"]:
        raise ValueError("frozen run ID differs")
    out.resolve().relative_to(Path(p["campaign_root"]) / "private/runs")
    os.umask(0o077)
    journal = Journal(out, None if resume else p)
    try:
        if sha256(path) != sha256(out / "protocol.json"):
            raise ValueError("resume protocol differs")
        journal.reconcile_dead_writers()
        for key, row in list(journal.states.items()):
            if row["lifecycle"] != "interrupted" or row["cleanup_confirmed"]:
                continue
            status = process_state(row["process_ref"])
            if status == "alive":
                continue
            # This registered operation has no child/background/network worker.
            # Other future operations require their own resource reconciler.
            ref = f"attempts/{row['unit_id']}/{row['attempt']}/cleanup.json"
            write_json(safe_path(out, ref), {"operation": "marker_calibration", "writer_state": status,
                                           "background_resources": "none_by_frozen_operation_contract"})
            journal.transition(key, "cleanup_confirmed", cleanup_confirmed=True,
                               event_trace_refs=[*row["event_trace_refs"], ref])
        if retry:
            journal.retry(retry)
        for key, row in list(journal.states.items()):
            if row["lifecycle"] != "scheduled":
                continue
            unit = next(u for u in p["allocation"] if u["unit_id"] == row["unit_id"])
            prefix = f"attempts/{row['unit_id']}/{row['attempt']}"
            directory = safe_path(out, prefix)
            directory.mkdir(parents=True, exist_ok=False)
            journal.transition(key, "started", execution_status="running", process_ref=process_identity(),
                               harm_unknown_reason="observation_window_open", utility_unknown_reason="observation_window_open")
            marker = directory / "marker.txt"
            with marker.open("xb") as stream:
                stream.write((key + "\n").encode())
                stream.flush()
                os.fsync(stream.fileno())
            effect_ref = prefix + "/effect.json"
            write_json(out / effect_ref, {"attempt_id": key, "marker_sha256": sha256(marker), "forbidden_write": unit["forbid_write"]})
            journal.transition(key, "observed", tool_executed=True,
                               harm_observed=True if unit["forbid_write"] else None,
                               harm_unknown_reason=None if unit["forbid_write"] else "observation_window_open",
                               harm_evidence_refs=[effect_ref] if unit["forbid_write"] else [],
                               event_trace_refs=[effect_ref])
            if unit["unit_id"] == "interrupted-write" and row["attempt"] == 1:
                # Bounded synchronization window for the external SIGKILL driver.
                deadline = time.monotonic() + p["pause_seconds"]
                while time.monotonic() < deadline:
                    time.sleep(0.05)
            journal.transition(key, "finished", execution_status="completed", measurement_status="determinate",
                               assertion_status="pass", harm_observed=unit["forbid_write"], harm_unknown_reason=None,
                               utility_completed=True, utility_unknown_reason=None, utility_evidence_refs=[effect_ref],
                               oracle={"source": "owned_marker_calibration", "coverage": "full", "healthy": True,
                                       "window_start": None, "window_end": utc_now(), "materials": [effect_ref]},
                               cleanup_confirmed=True)
        # Validate the whole append-only chain before projecting or sealing it.
        _, states, _, _ = project(out)
        summary = summarize(states)
        if seal:
            with (out / "cases.jsonl").open("x") as stream:
                for value in states.values():
                    stream.write(json.dumps(value, ensure_ascii=False) + "\n")
            write_json(out / "summary.json", summary)
            paths = [out / name for name in ("protocol.json", "journal.jsonl", "cases.jsonl", "summary.json")]
            paths += [f for f in (out / "attempts").rglob("*") if f.is_file()]
            write_json(out / "manifest.json", {"schema_version": "siq-journal-manifest/v1", "relationship": "author_run",
                       "measurement_kind": "harness_calibration", "artifacts": {str(f.relative_to(out)): sha256(f) for f in sorted(paths)}})
            summary = {**summary, "manifest_sha256": sha256(out / "manifest.json")}
        print(json.dumps(summary), flush=True)
        return summary["outcome_exit_code"]
    finally:
        journal.close()
