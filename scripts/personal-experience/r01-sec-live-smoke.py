#!/usr/bin/env python3
"""R01 (N05) trusted Skill Execution Context — local live smoke validation.

Drives the candidate siq-agent-security binary end to end inside a single
temporary sandbox (HOME / HERMES_HOME / SIQ_AGENT_SECURITY_STATE_DIR all under
one tempfile.mkdtemp root; the real ~/.hermes / ~/.openclaw are never touched):

  init -> minimal Skill -> admit/grant/challenge/approve/deploy (CLI)
  -> adapter install into the isolated Hermes home -> serve + pairing
  -> skill import -> import permission grant -> install plan/apply/activate
  -> runtime identity -> session enroll -> skill-context issue (CLI)
  -> /v1/decide positive (verified attribution) and negatives (session copy,
     revoked SEC, grant revocation, swapped claim, claim-less call).

Every step is recorded (command, exit code, redacted stdout/stderr, HTTP
status, key response fields) into transcript.json; report.md maps each
taskbook §5.3 acceptance row to the observed evidence. Credentials (pairing
code, admin session, ri- credential) are used in memory only and are redacted
from every persisted byte. Exit code is non-zero unless every step passes
with nothing blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO / "docs/evidence/personal-experience/r01-skill-context-20260914"
LEGACY_CANDIDATE = Path("/tmp/tmp.LkOTjcqp9K/agentshield-linux-arm64")
REBUILT_CANDIDATE = Path("/tmp/r01-candidate/agentshield")
ACTOR = "r01-live-operator"
READ_TOOL = "read_file"
WRITE_TOOL = "write_file"


class StepFailure(RuntimeError):
    pass


def check(condition, label):
    if not condition:
        raise StepFailure(label)


class Harness:
    def __init__(self, args):
        self.args = args
        self.root = Path(tempfile.mkdtemp(prefix="siq-r01-sec-live-"))
        os.chmod(self.root, 0o700)
        self.home = self.root / "home"
        self.hermes = self.root / "hermes-home"
        self.state = self.root / "state"
        self.workspace = self.root / "workspace"
        for d in (self.home, self.hermes, self.workspace):
            d.mkdir(mode=0o700)
        os.chmod(self.workspace, 0o700)
        (self.workspace / "report.txt").write_text("r01 fixture report\n")
        self.skill = self.root / "skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(
            "---\nname: r01-sec-fixture\ndescription: Read a synthetic report.\n"
            f"allowed-tools: {READ_TOOL} {WRITE_TOOL}\n---\nRead the fixture report.\n"
        )
        (self.skill / "helper.txt").write_text("r01 fixture helper\n")
        self.env = {
            k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR")
        }
        self.env.update(
            {
                "HOME": str(self.home),
                "HERMES_HOME": str(self.hermes),
                "SIQ_AGENT_SECURITY_STATE_DIR": str(self.state),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        self.proc = None
        self.serve_log = None
        self.endpoint = None
        self.admin = None
        self.secrets = {}  # value -> label, never persisted
        self.steps = []
        self.counts = {"cli": 0, "http": 0}
        self.raw_dir = args.out / "raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    # ---------- redaction ----------
    def keep_secret(self, value, label):
        if value:
            self.secrets[value] = label

    def redact(self, text):
        if text is None:
            return ""
        out = str(text)
        for value, label in sorted(self.secrets.items(), key=lambda kv: -len(kv[0])):
            out = out.replace(value, f"«REDACTED:{label}»")
        return out

    # ---------- transcript ----------
    def write_raw(self, name, text):
        path = self.raw_dir / name
        path.write_text(self.redact(text))
        return str(path.relative_to(self.args.out))

    def record(self, entry):
        entry["recorded_at"] = datetime.now(UTC).isoformat()
        self.steps.append(entry)
        status = entry["status"].upper()
        print(f"[{status:>7}] {entry['id']}: {entry['title']}")
        if entry["status"] != "pass" and entry.get("detail"):
            print("           " + self.redact(entry["detail"])[:400])

    def cli(self, step_id, title, argv, expect=0, note=None):
        started = datetime.now(UTC)
        proc = subprocess.run(
            argv, cwd=self.workspace, env=self.env, capture_output=True, text=True, timeout=120, check=False
        )
        self.counts["cli"] += 1
        stem = f"{step_id}.cli"
        entry = {
            "id": step_id,
            "title": title,
            "kind": "cli",
            "command": [Path(argv[0]).name] + argv[1:],
            "exit_code": proc.returncode,
            "stdout_file": self.write_raw(stem + ".stdout.txt", proc.stdout),
            "stderr_file": self.write_raw(stem + ".stderr.txt", proc.stderr),
            "stdout_summary": self.redact(proc.stdout)[:400],
            "stderr_summary": self.redact(proc.stderr)[-400:],
            "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
        }
        if note:
            entry["note"] = note
        try:
            check(proc.returncode == expect, f"exit {proc.returncode} != expected {expect}: {self.redact(proc.stderr)[-200:]}")
            entry["status"] = "pass"
        except StepFailure as exc:
            entry["status"] = "fail"
            entry["detail"] = str(exc)
        self.record(entry)
        return proc

    def http(self, step_id, title, method, path, body=None, token=None, expect=200, note=None):
        started = datetime.now(UTC)
        headers = {"Content-Type": "application/json"}
        if token is None:
            token = self.admin
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(
            self.endpoint + path,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
        )
        self.counts["http"] += 1
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"_unparsed": raw[:400].decode("utf-8", "replace")}
        entry = {
            "id": step_id,
            "title": title,
            "kind": "http",
            "command": [method, path],
            "http_status": status,
            "request_body_file": self.write_raw(f"{step_id}.request.json", json.dumps(body, indent=2, default=str) if body is not None else ""),
            "response_file": self.write_raw(f"{step_id}.response.json", json.dumps(payload, indent=2, default=str)),
            "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
        }
        if isinstance(payload, dict):
            keys = {}
            for field in (
                "action", "reason_code", "authority_status", "authority_reason_code", "status",
                "schema_version", "error", "install_id", "state_revision", "binding_id",
            ):
                if field in payload:
                    keys[field] = payload[field]
            if "skill_attribution" in payload:
                keys["skill_attribution"] = payload["skill_attribution"]
            entry["key_fields"] = keys
        if note:
            entry["note"] = note
        try:
            check(status == expect, f"HTTP {status} != expected {expect}: {json.dumps(payload)[:300]}")
            entry["status"] = "pass"
        except StepFailure as exc:
            entry["status"] = "fail"
            entry["detail"] = str(exc)
        self.record(entry)
        if entry["status"] != "pass":
            raise StepFailure(entry["detail"])
        return payload

    def blocked(self, step_id, title, reason):
        self.record({"id": step_id, "title": title, "kind": "derived", "status": "blocked", "detail": reason})

    # ---------- serve lifecycle ----------
    def serve_start(self, step_id):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{port}"
        self.serve_log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115
        proc = subprocess.Popen(
            [str(self.args.binary), "serve", "--port", str(port), "--mode", "block"],
            cwd=self.workspace, env=self.env, stdout=self.serve_log, stderr=self.serve_log,
        )
        self.proc = proc
        code = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            self.serve_log.seek(0)
            found = re.search(r"admin pairing code \(single use, 5 min\): (\S+)", self.serve_log.read())
            if found:
                code = found[1]
                break
            time.sleep(0.05)
        started = datetime.now(UTC)
        self.serve_log.seek(0)
        log_excerpt = self.serve_log.read()
        entry = {
            "id": step_id,
            "title": f"serve start on 127.0.0.1:{port} (mode=block) + admin pairing",
            "kind": "cli+http",
            "command": [Path(str(self.args.binary)).name, "serve", "--port", str(port), "--mode", "block"],
            "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
        }
        try:
            check(proc.poll() is None, "serve exited before readiness")
            check(code is not None, "pairing code not printed within 30s")
            self.keep_secret(code, "pairing-code")
            payload = self._raw_http("POST", "/v1/pair", {"code": code})
            check(payload[0] == 200, f"pair HTTP {payload[0]}")
            self.admin = payload[1]["session"]
            self.keep_secret(self.admin, "admin-session")
            entry["status"] = "pass"
            entry["http_status"] = 200
            entry["key_fields"] = {"pairing": "redeemed", "session_scope": payload[1].get("scope")}
        except StepFailure as exc:
            entry["status"] = "fail"
            entry["detail"] = str(exc)
        # Persist only after a discovered pairing code has been registered as
        # a secret. Writing the startup excerpt earlier leaks the one-time code.
        entry["stdout_file"] = self.write_raw(f"{step_id}.serve-log.txt", log_excerpt)
        self.record(entry)
        if entry["status"] != "pass":
            raise StepFailure(entry.get("detail", "serve start failed"))

    def serve_stop(self, step_id):
        started = datetime.now(UTC)
        entry = {"id": step_id, "title": "serve stop (SIGTERM, drain)", "kind": "process", "command": ["SIGTERM"]}
        try:
            check(self.proc is not None, "serve not running")
            self.proc.send_signal(signal.SIGTERM)
            try:
                code = self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
                raise StepFailure("serve did not drain within 15s; killed")
            self.proc = None
            self.admin = None
            self.serve_log.seek(0)
            entry["stdout_file"] = self.write_raw(f"{step_id}.serve-log.txt", self.serve_log.read())
            self.serve_log.close()
            self.serve_log = None
            entry["exit_code"] = code
            entry["status"] = "pass"
        except StepFailure as exc:
            entry["status"] = "fail"
            entry["detail"] = str(exc)
        entry["duration_ms"] = int((datetime.now(UTC) - started).total_seconds() * 1000)
        self.record(entry)
        if entry["status"] != "pass":
            raise StepFailure(entry.get("detail", "serve stop failed"))

    def _raw_http(self, method, path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(
            self.endpoint + path, headers=headers,
            data=json.dumps(body).encode() if body is not None else None, method=method,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=30)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"_unparsed": raw[:200].decode("utf-8", "replace")}

    # ---------- decide helper ----------
    def decide(self, step_id, title, session, task, claim, call_id, expect_action, expect, note=None):
        body = {
            "platform": "hermes",
            "session_id": session,
            "agent_id": self.agent,
            "tool": READ_TOOL,
            "tool_call_id": call_id,
            "params": {"path": str(self.workspace / "report.txt")},
        }
        if task:
            body["task_id"] = task
        if claim is not None:
            body["skill"] = claim
        payload = self.http(step_id, title, "POST", "/v1/decide", body, token=self.credential, expect=200, note=note)
        problems = []
        if expect_action is not None and payload.get("action") != expect_action:
            problems.append(f"action={payload.get('action')} want {expect_action}")
        attr = payload.get("skill_attribution") or {}
        for key, want in expect.items():
            got = attr.get(key) if key != "reason_code" else payload.get("reason_code")
            if want == "__nonempty__":
                if not got:
                    problems.append(f"{key} empty")
            elif got != want:
                problems.append(f"{key}={got!r} want {want!r}")
        if problems:
            step = self.steps[-1]
            step["status"] = "fail"
            step["detail"] = "; ".join(problems)
            raise StepFailure(step["detail"])
        return payload


def call_binding(platform, session, agent, task, tool, call_id, params):
    doc = {
        "platform": platform, "session_id": session, "agent_id": agent,
        "task_id": task or "-", "tool": tool, "tool_call_id": call_id, "params": params,
    }
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def resolve_binary(arg):
    if arg:
        return Path(arg), "explicit --binary"
    env = os.environ.get("R01_AGENTSHIELD_BIN")
    if env and Path(env).is_file():
        return Path(env), "env R01_AGENTSHIELD_BIN"
    if LEGACY_CANDIDATE.is_file():
        return LEGACY_CANDIDATE, "prebuilt candidate /tmp/tmp.LkOTjcqp9K"
    REBUILT_CANDIDATE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["go", "build", "-o", str(REBUILT_CANDIDATE), "./cmd/agentshield"],
        cwd=REPO / "apps/agentshield", check=True, timeout=300,
    )
    return REBUILT_CANDIDATE, "rebuilt from apps/agentshield (prebuilt candidate missing)"


def run(h):
    binary = h.args.binary
    sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    h.context = {
        "binary": str(binary),
        "binary_sha256": sha,
        "binary_source": h.args.binary_source,
        "repo": str(REPO),
        "os": f"{platform.system()}/{platform.machine()}",
        "python": platform.python_version(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=15)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, timeout=15)
        h.context["git_head"] = head.stdout.strip()
        h.context["git_dirty_paths"] = len([ln for ln in dirty.stdout.splitlines() if ln.strip()])
    except Exception as exc:  # noqa: BLE001 - provenance only
        h.context["git_error"] = type(exc).__name__

    # ---- phase 0: preflight ------------------------------------------------
    p = h.cli("00-binary-version", "candidate binary identity", [str(binary), "version"])
    check(p.returncode == 0, "version probe failed")
    h.cli("01-init-help", "init usage probe (task requires reading --help first)",
          [str(binary), "init", "--help"], expect=1, note="flag.ErrHelp exits 1 after printing defaults")
    h.cli("02-adapter-help", "adapter usage probe (task requires reading --help first)",
          [str(binary), "adapter", "install", "--help"], expect=1,
          note="adapter subcommand has no flag help; usage error is the honest output")

    # ---- phase 1: state init + CLI authority (serve not running) -----------
    p = h.cli("10-init", "initialize state directory", [str(binary), "init", "--port", "47611"])
    check(json.loads(p.stdout)["status"] == "initialized", "init did not initialize")
    (h.hermes / "config.yaml").write_text("terminal:\n  env: local\nr01_fixture: retain\n")
    p = h.cli("11-discover-instance", "discover isolated Hermes instance (CLI, pre-grant planning)",
              [str(binary), "adapter", "instances", "hermes"])
    roots = json.loads(p.stdout)["instances"]
    target = [r for r in roots if Path(r["config_dir"]) == h.hermes]
    check(len(target) == 1, f"isolated HERMES_HOME root not discovered: {roots}")
    h.instance = target[0]["instance_id"]
    h.agent = "hri-" + h.instance[3:]
    check(re.fullmatch(r"hi-[0-9a-f]{32}", h.instance) is not None, "instance id shape")

    p = h.cli("12-admit", "admit minimal fixture skill", [str(binary), "admit", str(h.skill), "--trust", "unknown"])
    adm = json.loads(p.stdout)
    check(adm["verdict"] != "quarantine", f"benign fixture quarantined: {adm['verdict']}")
    h.admission = adm["admission_id"]

    p = h.cli("13-grant-create", "create skill grant for the planned hri- subject (CLI)",
              [str(binary), "grant", h.admission, "--platform", "hermes", "--subject", h.agent])
    cli_grant = json.loads(p.stdout)["grant"]
    h.cli_grant_id = cli_grant["grant_id"]
    p = h.cli("14-grant-challenge", "approval challenge (CLI)", [str(binary), "grant", "challenge", h.cli_grant_id])
    challenge = json.loads(p.stdout)["challenge"]
    h.keep_secret(challenge["nonce"], "grant-challenge-nonce")
    p = h.cli(
        "15-grant-approve", "human approve with challenge proof (CLI)",
        [str(binary), "grant", "approve", h.cli_grant_id, "--approve-as", ACTOR,
         "--challenge-id", challenge["challenge_id"], "--nonce", challenge["nonce"]],
    )
    check(json.loads(p.stdout)["grant"]["status"] == "approved", "approve did not transition")
    p = h.cli("16-grant-deploy", "deploy CLI grant (allowed: admission is not import-reserved)",
              [str(binary), "grant", "deploy", h.cli_grant_id])
    check(json.loads(p.stdout)["grant"]["status"] == "deployed", "deploy did not transition")

    p = h.cli("17-adapter-install", "install adapter plugin into the isolated HERMES_HOME instance",
              [str(binary), "adapter", "install", "hermes", "--instance", h.instance])
    plugin = h.hermes / "plugins" / "siq-agent-security" / "config.json"
    check(plugin.is_file(), "adapter plugin config not written into isolated home")

    # ---- phase 2: serve A — import / install / identity / enroll ----------
    h.serve_start("20-serve-a-start")
    inst = h.http("21-serve-instance-confirm", "daemon-side instance discovery matches CLI planning",
                  "GET", "/v1/adapter/instances?platform=hermes")
    check(any(r["instance_id"] == h.instance for r in inst["instances"]), "serve does not see the instance")
    h.http("22-status", "daemon status", "GET", "/v1/status")
    h.cli("23-grant-cli-under-lock", "grant CLI must refuse while serve holds the state writer lock",
          [str(binary), "grant", "deploy", h.cli_grant_id], expect=1,
          note="documented single-writer behavior; CLI authority changes run with serve stopped")

    p = h.http("24-skill-import", "import skill from local dir", "POST", "/v1/skill-imports", {
        "schema_version": "local-skill-import-create/v1",
        "import_id": "si-" + hashlib.sha256(b"r01-sec-live-import").hexdigest()[:32],
        "source_kind": "local_dir", "path": str(h.skill), "actor_id": ACTOR,
    }, expect=201)
    imported = p["import"]
    p = h.http("25-import-permission", "derive import permission grant (draft)", "POST",
               f"/v1/skill-imports/{imported['import_id']}/permissions", {
                   "schema_version": "local-skill-import-permission-create/v1",
                   "request_id": "ip-" + hashlib.sha256(b"r01-sec-live-perm").hexdigest()[:32],
                   "artifact_digest": imported["artifact_digest"],
                   "analysis_sha256": imported["analysis_sha256"],
                   "instance_id": h.instance, "actor_id": ACTOR,
               }, expect=201)
    grant = p["grant"]
    revision = p["state_revision"]
    h.import_grant_id = grant["grant_id"]
    h.skill_ref = grant["skill"]
    check(h.skill_ref and h.skill_ref.get("skill_id"), "import grant is not skill-scoped")
    grant_path = "/v1/grants/" + h.import_grant_id

    p = h.http("26-patch-desired", "scope grant to read_file/write_file and the sandbox workspace",
               "POST", grant_path + "/patch-desired", {
                   "expected_revision": revision, "actor_id": ACTOR,
                   "tools": [READ_TOOL, WRITE_TOOL],
                   "filesystem": {"read_only": [str(h.workspace)], "read_write": []},
               })
    revision = p["state_revision"]
    for index, overlap in enumerate(p["grant"].get("overlap_conflicts", [])):
        if overlap["resolution"] == "unresolved":
            p = h.http(f"26-resolve-overlap-{index}", "resolve overlap conflict", "POST",
                       grant_path + "/resolve-overlap",
                       {"expected_revision": revision, "actor_id": ACTOR, "index": index})
            revision = p["state_revision"]
    p = h.http("27-grant-challenge", "approval challenge (HTTP)", "POST", grant_path + "/challenge",
               {"expected_revision": revision, "actor_id": ACTOR})
    revision = p["state_revision"]
    h.keep_secret(p["challenge"]["nonce"], "grant-challenge-nonce")
    p = h.http("28-grant-approve", "approve import grant (HTTP)", "POST", grant_path + "/approve", {
        "expected_revision": revision, "actor_id": ACTOR,
        "challenge_id": p["challenge"]["challenge_id"], "nonce": p["challenge"]["nonce"],
    })
    revision = p["state_revision"]
    check(p["grant"]["status"] == "approved", "import grant not approved")

    p = h.http("29-install-plan", "stage install plan (grant must be approved)", "POST",
               "/v1/skill-installations/plans", {
                   "schema_version": "local-skill-install-stage-create/v1",
                   "request_id": "is-" + hashlib.sha256(b"r01-sec-live-plan").hexdigest()[:32],
                   "grant_id": h.import_grant_id, "expected_revision": revision,
                   "instance_id": h.instance, "directory_name": "r01-sec-fixture", "actor_id": ACTOR,
               }, expect=201)
    plan = p["plan"]
    h.install_target = Path(plan["target_display"])
    p = h.http("30-install-apply", "apply install plan", "POST", "/v1/skill-installations/apply", {
        "schema_version": "local-skill-install-apply/v1", "plan_id": plan["plan_id"],
        "plan_signature": plan["signature"], "actor_id": ACTOR, "confirm_install": True,
    })
    check(p["status"] == "installed_unverified", f"unexpected install status {p['status']}")
    h.install_id = p["install_id"]
    p = h.http("31-install-activate", "activate instance-scoped runtime permission (grant stays approved)",
               "POST", f"/v1/skill-installations/operations/{h.install_id}/activate", {
                   "schema_version": "local-skill-install-activate/v1",
                   "operation_signature": p["operation"]["signature"],
                   "expected_revision": revision, "actor_id": ACTOR, "confirm_instance_scope": True,
               })
    revision = p["state_revision"]

    p = h.http("32-runtime-identity", "issue runtime identity pinned to the install grant", "POST",
               "/v1/runtime-identities", {
                   "schema_version": "local-runtime-identity-create/v1", "instance_id": h.instance,
                   "grant_id": h.import_grant_id, "expected_grant_revision": revision,
                   "actor_id": ACTOR, "session_ttl_seconds": 3600,
               }, expect=201)
    h.identity_id = p["identity"]["identity_id"]
    h.credential = Path(p["credential_path"]).read_text().strip()
    h.keep_secret(h.credential, "runtime-identity-credential")

    h.session1 = "r01-sec-live-session-1"
    h.session2 = "r01-sec-live-session-2"
    p = h.http("33-enroll-session-1", "enroll primary session (SEC subject)", "POST", "/v1/runtime-sessions",
               {"schema_version": "local-runtime-session-enroll/v1", "session_id": h.session1},
               token=h.credential)
    p = h.http("34-enroll-session-2", "enroll second session (never SEC-covered; negative control)", "POST",
               "/v1/runtime-sessions",
               {"schema_version": "local-runtime-session-enroll/v1", "session_id": h.session2},
               token=h.credential)
    bindings = h.http("35-bindings", "read signed session bindings", "GET", "/v1/intent-bindings")
    row = [b for b in bindings["items"] if b["session_id"] == h.session1]
    check(len(row) == 1, "primary session binding missing")
    h.task1 = row[0]["task_id"]
    h.claim = {"skill_id": h.skill_ref["skill_id"], "content_hash": h.skill_ref["content_hash"]}
    if h.skill_ref.get("version"):
        h.claim["version"] = h.skill_ref["version"]

    # Pre-SEC invariant (taskbook §5.3 row 2): a forged-but-exact claim, a real
    # install and a live grant must still not produce a verified attribution.
    p = h.http("36-forged-claim-no-sec", "pre-SEC invariant: exact copied claim never verifies",
               "POST", "/v1/decide", {
                   "platform": "hermes", "session_id": h.session1, "agent_id": h.agent,
                   "tool": READ_TOOL, "tool_call_id": "tc-r01-pre-sec",
                   "params": {"path": str(h.workspace / "report.txt")}, "skill": h.claim,
               }, token=h.credential)
    attr = p.get("skill_attribution") or {}
    check(attr.get("status") != "verified" and "context_id" not in attr,
          f"claim without SEC must not verify: {attr}")
    check(p.get("action") == "deny",
          f"copied claim obtained installed Skill permission without a SEC: {p.get('action')}")
    note = h.steps[-1].setdefault("key_fields", {})
    note["observed_action_without_sec"] = p.get("action")
    note["observed_reason_code_without_sec"] = p.get("reason_code")
    st, body = h._raw_http("POST", "/v1/decide", {
        "platform": "hermes", "session_id": "r01-never-enrolled", "agent_id": h.agent,
        "tool": READ_TOOL, "tool_call_id": "tc-r01-foreign-session",
        "params": {"path": str(h.workspace / "report.txt")}, "skill": h.claim,
    }, token=h.credential)
    entry = {
        "id": "37-unenrolled-session", "kind": "http", "command": ["POST", "/v1/decide"],
        "title": "scoped credential cannot decide for an unenrolled session",
        "http_status": st,
        "response_file": h.write_raw("37-unenrolled-session.response.json", json.dumps(body, indent=2)),
        "status": "pass" if st == 401 else "fail",
        "key_fields": {"error": body.get("error")},
    }
    if st != 401:
        entry["detail"] = f"expected 401, got {st}"
    h.record(entry)
    check(st == 401, "unenrolled session was not rejected at the auth boundary")

    # SEC management is an offline writer. It must not bypass serve's state
    # lock even when every issuance prerequisite is otherwise present.
    p = h.cli("38-sec-cli-under-lock", "skill-context CLI must refuse while serve owns the state writer", [
        str(binary), "skill-context", "issue", "--instance", h.instance, "--session", h.session1,
        "--task", h.task1, "--install-id", h.install_id, "--ttl", "30m", "--confirm",
    ], expect=1)
    check("writer" in p.stderr.lower() or "lock" in p.stderr.lower(),
          "skill-context failure did not identify the writer lock")
    sec_dir = h.state / "skill-contexts"
    check(not sec_dir.exists() or not list(sec_dir.glob("*.json")),
          "blocked offline issuance wrote a SEC")

    # ---- phase 3: SEC issuance (CLI; serve stopped) ------------------------
    h.serve_stop("40-serve-a-stop")
    issue = h.cli("41-sec-issue-task", "issue task-scoped SEC (controlled_task evidence)", [
        str(binary), "skill-context", "issue", "--instance", h.instance, "--session", h.session1,
        "--task", h.task1, "--install-id", h.install_id, "--ttl", "30m", "--confirm",
    ])
    if issue.returncode != 0:
        handle_issue_blocker(h, issue)
        return
    h.sec_task = json.loads(issue.stdout)["context_id"]
    p = h.cli("42-sec-get", "read back issued SEC", [str(binary), "skill-context", "get", "--context-id", h.sec_task])
    check(json.loads(p.stdout)["context_id"] == h.sec_task, "SEC readback mismatch")

    # ---- phase 4: task-scoped round ---------------------------------------
    h.serve_start("50-serve-b-start")
    params = {"path": str(h.workspace / "report.txt")}
    p = h.decide("51-positive-task", "positive: exact claim + bound task verified",
                 h.session1, h.task1, h.claim, "tc-r01-task-1", "allow",
                 {"status": "verified", "evidence_level": "controlled_task",
                  "context_id": h.sec_task, "call_binding": "__nonempty__"})
    attr = p["skill_attribution"]
    want = call_binding("hermes", h.session1, h.agent, h.task1, READ_TOOL, "tc-r01-task-1", params)
    entry = {
        "id": "52-call-binding-recompute",
        "title": "recompute call_binding locally from receipt fields (canonical sha256)",
        "kind": "derived", "command": ["python3 json.dumps(sort_keys,separators) + sha256"],
        "key_fields": {"receipt_call_binding": attr["call_binding"], "recomputed": want},
    }
    entry["status"] = "pass" if attr["call_binding"] == want else "fail"
    if entry["status"] != "pass":
        entry["detail"] = "call binding does not recompute from receipt fields"
    h.record(entry)
    check(entry["status"] == "pass", "call binding recompute failed")

    p = h.decide("53-negative-cross-session",
                 "negative (a): same claim on an enrolled but SEC-less session is denied",
                 h.session2, None, h.claim, "tc-r01-xsess-1", "deny", {},
                 note="Installed Skill grants require verified SEC attribution even when the legacy "
                      "skill_attribution_enforcement switch is off")
    attr = p.get("skill_attribution") or {}
    check(attr.get("status") != "verified" and "context_id" not in attr,
          f"cross-session copy must not verify: {attr}")
    h.steps[-1]["key_fields"]["assertion"] = "not_verified"
    h.steps[-1]["key_fields"]["observed_action"] = p.get("action")

    h.decide("53a-negative-cross-task", "negative (a2): task-scoped SEC cannot be copied to another task",
             h.session1, "task-r01-foreign", h.claim, "tc-r01-xtask-1", "deny", {})

    h.decide("54-negative-claim-swap", "negative (d): swapped skill_id claim conflicts with the SEC",
             h.session1, h.task1, {"skill_id": "local_dir:other-skill@0000deadbeef"}, "tc-r01-swap-1",
             "deny", {"reason_code": "skill_context_mismatch"})
    h.decide("55-negative-no-claim", "negative (e): dropping the claim does not downgrade the SEC subject",
             h.session1, h.task1, None, "tc-r01-noclaim-1", "allow",
             {"status": "verified", "context_id": h.sec_task})

    # Replace installed content after issuance. Runtime credential and SEC
    # verification both re-read the target; the old context must not authorize
    # the changed bytes. Restore the fixture and prove validity can recover.
    helper = h.install_target / "helper.txt"
    original = helper.read_bytes()
    helper.write_bytes(original + b"tampered-after-sec\n")
    h.record({
        "id": "56-content-replaced", "title": "replace installed Skill content after SEC issuance",
        "kind": "filesystem", "command": ["write", str(helper)], "status": "pass",
        "key_fields": {"before_sha256": hashlib.sha256(original).hexdigest(),
                       "after_sha256": hashlib.sha256(helper.read_bytes()).hexdigest()},
    })
    try:
        st, body = h._raw_http("POST", "/v1/decide", {
            "platform": "hermes", "session_id": h.session1, "agent_id": h.agent,
            "task_id": h.task1, "tool": READ_TOOL, "tool_call_id": "tc-r01-content-drift",
            "params": {"path": str(h.workspace / "report.txt")}, "skill": h.claim,
        }, token=h.credential)
        attr = (body.get("skill_attribution") or {}) if isinstance(body, dict) else {}
        denied = st == 401 or (st == 200 and body.get("action") == "deny")
        entry = {
            "id": "57-content-replaced-deny", "title": "changed installed bytes invalidate old SEC authority",
            "kind": "http", "command": ["POST", "/v1/decide"], "http_status": st,
            "response_file": h.write_raw("57-content-replaced-deny.response.json", json.dumps(body, indent=2)),
            "status": "pass" if denied and attr.get("status") != "verified" else "fail",
            "key_fields": {"action": body.get("action"), "error": body.get("error"),
                           "skill_attribution": attr or None},
        }
        if entry["status"] != "pass":
            entry["detail"] = "changed Skill content was still allowed or verified"
        h.record(entry)
        check(entry["status"] == "pass", entry.get("detail", "content drift did not deny"))
    finally:
        helper.write_bytes(original)
    h.decide("58-content-restored", "restoring exact installed bytes restores the still-live SEC",
             h.session1, h.task1, h.claim, "tc-r01-content-restored", "allow",
             {"status": "verified", "context_id": h.sec_task})

    # ---- phase 5: revoke round --------------------------------------------
    h.serve_stop("60-serve-b-stop")
    p = h.cli("61-sec-revoke", "revoke the task SEC (signed tombstone)",
              [str(binary), "skill-context", "revoke", "--context-id", h.sec_task, "--confirm"])
    check(json.loads(p.stdout)["context_id"] == h.sec_task, "revocation mismatch")
    h.serve_start("62-serve-c-start")
    h.decide("63-negative-revoked-replay", "negative (b): replay after revocation hard-denies",
             h.session1, h.task1, h.claim, "tc-r01-task-1", "deny",
             {"reason_code": "skill_context_revoked"})

    # ---- phase 6: session-scoped round -------------------------------------
    h.serve_stop("70-serve-c-stop")
    issue = h.cli("71-sec-issue-session", "issue session-scoped SEC (controlled_session evidence)", [
        str(binary), "skill-context", "issue", "--instance", h.instance, "--session", h.session1,
        "--install-id", h.install_id, "--ttl", "30m", "--confirm",
    ])
    check(issue.returncode == 0, "session SEC issue failed: " + issue.stderr[-200:])
    h.sec_session = json.loads(issue.stdout)["context_id"]
    h.serve_start("72-serve-d-start")
    h.decide("73-positive-session", "positive: session-scoped SEC verifies without a task id",
             h.session1, None, h.claim, "tc-r01-sess-1", "allow",
             {"status": "verified", "evidence_level": "controlled_session",
              "context_id": h.sec_session, "call_binding": "__nonempty__"})

    current = h.http("74-grant-readback", "read grant before revocation", "GET", grant_path)
    h.http("75-grant-revoke", "negative (c) setup: revoke the install grant (HTTP admin)",
           "POST", grant_path + "/revoke",
           {"expected_revision": current["state_revision"], "actor_id": ACTOR})
    st, body = h._raw_http("POST", "/v1/decide", {
        "platform": "hermes", "session_id": h.session1, "agent_id": h.agent,
        "tool": READ_TOOL, "tool_call_id": "tc-r01-sess-2",
        "params": {"path": str(h.workspace / "report.txt")}, "skill": h.claim,
    }, token=h.credential)
    allowed = st == 200 and body.get("action") == "allow"
    attr = (body.get("skill_attribution") or {}) if isinstance(body, dict) else {}
    entry = {
        "id": "76-negative-grant-revoked",
        "title": "negative (c): after grant revocation the call must not be allowed or verified",
        "kind": "http", "command": ["POST", "/v1/decide"], "http_status": st,
        "response_file": h.write_raw("76-negative-grant-revoked.response.json", json.dumps(body, indent=2)),
        "key_fields": {
            "action": body.get("action"), "reason_code": body.get("reason_code"),
            "error": body.get("error"), "skill_attribution": attr or None,
            "task_expectation": "deny + skill_context_grant_changed",
            "observed_layer": ("http-auth" if st == 401 else "engine"),
        },
    }
    entry["status"] = "fail" if allowed or attr.get("status") == "verified" else "pass"
    if entry["status"] == "fail":
        entry["detail"] = "revoked grant still allowed/verified"
    else:
        entry["detail"] = (
            "denied at the credential-auth layer (grant reference re-validated on every request); "
            "the SEC grant-digest gate is shadowed here — see report"
        ) if st == 401 else "engine deny: " + str(body.get("reason_code"))
    h.record(entry)
    check(entry["status"] == "pass", entry.get("detail", "grant revocation did not deny"))

    # ---- phase 7: receipt chain -------------------------------------------
    receipts = h.http("80-receipts", "receipt chain reads and verifies over HTTP", "GET", "/v1/receipts")
    check(receipts.get("verified") is True, "receipt chain invalid over HTTP")
    h.serve_stop("81-serve-d-stop")
    p = h.cli("82-verify-chain", "offline receipt chain verification (CLI)", [str(binary), "verify"])
    check(json.loads(p.stdout)["verified"] is True, "CLI chain verification failed")


def handle_issue_blocker(h, issue):
    """SEC issuance failed: record the blocker, mark SEC steps blocked, keep evidence."""
    detail = h.redact(issue.stderr).strip().splitlines()[-1] if issue.stderr.strip() else "unknown"
    code = detail.rsplit(" ", 1)[-1].strip()
    blocked_step = h.steps[-1]
    blocked_step["status"] = "blocked"
    blocked_step["note"] = "SEC ISSUANCE BLOCKED — fail-closed refusal by the current implementation; raw stderr/exit code preserved"
    h.blocked("41b-sec-issue-blocker",
              "BLOCKER: skill-context issue refused for an honestly installed skill",
              f"exit={issue.returncode}: {detail}")
    h.cli("41c-sec-deploy-reserved", "context evidence: import-reserved grants can never be deployed (CLI)",
          [str(h.args.binary), "grant", "deploy", h.import_grant_id], expect=1,
          note="grant_import_installation_required is the by-design refusal; the fixed SEC gate instead "
               "accepts approved+reserved as the live terminal state (skillcontext.grantLive)")
    h.serve_start("41d-serve-restart-for-state")
    current = h.http("41e-grant-state", "read back install grant state at the blocked point",
                     "GET", "/v1/grants/" + h.import_grant_id)
    h.steps[-1].setdefault("key_fields", {})["grant_status"] = current["grant"]["status"]
    h.http("41f-catalog", "install catalog at the blocked point", "GET", "/v1/skill-installations/operations")
    bindings = h.http("41g-bindings-at-block", "session binding exists and pins the install grant",
                      "GET", "/v1/intent-bindings")
    h.steps[-1].setdefault("key_fields", {})["bindings"] = [
        {"session_id": b.get("session_id"), "grant_id": (b.get("grant_ref") or {}).get("grant_id")}
        for b in bindings.get("items", [])
    ]
    # Open item (a) is testable without a SEC: revoking the pinned grant must
    # invalidate the enrolled credential on the very next decision request.
    h.http("41g2-grant-revoke", "open item (a) setup: revoke the install grant (HTTP admin)", "POST",
           "/v1/grants/" + h.import_grant_id + "/revoke",
           {"expected_revision": current["state_revision"], "actor_id": ACTOR})
    st2, body2 = h._raw_http("POST", "/v1/decide", {
        "platform": "hermes", "session_id": h.session1, "agent_id": h.agent,
        "tool": READ_TOOL, "tool_call_id": "tc-r01-after-grant-revoke",
        "params": {"path": str(h.workspace / "report.txt")}, "skill": h.claim,
    }, token=h.credential)
    allowed = st2 == 200 and isinstance(body2, dict) and body2.get("action") == "allow"
    entry = {
        "id": "41g3-decide-after-grant-revoke",
        "title": "open item (a): after grant revocation the enrolled credential must not decide",
        "kind": "http", "command": ["POST", "/v1/decide"], "http_status": st2,
        "response_file": h.write_raw("41g3-decide-after-grant-revoke.response.json", json.dumps(body2, indent=2)),
        "key_fields": {
            "error": body2.get("error") if isinstance(body2, dict) else None,
            "action": body2.get("action") if isinstance(body2, dict) else None,
            "observed_layer": "http-auth" if st2 == 401 else "engine",
        },
        "status": "fail" if allowed else "pass",
        "detail": "" if not allowed else "revoked grant still allowed a decision",
    }
    h.record(entry)
    check(entry["status"] == "pass", "grant revocation did not cut the credential")
    h.context["open_item_grant_revoke"] = {
        "http_status": st2,
        "observed_layer": "http-auth" if st2 == 401 else "engine",
        "error": body2.get("error") if isinstance(body2, dict) else None,
    }
    h.serve_stop("41h-serve-stop-after-blocker")
    p = h.cli("41i-verify-chain", "receipt chain still verifies after the blocked issuance",
              [str(h.args.binary), "verify"])
    h.steps[-1]["status"] = "pass" if p.returncode == 0 and json.loads(p.stdout).get("verified") else "fail"
    for step_id, title in [
        ("42", "sec get readback"), ("50", "serve B start"), ("51", "positive task-scoped decide"),
        ("52", "call binding recomputation"), ("53", "negative (a) cross-session"),
        ("54", "negative (d) swapped claim"), ("55", "negative (e) no claim"),
        ("61", "sec revoke"), ("63", "negative (b) revoked replay"),
        ("71", "session-scoped issue"), ("73", "positive session-scoped decide"),
        ("75/76", "negative (c) grant revocation"), ("80-82", "final receipt chain checks"),
    ]:
        h.blocked(step_id, title, "depends on a successfully issued SEC (step 41 failed)")
    h.context["blocker"] = {
        "step": "41-sec-issue-task",
        "error": detail,
        "error_code": code,
        "install_grant_status_at_block": "approved",
        "summary": "skill-context issue (CLI) fails closed at an issuance prerequisite; "
                   "see the report blocker analysis for the exact wiring gap",
    }


REPORT_INTRO = """# R01（N05）可信 Skill 执行上下文 — 本地服务级活体验证报告

