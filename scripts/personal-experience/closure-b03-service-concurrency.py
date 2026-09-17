#!/usr/bin/env python3
"""B03 service-level supplement (local-o05-b3 batch): drive UP05/UP07 through a
real isolated daemon's actual HTTP entry.

The B03 ledger gap (taskbook §8): "独立管理员配对、loopback HTTP 并发与签名 409
是另行 Go 回归，不能混称 44 项实机覆盖". This driver closes that gap on this
machine by running against a real installed candidate binary served as an
isolated daemon process (own HOME, own state dir), i.e. a real daemon entry —
NOT the in-process httptest server of skill_update_concurrency_test.go.

Legs:
  up07-future     state-format.json format_version 99  -> serve refuses, state untouched
  up07-corrupt    garbage state-format.json            -> serve refuses, state untouched
  up07-unmarked   nonempty state without marker        -> serve refuses, state untouched
  up05-same-plan  3 independent admin sessions commit the same signed plan concurrently
  up05-update-removal  commit vs removal interleave from 2 sessions
  up05-diff-plan  2 different staged plans committed concurrently from 2 sessions
  up07-stale      stale-revision stage + tampered plan signature via the live entry

Secrets: pairing codes, session credentials and the recovery token are used in
memory only; raw daemon logs stay under the batch private directory.
"""

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PAIRING_RE_MARKER = "admin pairing code (single use, 5 min): "
RETRY_BUDGET = 45
CONTRACT_UPDATE_ERRORS = {
    "skill_install_conflict", "skill_install_changed",
    "skill_install_removal_pending", "skill_install_recovery_required",
    "skill_install_not_found",
}


def utcnow():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Check(Exception):
    pass


def check(cond, label):
    if not cond:
        raise Check(label)


def grant_status(g):
    return (g.get("grant", {}) or {}).get("status") or g.get("status")


def grant_revision(g):
    return g.get("state_revision", (g.get("grant", {}) or {}).get("state_revision"))


def plan_of(out):
    return out.get("plan") or out


def StateFormatMarkerAbsent(snapshot):
    return "state-format.json" not in snapshot


class Http:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def __call__(self, method, path, body=None, token=None, headers=None):
        hdrs = {"Content-Type": "application/json"}
        if token:
            hdrs["Authorization"] = "Bearer " + token
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except ValueError:
                return exc.code, {"_unparsed": raw[:300].decode("utf-8", "replace")}
        except OSError as exc:
            return 0, {"_transport": str(exc)}


