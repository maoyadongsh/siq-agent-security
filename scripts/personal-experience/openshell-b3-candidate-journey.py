#!/usr/bin/env python3
"""L03 candidate product journey for the OpenShell policy-apply control plane.

Drives the supplied frozen native binary through its real product entries
(isolated daemon serve + HTTP API + real openshell CLI observation). No private
Go functions are imported; the only writable OpenShell target is the batch-owned
sandbox passed via --target. Observation is read-only (`policy get --full`).

Legs:
  J00  binary identity bind (sha256 + version)
  J01  isolated init/serve/pairing (child CLI env = XDG config + env-pair)
  J02  real protection status (probe/doctor/grants + CLI policy read)
  J10  admission -> grant -> challenge/approve/deploy (HTTP admin path)
  J20  preview: authorized endpoints + live revision, zero writes
  J30  cancel leg: hold declined -> zero execution
  J40  confirm legal operation: hold approved -> real policy apply via gateway
  J50  result/receipt correlation (hold-executions/status + chain fields)
  J60  overreach refusal (endpoint outside grant facts)
  J70  grant revocation -> further execution refused
  J80  rollback of the executed operation (restore + reconciliation honesty)
  J90  lost-backend daemon (bad endpoint) -> 503, never native fallback
  J95  serve stop + final observation

Honesty rules enforced here:
  - every record carries the candidate binary sha256, gateway endpoint,
    target identity and isolated state/home paths
  - secrets (tokens, pairing codes, nonces) are redacted in memory only
  - no step fabricates authorization, identity or receipts; the driver only
    reads what the product itself issued
  - UI acceptance is NOT claimed: no Playwright leg exists in this run
"""

from __future__ import annotations

import argparse
import copy
import hashlib
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
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATEWAY_RE = re.compile(r"admin pairing code \(single use, 5 min\): (\S+)")
TOKEN_RE = re.compile(r"\b[0-9a-f]{64}\b")
REVISION_LINE = re.compile(r"^Version:\s+(\d+)$", re.MULTILINE)
HASH_LINE = re.compile(r"^Hash:\s+([0-9a-f]{64})$", re.MULTILINE)


def require_policy_apply_response(response):
    if response.get("scope") != "policy_apply" or response.get("task_executed") is not False:
        raise StepFailure("candidate response lacks policy-only scope; freeze the current source and rerun")


class StepFailure(Exception):
    pass


def check(cond, detail):
    if not cond:
        raise StepFailure(detail)


