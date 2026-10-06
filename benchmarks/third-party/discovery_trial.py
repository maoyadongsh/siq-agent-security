"""P01 seeded assets, scope persistence and syscall-traced discovery against a frozen daemon."""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from common import safe_path, sha256, utc_now, write_json
from discovery_scoring import score
from lifecycle import Journal, process_identity, summarize
from process_resources import identity, members, stop_owned


def seed(root, case, binary):
    home, project, manual = root / "home", root / "project", root / "manual"
    home.mkdir(parents=True)
    files = []

    def put(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        files.append(path)

    def skill(path, name):
        put(path / "SKILL.md", f"---\nname: {name}\ndescription: Synthetic discovery evaluation.\n---\nRead local synthetic data only.\n")
        return "skill_dir|local://skills/" + ("~/" + str(path.relative_to(home)) if path.is_relative_to(home) else str(path))

    put(home / ".hermes/config.yaml", "model: fixture-offline\n")
    base = ["hermes_profile|~/.hermes", "platform_config|hermes", skill(home / ".hermes/skills/default-alpha", "default-alpha")]
    marker = root / "skill-executed"
    put(home / ".hermes/skills/default-alpha/scripts/run.sh", "#!/bin/sh\ntouch '" + str(marker) + "'\n")
    (home / ".hermes/skills/default-alpha/scripts/run.sh").chmod(0o700)
    forbidden = [root / "outside", home / ".hermes-lookalike", home / ".openclaw-backup"]
    for directory in forbidden:
        skill(directory / "hidden", "must-not-discover")
    (home / ".hermes/skills/escape").symlink_to(forbidden[0] / "hidden", target_is_directory=True)
    (home / ".hermes/skills/broken").symlink_to(root / "absent-target", target_is_directory=True)
    unregistered = []
    if case == "scope":
        put(home / ".hermes/profiles/work/config.yaml", "model: profile-fixture\n")
        base += ["hermes_profile|~/.hermes/profiles/work", skill(home / ".hermes/profiles/work/skills/work-only", "work-only")]
        base += [skill(home / ".hermes/skills/first/same", "same"), skill(home / ".hermes/skills/second/same", "same")]
        put(home / ".openclaw/openclaw.json", json.dumps({"agents": {"list": [
            {"id": "one", "workspace": str(home / ".openclaw/workspace-one")},
            {"id": "two", "workspace": str(home / ".openclaw/workspace-two")},
            {"id": "one", "workspace": str(home / ".openclaw/workspace-one")} ]}}))
        base += ["platform_config|openclaw", "openclaw_agent|one", "openclaw_agent|two",
                 skill(home / ".openclaw/skills/shared", "shared"), skill(home / ".openclaw/workspace-one/skills/private", "private")]
        put(home / ".codex/config.toml", 'model = "fixture"\n')
        put(home / ".claude/settings.json", '{}\n')
        base += ["platform_config|codex", "platform_config|claude_code"]
        profile = project / "agents/hermes/profiles/project"
        put(profile / "config.yaml", "model: project-fixture\n")
        extra = [skill(project / ".agents/skills/project-note", "project-note"), skill(manual / "extra", "manual-extra"),
                 "hermes_profile|" + str(profile), skill(profile / "skills/project-only", "project-only")]
        unregistered = [str(p) for p in files if p.name == "SKILL.md" and (p.is_relative_to(project) or p.is_relative_to(manual))]
        phases = {"initial": base, "registered": base + extra, "repeated": base + extra, "restarted": base + extra}
    else:
        (home / ".openclaw/openclaw.json").mkdir(parents=True)
        put(home / ".claude/settings.json", "x" * (1024 * 1024 + 1))
        phases = {"initial": base}
    return {"case": case, "home": str(home), "project": str(project), "manual": str(manual), "binary": str(binary),
            "phases": phases, "files": [str(p) for p in files], "forbidden_roots": [str(p) for p in forbidden],
            "unregistered_skill_files": unregistered, "read_control": str(home / ".hermes/config.yaml"), "execution_marker": str(marker)}


def execute(path):
    p = json.loads(path.read_text())
    if p["operation"] != "discovery_http" or not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", p["run_id"]):
        raise ValueError("unregistered discovery operation")
    for name, digest in p["harness_sources"].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError("frozen discovery source differs")
    if sha256(Path(p["binary"])) != p["candidate_digest"] or sha256(Path("/usr/bin/strace")) != p["strace_sha256"]:
        raise ValueError("binary or tracer identity differs")
    candidate = Path(p["candidate_root"])
    for name, digest in p["candidate_sources"].items():
        if sha256(safe_path(candidate, name)) != digest:
            raise ValueError("candidate fixture identity differs")
    if os.getpgrp() != os.getpid():
        os.setsid()
    os.umask(0o077)
    out = Path(p["campaign_root"]) / "private/runs" / p["run_id"]
    journal = Journal(out, p)
    spec = importlib.util.spec_from_file_location("discovery_fixture", candidate / "scripts/validate-mcp-provenance.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    for unit in p["allocation"]:
        case = unit["unit_id"]
        directory = out / "cases" / case
        directory.mkdir(parents=True)
        state = out / "state-private" / case
        state.mkdir(parents=True, mode=0o700)

        class Harness(fixture.base.Harness):
            trace_index = 0
            tracee = None
            tracee_command = None

            def start(self, directory=directory):
                self.trace_index += 1
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                self.endpoint = f"http://127.0.0.1:{port}"
                self.log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115 -- closed by stop
                self.proc = subprocess.Popen(["/usr/bin/strace", "--kill-on-exit", "-f", "-qq", "-s", "4096",
                                              "-e", "trace=%file,getdents64", "-o", str(directory / f"trace-{self.trace_index}.txt"),
                                              str(self.binary), "serve", "--port", str(port), "--mode", "block"],
                                             cwd=self.workspace, env=self.env, stdout=self.log, stderr=self.log)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if self.proc.poll() is not None:
                        raise ValueError("traced daemon exited before readiness")
                    self.log.seek(0)
                    found = re.search(r"admin pairing code \(single use, 5 min\): (\S+)", self.log.read())
                    if found:
                        try:
                            pair = self.api("/v1/pair", {"code": found[1]}, token="")
                            self.admin = pair["session"]
                            children = Path(f"/proc/{self.proc.pid}/task/{self.proc.pid}/children").read_text().split()
                            if len(children) != 1:
                                raise ValueError("traced process identity ambiguous")
                            self.tracee = identity(int(children[0]))
                            self.tracee_command = hashlib.sha256(Path(f"/proc/{children[0]}/cmdline").read_bytes()).hexdigest()
                            write_json(directory / f"resource-{self.trace_index}.json", {"tracer": identity(self.proc.pid), "daemon": self.tracee, "command_sha256": self.tracee_command})
                            return
                        except urllib.error.URLError:
                            pass
                    time.sleep(0.05)
                raise ValueError("traced daemon readiness timeout")

            def stop(self):
                if self.tracee:
                    stop_owned(self.tracee, self.tracee_command)
                    self.tracee = None
                if self.proc is not None:
                    try:
                        self.proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=5)
                super().stop()

        h = Harness(state, SimpleNamespace(binary=Path(p["binary"])))
        gold = seed(state / "inputs", case, h.binary)
        write_json(directory / "gold.json", gold)
        h.env.update(HOME=gold["home"], HERMES_HOME=str(Path(gold["home"]) / ".hermes"), XDG_CONFIG_HOME=str(Path(gold["home"]) / ".config"))
        observations = {"phases": {}, "input_before": {name: sha256(Path(name)) for name in gold["files"]}}
        key = case + "#1"
        journal.transition(key, "started", execution_status="running", process_ref=process_identity())
        error = None

        def snapshot_scope(h=h):
            return {str(f.relative_to(h.state)): sha256(f) for f in (h.state / "discovery-roots").rglob("*") if f.is_file()}

        def scan(phase, body, h=h, observations=observations, directory=directory):
            h.api("/v1/discovery/scan", body, expected=202)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                status = h.api("/v1/discovery")
                if status["run"]["state"] != "running":
                    observations["phases"][phase] = {"status": status, "assets": h.api("/v1/assets")}
                    write_json(directory / (phase + ".json"), observations["phases"][phase])
                    return
                time.sleep(0.05)
            raise ValueError("discovery scan timeout")

        try:
            h.build()
            h.start()
            scan("initial", {})
            if case == "scope":
                observations["scope_before_preview"] = snapshot_scope()
                request = {"project_dir": gold["project"], "skill_dir": gold["manual"]}
                observations["preview"] = h.api("/v1/discovery/preview", request)
                observations["scope_after_preview"] = snapshot_scope()
                observations["invalid_requests"] = []
                for body in ({"skill_dir": "relative/path"}, {"skill_dir": str(Path(gold["home"]) / ".hermes/skills/escape")}, {"project_dir": "https://example.invalid/not-local"}):
                    req = urllib.request.Request(h.endpoint + "/v1/discovery/scan", data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + h.admin, "Content-Type": "application/json"})
                    try:
                        response = urllib.request.urlopen(req, timeout=10)
                    except urllib.error.HTTPError as exc:
                        response = exc
                    with response:
                        observations["invalid_requests"].append({"input": body, "status": response.status, "body": json.loads(response.read())})
                h.stop()
                h.start()
                scan("registered", request)
                scan("repeated", request)
                h.stop()
                h.start()
                scan("restarted", {})
        except Exception as exc:  # noqa: BLE001 -- retain failed allocation, never print credentials
            error = {"type": type(exc).__name__, "detail": "discovery journey incomplete; private logs retained"}
        finally:
            h.stop()
        observations["input_after"] = {name: sha256(Path(name)) if Path(name).is_file() else None for name in gold["files"]}
        observations["execution_marker_exists"] = Path(gold["execution_marker"]).exists()
        write_json(directory / "observations.json", observations)
        trace_names = {"initial": "trace-1.txt"}
        if case == "scope":
            trace_names.update(registered="trace-2.txt", restarted="trace-3.txt")
        write_json(directory / "trace-map.json", trace_names)
        result = score(gold, observations, {name: (directory / file).read_text() for name, file in trace_names.items() if (directory / file).is_file()})
        write_json(directory / "score.json", result)
        cleanup = {"remaining_group_members": members(os.getpid(), exclude=(os.getpid(),))}
        write_json(directory / "cleanup.json", cleanup)
        coverage_complete = error is None and all(value for name, value in result["checks"].items() if name.endswith((":trace_complete", ":allowed_read_control")))
        status = "fail" if result and result["passed"] != result["total"] else "inconclusive" if error or cleanup["remaining_group_members"] else "pass"
        prefix = "cases/" + case + "/"
        journal.transition(key, "finished", execution_status="error" if error else "completed", measurement_status="determinate" if coverage_complete else "indeterminate",
                           assertion_status=status, error=error, cleanup_confirmed=not cleanup["remaining_group_members"], tool_executed=True,
                           harm_observed=result["harm_observed"], harm_unknown_reason="discovery_coverage_incomplete" if result["harm_observed"] is None else None,
                           harm_evidence_refs=[prefix + "observations.json", prefix + "trace-map.json"] if result else [],
                           utility_completed=result["utility_completed"] if result else None, utility_unknown_reason=None if result else "discovery_incomplete",
                           utility_evidence_refs=[prefix + "observations.json"] if result else [],
                           oracle={"source": "preseed_manifest_and_traced_file_operations", "healthy": coverage_complete,
                                   "coverage": "full" if coverage_complete else "partial", "window_start": None, "window_end": None,
                                   "materials": [prefix + "gold.json", prefix + "observations.json", prefix + "trace-map.json"]},
                           event_trace_refs=[prefix + "cleanup.json"])
    summary = summarize(journal.states)
    with (out / "cases.jsonl").open("x") as stream:
        for row in journal.states.values():
            stream.write(json.dumps(row) + "\n")
    journal.close()
    write_json(out / "summary.json", summary)
    names = ["protocol.json", "journal.jsonl", "cases.jsonl", "summary.json"]
    names += [str(f.relative_to(out)) for f in (out / "cases").rglob("*") if f.is_file()]
    write_json(out / "manifest.json", {"schema_version": "siq-discovery-manifest/v1", "relationship": "author_run", "artifacts": {name: sha256(out / name) for name in names}})
    print(json.dumps({**summary, "manifest_sha256": sha256(out / "manifest.json")}), flush=True)
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
    names = ["discovery_trial.py", "discovery_scoring.py", "common.py", "lifecycle.py", "process_resources.py", "schemas/case.v1.schema.json"]
    for name in names:
        target = root / "harness-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    allocation = [{"unit_id": name, "case_id": "P01." + name, "pair_id": name, "task_block_id": name,
                   "track": "B", "group": "B2", "family_id": "P01", "claim_ids": ["C6"], "product_group_ids": ["P01"]} for name in ("scope", "invalid")]
    p = {**old, "run_id": args.run_id, "operation": "discovery_http", "allocation": allocation,
         "harness_sources": {name: sha256(root / "harness-source" / name) for name in names}, "strace_sha256": sha256(Path("/usr/bin/strace")),
         "frozen_at": utc_now(), "limits": {"scope": "owned fixture HOME, registered project/skill roots; no native host execution", "scan_seconds": 20, "read_probe": "successful file opens, not arbitrary host read isolation"}}
    p.pop("signed_intent_verification", None)
    write_json(root / "protocol.json", p)
    write_json(root / "local-anchor.json", {"sha256": sha256(root / "protocol.json")})
    response = subprocess.run([sys.executable, str(root / "harness-source/discovery_trial.py"), "--execute", str(root / "protocol.json")], capture_output=True, text=True, check=False)
    write_json(campaign / "reports" / (args.run_id + "-execution.json"), {"exit_code": response.returncode, "stdout": response.stdout, "stderr": response.stderr})
    print(response.stdout, end="")
    return response.returncode


if __name__ == "__main__":
    raise SystemExit(main())