def dir_snapshot(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_dir():
            out[rel] = "dir"
        else:
            out[rel] = f"{p.stat().st_size}"
    return out


class Daemon:
    """One isolated rc.3 daemon: init + serve + pairing + recovery renewal."""

    def __init__(self, binary, leg_dir, env_base, workspace):
        self.binary = Path(binary)
        self.leg_dir = Path(leg_dir)
        self.home = self.leg_dir / "home"
        self.state = self.leg_dir / "state"
        self.home.mkdir(parents=True)
        self.state.mkdir()
        self.workspace = workspace
        (self.home / ".hermes" / "profiles" / "work").mkdir(parents=True)
        (self.home / ".hermes" / "profiles" / "work" / "config.yaml").write_text(
            "model: fixture\n", encoding="utf-8")
        self.env = dict(env_base)
        self.env["HOME"] = str(self.home)
        self.env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(self.state)
        self.env.pop("HERMES_HOME", None)
        self.port = free_port()
        self.http = Http(self.port)
        self.proc = None
        self.log_path = self.leg_dir / "serve.log"
        self.admin_a = None
        self.sessions = []

    def _run(self, args, timeout=60):
        return subprocess.run(
            [str(self.binary)] + args, cwd=self.workspace, env=self.env,
            capture_output=True, text=True, timeout=timeout)

    def init(self):
        # init uses state.DefaultDir() which honors SIQ_AGENT_SECURITY_STATE_DIR.
        r = self._run(["init", "--port", str(self.port)])
        check(r.returncode == 0, f"init failed rc={r.returncode}: {r.stderr[-300:]}")
        return r

    def serve_and_pair(self, expect_ready=True):
        log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [str(self.binary), "serve", "--port", str(self.port), "--mode", "block"],
            cwd=self.workspace, env=self.env, stdout=log, stderr=log)
        code = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                break
            text = open(self.log_path, encoding="utf-8").read()
            if PAIRING_RE_MARKER in text:
                code = text.split(PAIRING_RE_MARKER, 1)[1].split()[0]
                break
            time.sleep(0.05)
        if not expect_ready:
            # UP07 refusal legs: the daemon must NOT become ready. Allow a short
            # grace for the refusal exit before declaring failure.
            for _ in range(50):
                if self.proc.poll() is not None:
                    break
                time.sleep(0.1)
            check(self.proc.poll() is not None,
                  "up07: serve accepted incompatible state (process still running)")
            log.close()
            return
        check(self.proc is not None and self.proc.poll() is None,
              "serve exited before readiness")
        check(code is not None, "pairing code not printed within 30s")
        status, paired = self.http("POST", "/v1/pair", {"code": code})
        check(status == 200, f"pair HTTP {status}")
        self.admin_a = paired.get("session")
        check(bool(self.admin_a), "pair response missing session credential")
        self.sessions.append(self.admin_a)
        status, st = self.http("GET", "/v1/status", token=self.admin_a)
        check(status == 200, f"admin A status HTTP {status}")
        self.version = st.get("version")

    def recovery_renew_session(self):
        """Mint a new pairing code via the recovery token (local-CLI only path)."""
        tok_file = self.state / "admin-recovery.token"
        check(tok_file.exists(), "admin-recovery.token missing after serve")
        mode = oct(tok_file.stat().st_mode & 0o777)
        check(mode == "0o600", f"recovery token permissions {mode} != 0o600")
        recovery = tok_file.read_text(encoding="utf-8").strip()
        check(len(recovery) == 64, "recovery token not 64 hex chars")
        status, renewed = self.http(
            "POST", "/v1/session/pairing", token=recovery,
            headers={"X-SIQ-Local-CLI": "1"})
        check(status == 200, f"session/pairing HTTP {status}")
        new_code = renewed.get("code")
        check(bool(new_code), "renew response missing pairing code")
        status, paired = self.http("POST", "/v1/pair", {"code": new_code})
        check(status == 200, f"re-pair HTTP {status}")
        cred = paired.get("session")
        check(bool(cred), "re-pair response missing session credential")
        check(cred != self.admin_a, "second session credential equals first (not independent)")
        status, _ = self.http("GET", "/v1/status", token=cred)
        check(status == 200, "second session failed /v1/status")
        self.sessions.append(cred)
        return cred

    def stop(self):
        if self.proc is None or self.proc.poll() is not None:
            return self.proc.poll() if self.proc else None
        self.proc.terminate()
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)
        return self.proc.returncode


