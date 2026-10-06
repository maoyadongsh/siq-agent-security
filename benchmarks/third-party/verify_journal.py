"""Recompute canonical journal calibration and preserve first-attempt outcomes."""
import json

from common import safe_path, sha256
from lifecycle import project, summarize


def verify(run, anchor=None):
    manifest_path = safe_path(run, "manifest.json")
    if anchor is not None and sha256(manifest_path) != anchor:
        raise ValueError("journal manifest anchor differs")
    manifest = json.loads(manifest_path.read_text())
    if manifest["schema_version"] != "siq-journal-manifest/v1" or manifest["measurement_kind"] != "harness_calibration":
        raise ValueError("journal scope unsupported")
    required = {"protocol.json", "journal.jsonl", "cases.jsonl", "summary.json"}
    if not required <= set(manifest["artifacts"]):
        raise ValueError("journal payload missing")
    for name, digest in manifest["artifacts"].items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("journal payload changed")
    protocol, states, _, _ = project(run)
    if protocol["operation"] != "marker_calibration" or protocol["measurement_kind"] != "harness_calibration":
        raise ValueError("unregistered calibration")
    cases = [json.loads(x) for x in safe_path(run, "cases.jsonl").read_text().splitlines()]
    if cases != list(states.values()):
        raise ValueError("canonical case projection differs")
    for row in cases:
        for field in ("harm_evidence_refs", "utility_evidence_refs", "receipt_refs", "product_observer_refs", "event_trace_refs"):
            if not set(row[field]) <= set(manifest["artifacts"]):
                raise ValueError("case evidence not sealed")
        unit = next(u for u in protocol["allocation"] if u["unit_id"] == row["unit_id"])
        prefix = f"attempts/{row['unit_id']}/{row['attempt']}"
        if row["tool_executed"] is True:
            if not {prefix + "/marker.txt", prefix + "/effect.json"} <= set(manifest["artifacts"]):
                raise ValueError("observed operation lacks evidence")
            marker = safe_path(run, prefix + "/marker.txt")
            effect = json.loads(safe_path(run, prefix + "/effect.json").read_text())
            if marker.read_text() != row["attempt_id"] + "\n" or effect != {
                    "attempt_id": row["attempt_id"], "marker_sha256": sha256(marker), "forbidden_write": unit["forbid_write"]}:
                raise ValueError("marker identity or content differs")
            if unit["forbid_write"] and row["harm_observed"] is not True:
                raise ValueError("observed prohibited marker erased")
        if row["lifecycle"] == "interrupted" and row["cleanup_confirmed"]:
            ref = prefix + "/cleanup.json"
            if ref not in manifest["artifacts"]:
                raise ValueError("reconciled retry lacks cleanup record")
            cleanup = json.loads(safe_path(run, ref).read_text())
            if cleanup["operation"] != "marker_calibration" or cleanup["writer_state"] not in {"absent", "different_boot", "pid_reused", "zombie"}:
                raise ValueError("cleanup does not establish writer exit")
    summary = summarize(states)
    if json.loads(safe_path(run, "summary.json").read_text()) != summary:
        raise ValueError("first-attempt result replaced")
    return {"integrity": "verified_against_supplied_digest" if anchor else "internal_consistency_only",
            "scope": "evaluation infrastructure calibration, not product security results", **summary}, summary["outcome_exit_code"]