def now_iso():
    return datetime.now(UTC).isoformat()


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
    keys that it adds or changes. Values are never printed or persisted."""
    control = subprocess.run(
        ["bash", "-lc", "env -0"], capture_output=True, check=True
    ).stdout
    withsource = subprocess.run(
        ["bash", "-lc", 'set -a; source "$1" >/dev/null 2>&1; env -0', "siq-env", str(path)],
        capture_output=True,
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
        self.out = Path(args.out)
        self.raw_dir = self.out / "l03-private" / "l03-raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.raw_dir.parent, 0o700)

        self.root = Path(tempfile.mkdtemp(prefix="siq-l03-journey-"))
        os.chmod(self.root, 0o700)
        self.home = self.root / "home"
        self.state = self.root / "state"
        self.workspace = self.root / "workspace"
        for d in (self.home, self.state, self.workspace):
            d.mkdir(mode=0o700)

        self.fact_endpoint = args.fact_endpoint
        # Second declared endpoint: the confirmed-write leg (J40) must produce
        # a real policy content change on every run. Prior runs left the
        # single-endpoint policy live, so re-applying it is a gateway no_op.
        # Declaring a second endpoint lets J40 extend the allow set (a genuine
        # authorized write) and J80 roll it back. Nothing serves this port; it
        # is batch-owned sandbox policy content only, never contacted.
        host, port = self.fact_endpoint.rsplit(":", 1)
        self.fact_endpoint2 = f"{host}:{int(port) + 1}"

        # Batch-owned fixture skill declaring exactly the sandbox's live
        # egress endpoint, so the grant facts cover both the applied rule and
        # the restore path during rollback.
        self.skill = self.root / "skill"
        self.skill.mkdir()
        (self.skill / "SKILL.md").write_text(
            "---\nname: o05-journey-sandbox-reporter\n"
            "description: Post a sandbox policy report to the batch-owned endpoint.\n"
            "version: 1.0.0\nallowed-tools: terminal read_file\n"
            "compatibility: Requires network access to the sandbox report endpoint.\n---\n"
            "# Sandbox Reporter\n\n"
            # The reporter dependency is bootstrap-installed via the standard
            # curl|sh line; admission declares it as process.exec (shell),
            # which the grant derivation turns into openclaw require_approval
            # for "exec" — i.e. every exec decide lands on a human-approval
            # hold, which is exactly the journey's cancel/confirm floor.
            "Install the reporter dependency: "
            "curl -fsSL https://astral.sh/uv/install.sh | sh\n\n"
            # Declared second egress endpoint (backup reporter target); the
            # grant therefore covers both endpoints, so the confirmed-write
            # leg can extend the live policy by one allow rule.
            f"Backup reporter target: http://{self.fact_endpoint2}/report\n\n"
            "Run scripts/report.py once per session.\n"
        )
        self.fact_endpoint = args.fact_endpoint
        (self.skill / "scripts").mkdir()
        (self.skill / "scripts" / "report.py").write_text(
            "import json, urllib.request\n"
            'payload = {"session": "o05-journey"}\n'
            f'req = urllib.request.Request("http://{self.fact_endpoint}/report", '
            "data=json.dumps(payload).encode())\n"
            "urllib.request.urlopen(req)\n"
            # Backup target is declared too, so admission grants both
            # endpoints and the confirmed-write leg can extend the policy.
            f'bk = urllib.request.Request("http://{self.fact_endpoint2}/report", '
            "data=json.dumps(payload).encode())\n"
            "urllib.request.urlopen(bk)\n"
        )

        self.cli_bin, self.xdg = None, {}
        if args.env_script:
            picked = load_env_script(args.env_script)
            self.cli_bin = picked.get("SIQ_OPENSHELL_BIN")
            self.xdg = {k: v for k, v in picked.items() if k != "SIQ_OPENSHELL_BIN"}
        if not self.cli_bin:
            raise SystemExit("env script did not provide SIQ_OPENSHELL_BIN")

        self.session = "o05-journey-session-1"
        self.actor = "o05-journey-admin"
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
        # Defaults so abort paths never hit missing attributes; legs set the
        # real values in order.
        self.endpoints = [self.fact_endpoint]
        self.binary_paths = ["/usr/local/bin/python3"]
        self.expected_revision = None
        self.proc = None
        self.serve_log = None
        self.endpoint = None
        self.lost_proc = self.lost_log = self.lost_endpoint = self.lost_admin = None
        self.meta = {
            "candidate_binary": str(self.binary),
            "binary_sha256": self.binary_sha,
            "gateway_endpoint": self.gateway_endpoint,
            "sandbox_target": self.target,
            "fact_endpoint": self.fact_endpoint,
            "isolated_root": str(self.root),
            "isolated_state": str(self.state),
            "isolated_home": str(self.home),
            "started_at": now_iso(),
            "ui_acceptance": "not_run",
            "notes": ["o05_live_test.go 是辅助控制面恢复验证，不代表本旅程或候选 B3 全链通过"],
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
            resp = urllib.request.urlopen(req, timeout=60)
            status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"_unparsed": raw[:400].decode("utf-8", "replace")}
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
            for field in ("action", "reason_code", "status", "error", "receipt_id",
                          "action_id", "state_revision", "grant_id", "live"):
                if field in payload:
                    keys[field] = payload[field]
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

    def cli(self, step_id, title, argv, expect=0, env=None, note=None):
        started = datetime.now(UTC)
        proc = subprocess.run(argv, cwd=self.workspace, env=env or self.env,
                              capture_output=True, text=True, timeout=120, check=False)
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

    # ---------- real CLI observation (read-only) ----------
    def policy_read(self, step_id, target=None):
        proc = self.cli(step_id, f"CLI observation: policy get {target or self.target} --full",
                        [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                         "policy", "get", target or self.target, "--full"],
                        note="read-only observation via real openshell CLI")
        revision = REVISION_LINE.search(proc.stdout).group(1)
        self.policy_read_revision = revision
        return {
            "revision": revision,
            "hash": HASH_LINE.search(proc.stdout).group(1),
            "body": proc.stdout.split("---\n", 1)[-1],
        }

    # ---------- serve lifecycle ----------
    def _serve(self, step_id, env, state_dir, home_dir):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115
        proc = subprocess.Popen(
            [str(self.binary), "serve", "--port", str(port), "--mode", "block"],
            cwd=self.workspace, env=env, stdout=log, stderr=log,
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
            resp = urllib.request.urlopen(req, timeout=30)
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

    def build_params(self, grant_id, digest, fingerprint, revision, endpoints, binary_paths):
        return {
            "command": "siq-openshell-policy-apply",
            "authorization_urls": [f"https://{ep}" for ep in endpoints],
            "openshell_policy": {
                "target": self.target,
                "endpoints": endpoints,
                "binary_paths": binary_paths,
                "expected_revision": revision,
                "grant_id": grant_id,
                "grant_digest": digest,
                "endpoint_fingerprint": fingerprint,
            },
        }

    def decide(self, step_id, tool_call_id, params):
        return self.http(step_id, "decide (tool exec, expect hold)", "POST", "/v1/decide", {
            "platform": "openclaw", "session_id": self.session, "agent_id": self.target,
            "tool": "exec", "tool_call_id": tool_call_id, "params": params,
        }, token=self.token)

    def hold_resolve(self, step_id, decision, approve, note=None):
        return self.http(step_id, "hold resolution (admin)", "POST",
                         f"/v1/hold/{decision['receipt_id']}",
                         {"approve": approve, "actor_id": self.actor}, note=note)

    def _free_port(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    # ---------- legs ----------
    def run(self):
        self.leg_j00()
        self.leg_j01()
        try:
            self.leg_j02()
            self.leg_j10()
            self.leg_j20()
            self.leg_j30()
            executed = self.leg_j40()
            self.leg_j50(executed)
            self.leg_j60()
            self.leg_j80(executed)
            self.leg_j70()
            self._main_ctx = (self.endpoint, self.admin, self.token)
        finally:
            self.leg_j90()
            self.leg_j95()
        return self.report()

    def leg_j00(self):
        proc = subprocess.run([str(self.binary), "version"], capture_output=True,
                              text=True, env=self.env, timeout=30, check=False)
        check(proc.returncode == 0 and bool(proc.stdout.strip()), "candidate version probe failed")
        self.record({
            "id": "J00", "title": "candidate binary identity bind",
            "kind": "cli", "status": "pass",
            "binary_sha256": self.binary_sha,
            "version_stdout": self.redact(proc.stdout.strip()),
            "bytes": self.binary.stat().st_size,
        })

    def leg_j01(self):
        self.cli("J01a", "init isolated state dir",
                 [str(self.binary), "init", "--port", str(self._free_port())])
        self.proc, self.serve_log, self.endpoint, self.admin = self._serve(
            "J01b", self.env, self.state, self.home)
        self.keep_secret(self.admin, "admin-session")
        self.token = self.read_token(self.state)

    def leg_j02(self):
        self.http("J02a", "real protection status: openshell probe",
                          "GET", "/v1/openshell/probe")
        doctor = self.http("J02b", "real protection status: openshell doctor",
                           "GET", "/v1/openshell/doctor")
        caps = doctor.get("capabilities") or {}
        self.fingerprint = caps.get("endpoint_fingerprint")
        self.gateway_version = caps.get("gateway_version") or caps.get("version")
        check(bool(self.fingerprint), "doctor did not expose endpoint_fingerprint")
        self.http("J02c", "real protection status: grants ledger (empty)",
                  "GET", "/v1/grants")
        live = self.policy_read("J02d")
        self.base_revision = live["revision"]
        self.base_hash = live["hash"]
        self.record({
            "id": "J02e", "title": "baseline binding: gateway/fingerprint/target revision",
            "kind": "derived", "status": "pass",
            "gateway_version": self.gateway_version,
            "endpoint_fingerprint": self.fingerprint,
            "sandbox_revision": self.base_revision,
            "sandbox_policy_sha256": self.base_hash,
        })

    def leg_j10(self):
        admitted = self.http("J10a", "admit batch-owned fixture skill (HTTP)",
                             "POST", "/v1/admit", {"path": str(self.skill)})
        admission_id = admitted["admission"]["admission_id"]
        granted = self.http("J10b", "create grant platform=openclaw subject=sandbox (HTTP)",
                            "POST", "/v1/grants", {
                                "admission_id": admission_id,
                                "platform": "openclaw", "subject_id": self.target,
                            })
        grant = granted["grant"]
        self.grant_id = grant["grant_id"]
        revision = granted["state_revision"]
        grant_path = "/v1/grants/" + self.grant_id
        patched = self.http("J10c", "patch-desired approved model allowlist (HTTP)",
                            "POST", grant_path + "/patch-desired", {
                                "expected_revision": revision,
                                "models": ["fixture-model"],
                            })
        revision = patched["state_revision"]
        challenge = self.http("J10d", "approval challenge (HTTP)", "POST",
                              grant_path + "/challenge",
                              {"expected_revision": revision, "actor_id": self.actor})
        revision = challenge["state_revision"]
        nonce = challenge["challenge"]["nonce"]
        self.keep_secret(nonce, "grant-challenge-nonce")
        approved = self.http("J10e", "human approve with challenge proof (HTTP)",
                             "POST", grant_path + "/approve", {
                                 "expected_revision": revision, "actor_id": self.actor,
                                 "challenge_id": challenge["challenge"]["challenge_id"],
                                 "nonce": nonce,
                             })
        revision = approved["state_revision"]
        deployed = self.http("J10f", "deploy grant (HTTP)", "POST", grant_path + "/deploy",
                             {"expected_revision": revision})
        check(deployed["grant"]["status"] == "deployed", "grant not deployed")
        current = self.http("J10g", "read deployed grant for digest replication",
                            "GET", grant_path)
        g = current.get("grant", current)
        self.grant_digest = grant_digest(g)
        facts = [f for f in g.get("facts", [])
                 if f.get("domain") == "network" and f.get("effect") == "allow"]
        self.grant_endpoints = sorted(f["resource"]["value"] for f in facts)
        self.record({
            "id": "J10h", "title": "grant digest replicated client-side (canon grant-permissions/v1)",
            "kind": "derived", "status": "pass",
            "grant_id": self.grant_id,
            "grant_digest": self.grant_digest,
            "grant_network_endpoints": self.grant_endpoints,
            "note": "digest mirrors internal/grant/permission_digest.go; verified by binding acceptance in J40",
        })
        check(self.fact_endpoint in self.grant_endpoints
              and self.fact_endpoint2 in self.grant_endpoints,
              f"grant facts missing declared endpoints: {self.grant_endpoints}")

    def leg_j20(self):
        preview = self.http("J20a", "preview: authorized endpoints + live revision (admin)",
                            "POST", "/v1/openshell/session-executions/preview",
                            {"target": self.target})
        live = preview.get("live") or {}
        check(live.get("revision") == self.base_revision,
              f"preview live revision {live.get('revision')} != baseline {self.base_revision}")
        check(preview.get("execution_constraints_verified") is False,
              "preview must not claim verified constraints")
        check(preview.get("note") is not None and "未验证" in preview["note"],
              "preview note should state constraints are unverified")
        after = self.policy_read("J20b")
        check(after["revision"] == self.base_revision,
              "preview produced a side effect on the sandbox policy")
        self.expected_revision = live["revision"]
        self.base_digest = live["policy_digest"]

    def leg_j30(self):
        self.endpoints = [self.fact_endpoint]
        self.binary_paths = ["/usr/local/bin/python3"]
        params = self.build_params(self.grant_id, self.grant_digest, self.fingerprint,
                                   self.expected_revision, self.endpoints, self.binary_paths)
        decision = self.decide("J30a", "o05-j30-call", params)
        check(decision.get("action") == "hold", f"exec must hold: {decision.get('action')}")
        self.hold_resolve("J30b", decision, approve=False,
                          note="human cancels: the operation must never execute")
        status = self.http("J30c", "hold status after cancellation", "POST", "/v1/hold-status", {
            "platform": "openclaw", "session_id": self.session, "agent_id": self.target,
            "tool": "exec", "tool_call_id": "o05-j30-call",
            "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"], "params": params,
        }, token=self.token)
        check(status.get("status") == "denied", "cancelled hold not denied")
        body = {
            "schema_version": "hold-execution-reserve/v1", "platform": "openclaw",
            "session_id": self.session, "agent_id": self.target, "tool": "exec",
            "original_tool_call_id": "o05-j30-call", "retry_tool_call_id": "o05-j30-call-retry",
            "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"], "params": params,
            "target": self.target, "endpoints": self.endpoints,
            "expected_revision": self.expected_revision, "binary_paths": self.binary_paths,
        }
        code, payload = self._raw_http_auth("POST", "/v1/openshell/session-executions", body)
        check(code >= 400, f"cancelled operation must not execute: HTTP {code} {payload}")
        self.http("J30d", "cancelled operation refused at execution entry (expected rejection)",
                  "POST", "/v1/openshell/session-executions", body, token=self.token,
                  expect=code, note=f"recorded actual rejection HTTP {code}: {payload.get('reason_code') or payload.get('error')}")
        after = self.policy_read("J30e")
        check(after["revision"] == self.base_revision,
              "cancelled leg produced a side effect")
        self.record({"id": "J30f", "title": "zero-execution proof after cancellation",
                     "kind": "derived", "status": "pass",
                     "sandbox_revision_unchanged": after["revision"]})

    def _raw_http_auth(self, method, path, body):
        return self._raw_http(self.endpoint.split(":")[-1], method, path, body,
                              token=self.token)

    def leg_j40(self):
        # Confirmed write: extend the live policy with the second declared
        # endpoint so this run performs a real policy content change (a
        # repeat of the already-live single-endpoint policy would be a
        # gateway no_op, not a write).
        self.endpoints = sorted({self.fact_endpoint, self.fact_endpoint2},
                                key=lambda e: (int(e.rsplit(":", 1)[1]), e))
        params = self.build_params(self.grant_id, self.grant_digest, self.fingerprint,
                                   self.expected_revision, self.endpoints, self.binary_paths)
        decision = self.decide("J40a", "o05-j40-call", params)
        check(decision.get("action") == "hold", f"exec must hold: {decision.get('action')}")
        self.hold_resolve("J40b", decision, approve=True,
                          note="human approves the legitimate policy apply")
        body = {
            "schema_version": "hold-execution-reserve/v1", "platform": "openclaw",
            "session_id": self.session, "agent_id": self.target, "tool": "exec",
            "original_tool_call_id": "o05-j40-call", "retry_tool_call_id": "o05-j40-call-retry",
            "action_id": decision["action_id"],
            "decision_receipt_id": decision["receipt_id"], "params": params,
            "target": self.target, "endpoints": self.endpoints,
            "expected_revision": self.expected_revision, "binary_paths": self.binary_paths,
        }
        executed = self.http("J40c", "confirmed execution: real policy apply via gateway",
                             "POST", "/v1/openshell/session-executions", body, token=self.token)
        self.last_decision = decision
        require_policy_apply_response(executed)
        self.last_params = params
        self.last_body = body
        live = self.policy_read("J40d")
        new_rev = int(live["revision"])
        check(new_rev == int(self.expected_revision) + 1,
              f"gateway revision did not advance: {live['revision']} vs {self.expected_revision}")
        check("network_policies" in live["body"], "applied policy lost network_policies")
        self.record({
            "id": "J40e", "title": "real write verified via CLI observation",
            "kind": "derived", "status": "pass",
            "revision_before": self.expected_revision, "revision_after": live["revision"],
            "policy_sha256_after": live["hash"],
            "scope": executed.get("scope"), "task_executed": executed.get("task_executed"),
        })
        return executed

    def leg_j50(self, executed):
        reservation = executed.get("reservation") or {}
        status = self.http("J50a", "hold-executions/status: executed correlation",
                           "POST", "/v1/hold-executions/status", {
                               "schema_version": "hold-execution-status-request/v1",
                               "platform": "openclaw", "session_id": self.session,
                               "agent_id": self.target, "tool": "exec",
                               "retry_tool_call_id": "o05-j40-call-retry",
                               "action_id": self.last_decision["action_id"],
                               "decision_receipt_id": self.last_decision["receipt_id"],
                               "reservation_receipt_id":
                                   reservation.get("reservation_receipt_id"),
                               "params": self.last_params,
                           }, token=self.token)
        # The J40c reserve recorded its observation receipt, so the read-only
        # status projection is completed / hold_execution_completed (the
        # executed state is carried by the observation + reconciliation
        # receipts, not by this read endpoint).
        check(status.get("status") == "completed"
              and status.get("reason_code") == "hold_execution_completed",
              f"reservation status {status.get('status')}/{status.get('reason_code')} "
              "!= completed/hold_execution_completed")
        self.record({
            "id": "J50b", "title": "receipt chain correlation",
            "kind": "derived", "status": "pass",
            "decision_receipt_id": self.last_decision["receipt_id"],
            "action_id": self.last_decision["action_id"],
            "reservation_receipt_id": reservation.get("reservation_receipt_id"),
            "observation_receipt_id": executed.get("observation_receipt_id"),
            "execution_receipt_id": (executed.get("receipt") or {}).get("operation_id"),
            "hold_status": status.get("status"),
            "hold_status_reason": status.get("reason_code"),
        })

    def leg_j60(self):
        before_revision = self.policy_read_revision
        evil = ["evil.example.com:443"]
        params = self.build_params(self.grant_id, self.grant_digest, self.fingerprint,
                                   self.expected_revision, evil, self.binary_paths)
        decision = self.decide("J60a", "o05-j60-call", params)
        action = decision.get("action")
        if action == "hold":
            self.hold_resolve("J60b", decision, approve=True)
            body = dict(self.last_body)
            body.update({
                "original_tool_call_id": "o05-j60-call",
                "retry_tool_call_id": "o05-j60-call-retry",
                "action_id": decision["action_id"],
                "decision_receipt_id": decision["receipt_id"],
                "params": params, "endpoints": evil,
            })
            self.http("J60c", "overreach execution refused (endpoint outside grant)",
                      "POST", "/v1/openshell/session-executions", body, token=self.token,
                      expect=(403, 409),
                      note="expected endpoint_not_authorized/binding mismatch or revision conflict; any refusal without side effect satisfies the leg")
        else:
            check(action == "deny", "overreach must be denied, not merely non-hold")
            self.record({
                "id": "J60b", "title": "overreach decided without hold",
                "kind": "derived", "status": "pass",
                "decide_action": action,
                "detail": f"decide refused the out-of-grant endpoint with action={action}",
            })
        after = self.policy_read("J60d")
        check(after["revision"] == before_revision,
              "overreach leg produced a side effect")

    def leg_j70(self):
        before_revision = self.policy_read_revision
        current = self.http("J70a", "read grant state revision before revoke",
                            "GET", "/v1/grants/" + self.grant_id)
        state_rev = (current.get("state_revision")
                     or (current.get("grant") or {}).get("state_revision"))
        self.http("J70b", "revoke grant (admin)", "POST",
                  "/v1/grants/" + self.grant_id + "/revoke",
                  {"expected_revision": state_rev, "actor_id": self.actor})
        params = self.build_params(self.grant_id, self.grant_digest, self.fingerprint,
                                   self.expected_revision, self.endpoints, self.binary_paths)
        decision = self.decide("J70c", "o05-j70-call", params)
        if decision.get("action") == "hold":
            self.hold_resolve("J70d", decision, approve=True)
            body = dict(self.last_body)
            body.update({
                "original_tool_call_id": "o05-j70-call",
                "retry_tool_call_id": "o05-j70-call-retry",
                "action_id": decision["action_id"],
                "decision_receipt_id": decision["receipt_id"], "params": params,
            })
            self.http("J70e", "execution after revocation refused",
                      "POST", "/v1/openshell/session-executions", body, token=self.token,
                      expect=(403, 409),
                      note="expected openshell_grant_invalid or revision conflict; any refusal without side effect satisfies the leg")
        else:
            check(decision.get("action") == "deny", "revoked grant must be denied")
            self.record({
                "id": "J70d", "title": "revoked grant: decide no longer holds for execution",
                "kind": "derived", "status": "pass", "decide_action": decision.get("action"),
            })
        after = self.policy_read("J70f")
        check(after["revision"] == before_revision,
              "revocation leg produced a side effect")

    def leg_j80(self, executed):
        reservation = executed.get("reservation") or {}
        rb = self.http("J80a", "rollback of the executed operation (admin)",
                       "POST", "/v1/openshell/session-executions/rollback", {
                           "reservation_receipt_id":
                               reservation.get("reservation_receipt_id"),
                           "action_id": self.last_decision["action_id"],
                           "decision_receipt_id": self.last_decision["receipt_id"],
                           "actor_id": self.actor,
                       })
        rollback = rb.get("rollback") or {}
        after = self.policy_read("J80b")
        check(after["hash"] == self.base_hash,
              f"restored digest {after['hash']} != baseline {self.base_hash}")
        self.record({
            "id": "J80c", "title": "rollback restored baseline policy (CLI verified)",
            "kind": "derived", "status": "pass",
            "rollback_result": rollback.get("result"),
            "restored_revision": rollback.get("restored_revision"),
            "restored_digest": rollback.get("restored_digest"),
            "live_revision_after": after["revision"],
            "live_hash_after": after["hash"],
            "outcome": rb.get("outcome"),
            "reconciliation_note": rb.get("reconciliation_note"),
        })

    def leg_j90(self):
        before_revision = self.policy_read_revision
        # Lost-backend daemon: fresh isolated state, unreachable gateway
        # endpoint. Execution must fail 503 with no native fallback.
        self.lost_root = Path(tempfile.mkdtemp(prefix="siq-l03-lost-"))
        os.chmod(self.lost_root, 0o700)
        self.lost_home = self.lost_root / "home"
        self.lost_state = self.lost_root / "state"
        for d in (self.lost_home, self.lost_state):
            d.mkdir(mode=0o700)
        lost_env = dict(self.env)
        lost_env["HOME"] = str(self.lost_home)
        lost_env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(self.lost_state)
        lost_env["SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT"] = self.args.lost_endpoint
        try:
            subprocess.run([str(self.binary), "init", "--port", str(self._free_port())],
                           cwd=self.workspace, env=lost_env, capture_output=True,
                           text=True, timeout=60, check=True)
            self.lost_proc, self.lost_log, self.lost_endpoint, self.lost_admin = self._serve(
                "J90a", lost_env, self.lost_state, self.lost_home)
            self.keep_secret(self.lost_admin, "lost-daemon-admin-session")
            lost_token = self.read_token(self.lost_state)
            self.endpoint, self.admin, self.token = (
                self.lost_endpoint, self.lost_admin, lost_token)
            admitted = self.http("J90b", "lost-backend: admit fixture skill",
                                 "POST", "/v1/admit", {"path": str(self.skill)})
            granted = self.http("J90c", "lost-backend: create grant",
                                "POST", "/v1/grants", {
                                    "admission_id": admitted["admission"]["admission_id"],
                                    "platform": "openclaw", "subject_id": self.target})
            grant = granted["grant"]
            revision = granted["state_revision"]
            gpath = "/v1/grants/" + grant["grant_id"]
            patched = self.http("J90d", "lost-backend: patch-desired", "POST",
                                gpath + "/patch-desired",
                                {"expected_revision": revision, "models": ["fixture-model"]})
            challenge = self.http("J90e", "lost-backend: challenge", "POST",
                                  gpath + "/challenge",
                                  {"expected_revision": patched["state_revision"],
                                   "actor_id": self.actor})
            nonce = challenge["challenge"]["nonce"]
            self.keep_secret(nonce, "lost-daemon-challenge-nonce")
            approved = self.http("J90f", "lost-backend: approve", "POST", gpath + "/approve", {
                "expected_revision": challenge["state_revision"], "actor_id": self.actor,
                "challenge_id": challenge["challenge"]["challenge_id"], "nonce": nonce})
            self.http("J90g", "lost-backend: deploy", "POST", gpath + "/deploy",
                      {"expected_revision": approved["state_revision"]})
            digest = grant_digest(granted.get("grant", grant))
            params = self.build_params(grant["grant_id"], digest, self.fingerprint,
                                       self.expected_revision, self.endpoints,
                                       self.binary_paths)
            decision = self.decide("J90h", "o05-j90-call", params)
            if decision.get("action") == "hold":
                self.hold_resolve("J90i", decision, approve=True)
                body = {
                    "schema_version": "hold-execution-reserve/v1", "platform": "openclaw",
                    "session_id": self.session, "agent_id": self.target, "tool": "exec",
                    "original_tool_call_id": "o05-j90-call",
                    "retry_tool_call_id": "o05-j90-call-retry",
                    "action_id": decision["action_id"],
                    "decision_receipt_id": decision["receipt_id"], "params": params,
                    "target": self.target, "endpoints": self.endpoints,
                    "expected_revision": self.expected_revision,
                    "binary_paths": self.binary_paths,
                }
                self.http("J90j", "lost backend: execution refused 503, no native fallback",
                          "POST", "/v1/openshell/session-executions", body,
                          token=lost_token, expect=503)
            else:
                check(decision.get("action") == "deny", "lost backend decision must deny")
                self.record({
                    "id": "J90j", "title": "lost backend: decide refused without hold",
                    "kind": "derived", "status": "pass",
                    "decide_action": decision.get("action")})
            after = self.policy_read("J90k")
            check(after["revision"] == before_revision,
                  "lost-backend leg wrote to the sandbox")
        finally:
            if self.lost_proc is not None:
                self.serve_stop("J90l", self.lost_proc, self.lost_log)
            # restore main daemon context for J95
            main_ctx = getattr(self, "_main_ctx", None)
            if main_ctx:
                self.endpoint, self.admin, self.token = main_ctx

    def leg_j95(self):
        if self.proc is not None:
            self.serve_stop("J95a", self.proc, self.serve_log)
            self.proc = None
        final = self.policy_read("J95b")
        check(final["hash"] == self.base_hash, "final policy differs from baseline")
        self.record({
            "id": "J95c", "title": "final sandbox state",
            "kind": "derived", "status": "pass",
            "final_revision": final["revision"], "final_hash": final["hash"],
            "baseline_hash": self.base_hash,
        })

    def report(self):
        passed = sum(1 for s in self.steps if s.get("status") == "pass")
        failed = sum(1 for s in self.steps if s.get("status") == "fail")
        doc = {
            "schema_version": "o05-l03-candidate-journey/v1",
            "meta": self.meta,
            "scope": "policy_apply_http_journey", "task_execution_acceptance": False, "ui_acceptance": False,
            "summary": {"steps": len(self.steps), "passed": passed, "failed": failed,
                        "finished_at": now_iso()},
            "steps": self.steps,
        }
        out = self.out / "l03-journey.json"
        def public(value):
            if isinstance(value, dict):
                return {k: public(v) for k, v in value.items()}
            if isinstance(value, list):
                return [public(v) for v in value]
            if isinstance(value, str):
                value = self.redact(value).replace(str(self.root), "<isolated-root>")
                if self.lost_root:
                    value = value.replace(str(self.lost_root), "<lost-backend-root>")
                return value.replace(str(REPO), "<repo>")
            return value
        out.write_text(json.dumps(public(doc), indent=2, ensure_ascii=False, default=str))
        print(f"\nwrote {out} ({passed} pass / {failed} fail)")
        return 1 if failed else 0

    @property
    def policy_read_revision(self):
        # last observed revision, refreshed by each policy_read caller
        return getattr(self, "_last_rev", None)

    @policy_read_revision.setter
    def policy_read_revision(self, value):
        self._last_rev = value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", required=True)
    ap.add_argument("--expected-sha256", required=True, help="frozen candidate SHA256")
    ap.add_argument("--env-script", required=True,
                    help="private env script exporting SIQ_OPENSHELL_BIN + XDG dirs")
    ap.add_argument("--gateway-endpoint", default="https://127.0.0.1:17671")
    ap.add_argument("--lost-endpoint", default="https://127.0.0.1:1")
    ap.add_argument("--target", required=True, help="explicitly owned writable test target")
    ap.add_argument("--fact-endpoint", default="172.23.0.1:42865",
                    help="the sandbox's pre-existing egress endpoint for grant facts")
    ap.add_argument("--out", required=True, help="evidence directory")
    args = ap.parse_args()

    j = Journey(args)
    # main-daemon context is swapped during J90; keep a copy to restore
    rc = 1
    try:
        rc = j.run()
    except Exception as exc:  # noqa: BLE001 -- record failed evidence, then rethrow or exit nonzero
        print(f"JOURNEY FAILED: {j.redact(exc)}", file=sys.stderr)
        j.record({"id": "ABORT", "title": "journey aborted", "kind": "derived",
                  "status": "fail", "detail": str(exc)})
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