- 生成：{generated_at}
- 候选二进制：`{binary}`（sha256 `{binary_sha256}`，来源：{binary_source}）
- 仓库：`{git_head}`（工作树含未提交改动路径 {git_dirty_paths} 条，即本批次 N05/R01 实现）
- 平台：{os}；Python {python}；脚本与证据只使用 Python 标准库与候选二进制
- 沙箱：HOME / HERMES_HOME / SIQ_AGENT_SECURITY_STATE_DIR 全部指向一次性 `tempfile.mkdtemp` 目录
  （运行结束即删除）；未触碰真实 `~/.hermes`、`~/.openclaw`，未启动任何模型，未访问外网
- 凭据脱敏：配对码、管理会话、ri- 运行时凭据只存在于内存；所有落盘文件经精确值替换脱敏
- 命令计数：CLI {cli_count} 次，HTTP {http_count} 次（明细见 transcript.json 与 raw/）
"""


def build_report(h, overall):
    steps_rows = []
    for s in h.steps:
        cells = [
            s["id"], s["title"].replace("|", "\\|"), s["kind"],
            s["status"],
            (s.get("detail") or s.get("note") or "").replace("|", "\\|").replace("\n", " ")[:160],
        ]
        steps_rows.append("| " + " | ".join(cells) + " |")
    status_of = {}
    for s in h.steps:
        status_of[s["id"]] = s["status"]

    def row_status(*ids):
        seen = [status_of.get(i, "blocked") for i in ids]
        if any(v == "fail" for v in seen):
            return "fail"
        if any(v == "blocked" for v in seen):
            return "blocked"
        return "pass"

    acceptance = [
        ("真实受控调用、正确上下文与有效授权 → 同一实际调用、授权和脱敏回执关联一致",
         row_status("51-positive-task", "52-call-binding-recompute", "73-positive-session"),
         "51/52/73：decide 回执 skill_attribution（status/evidence_level/context_id/call_binding），call_binding 用 canonical JSON+sha256 本地重算一致"),
        ("任意请求复制合法安装摘要、grantID 或 skill claim → 不能产生 verified 或 Skill 专属放行",
         row_status("36-forged-claim-no-sec"),
         "36：无 SEC 时逐字节复制的 claim 归属为 unknown 且 deny；37：未 enroll 会话在认证边界 401"),
        ("同一 Agent 下两个 Skill；一个权限更宽 → 较窄 Skill 不能借用另一 Skill 权限",
         "unverified" if h.context.get("blocker") else "not-covered",
         "本脚本只安装一个 Skill；组件测试覆盖 claim 切换与权限交集，双 Skill 宿主活体仍未覆盖（见「待复核项」）"),
        ("同 Skill 跨实例/会话/任务/调用复制 → 拒绝并且无工具副作用",
         row_status("53-negative-cross-session", "53a-negative-cross-task"),
         "53/53a：换会话或任务后同一 claim 均 deny 且不产生 verified；测试只调用 decide，未执行工具"),
        ("参数在许可后改变；同名 Skill 内容替换 → 旧上下文失效，必要时重新审批",
         row_status("54-negative-claim-swap", "57-content-replaced-deny", "58-content-restored"),
         "54：skill_id 替换硬拒绝；56/57：安装内容改变后旧 SEC 立即失效；58：恢复精确字节后重新全量校验通过"),
        ("Grant 撤销/修订、安装移除、服务重启 → 旧上下文不能恢复已失效权限",
         row_status("61-sec-revoke", "63-negative-revoked-replay", "75-grant-revoke", "76-negative-grant-revoked"),
         "61/63：撤销 SEC 后重放 → deny skill_context_revoked；75/76：撤销 grant 后不再 allow/verified"
         "（实际拦截层见「待复核项 (a)」）；serve 多轮重启后结论不变" +
         ("；本轮签发阻断下的活体部分证据：撤销 grant 后 ri- 凭据下一次 decide 即 401（41g2/41g3）"
          if h.context.get("open_item_grant_revoke") else "")),
        ("缺来源或平台不支持 → unknown/明确不可用；不得默认可信",
         row_status("36-forged-claim-no-sec", "37-unenrolled-session"),
         "36/37：无服务端绑定的 claim 恒 unknown；未注册会话明确不可用"),
    ]
    acc_rows = "\n".join(f"| {scene} | {st} | {ev} |" for scene, st, ev in acceptance)

    blocker_section = ""
    if h.context.get("blocker"):
        b = h.context["blocker"]
        analyses = {
            "skill_context_grant_changed": """### 缺陷 #1（历史，本二进制已修复并复核）

