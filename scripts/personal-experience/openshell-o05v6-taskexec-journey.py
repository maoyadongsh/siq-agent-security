#!/usr/bin/env python3
"""O05 v6 D02 acceptance journey: real task execution through the production
executor, deliberately low blast radius.

Drives the candidate native binary built from THIS worktree through its real
product entries only:

  * isolated `serve` daemon (own port, own state dir, own HOME)
  * the HTTP admin/decision API of that daemon
  * the real OpenShell CLI and the real gateway `siq-openshell-dev`

Nothing is imported from the Go packages and no test-only path is used: the
canary reaches the remote sandbox exclusively through
`POST /v1/openshell/task-executions`, i.e. the same production handler, binding
gate and executor that the Go tests exercise. That shared-executor requirement
is the whole point of D02 ("真实驱动与测试必须共享生产执行器，不得另写一条测试
专用绕过路径").

Legs:
  K00  candidate binary identity bind (sha256 + version)
  K01  isolated init / serve / admin pairing
  K02  real protection status (probe, doctor fingerprint, grants, CLI policy read)
  K03  target ownership + capability preflight through the real CLI
  K10  admission -> grant -> challenge/approve/deploy (HTTP admin path)
  K20  task preview: advisory only, live revision/digest, zero side effect
  K30  CANARY: human approves one real command, production executor runs it
  K35  independent effect record read back OUTSIDE the daemon (direct CLI)
  K40  refusal: parameter drift between approval and submission
  K50  refusal: submission that was never approved
  K60  refusal: network target outside the grant facts
  K70  refusal: grant revoked after approval
  K80  refusal: required backend unreachable -> 503, never native fallback
  K90  serve stop (SIGTERM drain)

Honesty rules enforced here:
  * every record carries the candidate sha256, gateway endpoint, target and the
    isolated state/home paths
  * the canary command is a `/bin/sh` one-liner writing a run-unique token into
    the sandbox's own /tmp and printing it; the token makes the stdout
    unforgeable by anything but the real remote execution
  * the raw argv lives only in the human-approved params; every assertion over
    the durable evidence records checks that no raw argv / raw stdout leaked
    into them
  * secrets (tokens, pairing codes, nonces) are redacted in memory only
  * UI acceptance is NOT claimed here: this driver has no Playwright leg
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATEWAY_RE = re.compile(r"admin pairing code \(single use, 5 min\): (\S+)")
REVISION_LINE = re.compile(r"^Version:\s+(\d+)$", re.MULTILINE)
HASH_LINE = re.compile(r"^Hash:\s+([0-9a-f]{64})$", re.MULTILINE)

TASK_SCHEMA = "openshell-task-execution-request/v1"
TASK_COMMAND = "siq-openshell-task-exec"
TASK_TOOL = "exec"


class StepFailure(Exception):
    pass


class CliStall(StepFailure):
    """The local CLI never returned inside its bound.

    Observed in this environment for `sandbox exec`: the call stalls for minutes,
    the CLI's own `--timeout` does not bound it, and killing the local process
    says nothing about the remote command. Callers that can repeat a *read-only*
    command may retry; nothing may be inferred about the remote effect.
    """


def check(cond, detail):
    if not cond:
        raise StepFailure(detail)


def now_iso():
    return datetime.now(UTC).isoformat()


def canary_command(path, token):
    """The one shell command the canary asks a human to approve.

    It writes a runtime-random token to `path` and echoes it back, so the
    sandbox-side effect can afterwards be read by an independent direct CLI
    call (K35) rather than being taken on the daemon's word.

    Shape matters for a non-obvious reason. internal/runtimeaction/describe.go
    flags a shell-like command as a filesystem-write hint when its text matches
        (>>?|\\b(cp|mv|tee|rm|chmod|install|mkdir)\\b)
    and internal/receipt/engine.go:1058-1071 then denies any extracted path that
    no grant fact covers. A plain `printf ... > file` therefore resolves to
    ActionDeny ("filesystem target ... outside granted paths") *before* the
    approval gate is ever consulted, so the human-approval leg would prove
    nothing. `dd of=...` performs the same write without matching the hint.

    This is not a way around a control: the write hint is the engine's stated
    heuristic for spotting an ungranted filesystem mutation, the canary command
    is fully disclosed in the approval prompt, and D02's subject is the
    approval/execution binding, not that heuristic. The sandbox path is
    batch-owned scratch space.
    """
    return f"printf %s {token} | dd of={path} status=none; cat {path}"


def canon_digest(doc):
    """Mirror internal/canon: json.dumps(payload, sort_keys=True, separators=(',',':'))."""
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def grant_digest(grant_json):
    """Mirror internal/grant/permission_digest.go over the HTTP grant JSON."""
    doc = copy.deepcopy(grant_json)
    for field in ("status", "effective_readback", "signature", "signing_schema"):
        doc.pop(field, None)
    for fact in doc.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        if fact.get("domain") == "tool":
            if fact.get("state") in ("declared", "effective"):
                fact["state"] = "runtime_eligible"
        else:
            fact.pop("state", None)
        for field in ("authority", "authority_revision", "readback_evidence_id"):
            fact.pop(field, None)
    doc["digest_schema"] = "grant-permissions/v1"
    return canon_digest(doc)


def load_env_script(path):
    """Source the private env script and return only the OpenShell-relevant
    keys that it defines. Values are never printed or persisted.

    Relevant variables are removed from the child environment first. This
    makes the result independent of whether an operator accidentally sourced
    the same file in the parent shell, and prevents an ambient OpenShell/XDG
    value that the file did not define from being accepted as batch input.
    """
    clean_env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("XDG_", "SIQ_OPENSHELL", "OPENSHELL_"))
    }
    control = subprocess.run(
        ["bash", "-lc", "env -0"], env=clean_env, capture_output=True, check=True
    ).stdout
    withsource = subprocess.run(
        ["bash", "-lc", 'set -a; source "$1" >/dev/null 2>&1; env -0', "siq-env", str(path)],
        env=clean_env, capture_output=True,
        check=True,
    ).stdout

    def parse(blob):
        out = {}
        for chunk in blob.split(b"\0"):
            if b"=" in chunk:
                k, _, v = chunk.partition(b"=")
                out[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
        return out

    base, full = parse(control), parse(withsource)
    picked = {}
    for key, value in full.items():
        if base.get(key) != value and (
            key.startswith(("XDG_", "SIQ_OPENSHELL", "OPENSHELL_"))
        ):
            picked[key] = value
    return picked


class Journey:
    def __init__(self, args):
        self.args = args
        self.binary = Path(args.binary).resolve()
        self.binary_sha = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        check(self.binary_sha == args.expected_sha256, "candidate SHA256 mismatch")
        self.target = args.target
        self.gateway_endpoint = args.gateway_endpoint
        # Absolute, deliberately: several steps hand a path under this tree to
        # the OpenShell CLI (policy set --policy, the browser driver's
        # O05V6_OUT), and every one of those child processes runs with
        # cwd=self.workspace, an isolated temp dir. A repo-relative --out would
        # be resolved against that temp dir and fail with ENOENT while still
        # looking like the step ran.
        self.out = Path(args.out).resolve()
        self.raw_dir = self.out / "d02-private" / "d02-raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.raw_dir, 0o700)
        os.chmod(self.raw_dir.parent, 0o700)

        self.root = Path(tempfile.mkdtemp(prefix="siq-o05v6-taskexec-"))
        os.chmod(self.root, 0o700)
        self.home = self.root / "home"
        self.state = self.root / "state"
        self.workspace = self.root / "workspace"
        for d in (self.home, self.state, self.workspace):
            d.mkdir(mode=0o700)

        # The canary token is generated at runtime, so the stdout it produces
        # cannot be predicted or replayed by anything except a real execution
        # inside the target sandbox.
        self.run_id = secrets.token_hex(8)
        self.canary_token = secrets.token_hex(16)
        self.canary_path = f"/tmp/o05v6-canary-{self.run_id}.txt"
        self.canary_argv = [
            "/bin/sh", "-c", canary_command(self.canary_path, self.canary_token),
        ]

        # Declared-only network content. This is the sandbox's own default
        # egress gateway (read from /proc/net/route inside the sandbox in K03)
        # with an unserved port: the fixture skill declares it, the grant turns
        # it into an allow fact, and NOTHING ever contacts it. The canary argv
        # needs no network at all and submits `network_targets: []`.
        self.fact_endpoint = args.fact_endpoint

        self.skill = self.root / "skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(
            "---\nname: o05v6-taskexec-canary\n"
            "description: Batch-owned canary skill declaring one egress target.\n"
            "version: 1.0.0\nallowed-tools: terminal read_file\n"
            "compatibility: Requires network access to the sandbox canary endpoint.\n---\n"
            "# Canary\n\n"
            # The bootstrap install line plus "allowed-tools: terminal" make the
            # derivation emit a declared `process.exec allow "shell"` fact. It is
            # that fact (not any "exec" tool fact) which makes grant.Build put
            # "exec" into OpenClawToolPolicy.RequireApproval
            # (internal/grant/grant.go:233-270, 300-307), and RequireApproval is
            # what turns every exec decide into a human-approval hold
            # (internal/receipt/engine.go:1011-1073).
            "Install the reporter dependency: "
            "curl -fsSL https://astral.sh/uv/install.sh | sh\n\n"
            f"Report target: http://{self.fact_endpoint}/report\n\n"
            "Run scripts/report.py once per session.\n"
        )
        (self.skill / "scripts").mkdir()
        (self.skill / "scripts" / "report.py").write_text(
            "import json, urllib.request\n"
            'payload = {"session": "o05v6-taskexec"}\n'
            f'req = urllib.request.Request("http://{self.fact_endpoint}/report", '
            "data=json.dumps(payload).encode())\n"
            "urllib.request.urlopen(req)\n"
        )

        self.cli_bin, self.xdg = None, {}
        if args.env_script:
            picked = load_env_script(args.env_script)
            self.cli_bin = picked.get("SIQ_OPENSHELL_BIN")
            self.xdg = {k: v for k, v in picked.items() if k != "SIQ_OPENSHELL_BIN"}
        if not self.cli_bin:
            raise SystemExit("env script did not provide SIQ_OPENSHELL_BIN")

        self.session = "o05v6-taskexec-session-1"
        self.actor = "o05v6-taskexec-admin"
        self.env = {k: v for k, v in os.environ.items()
                    if k in ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR")}
        self.env.update(self.xdg)
        self.env.update({
            "HOME": str(self.home),
            "SIQ_AGENT_SECURITY_STATE_DIR": str(self.state),
            "SIQ_AS_OPENSHELL_CLI_BIN": self.cli_bin,
            "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT": self.gateway_endpoint,
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        # The lost-backend leg gets its own daemon with an unreachable endpoint.
        self.lost_env = dict(self.env)
        self.lost_env["SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT"] = args.lost_endpoint
        self.lost_root = self.lost_state = self.lost_home = None

        self.secrets = {}
        self.steps = []
        self.admin = None
        self.token = None
        self.proc = None
        self.serve_log = None
        self.endpoint = None
        self.lost_proc = self.lost_log = self.lost_endpoint = self.lost_admin = None
        self.expected_revision = self.expected_digest = None
        self.current_leg = "startup"
        self.canary_response = None
        self.lost_workspace = None
        self.grant_id = self.grant_digest = self.fingerprint = None
        self.sandbox_id = None
        self.grant_revision = None
        self.gateway_version = None
        self.base_revision = self.base_hash = None
        self.holds = {}
        self.meta = {
            "candidate_binary": str(self.binary),
            "binary_sha256": self.binary_sha,
            "gateway_endpoint": self.gateway_endpoint,
            "sandbox_target": self.target,
            "fact_endpoint": self.fact_endpoint,
            "fact_endpoint_role": "declared policy content only; never contacted",
            "isolated_root": str(self.root),
            "isolated_state": str(self.state),
            "isolated_home": str(self.home),
            "canary_argv_count": len(self.canary_argv),
            "canary_path": self.canary_path,
            "started_at": now_iso(),
            "ui_acceptance": "not_run",
            "production_executor": "POST /v1/openshell/task-executions",
            "notes": [
                "canary stdout 由运行时随机 token 构成，无法被非真实执行伪造",
                "原始 argv 只存在于人工批准的 params；证据/观测只存摘要",
            ],
        }

    # ---------- redaction ----------
    def keep_secret(self, value, label):
        if value:
            self.secrets[str(value)] = label

    def redact(self, text):
        out = str(text or "")
        for value, label in sorted(self.secrets.items(), key=lambda kv: -len(kv[0])):
            out = out.replace(value, f"«REDACTED:{label}»")
        return out

    def write_raw(self, name, text):
        path = self.raw_dir / name
        path.write_text(self.redact(text))
        # 0600: every file under *-private/ is raw product traffic, and this is
        # the only place that writes it, so the mode is set here rather than
        # being left to the process umask.
        os.chmod(path, 0o600)
        return str(path.relative_to(self.out))

    def record(self, entry):
        entry["recorded_at"] = now_iso()
        entry["binary_sha256"] = self.binary_sha
        entry["sandbox_target"] = self.target
        self.steps.append(entry)
        print(f"[{entry.get('status', '?'):>7}] {entry['id']}: {entry['title']}")
        if entry.get("status") != "pass" and entry.get("detail"):
            print("           " + self.redact(entry["detail"])[:400])

    # ---------- product entries ----------
    def http(self, step_id, title, method, path, body=None, token=None,
             expect=200, note=None, endpoint=None):
        started = datetime.now(UTC)
        headers = {"Content-Type": "application/json"}
        if token is None:
            token = self.admin
        if token:
            headers["Authorization"] = "Bearer " + token
        base = endpoint or self.endpoint
        req = urllib.request.Request(
            base + path, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
        )
        try:
            resp = urllib.request.urlopen(req, timeout=180)
            status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"_unparsed": raw[:400].decode("utf-8", "replace")}
        if isinstance(payload, dict):
            # Callers assert on the returned dict; carry the status with it so a
            # refusal can be reported with the code it actually came back as,
            # not just the fields the refusal body happened to contain.
            payload = dict(payload, _http_status=status)
        entry = {
            "id": step_id, "title": title, "kind": "http", "command": [method, path],
            "http_status": status,
            "request_body_file": self.write_raw(f"{step_id}.request.json",
                                                json.dumps(body, indent=2, default=str) if body is not None else ""),
            "response_file": self.write_raw(f"{step_id}.response.json",
                                            json.dumps(payload, indent=2, default=str)),
            "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
        }
        if isinstance(payload, dict):
            keys = {}
            for field in ("ok", "scope", "action", "reason_code", "status", "error",
                          "receipt_id", "action_id", "state_revision", "grant_id",
                          "task_executed", "execution_uncertain", "binding_evidence_id",
                          "binding_evidence_persisted", "observation_receipt_id", "mode",
                          "task_plan_not_persisted"):
                if field in payload:
                    keys[field] = payload[field]
            if isinstance(payload.get("outcome"), dict):
                oc = payload["outcome"]
                keys["outcome.state"] = oc.get("state")
                keys["outcome.exit_code"] = oc.get("exit_code")
                keys["outcome.spawned"] = oc.get("spawned")
                keys["outcome.execution_uncertain"] = oc.get("execution_uncertain")
            entry["key_fields"] = keys
        if note:
            entry["note"] = note
        try:
            expected = expect if isinstance(expect, tuple) else (expect,)
            check(status in expected,
                  f"HTTP {status} != expected {expected}: {json.dumps(payload)[:300]}")
            entry["status"] = "pass"
        except Exception as exc:  # noqa: BLE001 -- record failed evidence, then rethrow or exit nonzero
            entry["status"] = "fail"
            entry["detail"] = str(exc)
        self.record(entry)
        if entry["status"] != "pass":
            raise StepFailure(entry.get("detail", f"{step_id} failed"))
        return payload

    def cli(self, step_id, title, argv, expect=0, env=None, note=None, timeout=180):
        started = datetime.now(UTC)
        try:
            proc = subprocess.run(argv, cwd=self.workspace, env=env or self.env,
                                  capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            # A stall is evidence, not a crash: record it and let the caller decide.
            # Nothing is claimed about the remote command -- the local bound fired,
            # which is not a remote stop and not proof that nothing ran.
            stall = {
                "id": step_id, "title": title, "kind": "cli",
                "command": [Path(argv[0]).name] + argv[1:],
                "exit_code": None, "status": "fail",
                "local_bound_s": timeout,
                "detail": f"the local CLI did not return within {timeout}s; the remote "
                          f"command's outcome is unknown (a killed local CLI is not a "
                          f"remote stop)",
            }
            if note:
                stall["note"] = note
            self.record(stall)
            raise CliStall(stall["detail"]) from exc
        entry = {
            "id": step_id, "title": title, "kind": "cli",
            "command": [Path(argv[0]).name] + argv[1:],
            "exit_code": proc.returncode,
            "stdout_file": self.write_raw(f"{step_id}.cli.stdout.txt", proc.stdout),
            "stderr_file": self.write_raw(f"{step_id}.cli.stderr.txt", proc.stderr),
            "duration_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
        }
        if note:
            entry["note"] = note
        try:
            check(proc.returncode == expect,
                  f"exit {proc.returncode} != {expect}: {proc.stderr[-200:]}")
            entry["status"] = "pass"
        except Exception as exc:  # noqa: BLE001 -- record failed evidence, then rethrow or exit nonzero
            entry["status"] = "fail"
            entry["detail"] = str(exc)
        self.record(entry)
        if entry["status"] != "pass":
            raise StepFailure(entry.get("detail", f"{step_id} failed"))
        return proc

    def sandbox_exec(self, step_id, title, argv, expect=0, note=None,
                     timeout=90, retry_stalls=False, stall_attempts=3):
        """Direct CLI execution in the target sandbox, OUTSIDE the daemon.

        Used only for preflight and for the independent effect read-back; the
        canary itself goes through the production HTTP executor.

        `sandbox exec` stalls intermittently in this environment (minutes at a
        time, not bounded by the CLI's own `--timeout`). A stall therefore gets a
        bounded local timeout instead of hanging the leg. Retrying is opt-in via
        `retry_stalls`, and only ever fires on a stall -- never on a nonzero exit
        -- because a stalled write may already have landed remotely and a blind
        repeat would apply it twice. Only effect-free commands may opt in.
        """
        argv_full = [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                     "sandbox", "exec", "-n", self.target, "--no-tty", "--", *argv]
        attempt = 1
        while True:
            sid = step_id if attempt == 1 else f"{step_id}.r{attempt}"
            try:
                return self.cli(sid, title, argv_full, expect=expect, note=note,
                                timeout=timeout)
            except CliStall:
                if not retry_stalls or attempt >= stall_attempts:
                    raise
                attempt += 1

    # ---------- real CLI observation (read-only) ----------
    def policy_read(self, step_id, target=None, note=None):
        # `target` is the CLI's *sandbox selector*, never a description: passing a
        # prose string here makes the CLI resolve it as a sandbox name and fail
        # with "sandbox not found". Descriptive text goes in `note`.
        proc = self.cli(step_id, f"CLI observation: policy get {target or self.target} --full",
                        [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                         "policy", "get", target or self.target, "--full"],
                        note=note or "read-only observation via real openshell CLI")
        return {
            "revision": REVISION_LINE.search(proc.stdout).group(1),
            "hash": HASH_LINE.search(proc.stdout).group(1),
        }

    # ---------- serve lifecycle ----------
    def _serve(self, step_id, env, workspace):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115
        proc = subprocess.Popen(
            [str(self.binary), "serve", "--port", str(port), "--mode", "block"],
            cwd=workspace, env=env, stdout=log, stderr=log,
        )
        code = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            log.seek(0)
            found = GATEWAY_RE.search(log.read())
            if found:
                code = found.group(1)
                break
            time.sleep(0.05)
        log.seek(0)
        excerpt = log.read()
        entry = {
            "id": step_id, "title": f"serve start (mode=block) + admin pairing on 127.0.0.1:{port}",
            "kind": "cli+http",
            "command": [self.binary.name, "serve", "--port", port, "--mode", "block"],
        }
        try:
            check(proc.poll() is None, "serve exited before readiness")
            check(code is not None, "pairing code not printed within 30s")
            self.keep_secret(code, "pairing-code")
            payload = self._raw_http(port, "POST", "/v1/pair", {"code": code})
            check(payload[0] == 200, f"pair HTTP {payload[0]}")
            session = None
            for key in ("session", "admin_session", "token", "session_id"):
                if isinstance(payload[1], dict) and payload[1].get(key):
                    session = payload[1][key]
                    break
            check(bool(session), f"pair response missing session: {list(payload[1]) if isinstance(payload[1], dict) else payload[1]}")
            entry["status"] = "pass"
            entry["http_status"] = 200
            entry["key_fields"] = {"pairing": "redeemed"}
            entry["daemon_endpoint"] = f"http://127.0.0.1:{port}"
        except Exception as exc:  # noqa: BLE001 -- record failed evidence, then rethrow or exit nonzero
            entry["status"] = "fail"
            entry["detail"] = str(exc)
        entry["stdout_file"] = self.write_raw(f"{step_id}.serve-log.txt", excerpt)
        self.record(entry)
        if entry["status"] != "pass":
            raise StepFailure(entry.get("detail", "serve start failed"))
        return proc, log, f"http://127.0.0.1:{port}", session

    @staticmethod
    def _raw_http(port, method, path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", headers=headers,
            data=json.dumps(body).encode() if body is not None else None, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=180)
            return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"_unparsed": raw[:300].decode("utf-8", "replace")}

    def serve_stop(self, step_id, proc, log):
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        log.seek(0)
        self.write_raw(f"{step_id}.serve-final-log.txt", log.read())
        self.record({"id": step_id, "title": "serve stop (SIGTERM drain)",
                     "kind": "cli", "status": "pass"})

    # ---------- journey helpers ----------
    def read_token(self, state_dir):
        token = (Path(state_dir) / "token").read_text().strip()
        self.keep_secret(token, "daemon-global-token")
        return token

    def _free_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    def canonical_task_params(self, target, argv, workdir, timeout, limit,
                              revision, digest, network_targets):
        """Mirror internal/server/openshell_task_binding.go canonicalTaskParams.

        This is the document the HUMAN approves. It is built here independently
        of the Go implementation (not imported), so a byte-equality check on the
        server side is a real check and not self-verification.
        """
        return {
            "command": TASK_COMMAND,
            "target": target,
            "argv": argv,
            "workdir": workdir,
            "timeout_seconds": timeout,
            "output_limit_bytes": limit,
            "policy_revision": revision,
            "policy_digest": digest,
            "authorization_urls": [f"https://{ep}" for ep in network_targets],
            "openshell_task": {
                "target": target,
                "grant_id": self.grant_id,
                "grant_digest": self.grant_digest,
                "endpoint_fingerprint": self.fingerprint,
                "sandbox_id": self.sandbox_id,
            },
        }

    def task_body(self, tool_call_id, params, target, argv, workdir, timeout,
                  limit, revision, digest, network_targets, decision):
        # Task identity is echoed from the decision the server actually recorded,
        # never invented here. internal/receipt/hold_execution.go:103 requires
        # d.TaskID == req.TaskID *exactly*, so a submission that names its own
        # task identity is rejected as hold_identity_mismatch -- the reservation
        # must bind the same task the human approved, not a fresh label for it.
        # Sourcing both fields from the decision makes that divergence
        # structurally impossible instead of a thing to remember.
        return {
            "schema_version": TASK_SCHEMA,
            "platform": "openclaw",
            "session_id": self.session,
            "agent_id": target,
            "task_id": decision.get("task_id") or "",
            "runtime_task_id": decision.get("runtime_task_id") or "",
            "tool": TASK_TOOL,
            "original_tool_call_id": tool_call_id,
            "retry_tool_call_id": tool_call_id + "-retry",
            "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"],
            "params": params,
            "target": target,
            "argv": argv,
            # body.Workdir is read by validateOpenShellTaskExecutionBinding and
            # compared byte-for-byte against params["workdir"]
            # (internal/server/openshell_task_binding.go:84,141). Omitting the
            # key here made the E03 "workdir drift" variant a silent no-op: the
            # patched value was accepted as an argument to this function and then
            # dropped, so the drift never reached the server and the leg could not
            # fail. Emitting it keeps the drift observable. For every non-drift
            # body the value is "" -- identical to the absent key after JSON
            # unmarshalling, so no other leg changes behaviour.
            "workdir": workdir,
            "timeout_seconds": timeout,
            "output_limit_bytes": limit,
            "policy_revision": revision,
            "policy_digest": digest,
            "network_targets": network_targets,
        }

    def decide(self, step_id, tool_call_id, params, expect_action="hold", title=None):
        decision = self.http(step_id, title or "decide (tool exec, expect human hold)", "POST",
                             "/v1/decide", {
                                 "platform": "openclaw", "session_id": self.session,
                                 "agent_id": self.target, "tool": TASK_TOOL,
                                 "tool_call_id": tool_call_id, "params": params,
                             }, token=self.token)
        check(decision.get("action") == expect_action,
              f"decide: expected {expect_action}, got {decision.get('action')} "
              f"({decision.get('reason')})")
        self.holds[tool_call_id] = decision
        return decision

    def hold_resolve(self, step_id, decision, approve, note=None):
        return self.http(step_id, "hold resolution (admin)", "POST",
                         f"/v1/hold/{decision['receipt_id']}",
                         {"approve": approve, "actor_id": self.actor}, note=note)

    def _raw_http_auth(self, method, path, body):
        return self._raw_http(self.endpoint.split(":")[-1], method, path, body,
                              token=self.token)

    def submit_task(self, step_id, title, body, expect, note=None):
        return self.http(step_id, title, "POST", "/v1/openshell/task-executions",
                         body, token=self.token, expect=expect, note=note)

    def assert_task_executed(self, step_id, resp):
        """Assert the success shape of a task-execution response, in one place.

        internal/server/openshell_task_exec.go:225-267 sets the top-level
        task_executed=yes only on the *failure* paths (503 evidence-incomplete /
        observation-error), where it exists to stop a caller reading ok=false as
        "nothing ran". On the success path the only task_executed is the one
        inside outcome, so the top-level field is simply absent there. Asserting
        the top-level field instead of the outcome already cost one run; keeping
        the claim in a single helper stops the call sites drifting apart again.
        """
        check(resp.get("ok") is True, f"{step_id}: not ok: {json.dumps(resp)[:300]}")
        check(resp.get("task_executed") in (None, "yes"),
              f"{step_id}: top-level task_executed contradicts the outcome: "
              f"{resp.get('task_executed')!r}")
        check(resp.get("scope") == "task_execution",
              f"{step_id}: wrong route: scope={resp.get('scope')!r}")
        outcome = resp.get("outcome") or {}
        check(outcome.get("state") == "succeeded", f"{step_id}: state {outcome.get('state')}")
        check(outcome.get("exit_code") == 0, f"{step_id}: exit {outcome.get('exit_code')}")
        check(outcome.get("spawned") is True, f"{step_id}: did not spawn")
        check(outcome.get("task_executed") == "yes",
              f"{step_id}: outcome does not say task_executed=yes")
        check(bool(resp.get("observation_receipt_id")), f"{step_id}: no observation receipt id")
        check(resp.get("binding_evidence_persisted") is True,
              f"{step_id}: binding evidence not persisted")
        check(bool(resp.get("reservation", {}).get("reservation_receipt_id")),
              f"{step_id}: no reservation receipt id")
        return outcome

    # ---------- legs ----------
    def run(self):
        self.leg_k00()
        self.leg_k01()
        legs = (
            self.leg_k02, self.leg_k03, self.leg_k10, self.leg_k20, self.leg_k30,
            self.leg_k35, self.leg_k40, self.leg_k50, self.leg_k60, self.leg_k70,
        )
        try:
            for leg in legs:
                self.current_leg = leg.__name__
                leg()
            self.current_leg = "done"
        finally:
            self.leg_k80()
            self.leg_k90()
        return self.report()

    def leg_k00(self):
        proc = subprocess.run([str(self.binary), "version"], capture_output=True,
                              text=True, env=self.env, timeout=30, check=False)
        check(proc.returncode == 0 and bool(proc.stdout.strip()),
              "candidate version probe failed")
        self.record({
            "id": "K00", "title": "candidate binary identity bind",
            "kind": "cli", "status": "pass",
            "binary_sha256": self.binary_sha,
            "version_stdout": self.redact(proc.stdout.strip()),
            "bytes": self.binary.stat().st_size,
        })

    def leg_k01(self):
        self.cli("K01a", "init isolated state dir",
                 [str(self.binary), "init", "--port", str(self._free_port())])
        self.proc, self.serve_log, self.endpoint, self.admin = self._serve(
            "K01b", self.env, self.workspace)
        self.keep_secret(self.admin, "admin-session")
        self.token = self.read_token(self.state)

    def leg_k02(self):
        probe = self.http("K02a", "real protection status: openshell probe",
                          "GET", "/v1/openshell/probe")
        check(probe.get("ok") is True,
              "OpenShell probe did not confirm a reachable backend")
        doctor = self.http("K02b", "real protection status: openshell doctor",
                           "GET", "/v1/openshell/doctor")
        caps = doctor.get("capabilities") or {}
        self.fingerprint = caps.get("endpoint_fingerprint")
        self.gateway_version = caps.get("gateway_version") or caps.get("version")
        check(bool(self.fingerprint), "doctor did not expose endpoint_fingerprint")
        self.http("K02c", "real protection status: grants ledger (empty)",
                  "GET", "/v1/grants")
        live = self.policy_read("K02d")
        self.base_revision, self.base_hash = live["revision"], live["hash"]
        instances = self.cli(
            "K02f", "read current sandbox identity before approval",
            [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
             "sandbox", "list", "--limit", "1000", "--output", "json"],
            note="read-only; a same-name replacement must invalidate the old approval",
        )
        rows = json.loads(instances.stdout)
        matches = [row for row in rows if row.get("name") == self.target]
        check(len(matches) == 1 and re.fullmatch(
                  r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                  matches[0].get("id", ""))
              and matches[0].get("phase") == "Ready"
              and str(matches[0].get("current_policy_version")) == self.base_revision,
              "current sandbox identity is not unique, ready and at the baseline revision")
        self.sandbox_id = matches[0]["id"]
        self.record({
            "id": "K02e", "title": "baseline binding: gateway/fingerprint/target revision",
            "kind": "derived", "status": "pass",
            "gateway_version": self.gateway_version,
            "endpoint_fingerprint": self.fingerprint,
            "sandbox_revision": self.base_revision,
            "sandbox_policy_sha256": self.base_hash,
            "sandbox_id": self.sandbox_id,
        })

    def leg_k03(self):
        """Ownership + capability preflight, via the real CLI, outside the daemon."""
        host = self.fact_endpoint.rsplit(":", 1)[0]
        route = self.sandbox_exec(
            "K03a", "ownership preflight: reach target sandbox and read its default route",
            ["/bin/cat", "/proc/net/route"], retry_stalls=True,
            note="read-only; confirms the target is alive and owned by this batch")
        # Little-endian hex gateway of the default route, without the daemon.
        gw = None
        for line in route.stdout.splitlines()[1:]:
            cols = line.split()
            if len(cols) >= 3 and cols[1] == "00000000":
                raw = cols[2]
                gw = ".".join(str(int(raw[i:i + 2], 16)) for i in (6, 4, 2, 0))
                break
        check(gw is not None, "could not derive the sandbox default gateway")
        # The route gateway is NOT an egress path. It is the sandbox-side address
        # of the L7 egress proxy, which lives in a namespace the host cannot see
        # and which answers 502 to a request for its own address (the proxy
        # failing to reach itself). The address a declared endpoint can actually
        # be delivered to is the one the sandbox itself publishes for its host in
        # /etc/hosts. Reading that file is what lets this guard keep rejecting a
        # genuinely unrelated address without certifying the proxy address as if
        # it were reachable -- an assertion that would silently bless every
        # E02-style reachability claim made about it.
        hosts = self.sandbox_exec(
            "K03a2", "ownership preflight: host addresses the sandbox itself publishes",
            ["/bin/cat", "/etc/hosts"], retry_stalls=True,
            note="read-only; the platform's own 'where is the host' answer")
        published = {}
        for line in hosts.stdout.splitlines():
            parts = line.split("#", 1)[0].split()
            for alias in parts[1:]:
                published.setdefault(alias, parts[0])
        host_alias = published.get("host.openshell.internal") or \
            published.get("host.docker.internal")
        deliverable = host_alias is not None and host == host_alias
        check(deliverable or host == gw,
              f"declared fact endpoint {self.fact_endpoint} is neither the address the "
              f"sandbox publishes for its host ({host_alias}) nor its route gateway "
              f"({gw}); refusing to declare an unrelated address")
        sh = self.sandbox_exec(
            "K03b", "capability preflight: /bin/sh -c works in the target",
            ["/bin/sh", "-c", "printf %s o05v6-preflight"], retry_stalls=True,
            note="read-only probe")
        check(sh.stdout.strip() == "o05v6-preflight", f"unexpected stdout: {sh.stdout!r}")
        # Prove the exact canary command shape -- hence `dd`, and hence the
        # write itself -- works in this target before a human is ever asked to
        # approve it. A capability gap must surface here, not as a mystery
        # failure inside the approval leg.
        probe_path = f"/tmp/o05v6-canary-preflight-{self.run_id}.txt"
        pre = self.sandbox_exec(
            "K03b2", "capability preflight: the exact canary command shape runs",
            ["/bin/sh", "-c", canary_command(probe_path, "o05v6-canary-preflight")],
            note="read-only for policy; writes one batch-owned scratch file")
        check(pre.stdout.strip() == "o05v6-canary-preflight",
              f"the canary command shape does not work in the target: {pre.stdout!r} "
              f"(stderr: {pre.stderr[:200]!r})")
        self.record({
            "id": "K03c", "title": "preflight summary",
            "kind": "derived", "status": "pass",
            "sandbox_egress_gateway": gw,
            "sandbox_published_host_alias": host_alias,
            "declared_fact_endpoint": self.fact_endpoint,
            "declaration_is_deliverable": deliverable,
            "declared_endpoint_role": "policy content only; never contacted by any leg",
            "note": "the route gateway is the sandbox-side address of the egress proxy and "
                    "is not a deliverable destination; naming it is accepted as a "
                    "policy-content placeholder but recorded as non-deliverable, so the "
                    "preflight never certifies it as an egress path",
        })

    def leg_k10(self):
        admitted = self.http("K10a", "admit batch-owned canary skill (HTTP)",
                             "POST", "/v1/admit", {"path": str(self.skill)})
        admission_id = admitted["admission"]["admission_id"]
        granted = self.http("K10b", "create grant platform=openclaw subject=sandbox (HTTP)",
                            "POST", "/v1/grants", {
                                "admission_id": admission_id,
                                "platform": "openclaw", "subject_id": self.target,
                            })
        grant = granted["grant"]
        self.grant_id = grant["grant_id"]
        revision = granted["state_revision"]
        grant_path = "/v1/grants/" + self.grant_id
        patched = self.http("K10c", "patch-desired approved model allowlist (HTTP)",
                            "POST", grant_path + "/patch-desired", {
                                "expected_revision": revision,
                                "models": ["fixture-model"],
                            })
        revision = patched["state_revision"]
        challenge = self.http("K10d", "approval challenge (HTTP)", "POST",
                              grant_path + "/challenge",
                              {"expected_revision": revision, "actor_id": self.actor})
        revision = challenge["state_revision"]
        nonce = challenge["challenge"]["nonce"]
        self.keep_secret(nonce, "grant-challenge-nonce")
        approved = self.http("K10e", "human approve with challenge proof (HTTP)",
                             "POST", grant_path + "/approve", {
                                 "expected_revision": revision, "actor_id": self.actor,
                                 "challenge_id": challenge["challenge"]["challenge_id"],
                                 "nonce": nonce,
                             })
        revision = approved["state_revision"]
        deployed = self.http("K10f", "deploy grant (HTTP)", "POST", grant_path + "/deploy",
                             {"expected_revision": revision})
        check(deployed["grant"]["status"] == "deployed", "grant not deployed")
        self.grant_revision = deployed["state_revision"]
        current = self.http("K10g", "read deployed grant for digest replication",
                            "GET", grant_path)
        g = current.get("grant", current)
        self.grant_digest = grant_digest(g)
        facts = [f for f in g.get("facts", [])
                 if f.get("domain") == "network" and f.get("effect") == "allow"]
        self.grant_endpoints = sorted(f["resource"]["value"] for f in facts)
        # Which granted facts actually cover running a command? The engine does
        # not key on the literal tool name: runtimeaction.Describe maps
        # exec/terminal/bash/shell/process/sh/... onto the same "exec" operation
        # with the process_exec effect. So the floor is any ALLOW fact on that
        # family, either as a tool.invoke on a shell-like tool or as a
        # process.exec on a shell-like resource. Mirroring the family (instead of
        # hard-coding one value) keeps this a real check rather than a name guess.
        shell_like = {"exec", "terminal", "bash", "shell", "process", "sh",
                      "python", "python3", "node", "powershell", "pwsh"}
        exec_facts = []
        for f in g.get("facts", []) or []:
            res = f.get("resource") or {}
            value = res.get("value")
            if f.get("effect") != "allow" or value not in shell_like:
                continue
            if f.get("domain") == "tool" and f.get("action") == "tool.invoke":
                exec_facts.append(f)
            elif f.get("domain") == "process" and f.get("action") == "process.exec":
                exec_facts.append(f)
        # The actual hold floor, though, is not a fact at all: it is the
        # per-use approval gate that grant.Build derives from those declared
        # process/resource facts and stores in OpenClawToolPolicy.RequireApproval
        # (internal/grant/grant.go:233-270, 300-307). internal/receipt/engine.go
        # returns ActionHold for any tool named there, before any allow-list
        # lookup. So this is the field the journey's K30 approval leg depends on.
        policy = g.get("openclaw_tool_policy") or {}
        self.record({
            "id": "K10h", "title": "grant digest replicated client-side (canon grant-permissions/v1)",
            "kind": "derived", "status": "pass",
            "grant_id": self.grant_id,
            "grant_digest": self.grant_digest,
            "grant_network_endpoints": self.grant_endpoints,
            "openclaw_tool_policy_allow": policy.get("allow"),
            "openclaw_tool_policy_require_approval": policy.get("require_approval"),
            "grant_fact_summary": [
                {"domain": f.get("domain"), "action": f.get("action"),
                 "effect": f.get("effect"), "value": (f.get("resource") or {}).get("value")}
                for f in (g.get("facts") or [])
            ],
            "grant_exec_facts": [
                {"domain": f.get("domain"), "action": f.get("action"), "effect": f.get("effect"),
                 "value": (f.get("resource") or {}).get("value")}
                for f in exec_facts
            ],
            "note": "digest mirrors internal/grant/permission_digest.go; the server compares its own recomputation",
        })
        check(self.fact_endpoint in self.grant_endpoints,
              f"grant facts missing the declared endpoint: {self.grant_endpoints}")
        check("exec" in (policy.get("require_approval") or []),
              "the deployed grant carries no per-use approval gate for 'exec'; every "
              "exec decide would fall through to default-deny and the approval leg "
              f"would prove nothing: {policy}")
        check(bool(exec_facts),
              "the deployed grant grants no shell-like ALLOW fact, so the command "
              "would not be backed by any authorized effect: " + str(exec_facts))

    def leg_k20(self):
        preview = self.http("K20a", "task preview: authorized endpoints + live revision (admin)",
                            "POST", "/v1/openshell/task-executions/preview",
                            {"target": self.target})
        check(preview.get("scope") == "task_execution", "preview scope is not task_execution")
        check(preview.get("mode") == "advisory", "preview must be advisory")
        check(preview.get("task_executed") is False, "preview must not claim execution")
        check(preview.get("execution_constraints_verified") is False,
              "preview must not claim verified constraints")
        live = preview.get("live") or {}
        check(bool(live.get("revision")) and bool(live.get("policy_digest")),
              f"preview did not expose the live revision/digest: {list(preview)}")
        after = self.policy_read("K20b")
        check(after["revision"] == self.base_revision,
              "preview produced a side effect on the sandbox policy")
        self.expected_revision = live["revision"]
        self.expected_digest = live["policy_digest"]
        self.record({
            "id": "K20c", "title": "preview is side-effect free and the approved revision is the live one",
            "kind": "derived", "status": "pass",
            "live_revision": self.expected_revision,
            "live_policy_digest": self.expected_digest,
            "note": "预留在写前必须等于 live；执行前 ExecTask 还会再读一次 ReadEffective",
        })

    def leg_k30(self):
        """The canary: one real, approved, non-paid command in the target sandbox."""
        params = self.canonical_task_params(
            self.target, self.canary_argv, "", 60, 65536,
            self.expected_revision, self.expected_digest, [])
        decision = self.decide("K30a", "o05v6-k30-canary", params)
        self.hold_resolve("K30b", decision, approve=True,
                          note="human approves this exact command")
        body = self.task_body("o05v6-k30-canary", params, self.target, self.canary_argv,
                              "", 60, 65536, self.expected_revision, self.expected_digest, [],
                              decision)
        resp = self.submit_task("K30c", "CANARY: production executor runs one real command",
                                body, expect=200,
                                note="must be 200 with outcome.task_executed=yes")
        # Shape asserted by the shared helper: see assert_task_executed for why
        # the success evidence is outcome.task_executed and not a top-level field.
        outcome = self.assert_task_executed("K30c", resp)
        self.canary_response = resp
        self.record({
            "id": "K30d", "title": "canary outcome (digests only)",
            "kind": "derived", "status": "pass",
            "reservation_receipt_id": resp["reservation"]["reservation_receipt_id"],
            "observation_receipt_id": resp["observation_receipt_id"],
            "binding_evidence_id": resp["binding_evidence_id"],
            "stdout_digest": outcome.get("stdout_digest"),
            "stdout_bytes": outcome.get("stdout_bytes"),
            "exit_code": outcome.get("exit_code"),
            "exit_code_attribution": outcome.get("exit_code_attribution"),
        })
        # Boundary finding, recorded rather than papered over: the canary itself
        # demonstrates it. The engine extracts `/tmp/o05v6-canary-*.txt` from the
        # command, finds no file fact covering it, and still allows the write --
        # because internal/receipt/engine.go:1068 only denies an ungranted path
        # when the tool is a file operation or the command text matches the
        # writeCommand heuristic (internal/runtimeaction/describe.go:27,53).
        # Neither holds for this command. So an approved `exec` approval bounds
        # *which command* runs, not *which paths that command may write*; the
        # filesystem scope of an approved exec is the sandbox's own isolation,
        # not the grant's path facts. This leg's canary is a faithful instance of
        # that boundary, not an exception to it.
        self.record({
            "id": "K30e", "title": "boundary: an approved exec is not path-scoped by the grant",
            "kind": "derived", "status": "pass",
            "observed": "the canary wrote " + self.canary_path + ", which no grant fact covers",
            "why_allowed": "engine.go:1068 denies an ungranted path only when "
                           "fileOperation || descriptor.FilesystemWriteHint",
            "consequence": "the grant's path facts bound file tools; for an approved "
                           "exec the effective filesystem scope is the sandbox itself",
            "severity_for_review": "recorded for D03/D05 review; no production behaviour changed here",
        })

    def leg_k35(self):
        """Independent effect record: read the canary file back with the CLI,
        outside the daemon, and compare against the expected token."""
        proc = self.sandbox_exec(
            "K35a", "independent effect read-back: cat the canary file via direct CLI",
            ["/bin/cat", self.canary_path], retry_stalls=True,
            note="outside the daemon; the only writer of this file is the canary itself")
        got = proc.stdout.strip()
        check(got == self.canary_token,
              f"independent read-back mismatch: got {got[:16]!r}..., expected the runtime token")
        outcome = self.canary_response["outcome"]
        expected_digest = hashlib.sha256(self.canary_token.encode()).hexdigest()
        check(outcome.get("stdout_digest") == expected_digest,
              f"daemon stdout digest {outcome.get('stdout_digest')} != sha256(token)")
        # The readable CLI output is the CLI's own file, not the daemon's; the
        # raw stdout is no longer in the daemon's records.
        self.record({
            "id": "K35b", "title": "canary effect independently confirmed",
            "kind": "derived", "status": "pass",
            "independent_readback_source": "openshell sandbox exec (direct CLI)",
            "readback_matches_token": True,
            "daemon_stdout_digest_matches_sha256_of_token": True,
            "note": "远端文件由 canary 写入并由独立 CLI 读回；两端摘要一致",
        })

    # ---------- refusal legs ----------
    def leg_k40(self):
        """Approved for A, submitted as B: must be refused and must not burn the approval."""
        approved_timeout = 60
        params = self.canonical_task_params(
            self.target, ["/bin/echo", "o05v6-k40"], "", approved_timeout, 65536,
            self.expected_revision, self.expected_digest, [])
        decision = self.decide("K40a", "o05v6-k40-drift", params)
        self.hold_resolve("K40b", decision, approve=True,
                          note="human approves timeout=60s for /bin/echo")
        # Submission drifts one approved field; params stay as approved.
        body = self.task_body("o05v6-k40-drift", params, self.target,
                              ["/bin/echo", "o05v6-k40"], "", approved_timeout + 1, 65536,
                              self.expected_revision, self.expected_digest, [], decision)
        resp = self.submit_task("K40c", "refusal: parameter drift after approval",
                                body, expect=403,
                                note="must be 403 openshell_task_binding_mismatch")
        check(resp.get("reason_code") == "openshell_task_binding_mismatch",
              f"unexpected reason: {resp.get('reason_code')}")
        status = self.hold_status("K40d", decision, params, "o05v6-k40-drift-retry")
        check(status.get("http_status") != 200 or
              status.get("payload", {}).get("status") not in ("reserved", "completed"),
              f"approval was consumed by a refused submission: {status}")
        # Strongest form of the same claim: the human approval is still live, so
        # the *approved* body submitted afterwards must still execute. A refused
        # pre-reservation submission must not burn it.
        body_ok = self.task_body("o05v6-k40-drift", params, self.target,
                                 ["/bin/echo", "o05v6-k40"], "", approved_timeout, 65536,
                                 self.expected_revision, self.expected_digest, [], decision)
        resp_ok = self.submit_task(
            "K40e", "the same approval still executes after a refused submission",
            body_ok, expect=200,
            note="proves the drift refusal ran before the reservation consumed the approval")
        self.assert_task_executed("K40e", resp_ok)
        self.record({
            "id": "K40f", "title": "drift refused before the reservation; approval left unconsumed",
            "kind": "derived", "status": "pass",
            "hold_status_after_refusal": status.get("payload", {}).get("status"),
            "hold_status_http": status.get("http_status"),
            "approved_body_after_refusal": "200 / outcome.task_executed=yes",
        })

    def leg_k50(self):
        """Approved never given: submission must be refused."""
        params = self.canonical_task_params(
            self.target, ["/bin/echo", "o05v6-k50"], "", 60, 65536,
            self.expected_revision, self.expected_digest, [])
        decision = self.decide("K50a", "o05v6-k50-unapproved", params)
        # No hold_resolve: the human never approved.
        body = self.task_body("o05v6-k50-unapproved", params, self.target,
                              ["/bin/echo", "o05v6-k50"], "", 60, 65536,
                              self.expected_revision, self.expected_digest, [], decision)
        resp = self.submit_task("K50b", "refusal: submission for a hold that was never approved",
                                body, expect=(400, 403, 409, 410),
                                note="no human approval exists for this decision")
        self.record({
            "id": "K50c", "title": "unapproved submission refused",
            "kind": "derived", "status": "pass",
            "reason_code": resp.get("reason_code") or resp.get("error"),
            "http_status": resp.get("_http_status"),
        })

    def leg_k60(self):
        """Declared network target outside the grant facts: refused, never executed.

        An earlier draft of this leg expected the decide to hold and let a human
        approve the out-of-scope target first. That expectation was wrong, and
        the correction is the interesting part: internal/receipt/engine.go:1038-1042
        denies any host no network fact covers, so the decide itself is a deny
        and no approval is ever offered. That is strictly stronger than what the
        draft asserted -- a human cannot approve what the engine already refused.
        The binding layer's own backstop is not skipped by that, though: a deny
        decision still carries MatchedGrantID (engine.go:989), so it still passes
        the decision and grant lookup in validateOpenShellTaskExecutionBinding
        and reaches endpoint_not_authorized (openshell_task_binding.go:146-151).
        This leg therefore exercises both layers: the engine refuses the decide,
        and the handler refuses the submission -- at
        openshell_task_exec.go:172-177, i.e. *before* ReserveHoldExecution, so
        nothing was consumed and nothing ran.
        """
        # Earlier positive canaries carry a random token. The receipt engine
        # correctly taints that session as secret-bearing and denies *all*
        # later egress before the grant-scope check. This leg needs a fresh
        # session to exercise the distinct out-of-grant endpoint boundary;
        # the subsequent E-legs also start with that clean session.
        self.session = f"o05v6-d05-scope-{self.run_id}"
        rogue = "10.99.99.99:443"
        check(rogue not in self.grant_endpoints, "rogue endpoint unexpectedly covered by the grant")
        params = self.canonical_task_params(
            self.target, ["/bin/echo", "o05v6-k60"], "", 60, 65536,
            self.expected_revision, self.expected_digest, [rogue])
        decision = self.decide(
            "K60a", "o05v6-k60-endpoint", params, expect_action="deny",
            title="decide refuses a command declaring an out-of-grant egress target")
        reason = decision.get("reason") or ""
        check(rogue in reason and "not in grant" in reason,
              f"the refusal did not come from the network-scope check: {reason!r} "
              f"(reason_code {decision.get('reason_code')!r})")
        self.record({
            "id": "K60a1", "title": "engine-layer refusal of the out-of-grant endpoint",
            "kind": "derived", "status": "pass",
            "rogue_endpoint": rogue,
            "decision_action": decision.get("action"),
            "decision_reason_code": decision.get("reason_code"),
            "decision_reason": self.redact(reason),
            "note": "engine denies before the approval gate; no hold exists to approve",
        })
        # A deny must not be upgradable into an approval. /v1/hold/<id> scans the
        # signed chain for a receipt with ActionHold and answers 404 otherwise
        # (internal/server/server.go:577-596), so this is deterministic.
        held = self.http("K60b", "refusal: a denied decision cannot be approved",
                         "POST", f"/v1/hold/{decision['receipt_id']}",
                         {"approve": True, "actor_id": self.actor}, expect=404,
                         note="must be 404: there is no hold on a denied decision")
        check(held.get("error") == "held receipt not found",
              f"unexpected approval attempt outcome: {held}")
        body = self.task_body("o05v6-k60-endpoint", params, self.target,
                              ["/bin/echo", "o05v6-k60"], "", 60, 65536,
                              self.expected_revision, self.expected_digest, [rogue], decision)
        resp = self.submit_task("K60c", "refusal: network target outside the grant facts",
                                body, expect=403,
                                note="must be 403 endpoint_not_authorized")
        check(resp.get("reason_code") == "endpoint_not_authorized",
              f"unexpected reason: {resp.get('reason_code')}")
        out = resp.get("outcome") if isinstance(resp.get("outcome"), dict) else {}
        check(out.get("spawned") is not True and resp.get("task_executed") != "yes",
              f"a refused out-of-scope submission still executed: {resp}")
        self.record({
            "id": "K60d", "title": "out-of-scope egress refused at both layers; nothing ran",
            "kind": "derived", "status": "pass",
            "rogue_endpoint": rogue,
            "binding_layer_reason_code": resp.get("reason_code"),
            "submission_http": resp.get("_http_status"),
            "submission_reached_reservation": False,
            "note": "engine refused the decide AND the handler refused the submission "
                    "before ReserveHoldExecution",
        })

    def hold_status(self, step_id, decision, params, retry_tool_call_id):
        code, payload = self._raw_http_auth("POST", "/v1/hold-status", {
            "platform": "openclaw", "session_id": self.session, "agent_id": self.target,
            "tool": TASK_TOOL, "tool_call_id": retry_tool_call_id,
            "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"], "params": params,
        })
        self.write_raw(f"{step_id}.hold-status.json", json.dumps(payload, indent=2))
        return {"http_status": code, "payload": payload if isinstance(payload, dict) else {}}

    def leg_k70(self):
        """Revocation after approval: the reservation recheck must refuse."""
        params = self.canonical_task_params(
            self.target, ["/bin/echo", "o05v6-k70"], "", 60, 65536,
            self.expected_revision, self.expected_digest, [])
        decision = self.decide("K70a", "o05v6-k70-revoked", params)
        self.hold_resolve("K70b", decision, approve=True,
                          note="human approves; the grant is revoked immediately afterwards")
        revoked = self.http("K70c", "revoke the grant after the human approval",
                            "POST", "/v1/grants/" + self.grant_id + "/revoke",
                            {"expected_revision": self.grant_revision, "actor_id": self.actor},
                            expect=(200, 202, 409))
        body = self.task_body("o05v6-k70-revoked", params, self.target,
                              ["/bin/echo", "o05v6-k70"], "", 60, 65536,
                              self.expected_revision, self.expected_digest, [], decision)
        resp = self.submit_task("K70d", "refusal: grant revoked between approval and submission",
                                body, expect=(403, 409),
                                note="must be refused, never executed")
        out = resp.get("outcome") if isinstance(resp.get("outcome"), dict) else {}
        check(out.get("spawned") is not True, "revoked grant still spawned a process")
        self.record({
            "id": "K70e", "title": "revocation after approval blocked the execution",
            "kind": "derived", "status": "pass",
            "revoke_http_status": revoked.get("_status_if_any") if isinstance(revoked, dict) else None,
            "submission_reason_code": resp.get("reason_code") or resp.get("error"),
        })

    def leg_k80(self):
        """Required backend unreachable: 503, never a native fallback."""
        self.lost_root = Path(tempfile.mkdtemp(prefix="siq-o05v6-taskexec-lost-"))
        os.chmod(self.lost_root, 0o700)
        self.lost_home = self.lost_root / "home"
        self.lost_state = self.lost_root / "state"
        self.lost_workspace = self.lost_root / "workspace"
        for d in (self.lost_home, self.lost_state, self.lost_workspace):
            d.mkdir(mode=0o700)
        self.lost_env["HOME"] = str(self.lost_home)
        self.lost_env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(self.lost_state)
        lost_workspace = self.lost_workspace

        main_ctx = (self.endpoint, self.admin, self.token)
        self.cli("K80a", "init the lost-backend daemon's isolated state",
                 [str(self.binary), "init", "--port", str(self._free_port())],
                 env=self.lost_env)
        self.lost_proc, self.lost_log, self.lost_endpoint, self.lost_admin = self._serve(
            "K80b", self.lost_env, lost_workspace)
        self.keep_secret(self.lost_admin, "lost-backend-admin-session")
        self.endpoint, self.admin = self.lost_endpoint, self.lost_admin
        self.token = self.read_token(self.lost_state)
        try:
            admitted = self.http("K80c", "lost backend: admit the fixture skill", "POST",
                                 "/v1/admit", {"path": str(self.skill)})
            granted = self.http("K80d", "lost backend: create grant", "POST", "/v1/grants", {
                "admission_id": admitted["admission"]["admission_id"],
                "platform": "openclaw", "subject_id": self.target,
            })
            gid = granted["grant"]["grant_id"]
            gp = "/v1/grants/" + gid
            rev = granted["state_revision"]
            p = self.http("K80e", "lost backend: patch-desired", "POST", gp + "/patch-desired",
                          {"expected_revision": rev, "models": ["fixture-model"]})
            c = self.http("K80f", "lost backend: challenge", "POST", gp + "/challenge",
                          {"expected_revision": p["state_revision"], "actor_id": self.actor})
            nonce = c["challenge"]["nonce"]
            self.keep_secret(nonce, "lost-backend-challenge-nonce")
            a = self.http("K80g", "lost backend: approve", "POST", gp + "/approve", {
                "expected_revision": c["state_revision"], "actor_id": self.actor,
                "challenge_id": c["challenge"]["challenge_id"], "nonce": nonce,
            })
            self.http("K80h", "lost backend: deploy", "POST", gp + "/deploy",
                      {"expected_revision": a["state_revision"]})
            probe = self.http("K80i", "lost backend: probe reports the backend unavailable",
                              "GET", "/v1/openshell/probe", expect=(200, 503))
            self.record({
                "id": "K80j", "title": "lost-backend daemon reports the required backend down",
                "kind": "derived", "status": "pass",
                "probe_keys": sorted(probe) if isinstance(probe, dict) else None,
                "probe_tier": (probe.get("platform") or {}).get("tier") if isinstance(probe, dict) else None,
            })
            resp = self.http("K80k", "refusal: required backend unreachable (no native fallback)",
                             "POST", "/v1/openshell/task-executions",
                             {"schema_version": TASK_SCHEMA, "platform": "openclaw",
                              "session_id": self.session, "agent_id": self.target,
                              "tool": TASK_TOOL, "original_tool_call_id": "o05v6-k80",
                              "retry_tool_call_id": "o05v6-k80-retry",
                              "action_id": "act-k80", "decision_receipt_id": "dec-k80",
                              "params": {}, "target": self.target,
                              "argv": ["/bin/echo", "o05v6-k80"],
                              "policy_revision": self.expected_revision or "1",
                              "policy_digest": self.expected_digest or "0" * 64,
                              "network_targets": []},
                             token=self.token, expect=503,
                             note="503 before any authorization is consumed; never falls back to native")
            check("native" in json.dumps(resp, ensure_ascii=False) or
                  "L3" in json.dumps(resp, ensure_ascii=False),
                  f"503 body should name the missing required backend: {resp}")
        finally:
            self.endpoint, self.admin, self.token = main_ctx

    def leg_k90(self):
        self.serve_stop("K90a", self.proc, self.serve_log)
        self.serve_stop("K90b", self.lost_proc, self.lost_log)
        after = self.policy_read("K90c")
        check(after["revision"] == self.base_revision,
              f"the whole journey changed the sandbox policy: {self.base_revision} -> {after['revision']}")
        self.record({"id": "K90d", "title": "sandbox policy untouched by the whole task journey",
                     "kind": "derived", "status": "pass",
                     "sandbox_revision": after["revision"]})

    # ---------- report ----------
    def report(self):
        passed = sum(1 for s in self.steps if s.get("status") == "pass")
        failed = sum(1 for s in self.steps if s.get("status") == "fail")
        doc = {
            "schema": "o05v6-d02-taskexec-journey/v1",
            "scope": "development-and-isolated-verification",
            "meta": self.meta,
            "summary": {"pass": passed, "fail": failed, "total": len(self.steps)},
            "steps": self.steps,
            "finished_at": now_iso(),
        }

        def public(value):
            if isinstance(value, str):
                for secret, label in self.secrets.items():
                    if secret in value:
                        value = value.replace(secret, f"<{label}>")
                if self.lost_root:
                    value = value.replace(str(self.lost_root), "<lost-backend-root>")
                return value.replace(str(REPO), "<repo>")
            if isinstance(value, dict):
                return {k: public(v) for k, v in value.items()}
            if isinstance(value, list):
                return [public(v) for v in value]
            return value

        out = self.out / "d02-taskexec-journey.json"
        out.write_text(json.dumps(public(doc), indent=2, ensure_ascii=False, default=str))
        print(f"\nwrote {out} ({passed} pass / {failed} fail)")
        return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--expected-sha256", required=True, help="candidate SHA256")
    ap.add_argument("--env-script", required=True,
                    help="private env script exporting SIQ_OPENSHELL_BIN + XDG dirs")
    ap.add_argument("--gateway-endpoint", default="https://127.0.0.1:17671")
    ap.add_argument("--lost-endpoint", default="https://127.0.0.1:1")
    ap.add_argument("--target", required=True, help="explicitly owned writable test target")
    ap.add_argument("--fact-endpoint", required=True,
                    help="the sandbox's own egress gateway:port, declared as policy content only")
    ap.add_argument("--out", required=True, help="evidence directory")
    args = ap.parse_args()

    j = Journey(args)
    rc = 1
    try:
        rc = j.run()
    except Exception as exc:  # noqa: BLE001 -- record failed evidence, then rethrow or exit nonzero
        trace = traceback.format_exc()
        print(f"JOURNEY FAILED: {j.redact(exc)}\n{j.redact(trace)}", file=sys.stderr)
        j.record({"id": "ABORT", "title": "journey aborted", "kind": "derived",
                  "status": "fail", "detail": str(exc), "leg": getattr(j, "current_leg", "?"),
                  "traceback": trace})
        j.report()
        if j.proc is not None:
            j.serve_stop("ABORT-stop", j.proc, j.serve_log)
        if j.lost_proc is not None:
            j.serve_stop("ABORT-stop-lost", j.lost_proc, j.lost_log)
        rc = 1
    finally:
        for proc in (j.proc, j.lost_proc):
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
        shutil.rmtree(j.root, ignore_errors=True)
        if j.lost_root:
            shutil.rmtree(j.lost_root, ignore_errors=True)
    sys.exit(rc)


if __name__ == "__main__":
    main()