class Driver:
    def __init__(self, args):
        self.args = args
        self.ev = Path(args.evidence_dir)
        self.priv = self.ev / "b03-private" / "b03-service"
        self.priv.mkdir(parents=True, exist_ok=True)
        self.results = {"generated_at": utcnow(), "binary": args.binary,
                        "binary_sha256": hashlib.sha256(
                            Path(args.binary).read_bytes()).hexdigest(),
                        "entry_kind": "real isolated daemon (own HOME + state dir), actual HTTP entry",
                        "not": "in-process httptest server (see skill_update_concurrency_test.go)",
                        "legs": {}}
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "LANG", "LC_ALL", "TZ", "TMPDIR")}
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env_base = env

    # ---------- shared install chain over the real entry ----------
    def _write_skill(self, d, name, body):
        src = d.leg_dir / name
        src.mkdir(exist_ok=True)
        (src / "SKILL.md").write_text(body, encoding="utf-8")
        return str(src)

    INSTALL_SKILL = ("---\nname: http-import\ndescription: Read a synthetic report.\n---\n"
                     "Read a report.\n")
    CANDIDATE_SKILL = ("---\nname: example\ndescription: Read the next report.\n"
                       "allowed-tools: read_file write_file\n---\nNext report.\n")

    def _instance(self, d):
        status, rows = d.http("GET", "/v1/adapter/instances?platform=hermes",
                              token=d.admin_a)
        check(status == 200, f"adapter instances HTTP {status}")
        items = rows.get("instances", [])
        check(len(items) >= 2, f"expected >=2 hermes roots, got {len(items)}")
        return items[1]["instance_id"]

    def _import(self, d, import_id, path):
        status, out = d.http("POST", "/v1/skill-imports", token=d.admin_a, body={
            "schema_version": "local-skill-import-create/v1",
            "import_id": import_id, "source_kind": "local_dir",
            "path": path, "actor_id": "b03-service-admin"})
        check(status == 201, f"skill-import HTTP {status}: {json.dumps(out)[:200]}")
        return out["import"]

    def _permission(self, d, import_id, candidate, instance_id):
        status, out = d.http(
            "POST", f"/v1/skill-imports/{import_id}/permissions", token=d.admin_a, body={
                "schema_version": "local-skill-import-permission-create/v1",
                "request_id": "ip-" + import_id[3:],
                "artifact_digest": candidate["artifact_digest"],
                "analysis_sha256": candidate["analysis_sha256"],
                "instance_id": instance_id, "actor_id": "b03-service-admin"})
        check(status == 201, f"permission HTTP {status}: {json.dumps(out)[:200]}")
        return out["grant"], out["state_revision"]

    def _approve(self, d, grant_id, revision):
        status, out = d.http("POST", f"/v1/grants/{grant_id}/patch-desired", token=d.admin_a, body={"expected_revision": revision,
                              "actor_id": "b03-service-admin", "tools": ["read_file"]})
        if status != 200:
            # candidate grants may not accept patch-desired; revision stays
            pass
        else:
            revision = out["state_revision"]
        status, out = d.http("POST", f"/v1/grants/{grant_id}/challenge", token=d.admin_a, body={"expected_revision": revision,
                              "actor_id": "b03-service-admin"})
        check(status == 200, f"challenge HTTP {status}: {json.dumps(out)[:200]}")
        ch = out["challenge"]
        status, out = d.http("POST", f"/v1/grants/{grant_id}/approve", token=d.admin_a, body={
            "expected_revision": revision, "actor_id": "b03-service-admin",
            "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})
        check(status == 200, f"approve HTTP {status}: {json.dumps(out)[:200]}")
        return out["state_revision"]

    def build_install(self, d, import_id):
        """import -> permission -> patch-desired -> approve -> plan -> apply."""
        instance = self._instance(d)
        src = self._write_skill(d, "src-install", self.INSTALL_SKILL)
        cand = self._import(d, import_id, src)
        grant, revision = self._permission(d, import_id, cand, instance)
        gid = grant["grant_id"]
        revision = self._approve(d, gid, revision)
        status, out = d.http("POST", "/v1/skill-installations/plans", token=d.admin_a, body={
            "schema_version": "local-skill-install-stage-create/v1",
            "request_id": "is-" + import_id[3:], "grant_id": gid,
            "expected_revision": revision, "instance_id": instance,
            "directory_name": "example", "actor_id": "b03-service-admin"})
        check(status == 201, f"install plan HTTP {status}: {json.dumps(out)[:200]}")
        plan = plan_of(out)
        status, out = d.http("POST", "/v1/skill-installations/apply", token=d.admin_a, body={
            "schema_version": "local-skill-install-apply/v1",
            "plan_id": plan.get("plan_id") or plan.get("id"), "plan_signature": plan["signature"],
            "actor_id": "b03-service-admin", "confirm_install": True})
        check(status == 200 and out.get("status") == "installed_unverified",
              f"apply HTTP {status}: {json.dumps(out)[:200]}")
        return {"install_id": out["install_id"],
                "operation_signature": out["operation"]["signature"],
                "grant_id": gid, "instance_id": instance,
                "original_route": f"/v1/skill-installations/operations/{out['install_id']}"}

    def stage_plan(self, d, inst, tag, run_comparison=False):
        """Fresh candidate -> approve -> update-plans stage; returns commit body."""
        instance = inst["instance_id"]
        src = self._write_skill(d, f"src-cand-{tag}", self.CANDIDATE_SKILL)
        import_id = "si-" + ("c" if tag == "b" else "d") + ("a" if tag == "b" else "b") * 31
        cand = self._import(d, import_id, src)
        grant, revision = self._permission(d, import_id, cand, instance)
        cgid = grant["grant_id"]
        comparison = None
        if run_comparison:
            status, comparison = d.http(
                "POST", inst["original_route"] + "/update-comparison", token=d.admin_a, body={
                    "schema_version": "local-skill-update-compare/v1",
                    "operation_signature": inst["operation_signature"],
                    "candidate_grant_id": cgid,
                    "expected_candidate_revision": revision})
            check(status == 200, f"update-comparison HTTP {status}: {json.dumps(comparison)[:200]}")
            check(comparison.get("requires_confirmation") is True,
                  "comparison lost requires_confirmation")
        approved = self._approve(d, cgid, revision)
        status, old = d.http("GET", f"/v1/grants/{inst['grant_id']}", token=d.admin_a)
        check(status == 200, f"old grant read HTTP {status}")
        status, out = d.http("POST", inst["original_route"] + "/update-plans", token=d.admin_a, body={
            "schema_version": "local-skill-update-stage-create/v1",
            "request_id": "up-" + tag * 32,
            "operation_signature": inst["operation_signature"],
            "candidate_grant_id": cgid,
            "expected_candidate_revision": approved,
            "expected_previous_revision": grant_revision(old),
            "expected_binding_signature": "",
            "actor_id": "b03-service-admin"})
        check(status == 201, f"update-plans stage HTTP {status}: {json.dumps(out)[:200]}")
        plan = plan_of(out)
        return {"update_id": plan["update_id"], "plan_signature": plan["signature"],
                "candidate_grant_id": cgid, "comparison": comparison}

    @staticmethod
    def commit_body(plan):
        return {"schema_version": "local-skill-update-commit/v1",
                "update_id": plan["update_id"],
                "plan_signature": plan["plan_signature"],
                "actor_id": "b03-service-admin", "confirm_update": True}

    # ---------- concurrent writer ----------
    def fire_concurrent(self, d, requests):
        """requests: list of (label, method, path, body). Fires simultaneously,
        retries 429 skill_install_busy per the Retry-After contract."""
        barrier = threading.Barrier(len(requests))
        results = [None] * len(requests)

        def one(i, label, method, path, body, token):
            barrier.wait()  # single synchronized first shot, like the Go <-start barrier
            attempts = []
            deadline = time.monotonic() + RETRY_BUDGET * 2
            for attempt in range(RETRY_BUDGET):
                status, out = d.http(method, path, body, token=token)
                attempts.append({"attempt": attempt, "status": status,
                                 "error": out.get("error")})
                if status == 429 and out.get("error") == "skill_install_busy":
                    if time.monotonic() > deadline:
                        break
                    time.sleep(1.0)
                    continue
                results[i] = {"label": label, "status": status, "error": out.get("error"),
                              "result": out.get("result"), "attempts": attempts}
                return
            results[i] = {"label": label, "status": 429,
                          "error": "skill_install_busy_retry_budget_exhausted",
                          "result": None, "attempts": attempts}

        threads = [threading.Thread(target=one, args=(i, *req, d.sessions[i]))
                   for i, req in enumerate(requests)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        return results

    @staticmethod
    def contract_outcome(f):
        if f is None:
            return "thread_did_not_finish"
        if f["status"] == 200:
            return "success"
        if f["status"] == 409 and f["error"] in CONTRACT_UPDATE_ERRORS:
            return "contract_error"
        return f"non_contract:{f['status']}:{f['error']}"

    # ---------- legs ----------
    def leg_up07_refusals(self):
        out = {"seeded": [], "refused": [], "state_untouched": [],
               "boundary_note": (
                   "compatibility.go checkUnmarkedState, observed at the real entry: "
                   "a marker-less state dir is accepted as legacy_unversioned whenever "
                   "it is either the complete core scaffold (up07-unmarked-legacy) OR "
                   "still carries a parseable config.json even with keys/ removed "
                   "(up07-keys-missing observation). ErrMissingMarker refuses only an "
                   "unrecognizable nonempty state (marker + keys + config.json gone, "
                   "up07-unmarked-incomplete). EnforceStateCompatibility never mutates "
                   "or migrates; a legacy-accepted serve does not rewrite the marker.")}
        cases = {
            "up07-future": lambda d: (d.state / "state-format.json").write_text(
                json.dumps({"schema": "state-format/v1", "program_version": "x",
                            "format_version": 99, "published_at": utcnow()}) + "\n",
                encoding="utf-8"),
            "up07-corrupt": lambda d: (d.state / "state-format.json").write_text(
                "{not json at all", encoding="utf-8"),
            "up07-unmarked-incomplete": lambda d: (
                (d.state / "state-format.json").unlink(),
                shutil.rmtree(d.state / "keys"),
                (d.state / "config.json").unlink()),
        }
        for name, seed in cases.items():
            d = Daemon(self.args.binary, self.priv / name, self.env_base, self.args.workspace)
            d.init()
            marker = d.state / "state-format.json"
            check(marker.exists(), f"{name}: init did not write state-format.json")
            seed(d)
            before = dir_snapshot(d.state)
            d.serve_and_pair(expect_ready=False)
            r = self._run_wait(d)
            after = dir_snapshot(d.state)
            ok_untouched = (before == after)
            refused = (r is not None and r != 0)
            serve_log = ""
            log_path = d.leg_dir / "serve.log"
            if log_path.exists():
                serve_log = log_path.read_text(encoding="utf-8", errors="replace")
            (self.priv / name / "refusal-stderr.txt").write_text(
                serve_log[-800:], encoding="utf-8")
            out["seeded"].append(name)
            out["refused"].append(refused)
            out["state_untouched"].append(ok_untouched)
            out[name] = {"refused": refused, "state_untouched": ok_untouched,
                         "exit_code": r}
            if not refused or not ok_untouched:
                # keep going; the summary marks the leg failed
                out.setdefault("failures", []).append(name)
        # Observational sub-leg: marker deleted but COMPLETE scaffold -> serve
        # accepts it as legacy_unversioned and must not rewrite the marker.
        d = Daemon(self.args.binary, self.priv / "up07-unmarked-legacy",
                   self.env_base, self.args.workspace)
        d.init()
        (d.state / "state-format.json").unlink()
        before = dir_snapshot(d.state)
        d.serve_and_pair(expect_ready=True)
        after = dir_snapshot(d.state)
        legacy = {
            "serve_accepted": True,
            "marker_still_absent": StateFormatMarkerAbsent(after),
            "created_files": sorted(set(after) - set(before)),
        }
        out["up07-unmarked-legacy"] = legacy
        d.stop()
        # Observational sub-leg #2: marker deleted AND keys/ removed but a
        # parseable config.json remains -> checkUnmarkedState decodes the
        # config and accepts the state as legacy (verified live). Record
        # whether serve recreates any identity material (names only, never
        # contents).
        d = Daemon(self.args.binary, self.priv / "up07-keys-missing",
                   self.env_base, self.args.workspace)
        d.init()
        (d.state / "state-format.json").unlink()
        shutil.rmtree(d.state / "keys")
        before = dir_snapshot(d.state)
        d.serve_and_pair(expect_ready=True)
        after = dir_snapshot(d.state)
        keys_missing = {
            "serve_accepted": True,
            "marker_still_absent": StateFormatMarkerAbsent(after),
            "keys_signing_seed_present_after_serve":
                (d.state / "keys" / "signing.seed").exists(),
            "created_files": sorted(set(after) - set(before)),
        }
        out["up07-keys-missing"] = keys_missing
        d.stop()
        out["status"] = "pass" if not out.get("failures") else "fail"
        return out

    @staticmethod
    def _run_wait(d, timeout=30):
        try:
            return d.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            d.stop()
            return None
        finally:
            if d.proc.stdout:
                d.proc.stdout.close()

    def verify_commit_durable(self, d, inst, plan, flights):
        """Post-commit single-valued durable state checks (mirrors Go test)."""
        v = {}
        wins = [f for f in flights if f["status"] == 200]
        v["successes"] = len(wins)
        v["outcomes"] = [self.contract_outcome(f) for f in flights]
        sigs = {f["result"]["signature"] for f in wins if f.get("result")}
        v["winning_signatures_agree"] = len(sigs) <= 1
        check(v["successes"] >= 1, "no session committed the update")
        check(v["winning_signatures_agree"], "committed sessions disagree on durable result")
        winning = next(iter(sigs))
        status, view = d.http("GET", f"/v1/skill-installations/updates/{plan['update_id']}",
                              token=d.sessions[0])
        v["update_view_status"] = view.get("status") if status == 200 else None
        check(status == 200 and view.get("status") == "updated_unverified",
              f"durable update view {status} {view.get('status')}")
        check(view.get("result", {}).get("signature") == winning,
              "durable result signature differs from winning commit")
        status, removal = d.http("GET", inst["original_route"] + "/removal", token=d.sessions[0])
        check(status == 200 and removal.get("status") == "removed" and removal.get("result"),
              f"original install not durably removed: {status} {removal.get('status')}")
        v["removal_status"] = removal.get("status")
        status, g1 = d.http("GET", f"/v1/grants/{inst['grant_id']}", token=d.sessions[0])
        check(status == 200 and grant_status(g1) == "revoked",
              "original grant not revoked")
        status, g2 = d.http("GET", f"/v1/grants/{inst['grant_id']}", token=d.sessions[0])
        check(status == 200 and grant_revision(g2) == grant_revision(g1),
              "revoked grant revision not frozen across reads")
        v["grant_frozen_revision"] = grant_revision(g1)
        ops_dir = d.state / "skill-installations" / "update-operations"
        files = sorted(p.name for p in ops_dir.iterdir()) if ops_dir.exists() else []
        expected = {f"{plan['update_id']}.claim.json", f"{plan['update_id']}.result.json"}
        v["update_operations_artifacts_exact"] = set(files) == expected
        check(set(files) == expected, f"update-operations artifacts: {files}")
        # signed receipts observable via the same entry
        status, receipts = d.http("GET", "/v1/receipts", token=d.sessions[0])
        entries = receipts.get("receipts", receipts) if isinstance(receipts, dict) else receipts
        if isinstance(entries, list):
            v["receipts_count"] = len(entries)
            v["receipts_have_signature_field"] = all(
                any("signature" in str(k) for k in e) for e in entries[:5])
        else:
            v["receipts_count"] = None
        v["status"] = "pass"
        return v

    def leg_up05_same_plan(self):
        d = Daemon(self.args.binary, self.priv / "up05-same-plan", self.env_base,
                   self.args.workspace)
        d.init()
        d.serve_and_pair()
        out = {"daemon_version": d.version, "sessions": 1}
        try:
            d.recovery_renew_session()
            d.recovery_renew_session()
            out["sessions"] = len(d.sessions)
            out["sessions_independent"] = len(set(d.sessions)) == len(d.sessions)
            inst = self.build_install(d, "si-" + "a" * 32)
            plan = self.stage_plan(d, inst, "a", run_comparison=True)
            out["comparison"] = {k: plan["comparison"].get(k) for k in
                                 ("requires_confirmation", "content_changes_total",
                                  "platform_changes", "runtime_verified")}
            body = self.commit_body(plan)
            flights = self.fire_concurrent(d, [
                ("commit", "POST", "/v1/skill-installations/updates", body)
                for _ in range(3)])
            redacted = [{k: v for k, v in f.items() if k != "result"} | {
                "result_signature": (f.get("result") or {}).get("signature")}
                for f in flights]
            out["flights"] = redacted
            out.update(self.verify_commit_durable(d, inst, plan, flights))
            # UP07 stale-revision + tampered signature via the live entry
            status, old = d.http("GET", f"/v1/grants/{inst['grant_id']}", token=d.sessions[0])
            status, stale = d.http("POST", inst["original_route"] + "/update-plans",
                                   token=d.sessions[0], body={
                                       "schema_version": "local-skill-update-stage-create/v1",
                                       "request_id": "up-" + "ef" * 16,
                                       "operation_signature": inst["operation_signature"],
                                       "candidate_grant_id": plan["candidate_grant_id"],
                                       "expected_candidate_revision": 1,
                                       "expected_previous_revision": grant_revision(old),
                                       "expected_binding_signature": "",
                                       "actor_id": "b03-service-admin"})
            out["stale_revision_stage"] = {"status": status, "error": stale.get("error")}
            # Well-formed probe (request_id matches ^up-[a-f0-9]{32}$) whose only
            # fault is the stale candidate revision -> ErrChanged contract error.
            check(status == 409 and stale.get("error") in CONTRACT_UPDATE_ERRORS,
                  f"stale revision stage accepted: {status} {stale.get('error')}")
            status, tampered = d.http("POST", "/v1/skill-installations/updates",
                                      token=d.sessions[0],
                                      body=dict(body, plan_signature="0" * 128))
            out["tampered_signature_commit"] = {"status": status,
                                                "error": tampered.get("error")}
            check(status in (409, 400), f"tampered plan signature accepted: {status}")
            out["status"] = "pass"
        except Check as exc:
            out["status"] = "fail"
            out["detail"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            out["status"] = "fail"
            out["detail"] = f"{exc.__class__.__name__}: {exc}"
            out["traceback"] = traceback.format_exc()
        finally:
            out["serve_exit"] = d.stop()
        return out

    def leg_up05_update_removal(self):
        d = Daemon(self.args.binary, self.priv / "up05-update-removal", self.env_base,
                   self.args.workspace)
        d.init()
        d.serve_and_pair()
        out = {"daemon_version": d.version}
        try:
            d.recovery_renew_session()
            inst = self.build_install(d, "si-" + "b" * 32)
            plan = self.stage_plan(d, inst, "a")
            status, removal_view = d.http("GET", inst["original_route"] + "/removal",
                                          token=d.sessions[0])
            check(status == 200 and removal_view.get("status") == "not_requested",
                  f"removal view pre-state {status} {removal_view.get('status')}")
            record = removal_view["record"]
            removal_req = {
                "schema_version": "local-skill-install-remove/v1",
                "operation_signature": record["operation"]["signature"],
                "expected_grant_revision": removal_view["state_revision"],
                "expected_binding_signature": removal_view["binding_signature"],
                "actor_id": "b03-service-admin", "confirm_remove": True}
            flights = self.fire_concurrent(d, [
                ("update", "POST", "/v1/skill-installations/updates",
                 self.commit_body(plan)),
                ("removal", "POST", inst["original_route"] + "/removal", removal_req),
            ])
            redacted = [{k: v for k, v in f.items() if k != "result"} | {
                "result_signature": (f.get("result") or {}).get("signature")}
                for f in flights]
            out["flights"] = redacted
            update_f, removal_f = flights[0], flights[1]
            update_won = update_f["status"] == 200
            out["update_won"] = update_won
            out["update_outcome"] = self.contract_outcome(update_f)
            out["removal_outcome"] = self.contract_outcome(removal_f)
            check(update_f["status"] == 200 or update_f["status"] == 409,
                  f"update flight non-contract: {update_f['status']} {update_f['error']}")
            check(removal_f["status"] in (200, 404, 409),
                  f"removal flight non-contract: {removal_f['status']} {removal_f['error']}")
            status, view = d.http("GET",
                                  f"/v1/skill-installations/updates/{plan['update_id']}",
                                  token=d.sessions[0])
            out["update_view_after"] = {"status_code": status,
                                        "status": view.get("status") if isinstance(view, dict) else None}
            if update_won:
                check(status == 200 and view.get("status") == "updated_unverified",
                      "durable update status after winning commit")
                if removal_f["status"] != 200:
                    check(removal_f["error"] in CONTRACT_UPDATE_ERRORS,
                          f"stale removal accepted after concurrent update: {removal_f['error']}")
            elif status == 200:
                vstatus = view.get("status", "")
                if vstatus and vstatus != "aborted":
                    rec = {"schema_version": "local-skill-update-recover/v1",
                           "update_id": plan["update_id"],
                           "claim_signature": view["claim"]["signature"],
                           "actor_id": "b03-service-admin", "confirm_recovery": True}
                    status2, rout = d.http(
                        "POST", f"/v1/skill-installations/updates/{plan['update_id']}/recover",
                        token=d.sessions[0], body=rec)
                    check(status2 == 200 and rout.get("status") == "aborted",
                          f"recover after removal win: {status2} {rout.get('status')}")
                    out["recovery_after_removal_win"] = "aborted"
            else:
                check(status == 404,
                      f"unexpected update view after removal win: {status}")
            status, removal = d.http("GET", inst["original_route"] + "/removal",
                                     token=d.sessions[0])
            check(status == 200 and removal.get("status") == "removed" and removal.get("result"),
                  "original install not durably removed")
            status, g1 = d.http("GET", f"/v1/grants/{inst['grant_id']}", token=d.sessions[0])
            check(status == 200 and grant_status(g1) == "revoked",
                  "original grant not revoked")
            status, g2 = d.http("GET", f"/v1/grants/{inst['grant_id']}", token=d.sessions[0])
            check(status == 200 and grant_revision(g2) == grant_revision(g1),
                  "original grant revoked more than once")
            out["grant_frozen_revision"] = grant_revision(g1)
            status, r2 = d.http("GET", inst["original_route"] + "/removal", token=d.sessions[0])
            check(status == 200 and r2["result"]["signature"] == removal["result"]["signature"],
                  "removal result changed between reads")
            out["status"] = "pass"
        except Check as exc:
            out["status"] = "fail"
            out["detail"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            out["status"] = "fail"
            out["detail"] = f"{exc.__class__.__name__}: {exc}"
            out["traceback"] = traceback.format_exc()
        finally:
            out["serve_exit"] = d.stop()
        return out

    def leg_up05_diff_plan(self):
        d = Daemon(self.args.binary, self.priv / "up05-diff-plan", self.env_base,
                   self.args.workspace)
        d.init()
        d.serve_and_pair()
        out = {"daemon_version": d.version}
        try:
            d.recovery_renew_session()
            inst = self.build_install(d, "si-" + "c" * 32)
            plan_a = self.stage_plan(d, inst, "a")
            plan_b = self.stage_plan(d, inst, "b")
            check(plan_a["update_id"] != plan_b["update_id"],
                  "two stagings produced the same update id")
            flights = self.fire_concurrent(d, [
                ("commit-a", "POST", "/v1/skill-installations/updates",
                 self.commit_body(plan_a)),
                ("commit-b", "POST", "/v1/skill-installations/updates",
                 self.commit_body(plan_b)),
            ])
            redacted = [{k: v for k, v in f.items() if k != "result"} | {
                "result_signature": (f.get("result") or {}).get("signature")}
                for f in flights]
            out["flights"] = redacted
            successes = [f for f in flights if f["status"] == 200]
            out["successes"] = len(successes)
            out["outcomes"] = [self.contract_outcome(f) for f in flights]
            check(len(successes) <= 1, "two different plans both committed")
            check(all(f["status"] in (200, 409) for f in flights),
                  f"non-contract statuses: {[(f['status'], f['error']) for f in flights]}")
            if successes:
                sig = {(f.get("result") or {}).get("signature") for f in successes}
                out["winning_plan"] = successes[0]["label"]
                status, view = d.http(
                    "GET", f"/v1/skill-installations/updates/{plan_a['update_id'] if successes[0]['label'] == 'commit-a' else plan_b['update_id']}",
                    token=d.sessions[0])
                check(status == 200 and view.get("result", {}).get("signature") in sig,
                      "durable view disagrees with winning commit")
            out["status"] = "pass"
        except Check as exc:
            out["status"] = "fail"
            out["detail"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            out["status"] = "fail"
            out["detail"] = f"{exc.__class__.__name__}: {exc}"
            out["traceback"] = traceback.format_exc()
        finally:
            out["serve_exit"] = d.stop()
        return out

    def run(self):
        self.results["legs"]["up07-refusals"] = self.leg_up07_refusals()
        self.results["legs"]["up05-same-plan"] = self.leg_up05_same_plan()
        self.results["legs"]["up05-update-removal"] = self.leg_up05_update_removal()
        self.results["legs"]["up05-diff-plan"] = self.leg_up05_diff_plan()
        statuses = [v.get("status") for v in self.results["legs"].values()]
        self.results["overall"] = "pass" if all(s == "pass" for s in statuses) else "fail"
        out_path = self.ev / "b03-service-concurrency.json"
        out_path.write_text(json.dumps(self.results, indent=2, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        return out_path


def main():
    ap = argparse.ArgumentParser()
    repo = Path(__file__).resolve().parents[2]
    ap.add_argument("--binary", default=str(
        repo / "dist/siq-agent-security-0.3.0-rc.3/siq-agent-security-linux-arm64"))
    ap.add_argument("--evidence-dir", default=str(
        repo / "docs/evidence/personal-experience/local-o05-b3-20260916-181347"))
    ap.add_argument("--workspace", default=str(repo))
    args = ap.parse_args()
    driver = Driver(args)
    path = driver.run()
    overall = driver.results["overall"]
    print(f"b03-service-concurrency: overall={overall}")
    for name, leg in driver.results["legs"].items():
        print(f"  {name}: {leg.get('status')}"
              + (f" — {leg.get('detail', '')[:120]}" if leg.get("status") != "pass" else ""))
    print(f"evidence: {path}")
    return 0 if overall == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