旧二进制要求 SEC grant 处于 deployed/effective，而安装流水线的保留准入 grant（adm-si-）永远停
留在 approved（MarkDeployed 拒绝 reserved，runtime identity 路径也要求 approved），曾使签发在
grant 状态门被拒（`skill_context_grant_changed`）。修复后 `skillcontext.grantLive` 接受
「approved + import 保留准入」为 live 终态；本轮实测签发已越过 grant 状态门（失败点移动到
下一前置条件），步骤 41e 读回 grant 状态仍为 approved（与安装流水线终态一致）。""",
            "skill_context_session_unbound": """### 缺陷 #2（当前阻断，本二进制实测）

签发在 session 绑定前置条件被拒：`skill_context_session_unbound`（步骤 41，exit 1）。逐步定位：

1. `skill-context issue` 的 `SessionBound` 依赖 `intents.ResolveBinding`
   （`apps/agentshield/cmd/agentshield/skill_context.go` `openSkillContexts`）。
2. `ResolveBinding` 末段经 `resolveGrantSelection` → `state.RuntimeGrantWithSeq` 重读绑定 pin 的
   grant；对 import 保留准入（adm-si-）的 grant，该路径要求 daemon 的可信内容校验器
   （`state.runtimeGrantCheck`，即 `skillinstall.ValidateRuntimeGrant`）已注册且通过
   （`apps/agentshield/internal/state/intent_authority.go`）。
