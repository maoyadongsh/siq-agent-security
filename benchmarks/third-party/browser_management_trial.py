"""Freeze and run the P06 embedded UI browser cohort, preserving failed attempts."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from browser_management import CHROME, WRAPPER, expected_checks, outcomes, run, score
from common import safe_path, sha256, utc_now, write_json
from lifecycle import Journal, process_identity, summarize
from process_resources import identity, members


def execute(path):
    p = json.loads(path.read_text())
    for name, digest in p["harness_sources"].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError("frozen browser harness differs")
    for name, digest in p["tools"].items():
        if sha256(Path(name)) != digest:
            raise ValueError("frozen browser tool differs")
    candidate = Path(p["candidate_root"])
    for name, digest in p["candidate_sources"].items():
        if sha256(safe_path(candidate, name)) != digest:
            raise ValueError("candidate fixture source differs")
    if sha256(Path(p["binary"])) != p["candidate_digest"]:
        raise ValueError("candidate binary differs")
    if os.getpgrp() != os.getpid():
        os.setsid()
    os.umask(0o077)
    out = Path(p["campaign_root"]) / "private/runs" / p["run_id"]
    journal = Journal(out, p)
    state = out / "state-private"
    state.mkdir(mode=0o700)
    spec = importlib.util.spec_from_file_location("browser_fixture", candidate / "scripts/validate-mcp-provenance.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    h = fixture.base.Harness(state, SimpleNamespace(binary=Path(p["binary"])))
    home = state / "home"
    home.mkdir(mode=0o700)
    h.env["HOME"] = str(home)
    h.env["XDG_CONFIG_HOME"] = str(home / ".config")
    h.env["XDG_DATA_HOME"] = str(home / ".local/share")
    key = "browser-session-boundary#1"
    journal.transition(key, "started", execution_status="running", process_ref=process_identity())
    error = None
    o = {}
    try:
        h.build()
        h.start()
        write_json(out / "daemon.json", {"owner": process_identity(), "daemon": identity(h.proc.pid),
                   "command_sha256": hashlib.sha256(Path(f"/proc/{h.proc.pid}/cmdline").read_bytes()).hexdigest()})
        h.setup_authority()
        o = run(h, out)
    except Exception as exc:  # noqa: BLE001 -- preserve failed browser cohorts without secret-bearing exceptions
        error = {"type": type(exc).__name__, "detail": "browser journey incomplete; inspect sanitized captures"}
        if (out / "browser-observations.json").exists():
            o = json.loads((out / "browser-observations.json").read_text())
    finally:
        h.stop()
    result = score(o)
    write_json(out / "score.json", result)
    cleanup = {"daemon_stopped": h.proc is None, "remaining_group_members": members(os.getpid(), exclude=(os.getpid(),))}
    write_json(out / "cleanup.json", cleanup)
    failed = any(v is False for v in result["checks"].values())
    complete = error is None and set(result["checks"]) == expected_checks() and not cleanup["remaining_group_members"]
    status = "fail" if failed else "pass" if complete else "inconclusive"
    harm, utility = outcomes(o, result)
    journal.transition(key, "finished", execution_status="error" if error else "completed",
                       measurement_status="determinate" if complete else "indeterminate", assertion_status=status, error=error,
                       harm_observed=bool(harm) if complete or harm else None, harm_unknown_reason=None if complete or harm else "browser_journey_incomplete",
                       harm_evidence_refs=["browser-observations.json"] if complete or harm else [],
                       utility_completed=utility,
                       utility_unknown_reason=None if "authorized_write" in o else "authorized_control_not_observed",
                       utility_evidence_refs=["browser-observations.json"] if "authorized_write" in o else [],
                       tool_executed=True, cleanup_confirmed=not cleanup["remaining_group_members"] and o.get("cleanup", {}).get("browser_closed", False),
                       oracle={"source": "browser_cdp_and_authority_file_snapshots", "healthy": complete, "coverage": "full" if complete else "partial",
                               "window_start": None, "window_end": None, "materials": ["browser-observations.json"] if o else []},
                       event_trace_refs=["cleanup.json"])
    summary = summarize(journal.states)
    with (out / "cases.jsonl").open("x") as stream:
        for row in journal.states.values():
            stream.write(json.dumps(row) + "\n")
    journal.close()
    write_json(out / "summary.json", summary)
    names = ["protocol.json", "journal.jsonl", "cases.jsonl", "summary.json", "score.json", "cleanup.json", "daemon.json"]
    names += [f.name for f in out.glob("checkpoint-*.json")]
    if (out / "browser-observations.json").exists():
        names.append("browser-observations.json")
    names += [str(f.relative_to(out)) for f in (out / "output/playwright").glob("*") if f.is_file() and f.suffix in (".txt", ".yaml", ".png")]
    write_json(out / "manifest.json", {"schema_version": "siq-management-browser-manifest/v1", "relationship": "author_run",
               "artifacts": {name: sha256(out / name) for name in names}})
    print(json.dumps({**summary, "browser_predicates": result["total"], "browser_passed": result["passed"], "manifest_sha256": sha256(out / "manifest.json")}), flush=True)
    return summary["outcome_exit_code"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.execute:
        return execute(args.execute)
    if not args.campaign or not args.run_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", args.run_id):
        raise ValueError("fresh campaign run ID required")
    campaign = args.campaign.resolve()
    old = json.loads((campaign / "protocols/management-http-003-protocol/protocol.json").read_text())
    root = campaign / "protocols" / (args.run_id + "-protocol")
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    names = [*old["harness_sources"], "browser_management.py", "browser_management_probe.js", "browser_management_trial.py"]
    for name in names:
        target = root / "harness-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    unit = {"unit_id": "browser-session-boundary", "case_id": "P06.browser-session-boundary", "pair_id": "P06-browser",
            "task_block_id": "P06-browser", "track": "B", "group": "B2", "family_id": "P06", "claim_ids": ["C6"], "product_group_ids": ["P06"]}
    p = {**old, "run_id": args.run_id, "operation": "management_browser", "allocation": [unit], "frozen_at": utc_now(),
         "expected_predicates": sorted(expected_checks()),
         "harness_sources": {name: sha256(root / "harness-source" / name) for name in names},
         "tools": {name: sha256(Path(name)) for name in (CHROME, WRAPPER)},
         "limits": {"cli_seconds": 45, "scope": "owned embedded UI and controlled loopback cross-origin pages", "chromium_sandbox": False,
                    "note": "host cannot initialize Chromium sandbox; no OS/browser sandbox isolation claim"}}
    write_json(root / "protocol.json", p)
    write_json(root / "local-anchor.json", {"sha256": sha256(root / "protocol.json")})
    response = subprocess.run([sys.executable, str(root / "harness-source/browser_management_trial.py"), "--execute", str(root / "protocol.json")],
                              capture_output=True, text=True, check=False)
    write_json(campaign / "reports" / (args.run_id + "-execution.json"), {"exit_code": response.returncode, "stdout": response.stdout, "stderr": response.stderr})
    print(response.stdout, end="")
    return response.returncode


if __name__ == "__main__":
    raise SystemExit(main())
