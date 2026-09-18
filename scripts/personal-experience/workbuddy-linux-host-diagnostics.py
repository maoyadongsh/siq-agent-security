#!/usr/bin/env python3
"""Linux WorkBuddy host diagnostics and real-host acceptance runner.

This is a public adapter diagnostic + acceptance asset for the WorkBuddy cell
of scripts/personal-experience/platform_acceptance.py. It exists because the
taskbook requires that a missing host be recorded as BLOCKED with explicit
evidence instead of being closed by "the directory exists" or by connector
fixture tests.

What it does, in order:

1. `probe` locates a real Linux WorkBuddy runtime: the connector's documented
   root (~/.workbuddy with config.yaml + buddies.json), a small set of other
   install layouts, a workbuddy/codebuddy executable on PATH or in a node
   package tree, and a running host process (read-only scan of /proc/*/comm).
   It never reads config.yaml, .env or any secret file; config.yaml is only
   ever stat'ed for presence, exactly like the connector.

2. `accept` additionally builds the repository's own WorkBuddy connector from
   connectors/workbuddy and drives it over its real NDJSON stdio protocol
   (`--serve`) against the real host root. Assertions run on the real host's
   own output: capability declaration, scope safety (positive and negative),
   candidate attribution back to the host's buddies.json, containment (an
   out-of-scope root yields nothing), absence of secret-shaped material in the
   output, and no write to the host root.

The script performs no writes to the host, reads no secret file, sends nothing
over the network, changes no proxy/DNS/hosts entry, relaxes no SSRF/TLS rule,
and never kills a process. Subprocesses are started with an argv vector; no
shell string is ever built. A missing host produces verdict "blocked" with
reason "environment_unavailable" and every check "not_run" - the cell is never
closed by this script alone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONNECTOR_DIR = REPO / "connectors" / "workbuddy"

# Mirror of connectors/workbuddy/workbuddy.go. Kept literal so the diagnostic
# reports the documented layout even when the host is absent.
ROOT_REL = ".workbuddy"
CONFIG_NAME = "config.yaml"
BUDDIES_NAME = "buddies.json"
LAYOUT_CANDIDATES = (
    "~/.workbuddy",
    "~/.config/workbuddy",
    "~/.local/share/workbuddy",
    "~/.codebuddy",
    "/opt/workbuddy",
    "/usr/local/lib/workbuddy",
)
EXECUTABLE_NAMES = ("workbuddy", "codebuddy", "workbuddy-cli")
PROCESS_NAMES = ("workbuddy", "codebuddy")
NODE_PACKAGE_NAMES = ("workbuddy", "codebuddy", "@workbuddy/cli", "@codebuddy/cli")

# Secret-shaped material that must never appear in connector output. These are
# patterns, not host values: matching them reports a redaction failure and
# never prints the matched text.
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|bearer|authorization)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)
SECRET_MATCH_LIMIT = 8

CHECK_NAMES = ("discovery", "normal_execution", "pre_execution_denial",
               "service_unavailable_denial", "approval_resume", "final_parameter_recheck",
               "skill_attribution", "install_interception")
# Only these two can be evidenced by this diagnostic against a real host; the
# rest stay "not_run" because they are daemon-side checks owned by other legs.
CHECK_SCOPE = {
    "discovery": "host buddies enumerated through the real connector protocol",
    "skill_attribution": "candidate identity traced back to the host buddies.json",
}
NOT_RUN_REASON = "not_tested"


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def probe_host(home: Path) -> dict:
    """Read-only host probing. Returns layout facts; never file contents."""
    real_home = home == Path.home().resolve()
    root = home / ROOT_REL
    layouts = []
    for candidate in LAYOUT_CANDIDATES:
        if candidate.startswith("~/"):
            path = home / candidate[2:]
            exists = path.is_dir()
        else:
            # A fixture HOME must never inherit the real machine's /opt or
            # /usr/local installations as evidence for that fixture.
            exists = real_home and Path(candidate).is_dir()
        layouts.append({"path": candidate, "exists": exists})
    root_facts = {
        "root": "~/" + ROOT_REL,
        "root_exists": root.is_dir(),
        "has_config": (root / CONFIG_NAME).is_file(),
        "has_buddies": (root / BUDDIES_NAME).is_file(),
    }
    executables = []
    for name in EXECUTABLE_NAMES:
        found = shutil.which(name) if real_home else None
        executables.append({"name": name, "found": bool(found)})
    node_packages = []
    for tree in (home / ".nvm" / "versions" / "node", home / ".hermes" / "node" / "lib" / "node_modules",
                 home / ".npm-global" / "lib" / "node_modules"):
        if not tree.is_dir():
            continue
        # nvm trees are one directory per node version; node_modules trees are not.
        bases = [tree] if tree.name == "node_modules" else [child for child in sorted(tree.iterdir())
                                                            if child.is_dir()]
        if tree.name == "node":
            bases = [child / "lib" / "node_modules" for child in bases if (child / "lib" / "node_modules").is_dir()]
        for base in bases:
            for package in NODE_PACKAGE_NAMES:
                hit = base / package
                if hit.exists():
                    node_packages.append({"path": str(hit.relative_to(home)) if home in hit.parents else str(hit)})
    processes = []
    proc = Path("/proc")
    if real_home and proc.is_dir():
        for entry in sorted(proc.iterdir()):
            if not entry.name.isdigit():
                continue
            try:
                comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if comm in PROCESS_NAMES:
                processes.append({"comm": comm})
    # Layouts that exist but are not the connector's documented integration
    # point. Reported separately so an adjacent family install (for example
    # ~/.codebuddy, which the CodeBuddy adapter owns) is never read as
    # WorkBuddy host support.
    adjacent = [item["path"] for item in layouts
                if item["exists"] and item["path"] != "~/" + ROOT_REL]
    return {
        "home": "~" if real_home else "<isolated-home>",
        "root": root_facts,
        "layouts": layouts,
        "adjacent_family_installs": adjacent,
        "executables": executables,
        "node_packages": node_packages,
        "processes": processes,
        "host_present": bool(root_facts["has_buddies"] or any(item["found"] for item in executables)
                             or processes or node_packages),
        "runtime_confirmed": bool(root_facts["root_exists"] and root_facts["has_buddies"]),
    }


class ProtocolRun:
    """NDJSON stdio driver for the real connector. argv only, no shell."""

    def __init__(self, binary: Path, env: dict):
        self.binary = binary
        self.env = env
        self.transcript: list[dict] = []
        self.process: subprocess.Popen | None = None

    def __enter__(self) -> ProtocolRun:
        self.process = subprocess.Popen(
            [str(self.binary), "--serve"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=self.env, text=True, encoding="utf-8", bufsize=1,
        )
        return self

    def call(self, op: str, params: dict | None = None) -> dict | None:
        assert self.process is not None and self.process.stdin and self.process.stdout
        request_id = f"wbdiag-{len(self.transcript) + 1}"
        payload = {"id": request_id, "op": op, "params": params if params is not None else {}}
        self.process.stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            self.transcript.append({"op": op, "transport": "closed"})
            return None
        try:
            response = json.loads(line)
        except ValueError:
            self.transcript.append({"op": op, "transport": "unparsable"})
            return None
        self.transcript.append({"op": op, "ok": response.get("ok"), "result": response.get("result"),
                               "error": response.get("error")})
        return response

    def __exit__(self, *_exc) -> None:
        if self.process is None:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)


def build_connector(out_dir: Path) -> tuple[Path | None, dict]:
    binary = out_dir / "workbuddy-connector"
    if not CONNECTOR_DIR.is_dir():
        return None, {"built": False, "detail": "connector_source_absent"}
    argv = ["go", "build", "-o", str(binary), "."]
    try:
        proc = subprocess.run(argv, cwd=str(CONNECTOR_DIR), capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, {"built": False, "detail": type(err).__name__}
    if proc.returncode != 0 or not binary.is_file():
        return None, {"built": False, "detail": "build_failed", "exit_code": proc.returncode}
    return binary, {"built": True, "sha256": sha256_file(binary), "exit_code": 0}


def iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from iter_strings(key)
            yield from iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_strings(item)


def scan_secret_shapes(value) -> list[str]:
    hits = []
    for text in iter_strings(value):
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(pattern.pattern)
                break
        if len(hits) >= SECRET_MATCH_LIMIT:
            break
    return hits


def read_buddies_names(root: Path) -> tuple[list[str], str | None]:
    """Read only buddies.json (whitelist-decoded, like the connector).

    config.yaml is deliberately never opened here either.
    """
    path = root / BUDDIES_NAME
    try:
        if path.stat().st_size > 1 << 20:
            return [], "buddies_too_large"
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], "buddies_unreadable"
    names = []
    for buddy in document.get("buddies", []) if isinstance(document, dict) else []:
        if isinstance(buddy, dict) and isinstance(buddy.get("id"), str):
            names.append(buddy["id"])
    return names, None


def directory_snapshot(root: Path) -> list[str]:
    """Names and sizes only; no file contents are read."""
    if not root.is_dir():
        return []
    snapshot = []
    for path in sorted(root.rglob("*")):
        try:
            kind = "dir" if path.is_dir() else "file"
            size = 0 if path.is_dir() else path.stat().st_size
        except OSError:
            kind, size = "unknown", 0
        snapshot.append(f"{kind}:{path.relative_to(root)}:{size}")
    return snapshot


def run_acceptance(home: Path, probe: dict, workspace: Path, forbidden: tuple[str, ...] = (),
                   method: str = "native_desktop") -> dict:
    root = home / ROOT_REL
    facts: dict = {"assertions": [], "transcript": [], "checks": {}}

    def record(name: str, ok: bool, detail: str) -> None:
        facts["assertions"].append({"name": name, "ok": ok, "detail": detail})

    if not probe["runtime_confirmed"]:
        return facts

    binary, build = build_connector(workspace)
    facts["connector_build"] = build
    if binary is None:
        record("connector_build", False, build.get("detail", "build_failed"))
        return facts
    record("connector_build", True, "built from connectors/workbuddy")

    before = directory_snapshot(root)
    host_names, buddies_error = read_buddies_names(root)
    facts["host_buddy_count"] = len(host_names)
    facts["buddies_error"] = buddies_error
    # The connector expands "~" through $HOME, so the inspected home must be handed
    # to the child explicitly. Without this, --home would be honoured by the probe
    # but silently ignored by the protocol run, which would then scan the real HOME.
    env = dict(os.environ)
    env["HOME"] = str(home)
    facts["connector_home"] = str(home)

    with ProtocolRun(binary, env) as run:
        describe = run.call("describe")
        health = run.call("health")
        # Negatives: the filesystem root and an ambiguous wildcard are both
        # refused by protocol.ValidateScopeSafety.
        bad_root = run.call("validate_scope", {"scope": {"roots": ["/"]}})
        bad_glob = run.call("validate_scope", {"scope": {"roots": ["/etc/*/x"]}})
        empty_root = run.call("validate_scope", {"scope": {"roots": ["/" + "nonexistent-wbdiag-path"]}})
        plan = run.call("plan_scan", {"scope": {"roots": ["~/" + ROOT_REL]}})
        scope_ok = run.call("validate_scope", {"scope": {"roots": ["~/" + ROOT_REL]}})
        collect = run.call("collect", {"plan": (plan or {}).get("result") or {}})
        contained = run.call("collect", {"plan": {"scope": {"roots": ["/etc"]}, "limits": {"max_files": 50}}})
        facts["transcript"] = run.transcript

    after = directory_snapshot(root)
    facts["host_root_unchanged"] = before == after

    caps = ((describe or {}).get("result") or {})
    record("describe_ok", bool(describe and describe.get("ok")), "connector capabilities returned")
    record("no_network_access", caps.get("network_access") is False, "connector declares no network access")
    record("scope_declared", bool(caps.get("required_permissions")), "required permissions declared")
    record("health_reported", bool(health and health.get("ok")), "health op answered")
    def refused(response) -> bool:
        return bool(response and response.get("ok") and not (response.get("result") or {}).get("valid"))

    record("scope_negative_rejected",
           refused(bad_root) and refused(bad_glob) and refused(empty_root),
           "filesystem root, ambiguous wildcard and non-existent root all refused")
    record("scope_positive_accepted", bool(scope_ok and (scope_ok.get("result") or {}).get("valid")),
           "host root accepted by validate_scope")

    batch = ((collect or {}).get("result") or {})
    candidates = batch.get("candidates") or []
    # candidate_id is "workbuddy:<buddy id>" and source_locator ends in
    # "#<buddy id>"; both are traced back to the host's own buddies.json.
    candidate_ids = set()
    locators = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue
        identifier = item.get("candidate_id")
        if isinstance(identifier, str) and ":" in identifier:
            candidate_ids.add(identifier.split(":", 1)[1])
        locator = item.get("source_locator")
        if isinstance(locator, str) and "#" in locator:
            locators.add(locator.rsplit("#", 1)[1])
    facts["candidate_count"] = len(candidates)
    facts["evidence_count"] = len(batch.get("evidence") or [])
    facts["candidate_ids_matched"] = sorted(candidate_ids & set(host_names))
    record("collect_ok", bool(collect and collect.get("ok")), "collect returned a batch")
    record("candidates_present", len(candidates) > 0, "host buddies surfaced as candidates")
    record("attribution_subset",
           bool(candidate_ids) and not (candidate_ids - set(host_names)),
           "every candidate id traces back to a host buddies.json entry")
    record("locator_attribution_subset",
           bool(locators) and not (locators - set(host_names)),
           "every source_locator fragment traces back to a host buddies.json entry")
    container = ((contained or {}).get("result") or {})
    record("containment_out_of_scope_empty", not (container.get("candidates") or []),
           "collect outside the host root yields nothing")
    secrets = scan_secret_shapes(batch) + scan_secret_shapes(caps) + scan_secret_shapes(facts["transcript"])
    facts["secret_pattern_hits"] = sorted(set(secrets))
    record("no_secret_shaped_output", not secrets, "no secret-shaped material in connector output")
    if forbidden:
        text = json.dumps(batch, ensure_ascii=True) + json.dumps(caps, ensure_ascii=True)
        leaked = [index for index, value in enumerate(forbidden) if value and value in text]
        facts["forbidden_literal_hits"] = len(leaked)
        record("no_forbidden_literal", not leaked, "no caller-supplied canary appeared in connector output")
    record("host_root_unchanged", facts["host_root_unchanged"], "host root listing unchanged after run")

    passed = all(item["ok"] for item in facts["assertions"])
    checks = {}
    for name in CHECK_NAMES:
        if name in CHECK_SCOPE and passed:
            checks[name] = {"status": "pass", "method": method, "reason": None, "evidence": []}
        elif name in CHECK_SCOPE:
            checks[name] = {"status": "fail", "method": method,
                            "reason": "observed_failure", "evidence": []}
        else:
            checks[name] = {"status": "not_run", "method": "none",
                            "reason": NOT_RUN_REASON, "evidence": []}
    facts["checks"] = checks
    facts["verdict"] = "pass" if passed else "fail"
    return facts


def blocked_checks(reason: str) -> dict:
    return {name: {"status": "blocked", "method": "none", "reason": reason, "evidence": []}
            for name in CHECK_NAMES}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("probe", "accept"))
    parser.add_argument("--home", type=Path, default=Path.home(),
                        help="host HOME to inspect (default: the real HOME)")
    parser.add_argument("--workspace", type=Path,
                        help="scratch dir for the connector build (default: a new temp dir)")
    parser.add_argument("--out", type=Path, help="write the report here (created O_EXCL, 0600)")
    parser.add_argument("--transcript", type=Path, help="write the raw NDJSON transcript here (0600)")
    parser.add_argument("--grade", choices=("host", "component_fixture"),
                        help="evidence grade; derived from --home when omitted, and never upgradable "
                             "to 'host' for an isolated HOME")
    parser.add_argument("--evidence-root", type=Path,
                        help="root the --evidence-ref paths are relative to")
    parser.add_argument("--evidence-ref", action="append", default=[],
                        help="evidence path (relative to --evidence-root) to attach to passed checks")
    parser.add_argument("--forbid-literal", action="append", default=[],
                        help="a literal that must never appear in connector output; the value is "
                             "never printed, only counted")
    args = parser.parse_args(argv)

    home = args.home.expanduser().resolve()
    probe = probe_host(home)
    # Evidence grade is derived from the target HOME, not from a caller flag: an
    # isolated HOME can only ever produce component-fixture evidence, and a fixture
    # run must never be readable as real-host WorkBuddy support.
    host_home = home == Path.home().resolve()
    grade = args.grade or ("host" if host_home else "component_fixture")
    if grade == "host" and not host_home:
        grade = "component_fixture"
    method = "native_desktop" if grade == "host" else "component_fixture"
    report: dict = {
        "schema_version": "workbuddy-linux-host-diagnostics/v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "platform": "workbuddy",
        "environment": {"os": "linux", "arch": os.uname().machine, "mode": "native"},
        "probe": probe,
        "evidence_grade": grade,
        "host_home": host_home,
        "acceptance_usable": grade == "host",
        "authorization": "diagnostic only; never a runtime authorization or certification",
    }
    workspace = args.workspace
    temp_created = False
    if args.mode == "accept" and workspace is None:
        import tempfile
        workspace = Path(tempfile.mkdtemp(prefix="wbdiag-"))
        temp_created = True

    try:
        if args.mode == "probe" or not probe["runtime_confirmed"]:
            reason = "environment_unavailable" if not probe["runtime_confirmed"] else NOT_RUN_REASON
            report["acceptance"] = {"assertions": [], "verdict": "blocked" if not probe["runtime_confirmed"]
                                    else "not_run", "checks": blocked_checks(reason)}
            if not probe["runtime_confirmed"]:
                report["blocked_reason"] = "environment_unavailable"
                report["blocked_detail"] = ("no real Linux WorkBuddy host: "
                                            "~/.workbuddy has no buddies.json, no executable on PATH, "
                                            "no running host process")
        else:
            report["acceptance"] = run_acceptance(home, probe, workspace, tuple(args.forbid_literal), method)
            report["status"] = report["acceptance"].get("verdict", "blocked")
        report["checks"] = report["acceptance"]["checks"]
        if args.evidence_ref:
            references = []
            for relative in args.evidence_ref:
                target = (args.evidence_root or Path.cwd()) / relative
                digest = sha256_file(target)
                if digest is not None:
                    references.append({"path": relative, "sha256": digest})
            if references and report["acceptance"].get("verdict") == "pass":
                for name, check in report["checks"].items():
                    if check["status"] == "pass":
                        check["evidence"] = references[:4]
    finally:
        if temp_created and workspace is not None and workspace.is_dir():
            shutil.rmtree(workspace, ignore_errors=True)

    text = json.dumps(report, ensure_ascii=True, indent=2) + "\n"
    if args.transcript and report["acceptance"].get("transcript"):
        descriptor = os.open(args.transcript, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            for entry in report["acceptance"]["transcript"]:
                stream.write(json.dumps(entry, ensure_ascii=True) + "\n")
    if args.out:
        descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        print(f"report={args.out}")
    else:
        sys.stdout.write(text)
    return 0 if report.get("acceptance", {}).get("verdict") != "fail" else 1


if __name__ == "__main__":
    raise SystemExit(main())