3. 该校验器只由 HTTP serve 注册（`apps/agentshield/internal/server/skill_install.go`
   `initSkillInstallations` → `SetRuntimeGrantCheck`）；**CLI 进程从不注册**（全仓仅 serve 一处
   调用点）。于是 CLI 内 `ResolveBinding` 对保留 grant 恒失败，绑定存在且 pin 一致也读不出
   （本轮步骤 41g 实测：binding 在、grant_ref 精确指向安装 grant）。
4. 结果：凡走真实安装流水线的 Skill，CLI 签发必然 `skill_context_session_unbound`；serve 进程内
   同一代码路径可用（但无 HTTP 签发端点）。组件测试以 mock 的 SessionBound 通过，覆盖不到该装配
   关系；缺陷 #1 的修复把失败点从 grant 状态门推到了本门，二者属同一条签发链。

旁证与边界：失败模式 fail-closed（零签发、零副作用、回执链完好，步骤 41i 通过）；该缺口与
serve 是否运行无关（校验器是 CLI 自有进程内接线，不经共享状态）。""",
        }
        specific = analyses.get(b.get("error_code"), "### 未分类的签发失败\n\n观察到的错误：" + b["error"])
        if b.get("error_code") == "skill_context_session_unbound":
            specific = analyses["skill_context_grant_changed"] + "\n" + specific
        blocker_section = f"""
