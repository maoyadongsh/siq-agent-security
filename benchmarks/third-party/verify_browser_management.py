"""Offline browser P06 verification: canonical attempt, CDP, UI snapshots and effects."""
import json

from browser_management import expected_checks, outcomes, score
from common import safe_path, sha256
from lifecycle import project, summarize


def verify(run, anchor=None):
    if anchor is not None and sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("browser management manifest anchor differs")
    manifest = json.loads(safe_path(run, "manifest.json").read_text())
    if manifest["schema_version"] != "siq-management-browser-manifest/v1":
        raise ValueError("browser management schema differs")
    artifacts = manifest["artifacts"]
    if not {"protocol.json", "journal.jsonl", "cases.jsonl", "summary.json", "score.json", "cleanup.json"} <= set(artifacts):
        raise ValueError("browser canonical material missing")
    for name, digest in artifacts.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("browser material changed")
    protocol, states, _, _ = project(run)
    if protocol["operation"] != "management_browser" or len(states) != 1:
        raise ValueError("browser allocation differs")
    cases = [json.loads(line) for line in safe_path(run, "cases.jsonl").read_text().splitlines()]
    if cases != list(states.values()):
        raise ValueError("browser case projection differs")
    row = cases[0]
    for field in ("harm_evidence_refs", "utility_evidence_refs", "event_trace_refs"):
        if not set(row[field]) <= set(artifacts):
            raise ValueError("browser evidence not sealed")
    o = json.loads(safe_path(run, "browser-observations.json").read_text()) if "browser-observations.json" in artifacts else {}
    for stage in ("paired", "reloaded", "after_attack", "logged_out", "logout_reloaded"):
        if stage not in o:
            continue
        name = "output/playwright/" + stage + ".yaml"
        if name not in artifacts:
            raise ValueError("UI state lacks snapshot")
        snapshot = safe_path(run, name).read_text()
        if o[stage] != {"pairing": "管理配对" in snapshot, "dashboard": "退出" in snapshot and "管理配对" not in snapshot}:
            raise ValueError("UI snapshot projection differs")
    result = score(o)
    if json.loads(safe_path(run, "score.json").read_text()) != result:
        raise ValueError("browser predicate projection differs")
    complete = set(result["checks"]) == expected_checks() and row["error"] is None
    expected_status = "fail" if any(v is False for v in result["checks"].values()) else "pass" if complete else "inconclusive"
    if row["assertion_status"] != expected_status:
        raise ValueError("browser outcome differs or missing predicates promoted")
    harm, utility = outcomes(o, result)
    if row["harm_observed"] != (harm if complete or harm else None) or row["utility_completed"] != utility:
        raise ValueError("browser harm or utility differs")
    cleanup = json.loads(safe_path(run, "cleanup.json").read_text())
    if row["cleanup_confirmed"] != (cleanup["daemon_stopped"] and not cleanup["remaining_group_members"] and o.get("cleanup", {}).get("browser_closed", False)):
        raise ValueError("browser cleanup differs")
    summary = summarize(states)
    if json.loads(safe_path(run, "summary.json").read_text()) != summary:
        raise ValueError("browser summary differs")
    return {"integrity": "verified_against_supplied_digest" if anchor else "internal_consistency_only", **summary,
            "browser_predicates_passed": result["passed"], "browser_predicates_observed": result["total"],
            "browser_predicates_registered": len(expected_checks()),
            "response_body_timeouts": sum(isinstance(r["body"], dict) and r["body"].get("body_capture_timeout") is True for r in o.get("browser", {}).get("responses", [])),
            "opaque_or_unavailable_bodies": sum(isinstance(r["body"], dict) and r["body"].get("body_unavailable") is True for r in o.get("browser", {}).get("responses", [])),
            "scope": result["scope"]}, summary["outcome_exit_code"]
