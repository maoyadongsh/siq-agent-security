"""Offline P01 verification: frozen planted manifest, trace evidence and canonical journal."""
import hashlib
import json
import tempfile
from pathlib import Path

from common import safe_path, sha256
from discovery_scoring import score
from discovery_trial import seed
from lifecycle import project, summarize


def verify(run, anchor=None):
    if anchor is not None and sha256(safe_path(run, "manifest.json")) != anchor:
        raise ValueError("discovery manifest anchor differs")
    manifest = json.loads(safe_path(run, "manifest.json").read_text())
    if manifest["schema_version"] != "siq-discovery-manifest/v1":
        raise ValueError("discovery manifest schema differs")
    artifacts = manifest["artifacts"]
    if not {"protocol.json", "journal.jsonl", "cases.jsonl", "summary.json"} <= artifacts.keys():
        raise ValueError("canonical discovery material missing")
    for name, digest in artifacts.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError("discovery material changed")
    protocol, states, _, _ = project(run)
    if protocol["operation"] != "discovery_http" or [u["unit_id"] for u in protocol["allocation"]] != ["scope", "invalid"]:
        raise ValueError("discovery allocation differs")
    rows = [json.loads(line) for line in safe_path(run, "cases.jsonl").read_text().splitlines()]
    if rows != list(states.values()):
        raise ValueError("discovery case projection differs")
    totals = {"predicates_passed": 0, "predicates": 0, "phase_metrics": {}}
    for row in rows:
        case = row["unit_id"]
        prefix = "cases/" + case + "/"

        def read(name, prefix=prefix):
            ref = prefix + name
            if ref not in artifacts:
                raise ValueError("discovery reference not sealed")
            return json.loads(safe_path(run, ref).read_text())

        for field in ("harm_evidence_refs", "utility_evidence_refs", "receipt_refs", "event_trace_refs"):
            if not set(row[field]) <= artifacts.keys():
                raise ValueError("discovery evidence not sealed")
        if not set(row["oracle"]["materials"]) <= artifacts.keys():
            raise ValueError("discovery oracle not sealed")
        gold, observations = read("gold.json"), read("observations.json")
        original = Path(protocol["campaign_root"]) / "private/runs" / protocol["run_id"] / "state-private" / case
        # Recreate synthetic inputs in a verifier-owned temp directory only. No product code runs.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "inputs"
            expected = seed(root, case, original / "siq-agent-security")
            expected = json.loads(json.dumps(expected).replace(str(root), str(original / "inputs")))
            if gold != expected:
                raise ValueError("planted asset manifest differs from registered fixture")
            hashes = {str(f).replace(str(root), str(original / "inputs")): hashlib.sha256(f.read_bytes().replace(str(root).encode(), str(original / "inputs").encode())).hexdigest() for f in root.rglob("*") if f.is_file() and not f.is_symlink()}
            # rglob does not descend fixture symlinks. Every planted file must be accounted for.
            if observations["input_before"] != hashes:
                raise ValueError("planted file identity differs")
        trace_map = read("trace-map.json")
        expected_traces = {"initial": "trace-1.txt"}
        if case == "scope":
            expected_traces.update(registered="trace-2.txt", restarted="trace-3.txt")
        if trace_map != expected_traces:
            raise ValueError("discovery trace allocation differs")
        traces = {}
        for name, file in trace_map.items():
            if prefix + file in artifacts:
                traces[name] = safe_path(run, prefix + file).read_text()
            elif row["execution_status"] == "completed":
                raise ValueError("completed discovery trace missing")
        for phase, observation in observations["phases"].items():
            if read(phase + ".json") != observation:
                raise ValueError("discovery HTTP projection differs")
        result = score(gold, observations, traces)
        if read("score.json") != result:
            raise ValueError("discovery score differs")
        for field in ("harm_observed", "utility_completed"):
            if row[field] != result[field]:
                raise ValueError("discovery canonical outcome differs")
        cleanup = read("cleanup.json")
        confirmed = not cleanup["remaining_group_members"]
        expected_status = "fail" if result["passed"] != result["total"] else "inconclusive" if row["error"] or not confirmed else "pass"
        if row["cleanup_confirmed"] != confirmed or row["assertion_status"] != expected_status:
            raise ValueError("discovery cleanup or assertion differs")
        totals["predicates_passed"] += result["passed"]
        totals["predicates"] += result["total"]
        totals["phase_metrics"][case] = result["metrics"]
    summary = summarize(states)
    if json.loads(safe_path(run, "summary.json").read_text()) != summary:
        raise ValueError("discovery summary differs")
    return {"integrity": "verified_against_supplied_digest" if anchor else "internal_consistency_only", **totals, **summary,
            "scope": "seeded Linux configuration assets and successful file-open probes; not native host execution, browser display or general OS confinement"}, summary["outcome_exit_code"]