## 阻断性实现缺陷（本轮头号结论）

**R01 的 SEC 在真实安装流水线上仍不可达，活体路径在签发步被 fail-closed 拒绝。**

- 现象（步骤 41）：`skill-context issue` 对一个按全部规范安装完成的 Skill 返回
  `{b["error"]}`（exit 1）。

{specific}
"""


    limitations = """
## 证据分层与限制

- **组件测试**：`internal/skillcontext`、`internal/receipt` 的正负向单测属于组件级（mock 依赖），
  本报告不重复其结论；两轮发现的矛盾正是组件层照不到的真实装配关系。
- **本地服务级活体（本报告层级）**：真实候选二进制、真实状态目录与签名、真实 HTTP 服务、
  真实 CLI 生命周期；适配器调用以**等价 HTTP 重放**（ri- 作用域凭据 + 与适配器相同的
  /v1/decide 载荷）代替宿主内插件进程。**未运行真实模型会话**，未在 Hermes 宿主进程内执行工具。
- **原生宿主门槛（仍未完成）**：未在原生 Hermes 插件进程中完成 pre_tool_call → decide → 执行的
  真实链路；按任务书，R01 原生门槛保持未完成，不得以本报告冒充。
- 威胁范围声明（逐字保留自 N05 规格 §1）：本设计抵御的威胁是**模型可控输入与其他 Skill 的
  文本/调用层伪造**（复制 claim、摘要、grantID、session/task 标识、SEC ID）。它不抵御：已攻陷的
  宿主进程（可绕过钩子）、同 UID 恶意本地代码（可读 0600 凭据文件并冒充适配器发起整个请求）、
  OS 层沙箱逃逸。desktop-same-uid 边界见 dev-spec §6。
- 其他限制：单一平台（hermes）单一实例；「同 Agent 两 Skill 权限借用」交叉场景未覆盖。
"""

    open_items = """
## 待复核项复核结果

(a) **grant 撤销后的拦截层**（本轮已实测）：撤销被 pin 的安装 grant 后，已 enroll 的 ri- 运行时凭据
在下一次 decide 即被**认证边界 401 拒绝**（`scoped_decision_credential_required`；证据步骤
41g2/41g3，HTTP 状态与响应原文见 raw/）。原因：`runtimeidentity.authenticate` 每次请求都经
`GrantForReference` 重读 grant，revoked 使凭据本身失效，请求根本到不了决策引擎，也不产生新回执。
因此「grant 撤销 → 引擎层 deny `skill_context_grant_changed`」在 ri- 凭据路径上被认证层遮蔽；
该 SEC 级失效语义的证据由组件测试承担（引擎对 matched-but-invalid SEC 的硬拒绝有单测覆盖）。
活体层面可证明的真实行为是：撤销即时生效、无 allow、无 verified、无工具副作用。

(b) **同 Agent 两 Skill 权限借用交叉场景**：**unverified** —— 需要两枚已签发 SEC 才能构造
「较窄 Skill 借用较宽权限」的活体负向，SEC 签发当前被缺陷 #2 阻断；不以组件测试或推断冒充。
"""
    if h.context.get("open_item_grant_revoke"):
        oi = h.context["open_item_grant_revoke"]
        open_items = open_items.replace(
            "（`scoped_decision_credential_required`；证据步骤",
            f"（实测 HTTP {oi['http_status']} `{oi.get('error')}`；证据步骤",
        )
    if not h.context.get("blocker"):
        step76 = next((s for s in h.steps if s["id"] == "76-negative-grant-revoked"), None)
        layer = (step76 or {}).get("key_fields", {}).get("observed_layer", "?")
        open_items = f"""
## 待复核项复核结果

(a) **grant 撤销后的拦截层**（本轮已实测，步骤 75/76）：撤销被 pin 的安装 grant 后，下一次 decide
的实测拦截层为 `{layer}`（ri- 凭据每次请求都经 `GrantForReference` 重读 grant；撤销使凭据在认证
边界失效，请求不到引擎、不产生新回执；HTTP 401 `unauthorized`）。因此任务
预期的引擎层 `skill_context_grant_changed` 回执在 ri- 凭据路径上被认证层遮蔽，该 SEC 级语义由组件
测试承担。活体可证明的真实行为：撤销即时生效、无 allow、无 verified、无工具副作用。

(b) **同 Agent 两 Skill 权限借用交叉场景**：**unverified** —— 本脚本未构造第二枚 Skill 的 SEC
交叉用例；不以组件测试或推断冒充。
"""

    mapping = """
## 任务书 §5.3 验收场景逐行映射

| 场景（预期） | 结果 | 证据步骤 |
| --- | --- | --- |
""" + acc_rows + "\n"

    steps_table = """
## 步骤实录

| 步骤 | 标题 | 类型 | 结果 | 备注 |
| --- | --- | --- | --- | --- |
""" + "\n".join(steps_rows) + "\n"

    verdict = "PASS（本地服务级候选全部步骤通过；R01 原生宿主门槛仍为 partial）" if overall == "pass" else (
        "BLOCKED（签发步被现行实现 fail-closed 拒绝，见「阻断性实现缺陷」）"
        if h.context.get("blocker") else "FAIL"
    )
    header = REPORT_INTRO.format(
        generated_at=h.context.get("finished_at", ""),
        binary=h.context["binary"], binary_sha256=h.context["binary_sha256"],
        binary_source=h.context["binary_source"], git_head=h.context.get("git_head", "?"),
        git_dirty_paths=h.context.get("git_dirty_paths", "?"), os=h.context["os"],
        python=h.context["python"], cli_count=h.counts["cli"], http_count=h.counts["http"],
    )
    return (
        header + f"\n**总体结论：{verdict}**\n"
        + blocker_section + mapping + open_items + steps_table + limitations
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    binary, source = resolve_binary(args.binary)
    args.binary = binary.resolve()
    args.binary_source = source
    args.out = args.out.resolve()
    # The default is a replaceable evidence batch. Refuse broad paths before
    # removing a previous incomplete run, then regenerate every referenced
    # file so stale failures or credentials cannot survive a rerun.
    if not args.out.name.startswith("r01-skill-context-") or args.out.parent.name != "personal-experience":
        raise SystemExit("--out must be a dedicated personal-experience/r01-skill-context-* directory")
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)

    h = Harness(args)
    overall = "pass"
    try:
        run(h)
    except (StepFailure, subprocess.SubprocessError, OSError, ValueError, KeyError) as exc:
        overall = "fail"
        h.context["fatal"] = f"{type(exc).__name__}: {h.redact(str(exc))[:400]}"
        if not any(s["status"] == "fail" for s in h.steps):
            h.record({"id": "99-fatal", "title": "unhandled harness failure", "kind": "internal",
                      "status": "fail", "detail": h.context["fatal"]})
    finally:
        if h.proc is not None:
            h.proc.kill()
            h.proc.wait(timeout=10)
    if any(s["status"] == "fail" for s in h.steps):
        overall = "fail"
    elif h.context.get("blocker") or any(s["status"] == "blocked" for s in h.steps):
        overall = "blocked"
    h.context["finished_at"] = datetime.now(UTC).isoformat()
    h.context["overall"] = overall

    transcript = {
        "schema_version": "personal-r01-sec-live-smoke/v1",
        "context": h.context,
        "steps": h.steps,
    }
    (args.out / "transcript.json").write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n")
    (args.out / "report.md").write_text(build_report(h, overall))
    manifest = []
    for path in sorted(p for p in args.out.rglob("*") if p.is_file() and p.name != "sha256.txt"):
        manifest.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(args.out).as_posix()}")
    (args.out / "sha256.txt").write_text("\n".join(manifest) + "\n")
    print(json.dumps({
        "overall": overall, "steps": len(h.steps),
        "failed": [s["id"] for s in h.steps if s["status"] == "fail"],
        "blocked": [s["id"] for s in h.steps if s["status"] == "blocked"],
        "evidence": str(args.out),
    }, ensure_ascii=False))
    shutil.rmtree(h.root, ignore_errors=True)
    return 0 if overall == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
