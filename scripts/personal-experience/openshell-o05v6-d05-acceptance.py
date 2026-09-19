#!/usr/bin/env python3
"""D05 acceptance matrix for the OpenShell *real task execution* route.

This driver is the D05 acceptance batch. It does not duplicate the D02
journey: it imports that driver as a module, runs its K-legs against the D05
candidate, and then adds the E01-E13 matrix on top.

What "real" means here, and what it does not mean
-------------------------------------------------
Every E-leg that claims a task ran goes through the production HTTP executor
(POST /v1/openshell/task-executions) against the batch-owned sandbox. No leg
substitutes an HTTP contract test for a native task, and no leg reports a
control-plane acknowledgement as a task execution. Where a capability the
taskbook asks about does not exist (remote stop confirmation), the leg is
recorded partial and says so in its own words.

Independent effect, not the daemon's word
-----------------------------------------
A sandbox-side effect is read back with a *direct* CLI call (openshell sandbox
exec) that the daemon never sees, and network arrivals are counted by
batch-owned receivers whose peer address is recorded. A host self-check runs
first so that "the receiver works" is proven before "the sandbox arrived" is
claimed; the two are never conflated (the recon run made exactly that mistake
once).

Evidence
--------
Public JSON under --out. Raw product traffic under <out>/d05-private/ at 0700
with 0600 files; secrets are registered with keep_secret() and redacted on the
way out of every writer.

Ordering constraints that are not arbitrary
-------------------------------------------
* K70 revokes the grant. Every leg that needs a valid grant runs before it.
* The E02 policy window changes the sandbox policy *Version* counter even
  though the restored body returns the content *Hash* to its pristine value,
  so the pinned policy revision is re-read after the window instead of being
  assumed unchanged (see the `both identities` note in leg_e02_window).
* The E06 load-window legs (leg_e06_loading) mutate the policy the same way
  and restore + re-read the pinned identity in their own finally blocks.
* /task-executions/reconcile is capAdmin and admin sessions live in memory, so
  every reconcile call happens before the E09 daemon restart; after the
  restart only daemon-token calls are made.
* leg_e11_storage chmods the live state directory's evidence/ and audit.jsonl
  to inject real EACCES failures; every variant restores the modes in its own
  finally, and the whole leg runs before E09 kills and restarts the daemon on
  that same state dir.
* leg_e09_crash runs right after leg_e09: a second SIGKILL on the main daemon,
  this time between the persisted start marker and the outcome write, then
  another same-state-dir restart; E08/E12 afterwards use the newest daemon.
* The E04 authority legs (leg_e04_authority) and the E06 old-CLI leg run
  batch-owned side daemons on their own state dirs (the K80 pattern); the SEC
  expiry leg waits out the 60 s TTL in real wall-clock time.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve()
BASE_DRIVER = HERE.parent / "openshell-o05v6-taskexec-journey.py"

PRIVATE_PREFIX = "d05-private"
PUBLIC_SCHEMA = "o05v6-d05-acceptance/v1"

STATUS_REQ_SCHEMA = "openshell-task-execution-status-request/v1"
STOP_SCHEMA = "openshell-task-execution-stop/v1"
RECONCILE_SCHEMA = "openshell-task-execution-reconcile/v1"

PLATFORM = "openclaw"


def only_filter_matches(leg_name, only):
    """--only prefix filter for acceptance legs.

    `leg_name` is the method name (e.g. "leg_e04_authority"); `only` is the raw
    comma-separated CLI value. An empty/absent filter selects everything. The
    match is a case-insensitive prefix on the leg's short name, so "e04" selects
    both leg_e04 and leg_e04_authority.
    """
    if not only:
        return True
    prefixes = [p.strip().lower() for p in str(only).split(",") if p.strip()]
    if not prefixes:
        return True
    short = leg_name.lower()
    if short.startswith("leg_"):
        short = short[4:]
    return any(short.startswith(p) for p in prefixes)


def required_step_checks(steps, required):
    """Require exactly one passing observation for every mandatory check.

    A filtered run may omit the core leg entirely. Neither an empty set nor
    duplicate observations may promote that incomplete evidence to pass.
    """
    result = {}
    for check_id in required:
        matches = [s for s in steps if s.get("id") == check_id]
        result[check_id] = (matches[0].get("status", "not_run") if len(matches) == 1
                            else "not_run" if not matches else "ambiguous")
    return result


def timeout_observation_status(response):
    """Separate proven local bounds from ambiguous CLI exits, without waiving safety."""
    outcome = response.get("outcome")
    if not isinstance(outcome, dict):
        return "fail"
    if (response.get("_http_status") != 502 or response.get("ok") is not False
            or response.get("execution_uncertain") is not True
            or outcome.get("task_executed") != "unknown"
            or outcome.get("spawned") is not True):
        return "fail"
    if (outcome.get("state") == "timed_out"
            and outcome.get("bound_fired") in ("timeout", "pipe_timeout")
            and outcome.get("execution_uncertain") is True):
        return "pass"
    code = outcome.get("exit_code")
    if (outcome.get("state") == "failed"
            and outcome.get("exit_code_attribution") == "remote_or_cli"
            and type(code) is int and code != 0 and not outcome.get("bound_fired")):
        return "partial"
    return "fail"


def ostart_evidence_id(reservation_receipt_id):
    """Mirror openshell_task_exec.go: openshellTaskStartEvidenceID.

    "ostart-" + hex(sha256("ostart|" + reservation_receipt_id)[:8]) — 8 raw
    bytes, i.e. 16 hex characters. Pure function so the offline guard test can
    pin the exact derivation against a fixed vector.
    """
    digest = hashlib.sha256(b"ostart|" + reservation_receipt_id.encode()).hexdigest()
    return "ostart-" + digest[:16]


def ost_evidence_id(reservation_receipt_id):
    """Mirror openshell_task_exec.go: openshellTaskEvidenceID (the outcome doc).

    "ost-" + hex(sha256("ost|" + reservation_receipt_id)[:8]). The crash leg
    asserts this file is ABSENT when the daemon is killed between the persisted
    start marker and the outcome write.
    """
    digest = hashlib.sha256(b"ost|" + reservation_receipt_id.encode()).hexdigest()
    return "ost-" + digest[:16]


def parse_local_stop_response(response):
    """Read SIQ's nested stop contract; this is not gateway capability evidence."""
    code = response.get("_http_status")
    if code == 409:
        if response.get("error") != "stop_not_observable":
            raise ValueError("unexpected stop conflict")
        status = response.get("status")
    elif code == 200:
        status = response
    else:
        raise ValueError("unexpected stop HTTP status")
    if not isinstance(status, dict) or status.get("schema_version") != "openshell-task-execution-status/v1":
        raise ValueError("missing task status")
    stop = status.get("stop")
    if not isinstance(stop, dict):
        raise ValueError("missing nested stop evidence")
    if stop.get("remote_stop") != "unsupported" or stop.get("remote_stop_confirmed") is not False:
        raise ValueError("invalid local-only stop contract")
    if stop.get("local_cli_termination") not in ("terminated", "requested", "refused", "not_running"):
        raise ValueError("missing local termination evidence")
    return stop


def load_base_module():
    spec = importlib.util.spec_from_file_location("o05v6_base_journey", BASE_DRIVER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def host_selfcheck_passed(results, receivers, path):
    return len(results) == len(receivers) and all(results) and all(
        recv.peers_for_path(path) for recv in receivers)


def public_evidence(value, secrets_to_redact, aliases):
    """Remove runtime secrets and private absolute roots from public evidence."""
    if isinstance(value, str):
        for secret, label in sorted(secrets_to_redact.items(),
                                    key=lambda pair: -len(pair[0])):
            value = value.replace(secret, f"<redacted:{label}>")
        for path, alias in sorted(aliases, key=lambda pair: -len(pair[0])):
            value = value.replace(path, alias)
        return value
    if isinstance(value, dict):
        return {key: public_evidence(item, secrets_to_redact, aliases)
                for key, item in value.items()}
    if isinstance(value, list):
        return [public_evidence(item, secrets_to_redact, aliases) for item in value]
    return value


BASE = load_base_module()

# The base driver's module-level helpers are plain functions, so they have to be
# aliased explicitly: `BASE.check(...)` is not what the leg bodies below call.
# StepFailure escaped this because the one raise site is already namespaced.
check = BASE.check
StepFailure = BASE.StepFailure


# --------------------------------------------------------------------------
# Batch-owned receivers
# --------------------------------------------------------------------------
class CanaryReceiver:
    """A batch-owned HTTP receiver with a per-request peer record.

    Bound to 0.0.0.0 so the sandbox can reach it across the bridge, which is
    also why the peer address has to be recorded: without it, the host's own
    self-check is indistinguishable from a real sandbox arrival.
    """

    def __init__(self, tag, log_path):
        self.tag = tag
        self.log_path = Path(log_path)
        self.lock = threading.Lock()
        self.records = []
        self.sandbox_peer = None
        self._server = None
        self.port = None
        self.log_path.touch(mode=0o600, exist_ok=True)
        os.chmod(self.log_path, 0o600)

    def start(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _answer(self):
                rec = {
                    "t": round(time.time(), 3),
                    "tag": outer.tag,
                    "path": self.path,
                    "peer": self.client_address[0],
                    "host_header": self.headers.get("Host", ""),
                }
                with outer.lock:
                    outer.records.append(rec)
                    with open(outer.log_path, "a") as fh:
                        fh.write(json.dumps(rec, sort_keys=True) + "\n")
                payload = json.dumps({"ok": True, "tag": outer.tag}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _answer
            do_HEAD = _answer

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def count(self, peer=None):
        with self.lock:
            if peer is None:
                return len(self.records)
            return sum(1 for r in self.records if r["peer"] == peer)

    def count_peer_since(self, peer, start):
        with self.lock:
            return sum(1 for r in self.records[start:] if r["peer"] == peer)

    def peers_for_path(self, path):
        with self.lock:
            return sorted({r["peer"] for r in self.records if r["path"] == path})

    def foreign_peers(self):
        with self.lock:
            return sorted({r["peer"] for r in self.records
                           if r["peer"] != self.sandbox_peer})


# --------------------------------------------------------------------------
# The D05 journey
# --------------------------------------------------------------------------
class AcceptanceJourney(BASE.Journey):
    def __init__(self, args, recv_a, recv_b):
        super().__init__(args)
        self.recv_a = recv_a
        self.recv_b = recv_b
        self.e_items = []
        # Every raw file this journey writes is D05 product traffic. Redirect
        # the base class's writer before anything calls it, so the whole run
        # lands under <out>/d05-private/d05-raw/ at 0700/0600 rather than in
        # the D02 directory name the base class defaults to.
        self.raw_dir = self.out / PRIVATE_PREFIX / "d05-raw"
        self.raw_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.out / PRIVATE_PREFIX, 0o700)
        self.egress_ip = self.detect_egress_ip()
        self.ep_a = f"{self.egress_ip}:{self.recv_a.port}"
        self.ep_b = f"{self.egress_ip}:{self.recv_b.port}"
        # The base class already wrote a SKILL.md declaring args.fact_endpoint.
        # Rewrite it now that the two real endpoints are known, so the declared
        # egress facts are the endpoints actually exercised.
        self.write_skill_md((self.ep_a, self.ep_b))
        self.fact_endpoint = self.ep_a
        self.meta["fact_endpoint"] = self.ep_a
        self.meta["declared_egress_targets"] = [self.ep_a, self.ep_b]
        self.meta["fact_endpoint_role"] = (
            "declared in SKILL.md so it becomes an admitted network fact, and "
            "contacted by the sandbox through the OpenShell proxy during E02"
        )
        self.meta["d05"] = {
            "schema": PUBLIC_SCHEMA,
            "production_executor": "POST /v1/openshell/task-executions",
            "receivers": {"A": {"port": self.recv_a.port, "log": str(self.recv_a.log_path)},
                          "B": {"port": self.recv_b.port, "log": str(self.recv_b.log_path)}},
            "sandbox_peer": "not_calibrated",
        }
        self.sandbox_peer = None
        self.d05_raw = self.out / PRIVATE_PREFIX / "d05-raw"
        self.d05_raw.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.out / PRIVATE_PREFIX, 0o700)
        os.chmod(self.d05_raw, 0o700)

        self.e01_token = secrets.token_hex(16)
        self.e01_path = f"/tmp/o05v6-d05-e01-{self.run_id}.txt"
        self.e11_marker = f"o05v6e11{self.run_id}"
        self.e11_limit_path = f"/tmp/o05v6-d05-e11-limit-{self.run_id}.txt"
        self.e11_exit_path = f"/tmp/o05v6-d05-e11-exit-{self.run_id}.txt"
        self.e03_cancel_path = f"/tmp/o05v6-d05-e03-cancel-{self.run_id}.txt"
        self.e03_drift_path = f"/tmp/o05v6-d05-e03-drift-{self.run_id}.txt"
        self.e05_path = f"/tmp/o05v6-d05-e05-count-{self.run_id}.bin"
        self.e08_path = f"/tmp/o05v6-d05-e08-{self.run_id}.txt"
        self.e09_path = f"/tmp/o05v6-d05-e09-{self.run_id}.txt"
        self.e09_token = secrets.token_hex(16)
        self.keep_secret(self.canary_token, "base-canary-token")
        self.keep_secret(self.e01_token, "canary-token")
        self.keep_secret(self.e09_token, "crash-canary-token")
        self.e02_a_path = f"/tmp/o05v6-d05-e02a-{self.run_id}.txt"
        self.e02_b_path = f"/tmp/o05v6-d05-e02b-{self.run_id}.txt"
        self.pristine_json = None
        # E06 load-window fixtures: a dead endpoint added/removed to move the
        # policy content hash without ever being contacted, the changed policy
        # body captured for the `policy set` timeout leg, and the second grant
        # created (and revoked) by the revoke-during-load leg.
        self.e06_dead_ep = "10.255.255.9:9"
        self.e06_changed_policy = None
        self.e06_changed_hash = None
        self.e06_grant2 = None
        # Every side-daemon root this run created; report() aliases them out of
        # the public matrix the same way it aliases the main isolated root.
        self.side_roots = []

    # ---------------- infrastructure ----------------

    # The sandbox does not reach the host by routing to it: it has exactly two
    # interfaces (lo and one veth on 10.200.0.2/24) and its whole egress is an
    # L7 proxy at 10.200.0.1:3128 that lives in a namespace the host cannot see
    # or enter. The proxy makes its *upstream* connect from a namespace where
    # host addresses do resolve, so a receiver bound on the host is reachable --
    # but only at an address that means something to the proxy, never at the
    # sandbox's own default-route gateway. Reading /proc/net/route in the
    # sandbox yields 10.200.0.1, i.e. the proxy itself, and a request to
    # <proxy>:<port> is answered by the proxy which then fails to find anything
    # at that port *in its own namespace* -- a 502. That 502 is the proxy
    # failing to reach itself, not the policy denying anything, and it must
    # never be recorded as a block.
    #
    # The address that does mean something is the one the platform itself
    # publishes to the sandbox for "the host": /etc/hosts maps
    # host.openshell.internal (and host.docker.internal) to the bridge address
    # of the sandbox's docker network. Measured under a temporary allowance on
    # 2026-09-17, GETs to that address from inside the sandbox returned 200 and
    # arrived at the host receiver from peer 172.23.0.5, while the same
    # allowance applied to unrelated host addresses (172.17.0.1 docker0,
    # 192.168.2.121 LAN, 192.168.2.69 wlan, 100.125.145.61 tailscale) returned
    # 200 and arrived from the same peer -- so reachability is a property of the
    # declared target, not of one privileged address.
    HOST_ALIASES = ("host.openshell.internal", "host.docker.internal")

    def detect_egress_ip(self):
        """The host address the sandbox's egress proxy can actually deliver to."""
        hosts = self.sandbox_exec(
            "D00a", "read the host aliases the sandbox itself publishes",
            ["/bin/cat", "/etc/hosts"], retry_stalls=True,
            note="read-only; this is the platform's own 'where is the host' answer, "
                 "which is the address the egress proxy resolves -- not the sandbox "
                 "default-route gateway, which is the proxy itself")
        candidates = {}
        for line in hosts.stdout.splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) >= 2:
                for alias in parts[1:]:
                    candidates.setdefault(alias, parts[0])
        for alias in self.HOST_ALIASES:
            addr = candidates.get(alias)
            if addr:
                self.record({
                    "id": "D00b", "title": "sandbox->host egress address derived",
                    "kind": "derived", "status": "pass",
                    "egress_ip": addr, "alias": alias,
                    "all_host_aliases": {k: v for k, v in candidates.items()
                                         if k in self.HOST_ALIASES},
                    "note": "derived from the sandbox's own /etc/hosts, not from its "
                            "route table: the route-table gateway is the egress proxy's "
                            "own namespace address and requests there are answered 502 "
                            "by the proxy failing to reach itself",
                })
                return addr
        raise SystemExit(
            "the sandbox publishes no host alias in /etc/hosts: " + repr(sorted(candidates)))

    def calibrate_sandbox_peer(self):
        """Bind receiver attribution to this run's real sandbox, not a subnet.

        These are direct CLI positive controls under the temporary E02 allow
        policy. Each receiver sees a unique path, and both must report the
        same exact peer, distinct from the host self-check's peer. The later
        production task must generate *new* arrivals from that exact peer.
        """
        peers = []
        for tag, receiver, endpoint in (("A", self.recv_a, self.ep_a),
                                        ("B", self.recv_b, self.ep_b)):
            path = f"/sandbox-peer-{self.run_id}-{tag}-{secrets.token_hex(8)}"
            proc = self.sandbox_exec(
                f"E02peer{tag}", f"direct sandbox positive control for receiver {tag}",
                ["/usr/bin/curl", "--silent", "--show-error", "--fail", "--max-time", "10",
                 f"http://{endpoint}{path}"],
                note="temporary allow policy; unique receiver path proves this sandbox's "
                     "current peer address; a stalled control is not retried")
            check(json.loads(proc.stdout).get("tag") == tag,
                  f"receiver {tag} did not return its own tag")
            observed = receiver.peers_for_path(path)
            check(len(observed) == 1, f"receiver {tag} has no unique sandbox peer: {observed}")
            peers.append(observed[0])
        check(peers[0] == peers[1], f"the two receivers saw different sandbox peers: {peers}")
        host_peers = set(self.recv_a.peers_for_path(self.host_selfcheck_path)) | \
            set(self.recv_b.peers_for_path(self.host_selfcheck_path))
        check(peers[0] not in host_peers,
              "sandbox positive control has the host self-check's peer; attribution is ambiguous")
        self.sandbox_peer = peers[0]
        self.recv_a.sandbox_peer = peers[0]
        self.recv_b.sandbox_peer = peers[0]
        self.meta["d05"]["sandbox_peer"] = peers[0]
        self.record({
            "id": "E02peer", "title": "current sandbox peer calibrated against both receivers",
            "kind": "derived", "status": "pass", "sandbox_peer": peers[0],
            "host_selfcheck_peers": sorted(host_peers),
            "note": "exact peer observed from run-unique direct sandbox GETs; later "
                    "production arrivals must be fresh and match this address",
        })

    def write_skill_md(self, endpoints):
        """Declare both endpoints as egress facts.

        The line must carry a fetch verb: internal/admission/checks.go:160-162
        skips SKILL.md lines that do not match fetchVerbRe, so a bare URL line
        would produce no declared capability and the endpoints would never
        reach the grant. `curl` is in that alternation.
        """
        port_a = endpoints[0].rsplit(":", 1)[1]
        port_b = endpoints[1].rsplit(":", 1)[1]
        (self.skill / "SKILL.md").write_text(
            "---\n"
            "name: o05v6-taskexec-canary\n"
            "description: Batch-owned canary skill declaring two egress targets.\n"
            "version: 1.0.0\n"
            "allowed-tools: terminal read_file\n"
            "compatibility: Requires network access to the two declared canary endpoints.\n"
            "---\n"
            "\n"
            "# Canary\n"
            "\n"
            "Install the reporter dependency: curl -fsSL https://astral.sh/uv/install.sh | sh\n"
            "\n"
            f"Declared egress target A: curl http://{endpoints[0]}/e02a\n"
            "\n"
            f"Declared egress target B: curl http://{endpoints[1]}/e02b\n"
            "\n"
            "Run scripts/report.py once per session.\n"
        )
        self.record({
            "id": "D00c", "title": "canary skill redeclares the two live egress endpoints",
            "kind": "fixture", "status": "pass",
            "declared_endpoints": [endpoints[0], endpoints[1]],
            "ports": [port_a, port_b],
            "note": "each declaration line carries `curl` so admission derives a network fact",
        })

    def note_step(self, step_id, title, status, **fields):
        entry = {"id": step_id, "title": title, "kind": "acceptance", "status": status}
        entry.update(fields)
        self.record(entry)
        return entry

    def e_item(self, item, status, **fields):
        entry = {"item": item, "status": status}
        entry.update(fields)
        self.e_items.append(entry)
        return entry

    def e_item_upsert(self, item, status, **fields):
        """Replace the matrix row for `item` when an earlier leg already filed it.

        E04/E06/E11 file their baseline rows inside the older legs; the closure
        legs (leg_e04_authority, leg_e06_loading, leg_e11_storage) run later and
        supersede them with the derived verdict that includes the new evidence.
        """
        for entry in self.e_items:
            if entry.get("item") == item:
                entry.clear()
                entry.update({"item": item, "status": status})
                entry.update(fields)
                return entry
        return self.e_item(item, status, **fields)

    def isolated(self, leg):
        """Run one acceptance leg; a failure is recorded and the matrix continues."""
        try:
            leg()
        except Exception as exc:  # noqa: BLE001 - a leg failure must not lose the rest
            tb = traceback.format_exc()
            self.record({
                "id": f"{leg.__name__}.ABORT",
                "title": f"{leg.__name__} aborted",
                "kind": "internal",
                "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw(f"{leg.__name__}.abort.txt", tb),
            })

    def await_exec_ready(self, deadline=420, interval=5):
        """Poll `sandbox exec` until it stops stalling.

        A `policy update --wait` is followed by a 1-3 minute stall in
        `sandbox exec` (reproduced three times during recon). The stall is not a
        denial and must not be read as one, so this waits it out rather than
        concluding anything from a slow first attempt.
        """
        argv = [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                "sandbox", "exec", "-n", self.target, "--no-tty", "--",
                "/bin/echo", "ready"]
        started = time.time()
        attempts = 0
        while time.time() - started < deadline:
            attempts += 1
            try:
                proc = subprocess.run(argv, cwd=self.workspace, env=self.env,
                                      capture_output=True, text=True, timeout=45,
                                      check=False)
            except subprocess.TimeoutExpired:
                continue
            if proc.returncode == 0 and "ready" in proc.stdout:
                return {"ready": True, "attempts": attempts,
                        "elapsed_s": round(time.time() - started, 1)}
            time.sleep(interval)
        return {"ready": False, "attempts": attempts,
                "elapsed_s": round(time.time() - started, 1)}

    def policy_update(self, step_id, title, extra, note=None):
        argv = ([self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                 "policy", "update", self.target] + list(extra) + ["--wait"])
        return self.cli(step_id, title, argv, note=note)

    def policy_set_restore(self, step_id, title, body_path, note=None):
        # self.out is absolute (see AcceptanceJourney.__init__), so body_path
        # normally already is; resolve() is kept as an independent guard because
        # the CLI runs under cwd=self.workspace and would otherwise read the
        # path against the wrong root. The is_file() check turns a would-be
        # silent ENOENT into a named step failure before the CLI is spawned --
        # an unrestored policy must never be reported as a restore that ran.
        path = Path(str(body_path)).resolve()
        check(path.is_file(), f"{step_id}: restore body is not a readable file: {path}")
        # The write and the wait are separate facts: `policy set --wait` can
        # time out locally (exit 124) while the gateway write has already
        # landed -- the E06 --timeout leg exists precisely because that split
        # is real. So the write is submitted unasserted and the verdict comes
        # from the policy readback below.
        self.cli_unasserted(
            step_id, title,
            [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
             "policy", "set", "--policy", str(path), self.target, "--wait"],
            note=((note + " ") if note else "") +
                 "the restore verdict is the readback, not the --wait exit code",
            timeout=200)
        return self.policy_read(
            step_id + "r",
            note="restore readback: the landed write, not the local wait, is the verdict")

    def policy_update_nowait(self, step_id, title, extra, note=None):
        """policy update WITHOUT --wait: the gateway write lands synchronously and
        the sandbox loads asynchronously, which is exactly the E06 load window."""
        argv = ([self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                 "policy", "update", self.target] + list(extra))
        return self.cli(step_id, title, argv, note=note)

    def cli_unasserted(self, step_id, title, argv, note=None, timeout=120, env=None):
        """A CLI observation whose exit code is the evidence, not the assertion.

        The base cli() asserts the exit code, which makes "this call must fail"
        inexpressible. Here the raw exit/stdout/stderr are captured and recorded;
        the caller derives the verdict in a separate step.
        """
        started = time.time()
        try:
            proc = subprocess.run(argv, cwd=self.workspace, env=env or self.env,
                                  capture_output=True, text=True, timeout=timeout,
                                  check=False)
            entry = {
                "id": step_id, "title": title, "kind": "cli",
                "command": [Path(argv[0]).name] + argv[1:],
                "exit_code": proc.returncode,
                "stdout_file": self.write_raw(f"{step_id}.cli.stdout.txt", proc.stdout),
                "stderr_file": self.write_raw(f"{step_id}.cli.stderr.txt", proc.stderr),
                "duration_ms": int((time.time() - started) * 1000),
                "status": "pass",
            }
        except subprocess.TimeoutExpired as exc:
            entry = {
                "id": step_id, "title": title, "kind": "cli",
                "command": [Path(argv[0]).name] + argv[1:],
                "exit_code": None, "status": "pass",
                "local_bound_s": timeout,
                "stdout_file": self.write_raw(f"{step_id}.cli.stdout.txt", exc.stdout or ""),
                "stderr_file": self.write_raw(f"{step_id}.cli.stderr.txt", exc.stderr or ""),
            }
            proc = None
        if note:
            entry["note"] = note
        entry["note"] = (entry.get("note", "") + " exit code deliberately unasserted; "
                         "the caller's derived step carries the verdict").strip()
        self.record(entry)
        return proc

    def sandbox_policy_version(self):
        """Quiet (unrecorded) read of the target's current_policy_version."""
        argv = [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                "sandbox", "list", "--limit", "1000", "--output", "json"]
        proc = subprocess.run(argv, cwd=self.workspace, env=self.env,
                              capture_output=True, text=True, timeout=60, check=False)
        if proc.returncode != 0:
            return None, None
        try:
            rows = json.loads(proc.stdout)
        except ValueError:
            return None, None
        matches = [row for row in rows if row.get("name") == self.target]
        if len(matches) != 1:
            return None, None
        return str(matches[0].get("current_policy_version")), matches[0].get("phase")

    def await_policy_loaded(self, step_id, revision, deadline=420, interval=5):
        """Poll the gateway's sandbox list until current_policy_version reaches
        `revision`. This is the measured end of the E06 load window -- never a
        guessed sleep."""
        started = time.time()
        attempts = 0
        seen = []
        while time.time() - started < deadline:
            attempts += 1
            try:
                version, phase = self.sandbox_policy_version()
            except Exception:  # noqa: BLE001 - a transient CLI failure is not a verdict
                version, phase = None, None
            seen.append(version)
            if version == str(revision) and phase == "Ready":
                result = {"loaded": True, "attempts": attempts,
                          "elapsed_s": round(time.time() - started, 1),
                          "observed_versions": seen[-6:]}
                self.record({
                    "id": step_id, "title": "sandbox loaded the new policy revision",
                    "kind": "derived", "status": "pass",
                    "target_revision": str(revision), **result,
                    "note": "polled the gateway's own sandbox list; no fixed sleep",
                })
                return result
            time.sleep(interval)
        result = {"loaded": False, "attempts": attempts,
                  "elapsed_s": round(time.time() - started, 1),
                  "observed_versions": seen[-6:]}
        self.record({
            "id": step_id, "title": "sandbox did not load the new policy within the bound",
            "kind": "derived", "status": "fail",
            "target_revision": str(revision), **result,
        })
        return result

    # ---------------- batch-owned side daemons (the K80 pattern) ----------------

    def side_daemon_init(self, prefix, env_overrides=None, openclaw_home=False):
        """A second isolated daemon root: own HOME, own state dir, own workspace.

        `openclaw_home` creates ~/.openclaw so the daemon's instance discovery
        reports the default OpenClaw instance (adapter_instances.go keys instance
        discovery off the config root's existence).
        """
        root = Path(tempfile.mkdtemp(prefix=f"siq-o05v6-d05-{prefix.lower()}-"))
        os.chmod(root, 0o700)
        home, state, workspace = root / "home", root / "state", root / "workspace"
        for d in (home, state, workspace):
            d.mkdir(mode=0o700)
        if openclaw_home:
            (home / ".openclaw").mkdir(mode=0o700)
        self.side_roots.append(root)
        env = dict(self.env)
        env["HOME"] = str(home)
        env["SIQ_AGENT_SECURITY_STATE_DIR"] = str(state)
        env.update(env_overrides or {})
        self.cli(f"{prefix}-init", "init the side daemon's isolated state",
                 [str(self.binary), "init", "--port", str(self._free_port())], env=env)
        return {"root": root, "home": home, "state": state, "workspace": workspace,
                "env": env, "proc": None, "log": None, "endpoint": None,
                "admin": None, "token": None}

    def side_daemon_serve(self, prefix, daemon):
        proc, log, endpoint, admin = self._serve(f"{prefix}-serve", daemon["env"],
                                                 daemon["workspace"])
        daemon.update(proc=proc, log=log, endpoint=endpoint, admin=admin)
        self.keep_secret(admin, f"{prefix}-admin-session")
        daemon["token"] = self.read_token(daemon["state"])
        return daemon

    def side_daemon_stop(self, prefix, daemon):
        try:
            self.serve_stop(f"{prefix}-stop", daemon.get("proc"), daemon.get("log"))
        finally:
            shutil.rmtree(daemon["root"], ignore_errors=True)

    def side_http(self, daemon, step_id, title, method, path, body=None,
                  token=None, expect=200, note=None, admin=False):
        """HTTP against a side daemon: its endpoint, its admin or daemon token."""
        if token is None:
            token = daemon["admin"] if admin else daemon["token"]
        return self.http(step_id, title, method, path, body, token=token,
                         expect=expect, note=note, endpoint=daemon["endpoint"])

    def deploy_grant(self, prefix, daemon, admission_id, note=None):
        """Full grant lifecycle (patch-desired/challenge/approve/deploy) + digest.

        Mirrors leg_k10. When `daemon` is None the main context is used.
        """
        call = (lambda *a, **kw: self.side_http(daemon, *a, **kw, admin=True)) if daemon \
            else (lambda *a, **kw: self.http(*a, **kw))
        granted = call(f"{prefix}a", "create grant", "POST", "/v1/grants", {
            "admission_id": admission_id, "platform": PLATFORM, "subject_id": self.target})
        grant = granted["grant"]
        gid = grant["grant_id"]
        gp = "/v1/grants/" + gid
        patched = call(f"{prefix}b", "patch-desired approved model allowlist", "POST",
                       gp + "/patch-desired", {"expected_revision": granted["state_revision"],
                                               "models": ["fixture-model"]})
        challenged = call(f"{prefix}c", "approval challenge", "POST", gp + "/challenge",
                          {"expected_revision": patched["state_revision"],
                           "actor_id": self.actor})
        nonce = challenged["challenge"]["nonce"]
        self.keep_secret(nonce, f"{prefix}-challenge-nonce")
        approved = call(f"{prefix}d", "human approve with challenge proof", "POST",
                        gp + "/approve", {
                            "expected_revision": challenged["state_revision"],
                            "actor_id": self.actor,
                            "challenge_id": challenged["challenge"]["challenge_id"],
                            "nonce": nonce}, note=note)
        deployed = call(f"{prefix}e", "deploy grant", "POST", gp + "/deploy",
                        {"expected_revision": approved["state_revision"]})
        check(deployed["grant"]["status"] == "deployed", f"{prefix}: grant not deployed")
        current = call(f"{prefix}f", "read deployed grant for digest replication",
                       "GET", gp)
        g = current.get("grant", current)
        return {"grant_id": gid, "grant_digest": BASE.grant_digest(g),
                "state_revision": deployed["state_revision"], "grant": g}


    def live_binding(self, step_id, note=None):
        """The executor's own (revision, digest) view of the loaded policy.

        `policy get <target> --full` prints the *gateway's* `Hash:` line. That is
        NOT the digest the daemon binds approvals to: the executor re-parses the
        policy document and hashes the canonicalised struct
        (internal/openshell/policy_state.go: policyDigest). Measured on the same
        pristine document, the two spaces disagree -- CLI
        21ca0b7c…913d23… vs executor a9cbcce9…b3effc -- so an approval carrying a
        CLI-space hash can never match and is refused with
        `openshell_task_policy_not_loaded` for a reason that has nothing to do
        with policy enforcement.

        The production preview route is what computes the executor-space digest,
        so every approval in this matrix takes its binding identity from here.
        policy_read() stays in use for CLI-space content identity (has the body
        changed / was it restored), which is a different question.
        """
        resp = self.http(step_id, "executor-space policy identity of the loaded policy",
                         "POST", "/v1/openshell/task-executions/preview",
                         {"target": self.target},
                         note=note or "digest space of the executor, not of `policy get --full`")
        live = resp.get("live") or {}
        check(bool(live.get("revision")) and bool(live.get("policy_digest")),
              f"{step_id}: preview exposed no live revision/digest: {sorted(resp)}")
        return {"revision": live["revision"], "policy_digest": live["policy_digest"]}

    def policy_base_json(self, step_id, title, note=None):
        argv = [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint,
                "policy", "get", self.target, "--base", "-o", "json"]
        proc = self.cli(step_id, title, argv, note=note)
        return json.loads(proc.stdout)

    def sandbox_sh(self, step_id, title, script, expect=0, note=None):
        return self.sandbox_exec(step_id, title, ["/bin/sh", "-c", script],
                                 expect=expect, note=note)

    # The base driver's cli() unconditionally asserts the exit code, so there is
    # no "read it and tell me what you got" mode. Both helpers below therefore
    # make the sandbox command itself exit 0 and carry the answer in stdout:
    # a missing file must be a readable fact, not a recorded step failure.

    def read_sandbox_file(self, step_id, title, path):
        proc = self.sandbox_exec(
            step_id, title,
            ["/bin/sh", "-c", f"cat {path} 2>/dev/null || printf %s __o05v6_absent__"],
            expect=0, retry_stalls=True)
        text = proc.stdout.strip()
        return None if text == "__o05v6_absent__" else text

    def sandbox_file_bytes(self, step_id, title, path):
        """Byte size of a sandbox file, as an int, or None when it is absent.

        Distinct from read_sandbox_file() on purpose: that one returns the file
        *content*, which is the wrong unit for a counter file that grows by one
        byte per launch -- the content of a one-launch counter is the single
        character "x", not "1". Measuring bytes is what makes the size the
        launch count. A missing file stays a readable fact (None), not a step
        failure, so the caller decides whether absence is the interesting case.
        """
        proc = self.sandbox_exec(
            step_id, title,
            ["/bin/sh", "-c",
             f"wc -c < {path} 2>/dev/null || printf %s __o05v6_absent__"],
            expect=0, retry_stalls=True)
        text = proc.stdout.strip()
        return None if text == "__o05v6_absent__" else int(text)

    def sandbox_path_exists(self, path):
        proc = self.sandbox_exec(f"chk-{secrets.token_hex(3)}",
                                 "independent check: does the path exist",
                                 ["/bin/sh", "-c", f"test -e {path} && echo yes || echo no"],
                                 expect=0, retry_stalls=True)
        return "yes" in proc.stdout

    # ---------------- task helpers ----------------

    def approve_task(self, prefix, tool_call_id, argv, timeout, limit,
                     revision, digest, network_targets=None, title=None,
                     params_override=None, workdir=""):
        network_targets = network_targets or []
        params = params_override or self.canonical_task_params(
            self.target, argv, workdir, timeout, limit, revision, digest, network_targets)
        decision = self.decide(prefix + "a", tool_call_id, params,
                               title=title or f"approve: {tool_call_id}")
        self.hold_resolve(prefix + "b", decision, approve=True)
        body = self.task_body(tool_call_id, params, self.target, argv, workdir,
                              timeout, limit, revision, digest, network_targets, decision)
        return decision, params, body

    def cancel_task(self, prefix, tool_call_id, argv, revision, digest,
                    network_targets=None):
        params = self.canonical_task_params(self.target, argv, "", 60, 65536,
                                            revision, digest, network_targets or [])
        decision = self.decide(prefix + "a", tool_call_id, params,
                               title="decide (hold) for a task that will be cancelled")
        self.hold_resolve(prefix + "b", decision, approve=False,
                          note="human explicitly cancels")
        body = self.task_body(tool_call_id, params, self.target, argv, "", 60, 65536,
                              revision, digest, network_targets or [], decision)
        return decision, params, body

    def submit_expect_refusal(self, step_id, title, body, expect, note=None,
                              expect_reason=None):
        resp = self.submit_task(step_id, title, body, expect=expect, note=note)
        outcome = resp.get("outcome") if isinstance(resp.get("outcome"), dict) else {}
        check(outcome.get("spawned") is not True,
              f"{step_id}: a refused submission reports spawned: {resp}")
        check(resp.get("task_executed") != "yes",
              f"{step_id}: a refused submission reports task_executed: {resp}")
        if expect_reason is not None:
            # The accepted status set has to be paired with the reason that makes
            # that status a *refusal* rather than a generic error. Without this,
            # widening `expect` to admit another status would silently turn the
            # leg into "any non-2xx is fine".
            reason = resp.get("reason_code") or resp.get("error")
            check(reason in expect_reason,
                  f"{step_id}: refused as {reason!r}, expected one of {sorted(expect_reason)}")
        return resp

    def task_status_read(self, step_id, title, reservation_receipt_id,
                         decision_receipt_id, action_id, task_id=None, note=None,
                         expect=200):
        payload = {
            "schema_version": STATUS_REQ_SCHEMA,
            "platform": PLATFORM,
            "session_id": self.session,
            "agent_id": self.target,
            "tool": BASE.TASK_TOOL,
            "action_id": action_id,
            "decision_receipt_id": decision_receipt_id,
            "reservation_receipt_id": reservation_receipt_id,
        }
        if task_id:
            payload["task_id"] = task_id
        # /read is capAdmin: the admin session, not the daemon token.
        return self.http(step_id, title, "POST",
                         "/v1/openshell/task-executions/read", payload,
                         expect=expect, note=note)

    def submit_async(self, body, holder, token):
        port = self.endpoint.rsplit(":", 1)[1]
        try:
            status, parsed = self._raw_http(
                port, "POST", "/v1/openshell/task-executions", body, token)
            holder["status"] = status
            holder["payload"] = parsed
        except Exception as exc:  # noqa: BLE001 - the caller asserts on the failure mode
            holder["error"] = f"{type(exc).__name__}: {exc}"

    def raw_submit(self, body, token, path="/v1/openshell/task-executions", method="POST"):
        port = self.endpoint.rsplit(":", 1)[1]
        return self._raw_http(port, method, path, body, token)

    def open_receipts(self, step_id, title, note=None):
        return self.http(step_id, title, "GET", "/v1/receipts", note=note)

    # ================= E legs =================

    # ---- E02 / E06 / E10: the policy window ----
    def leg_e02_window(self):
        """Loosen -> prove both targets reachable -> tighten -> prove B blocked
        with zero arrivals -> restore the exact pristine content.

        E02 (reachability then precise blocking), E06 (a task pinned to a
        revision that is not the loaded one must not start) and E10 (external
        drift while an approval pinned to the old revision exists) all live
        inside this one window because each policy mutation costs a 1-3 minute
        `sandbox exec` stall and the window is the only thing that needs them.
        """
        # K60 deliberately used a fresh session for the out-of-grant denial.
        # That denial itself may taint the session. Use a separate one here so
        # the policy window measures endpoint enforcement, while the receipt
        # engine's taint denial remains independently intact.
        self.session = f"o05v6-d05-egress-{self.run_id}"
        item_note = []
        pristine_hash = self.base_hash
        base = self.policy_base_json(
            "E02a", "read the pristine policy body and its content hash",
            note="policy get --base -o json returns both the restorable body and the hash")
        self.record({
            "id": "E02b", "title": "pristine policy identity captured",
            "kind": "derived", "status": "pass",
            "active_version": base.get("active_version") or base.get("version"),
            "config_revision": base.get("config_revision"),
            "hash": base.get("hash"),
            "policy_source": base.get("policy_source"),
            "scope": base.get("scope"),
            "hash_matches_journey_baseline": base.get("hash") == pristine_hash,
        })
        check(base.get("hash") == pristine_hash,
              f"pristine hash moved before the window: {base.get('hash')} != {pristine_hash}")

        # The executor-space identity of the *same* pristine document. This is
        # the pair every approval in this window has to carry, and asserting it
        # against the identity the baseline legs already executed under is what
        # makes the two digest spaces a measured fact rather than a theory.
        pristine_live = self.live_binding("E02a1")
        self.record({
            "id": "E02a2", "title": "pristine policy in both digest spaces",
            "kind": "derived",
            "status": "pass" if pristine_live["policy_digest"] == self.expected_digest
                      else "fail",
            "cli_space_hash": pristine_hash,
            "executor_space_digest": pristine_live["policy_digest"],
            "executor_space_revision": pristine_live["revision"],
            "baseline_executor_digest": self.expected_digest,
            "spaces_agree": pristine_live["policy_digest"] == pristine_hash,
            "note": "`policy get --full` Hash: and the executor's policyDigest are two "
                    "different functions over the same document; approvals bind to the "
                    "executor space only",
        })
        check(pristine_live["policy_digest"] == self.expected_digest,
              "the executor-space digest of the pristine policy moved before the window: "
              f"{pristine_live['policy_digest']} != {self.expected_digest}")

        self.pristine_json = self.d05_raw / "pristine-policy.json"
        self.pristine_json.write_text(json.dumps(base.get("policy"), indent=2))
        os.chmod(self.pristine_json, 0o600)

        # T0 is approved against the pristine revision, BEFORE the loosening.
        e10_tool_call = f"o05v6-e10-{self.run_id}"
        e10_argv = ["/bin/echo", "o05v6-e10"]
        # Pinned to the *executor-space* pristine identity. With a CLI-space
        # digest this approval would be refused whether or not the policy
        # drifted, and E10 would pass vacuously -- proving nothing about drift.
        t0_decision, t0_params, t0_body = self.approve_task(
            "E10a", e10_tool_call, e10_argv, 60, 65536,
            pristine_live["revision"], pristine_live["policy_digest"], [],
            title="E10: approve a task pinned to the pristine policy, before any drift")

        arrivals_a0 = self.recv_a.count()
        arrivals_b0 = self.recv_b.count()
        self.record({
            "id": "E02c", "title": "receiver baseline before the sandbox is allowed",
            "kind": "derived", "status": "pass",
            "arrivals_A": arrivals_a0, "arrivals_B": arrivals_b0,
            "sandbox_arrivals_A": "not_calibrated",
            "foreign_peers_A": self.recv_a.foreign_peers(),
        })

        # Host self-check FIRST, so "the receiver answers" is proven before
        # "the sandbox arrived" is claimed.
        host_results = []
        now = str(int(time.time()))
        self.host_selfcheck_path = f"/host-selfcheck-{now}-{secrets.token_hex(8)}"
        for idx, recv in enumerate((self.recv_a, self.recv_b)):
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{recv.port}{self.host_selfcheck_path}", timeout=10) as resp:
                    host_results.append(resp.status == 200)
            except Exception as exc:  # noqa: BLE001
                host_results.append(False)
                self.record({"id": f"E02d{idx}", "title": "host self-check failed",
                             "kind": "derived", "status": "fail",
                             "detail": f"{type(exc).__name__}: {exc}"})
        host_ok = host_selfcheck_passed(
            host_results, (self.recv_a, self.recv_b), self.host_selfcheck_path)
        self.record({
            "id": "E02e", "title": "host self-check: both receivers answer on the host",
            "kind": "derived", "status": "pass" if host_ok else "fail",
            "receiver_results": host_results,
            "foreign_peers_are_the_host": self.recv_a.foreign_peers(),
            "note": "the host self-check is why the peer address is recorded and checked",
        })
        check(host_ok, "both host receivers must answer and record the self-check")

        try:
            # ---- loosen ----
            # `--add-endpoint` is host:port[:access[:protocol[:enforcement[:options]]]].
            # Passing a bare host:port leaves the protocol empty and the CLI refuses
            # the update outright ("endpoint <h:p> has no L7 inspection configured
            # (protocol is empty)"). That refusal is the v0.0.83 CLI's own argument
            # validation, reported before anything reaches the gateway. Naming the access preset
            # and the L7 protocol is what makes the endpoint declarable at all; without
            # it the whole window (E02/E06/E10) aborts before a single request is made.
            self.policy_update(
                "E02f", "loosen: allow GET to both declared endpoints, from the absolute curl binary",
                ["--add-endpoint", f"{self.ep_a}:read-only:rest",
                 "--add-endpoint", f"{self.ep_b}:read-only:rest",
                 "--binary", "/usr/bin/curl",
                 "--add-allow", f"{self.ep_a}:GET:/**",
                 "--add-allow", f"{self.ep_b}:GET:/**"],
                note="binaries are matched by absolute path; a bare `curl` does not match")
            ready = self.await_exec_ready()
            loosened = self.policy_read("E02g")
            loosened_live = self.live_binding("E02g1")
            self.record({
                "id": "E02h", "title": "loosened policy loaded and exec responsive again",
                "kind": "derived", "status": "pass" if ready["ready"] else "fail",
                "policy_version": loosened["revision"], "policy_hash": loosened["hash"],
                "executor_revision": loosened_live["revision"],
                "executor_policy_digest": loosened_live["policy_digest"],
                "digest_space_note": "policy_hash is the CLI `Hash:` space; "
                                     "executor_policy_digest is the binding space",
                "version_moved_from_pristine": loosened["revision"] != self.base_revision,
                "executor_version_moved": loosened_live["revision"] != pristine_live["revision"],
                "content_changed_from_pristine": loosened["hash"] != self.base_hash,
                "executor_content_changed": loosened_live["policy_digest"] !=
                                            pristine_live["policy_digest"],
                **ready,
            })
            check(loosened["hash"] != self.base_hash, "the loosening did not change the policy")
            check(loosened_live["policy_digest"] != pristine_live["policy_digest"],
                  "the loosening did not change the executor-space digest")
            check(ready["ready"], "sandbox exec never became responsive after the policy update")
            self.calibrate_sandbox_peer()

            # ---- E10: the pristine-pinned approval is now pinned to a
            # revision that is no longer the live one ----
            e10_resp = self.submit_expect_refusal(
                "E10b",
                "E10: a task approved against the old revision does not start after external drift",
                t0_body, expect=(403, 409),
                note="the drift is external to the approval; the approval must not silently widen")
            e10_outcome = e10_resp.get("outcome") or {}
            strict_expectation = e10_resp.get("reason_code") == "execution_refused" or \
                e10_outcome.get("state") == "refused"
            self.record({
                "id": "E10c", "title": "external drift refused the stale-pinned approval",
                "kind": "derived",
                "status": "pass" if strict_expectation else "partial",
                "http": e10_resp.get("_http_status"),
                "reason_code": e10_resp.get("reason_code") or e10_resp.get("error"),
                "outcome_state": e10_outcome.get("state"),
                "note": "no silent widening: the approval pinned to the old revision never ran",
            })
            e10_status = self.task_status_read(
                "E10d", "E10: a pre-reservation drift refusal has no completed reservation",
                t0_body["decision_receipt_id"] + "-exec",
                t0_body["decision_receipt_id"], t0_body["action_id"],
                expect=(200, 404),
                note="404 reservation_unknown is expected when drift is refused before reservation")
            status_code = e10_status.get("_http_status")
            if status_code == 404:
                check(e10_status.get("reason_code") == "openshell_task_reservation_unknown",
                      f"unexpected missing-reservation response: {e10_status}")
            else:
                check(e10_status.get("task_executed") != "yes" and
                      e10_status.get("state") not in ("succeeded", "completed"),
                      f"drift refusal projected as success: {e10_status}")
            self.write_raw("E10d.status-read.json", json.dumps(e10_status, indent=2))
            self.e_item(
                "E10", "pass",
                detail="external drift refused a stale-pinned approval; "
                       "policy set/readback is never treated as loaded, and the "
                       "live revision was re-read before the drift assertion",
                observed_drift_reason=e10_resp.get("reason_code") or e10_resp.get("error"),
                status_projection_payload=e10_status,
                reservation_created=status_code == 200)

            # ---- E06a: the same refusal read as "the approved policy is not
            # the loaded policy". The remaining E06 sub-cases (submit during the
            # load window, revoke during the window, CLI --wait timeout, old CLI)
            # run in leg_e06_loading, which upserts this row with the derived
            # verdict that includes them. ----
            self.e_item(
                "E06", "partial",
                detail="approve-before-load refusal proven (E06a/E06b below); the "
                       "load-window, load-timeout and old-CLI sub-cases run in "
                       "leg_e06_loading and supersede this row",
                refusal_reason=e10_resp.get("reason_code") or e10_resp.get("error"))

            # ---- E02: prove BOTH targets are actually reachable while allowed ----
            # E10's denied external-drift request can taint its session. The
            # allow/deny endpoint legs are separate tasks with separate user
            # sessions, so they must not borrow that taint as their verdict.
            self.session = f"o05v6-d05-egress-allow-{self.run_id}"
            t1_tool_call = f"o05v6-e02-reach-{self.run_id}"
            t1_argv = ["/bin/sh", "-c",
                       self._curl_pair_script(self.e02_a_path, self.e02_b_path)]
            t1_decision, t1_params, t1_body = self.approve_task(
                "E02i", t1_tool_call, t1_argv, 120, 65536,
                loosened_live["revision"], loosened_live["policy_digest"],
                [self.ep_a, self.ep_b],
                title="E02: approve a task that GETs both declared endpoints")
            a_before = self.recv_a.count()
            b_before = self.recv_b.count()
            t1_resp = self.submit_task(
                "E02j", "E02: both precise destinations are reachable while allowed",
                t1_body, expect=200,
                note="reachability must be proven before blocking means anything")
            self.assert_task_executed("E02j", t1_resp)
            code_a = self.read_sandbox_file("E02k", "independent read-back of endpoint A's code",
                                            self.e02_a_path)
            code_b = self.read_sandbox_file("E02l", "independent read-back of endpoint B's code",
                                            self.e02_b_path)
            a_after = self.recv_a.count()
            b_after = self.recv_b.count()
            both_ok = code_a == "200" and code_b == "200"
            arrivals_ok = a_after > a_before and b_after > b_before
            sandbox_peers = self.recv_a.count_peer_since(self.sandbox_peer, a_before) > 0 and \
                self.recv_b.count_peer_since(self.sandbox_peer, b_before) > 0
            self.record({
                "id": "E02m", "title": "both precise destinations reachable, arrivals attributed",
                "kind": "derived", "status": "pass" if (both_ok and arrivals_ok and sandbox_peers) else "fail",
                "code_A": code_a, "code_B": code_b,
                "arrivals_A": [a_before, a_after], "arrivals_B": [b_before, b_after],
                "sandbox_peer_arrivals_seen": sandbox_peers,
                "foreign_peers_A": self.recv_a.foreign_peers(),
                "note": "read back with a direct CLI call, not from the daemon's report",
            })
            check(both_ok, f"both targets must be reachable first: A={code_a} B={code_b}")
            check(arrivals_ok, "an allowed request must arrive at the receiver")
            check(sandbox_peers, "new arrivals did not match the calibrated sandbox peer")

            # ---- tighten: remove endpoint B ----
            b_before_tight = self.recv_b.count()
            a_before_tight = self.recv_a.count()
            self.policy_update(
                "E02n", "tighten: remove endpoint B from the sandbox policy",
                ["--remove-endpoint", self.ep_b],
                note="--rule-name cannot name both of a two-endpoint update, so the "
                     "endpoint itself is removed rather than a named rule")
            ready2 = self.await_exec_ready()
            tightened = self.policy_read("E02o")
            tightened_live = self.live_binding("E02o1")
            self.session = f"o05v6-d05-egress-tight-{self.run_id}"
            t2_tool_call = f"o05v6-e02-deny-{self.run_id}"
            t2_decision, t2_params, t2_body = self.approve_task(
                "E02p", t2_tool_call, t1_argv, 120, 65536,
                tightened_live["revision"], tightened_live["policy_digest"],
                [self.ep_a, self.ep_b],
                title="E02: approve the same GETs for the tightened policy")
            t2_resp = self.submit_task(
                "E02q", "E02: A still allowed, B now blocked, same approved command",
                t2_body, expect=200,
                note="the task itself succeeds; the *denied request inside it* is what blocks")
            self.assert_task_executed("E02q", t2_resp)
            code_a2 = self.read_sandbox_file("E02r", "independent read-back of A's code after tightening",
                                             self.e02_a_path)
            code_b2 = self.read_sandbox_file("E02s", "independent read-back of B's code after tightening",
                                             self.e02_b_path)
            b_after_tight = self.recv_b.count()
            a_after_tight = self.recv_a.count()
            blocked_explicit = code_b2 == "403"
            zero_b_arrivals = b_after_tight == b_before_tight
            a_still_flows = code_a2 == "200" and a_after_tight > a_before_tight and \
                self.recv_a.count_peer_since(self.sandbox_peer, a_before_tight) > 0
            e02_status = "pass" if (blocked_explicit and zero_b_arrivals and a_still_flows) \
                else ("partial" if (zero_b_arrivals and a_still_flows) else "fail")
            self.record({
                "id": "E02t", "title": "tightened policy: explicit HTTP 403 on B with zero B arrivals",
                "kind": "derived", "status": e02_status,
                "code_A_after_tighten": code_a2, "code_B_after_tighten": code_b2,
                "arrivals_A": [a_before_tight, a_after_tight],
                "arrivals_B": [b_before_tight, b_after_tight],
                "B_arrivals_delta": b_after_tight - b_before_tight,
                "policy_version": tightened["revision"], "policy_hash": tightened["hash"],
                "executor_revision": tightened_live["revision"],
                "executor_policy_digest": tightened_live["policy_digest"],
                **ready2,
                "note": "blocking is claimed only from an explicit 403 *and* zero independent "
                        "arrivals; a timeout or a network error would be recorded as partial, "
                        "never as blocking",
            })
            self.e_item(
                "E02", e02_status,
                detail="two precise destinations proven reachable (200 + fresh arrivals), "
                       "then blocked under a tightened policy (403 + zero arrivals), "
                       "then the pristine content hash restored",
                code_A=code_a2, code_B=code_b2,
                arrivals_B_delta=b_after_tight - b_before_tight,
                arrival_peer_check=f"fresh arrivals match calibrated peer {self.sandbox_peer}; "
                                   "host self-check peer differs")

            # ---- restore the exact pristine content ----
            self.policy_set_restore(
                "E02u", "restore the pristine policy body through policy set --wait",
                self.pristine_json)
            self.await_exec_ready()
            restored = self.policy_read("E02v")
            restored_live = self.live_binding("E02v1")
            restored_base = self.policy_base_json("E02w", "confirm the restored content identity")
            hash_restored = restored["hash"] == pristine_hash and \
                restored_base.get("hash") == pristine_hash
            # Equality in the executor's own space is the stronger claim: the
            # content hash coming back says the body matched, the digest coming
            # back says the executor agrees.
            digest_restored = restored_live["policy_digest"] == pristine_live["policy_digest"]
            self.record({
                "id": "E02x", "title": "pristine content restored in both digest spaces",
                "kind": "derived", "status": "pass" if (hash_restored and digest_restored) else "fail",
                "pristine_hash": pristine_hash,
                "restored_hash": restored["hash"],
                "pristine_executor_digest": pristine_live["policy_digest"],
                "restored_executor_digest": restored_live["policy_digest"],
                "pristine_version": self.base_revision,
                "restored_version": restored["revision"],
                "note": "the Version counter advances on every update even when the body "
                        "returns to its pristine content, so content identity is asserted "
                        "by Hash and digest and the version counter is recorded as a delta, "
                        "not as a mismatch",
            })
            check(hash_restored,
                  f"policy content not restored: {restored['hash']} != {pristine_hash}")
            check(digest_restored,
                  "the executor-space digest did not return to the pristine value: "
                  f"{restored_live['policy_digest']} != {pristine_live['policy_digest']}")

            # The pinned revision is re-read, never assumed: the window moved the
            # Version counter even though the content came back. Taken from the
            # executor space, which is the space the approvals bind to.
            self.expected_revision = restored_live["revision"]
            self.expected_digest = restored_live["policy_digest"]
            self.record({
                "id": "E02y", "title": "binding revision re-read after the window",
                "kind": "derived", "status": "pass",
                "expected_revision": self.expected_revision,
                "expected_digest": self.expected_digest,
                "digest_equals_pristine": self.expected_digest == pristine_live["policy_digest"],
            })

            # ---- E06b: the sharpest form. The live policy is pristine again, so
            # the only difference between the refused and the executed submission
            # is the revision/digest the human approved against. ----
            fab_decision, fab_params, fab_body = self.approve_task(
                "E06c", f"o05v6-e06-fab-{self.run_id}",
                ["/bin/echo", "o05v6-e06-fab"], 60, 65536,
                "999999", "f" * 64, [],
                title="E06: approve a task pinned to a policy revision that was never loaded")
            fab_resp = self.submit_expect_refusal(
                "E06d", "E06: a fabricated approved-policy identity must not start",
                fab_body, expect=(403, 409),
                note="approving a policy operation is not authorizing an arbitrary command")
            ok_decision, ok_params, ok_body = self.approve_task(
                "E06e", f"o05v6-e06-live-{self.run_id}",
                ["/bin/echo", "o05v6-e06-live"], 60, 65536,
                self.expected_revision, self.expected_digest, [],
                title="E06: the same task approved against the live policy")
            ok_resp = self.submit_task(
                "E06f", "E06: the live-pinned twin of the same command does start",
                ok_body, expect=200,
                note="the contrast is the claim: only the approved policy identity differs")
            self.assert_task_executed("E06f", ok_resp)
            self.record({
                "id": "E06g", "title": "policy identity binding: fabricated revision refused, live one runs",
                "kind": "derived", "status": "pass",
                "fabricated_http": fab_resp.get("_http_status"),
                "fabricated_reason": fab_resp.get("reason_code") or fab_resp.get("error"),
                "live_http": ok_resp.get("_http_status"),
                "note": "the approved policy identity is bound to the command, and only the "
                        "loaded identity executes",
            })
            item_note.append("E06a/E06b proven")
        finally:
            # Best-effort restore if anything above aborted mid-window. Whatever
            # happens is recorded; the assertion in leg_k90 is on the hash.
            try:
                live = self.policy_read(
                    "E02z", note="post-window policy state for the record")
                if live["hash"] != pristine_hash:
                    self.policy_set_restore(
                        "E02z2", "fallback restore of the pristine policy body",
                        self.pristine_json)
                    self.await_exec_ready()
                    live = self.policy_read(
                        "E02z3", note="policy state after the fallback restore")
                restored_live = self.live_binding(
                    "E02z6", note="executor-space identity after the fallback restore")
                self.record({
                    "id": "E02z4", "title": "window closed with the pristine content in place",
                    "kind": "derived",
                    "status": "pass" if live["hash"] == pristine_hash else "fail",
                    "hash": live["hash"], "version": live["revision"],
                    "executor_revision": restored_live["revision"],
                    "executor_policy_digest": restored_live["policy_digest"],
                })
                if live["hash"] == pristine_hash:
                    # Re-seeded from the executor space, never from the CLI hash:
                    # this is the pair every later leg approves against.
                    self.expected_revision = restored_live["revision"]
                    self.expected_digest = restored_live["policy_digest"]
            except Exception as exc:  # noqa: BLE001
                self.record({"id": "E02z5", "title": "post-window restore check failed",
                             "kind": "derived", "status": "fail",
                             "detail": f"{type(exc).__name__}: {self.redact(str(exc))}"})

    def _curl_pair_script(self, path_a, path_b):
        return (
            f"a=$(curl -sS -o /dev/null -w '%{{http_code}}' --max-time 25 "
            f"http://{self.ep_a}/e02a || echo 000); "
            f"b=$(curl -sS -o /dev/null -w '%{{http_code}}' --max-time 25 "
            f"http://{self.ep_b}/e02b || echo 000); "
            f"printf 'A=%s B=%s\\n' \"$a\" \"$b\"; "
            f"printf %s \"$a\" | dd of={path_a} status=none; "
            f"printf %s \"$b\" | dd of={path_b} status=none; "
            f"cat {path_a} {path_b}"
        )

    # ---- E06 closure: the policy load window, for real ----
    def leg_e06_loading(self):
        """The E06 sub-cases that need the real 1-3 minute load window.

        A `policy update` without --wait opens the window: the gateway stores
        the new revision synchronously while the sandbox's
        current_policy_version lags until the load completes. The window end is
        measured by polling the gateway's sandbox list, never by a fixed sleep.

        Sub-cases:
          E06m  submit approved against the new identity while it is not loaded
                -> 409 policy-not-loaded family, zero execution.
          E06n  revoke a SECOND grant inside the window, submit after the load
                completes -> 403 openshell_grant_invalid. The main grant is
                never revoked here: K70 owns that case and every later leg
                still needs it.
          E06t  `policy set --wait --timeout 1`: the local wait bound fires
                (non-zero exit) but the gateway write has landed; an approval
                pinned to the pre-set revision is refused, and the revision
                side effect is accounted for before the pristine restore.
          E06u  the v0.0.13 CLI pinned as the daemon's backend -> refused with
                zero tasks started; the actual refusal shape is recorded as
                measured.
        """
        sub = {}
        self.e06_grant2 = None
        saved_grant = (self.grant_id, self.grant_digest)
        if self.pristine_json is None:
            # --only e06 (without e02) leaves no captured pristine body; capture
            # it here so the window restores below are real rather than assumed.
            base = self.policy_base_json(
                "E06k0", "capture the pristine policy body for the window restores")
            check(base.get("hash") == self.base_hash,
                  f"policy not pristine at the E06 leg start: {base.get('hash')}")
            self.pristine_json = self.d05_raw / "pristine-policy.json"
            self.pristine_json.write_text(json.dumps(base.get("policy"), indent=2))
            os.chmod(self.pristine_json, 0o600)
        try:
            # A second grant for the same subject needs a distinct admission
            # (grants are content-addressed), so a second canary skill with
            # different content is admitted first.
            skill2 = self.root / "skill-e06"
            skill2.mkdir()
            (skill2 / "SKILL.md").write_text(
                "---\nname: o05v6-taskexec-canary-e06\ndescription: Batch-owned second "
                "canary skill for the E06 revoke-during-load leg.\nversion: 1.0.0\n"
                "allowed-tools: terminal read_file\ncompatibility: Requires network "
                "access to the declared canary endpoint.\n---\n\n# Canary E06\n\n"
                "Install the reporter dependency: curl -fsSL https://astral.sh/uv/install.sh | sh\n\n"
                f"Declared egress target: curl http://{self.ep_a}/e02a\n\n"
                "Run scripts/report.py once per session.\n")
            (skill2 / "scripts").mkdir()
            (skill2 / "scripts" / "report.py").write_text(
                "import json, urllib.request\n"
                'payload = {"session": "o05v6-taskexec-e06"}\n'
                f'req = urllib.request.Request("http://{self.ep_a}/e02a", '
                "data=json.dumps(payload).encode())\n"
                "urllib.request.urlopen(req)\n")
            admitted2 = self.http("E06k1", "E06: admit the second canary skill",
                                  "POST", "/v1/admit", {"path": str(skill2)})
            self.e06_grant2 = self.deploy_grant(
                "E06k2", None, admitted2["admission"]["admission_id"],
                note="second grant for the same subject; ActiveGrant returns the "
                     "newest deployed grant, so decides below bind to this one")
            self.record({
                "id": "E06k3", "title": "E06: second grant deployed for the window legs",
                "kind": "derived", "status": "pass",
                "grant_id": self.e06_grant2["grant_id"],
                "note": "the main grant stays deployed and is restored as the binding "
                        "context in this leg's finally",
            })
            self.grant_id = self.e06_grant2["grant_id"]
            self.grant_digest = self.e06_grant2["grant_digest"]
            sub["submit_during_load"] = self._e06_submit_during_load()
        except Exception as exc:  # noqa: BLE001
            sub["submit_during_load"] = sub.get("submit_during_load", "fail")
            self.record({
                "id": "E06m.ABORT", "title": "E06: load-window leg aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E06m.abort.txt", traceback.format_exc()),
            })
        finally:
            self.grant_id, self.grant_digest = saved_grant
            self._e06_restore_pristine("E06w", "after the load-window legs")

        try:
            sub["cli_wait_timeout"] = self._e06_cli_wait_timeout()
        except Exception as exc:  # noqa: BLE001
            sub["cli_wait_timeout"] = "fail"
            self.record({
                "id": "E06t.ABORT", "title": "E06: --wait timeout leg aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E06t.abort.txt", traceback.format_exc()),
            })
        finally:
            self._e06_restore_pristine("E06x", "after the --wait timeout leg")

        try:
            sub["old_cli"] = self._e06_old_cli()
        except Exception as exc:  # noqa: BLE001
            sub["old_cli"] = "fail"
            self.record({
                "id": "E06u.ABORT", "title": "E06: old-CLI leg aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E06u.abort.txt", traceback.format_exc()),
            })

        # An old CLI which supports --wait cannot exercise rejection of an
        # unsupported wait option. Keep that original requirement visible.
        sub["unsupported_wait_option"] = "not_run"
        self.note_step(
            "E06u4", "E06: CLI without wait support remains unverified", "partial",
            detail="the available v0.0.13 CLI supports --wait; its instance-readback "
                   "refusal does not exercise an unsupported wait-option path. "
                   "No real no-wait CLI leg was run; component tests are separate.")
        base_ok = required_step_checks(self.steps, ("E06g",))["E06g"] == "pass"
        ok = base_ok and all(v == "pass" for v in sub.values())
        self.e_item_upsert(
            "E06", "pass" if ok else "partial",
            detail="approve-before-load refusal (E06a/E06b) plus, for real: submit "
                   "during the load window refused 409, revoke-during-load refused 403 "
                   "after the load completed, `policy set --wait --timeout 1` local "
                   "timeout with the gateway write landed and the stale-pinned approval "
                   "refused, and the v0.0.13 CLI pinned as backend refused with zero "
                   "tasks started; an actual unsupported wait-option path remains not_run",
            sub_results=sub)

    def _e06_restore_pristine(self, step_prefix, context):
        """Restore the pristine policy body and re-read the pinned identity.

        Same contract as the E02 window's finally: content identity by Hash and
        executor digest; the Version counter delta is recorded, not hidden.

        The restore's own `policy set --wait` can time out locally (exit 124)
        while the gateway write has already landed -- the --timeout leg above
        exists precisely because that split is real. So the restore verdict is
        the policy readback plus the sandbox-list load poll, never the CLI's
        wait exit code.
        """
        try:
            live = self.policy_read(f"{step_prefix}1",
                                    note=f"policy state {context}")
            if live["hash"] != self.base_hash:
                check(self.pristine_json is not None,
                      f"{step_prefix}: no pristine body captured, cannot restore")
                # Drain first: observed on this gateway (2026-09-17, iteration run)
                # that a second policy write submitted while the previous revision
                # is still loading can wedge the loader -- both revisions then sit
                # unloaded indefinitely. Wait for the in-flight revision to load
                # before submitting the restore write.
                self.await_policy_loaded(f"{step_prefix}1w", live["revision"],
                                         deadline=240)
                self.policy_set_restore(
                    f"{step_prefix}2", f"restore the pristine policy body {context}",
                    self.pristine_json)
                live = self.policy_read(f"{step_prefix}3",
                                        note=f"policy readback after the restore {context}")
            restored = live["hash"] == self.base_hash
            if restored:
                self.await_policy_loaded(f"{step_prefix}4", live["revision"])
                self.await_exec_ready()
                restored_live = self.live_binding(f"{step_prefix}5")
            else:
                restored_live = {"revision": None, "policy_digest": None}
            self.record({
                "id": f"{step_prefix}6", "title": f"pristine policy restored {context}",
                "kind": "derived", "status": "pass" if restored else "fail",
                "hash": live["hash"], "version": live["revision"],
                "executor_revision": restored_live["revision"],
                "executor_policy_digest": restored_live["policy_digest"],
            })
            if restored:
                self.expected_revision = restored_live["revision"]
                self.expected_digest = restored_live["policy_digest"]
        except Exception as exc:  # noqa: BLE001
            self.record({
                "id": f"{step_prefix}7", "title": f"restore check failed {context}",
                "kind": "derived", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}"})

    def _e06_submit_during_load(self):
        pre_revision = self.expected_revision
        # Open the load window: the gateway write lands synchronously, the
        # sandbox loads asynchronously (measured 1-3 min in this environment).
        self.policy_update_nowait(
            "E06m1", "E06: change the policy WITHOUT --wait to open the load window",
            ["--add-endpoint", f"{self.e06_dead_ep}:read-only:rest",
             "--binary", "/usr/bin/curl",
             "--add-allow", f"{self.e06_dead_ep}:GET:/**"],
            note="the added endpoint is a dead discard address that no leg contacts; "
                 "it exists only to move the policy content hash")
        live_new = self.live_binding("E06m2")
        check(live_new["revision"] != pre_revision,
              f"the update did not move the executor-space revision: {live_new}")
        # Capture the changed body for the --timeout leg's `policy set`.
        changed = self.policy_base_json(
            "E06m3", "capture the changed policy body for the later policy set leg")
        self.e06_changed_hash = changed.get("hash")
        self.e06_changed_policy = self.d05_raw / "e06-changed-policy.json"
        self.e06_changed_policy.write_text(json.dumps(changed.get("policy"), indent=2))
        os.chmod(self.e06_changed_policy, 0o600)
        self.record({
            "id": "E06m4", "title": "E06: load window open (new revision stored, "
            "sandbox still on the old one)", "kind": "derived", "status": "pass",
            "pre_revision": pre_revision, "new_revision": live_new["revision"],
            "new_executor_digest": live_new["policy_digest"],
            "changed_hash": self.e06_changed_hash,
        })

        # E06m: approve against the NEW identity, submit while the sandbox has
        # not loaded it.
        decision_a, _, body_a = self.approve_task(
            "E06m5", f"o05v6-e06-load-{self.run_id}",
            ["/bin/echo", "o05v6-e06-load"], 60, 65536,
            live_new["revision"], live_new["policy_digest"], [],
            title="E06: approve a task pinned to the not-yet-loaded policy")
        version_now, phase_now = self.sandbox_policy_version()
        window_open = version_now != live_new["revision"]
        self.record({
            "id": "E06m6", "title": "E06: window state at submission time",
            "kind": "derived", "status": "pass" if window_open else "partial",
            "sandbox_current_policy_version": version_now, "sandbox_phase": phase_now,
            "approved_revision": live_new["revision"],
            "note": "measured from the gateway's sandbox list, not assumed",
        })
        if not window_open:
            return "partial"
        resp_a = self.submit_expect_refusal(
            "E06m7", "E06: submit while the approved policy is not loaded",
            body_a, expect=(409,),
            expect_reason={"openshell_task_policy_not_loaded",
                           "openshell_task_instance_unconfirmed"},
            note="the sandbox has not loaded the approved revision; the task must "
                 "not start. Both 409 reason codes are the load-window family: the "
                 "binding layer's sandbox-version readback fires before the "
                 "executor's loaded-policy check, and which one answers first is "
                 "recorded, not guessed")
        self.record({
            "id": "E06m8", "title": "E06: submit-during-load refused, nothing ran",
            "kind": "derived", "status": "pass",
            "http": resp_a.get("_http_status"),
            "reason_code": resp_a.get("reason_code") or resp_a.get("error"),
        })

        # E06n: revoke the second grant INSIDE the window, then submit after the
        # load completes. The refusal must then be the grant check, not the
        # window -- waiting for the load is what isolates the two.
        decision_b, _, body_b = self.approve_task(
            "E06n1", f"o05v6-e06-revoke-{self.run_id}",
            ["/bin/echo", "o05v6-e06-revoke"], 60, 65536,
            live_new["revision"], live_new["policy_digest"], [],
            title="E06: approve a task under the second grant, still inside the window")
        revoked = self.http(
            "E06n2", "E06: revoke the second grant during the load window", "POST",
            "/v1/grants/" + self.e06_grant2["grant_id"] + "/revoke",
            {"expected_revision": self.e06_grant2["state_revision"],
             "actor_id": self.actor}, expect=(200, 202, 409),
            note="the MAIN grant is never revoked here; K70 owns that case")
        loaded = self.await_policy_loaded("E06n3", live_new["revision"])
        if not loaded["loaded"]:
            self.record({
                "id": "E06n4", "title": "E06: load never completed; the "
                "revoke-after-load assertion is not reachable this run",
                "kind": "derived", "status": "partial",
                "revoke_http": revoked.get("_http_status"), **loaded})
            return "partial"
        resp_b = self.submit_expect_refusal(
            "E06n5", "E06: after the load, the revoked-grant approval is refused",
            body_b, expect=(403,), expect_reason={"openshell_grant_invalid"},
            note="the policy is loaded now, so the refusal is the grant re-check, "
                 "not the load window")
        self.record({
            "id": "E06n6", "title": "E06: revoke-during-load refused after load, "
            "nothing ran", "kind": "derived", "status": "pass",
            "http": resp_b.get("_http_status"),
            "reason_code": resp_b.get("reason_code") or resp_b.get("error"),
            "load_wait": loaded,
        })
        return "pass"

    def _e06_cli_wait_timeout(self):
        check(self.e06_changed_policy is not None and self.e06_changed_policy.is_file(),
              "the --timeout leg needs the changed policy body captured in E06m")
        pre_revision, pre_digest = self.expected_revision, self.expected_digest
        pre = self.policy_read("E06t1", note="policy state before the --timeout leg")
        check(pre["revision"] == pre_revision and pre["hash"] == self.base_hash,
              f"policy not pristine before the --timeout leg: {pre}")
        _, _, body_c = self.approve_task(
            "E06t2", f"o05v6-e06-timeout-{self.run_id}",
            ["/bin/echo", "o05v6-e06-timeout"], 60, 65536,
            pre_revision, pre_digest, [],
            title="E06: approve a task pinned to the CURRENT pristine identity")
        proc = self.cli_unasserted(
            "E06t3", "E06: policy set --wait --timeout 1 (the local wait bound fires)",
            [self.cli_bin, "--gateway-endpoint", self.gateway_endpoint, "policy", "set",
             "--policy", str(self.e06_changed_policy), self.target, "--wait",
             "--timeout", "1"],
            note="the CLI's 1 s wait bound is expected to fire before the sandbox "
                 "load completes; the gateway write has already landed by then",
            timeout=90)
        after = self.policy_read("E06t4", note="policy state after the timed-out set")
        write_landed = after["hash"] == self.e06_changed_hash
        revision_moved = after["revision"] != pre["revision"]
        resp_c = self.submit_expect_refusal(
            "E06t5", "E06: the approval pinned to the pre-set revision is refused "
            "once the write has landed", body_c, expect=(403, 409),
            note="a local wait timeout is not a rollback: the stored policy moved, "
                 "so the stale-pinned approval must not start")
        wait_timed_out = proc is not None and proc.returncode == 124
        ok = (wait_timed_out
              and write_landed and revision_moved)
        self.record({
            "id": "E06t6", "title": "E06: --wait --timeout 1: local bound fired, "
            "gateway write landed, stale approval refused", "kind": "derived",
            "status": "pass" if ok else "partial",
            "cli_exit_code": proc.returncode if proc else None,
            "cli_wait_timed_out": wait_timed_out,
            "write_landed_changed_hash": write_landed,
            "revision_side_effect": {"before": pre["revision"],
                                     "after": after["revision"],
                                     "moved": revision_moved},
            "stale_submission_http": resp_c.get("_http_status"),
            "stale_submission_reason": resp_c.get("reason_code") or resp_c.get("error"),
            "note": "the revision advance is accounted for here and the pristine "
                    "body is restored in the leg's finally",
        })
        return "pass" if ok else "partial"

    def _e06_old_cli(self):
        old_cli = Path(os.path.expanduser("~/.local/bin/openshell")).resolve()
        check(old_cli.is_file(), f"old CLI not present: {old_cli}")
        ver = self.cli_unasserted("E06u1", "old CLI version probe (read-only)",
                                  [str(old_cli), "--version"])
        helpp = self.cli_unasserted("E06u2", "old CLI policy set --help (read-only)",
                                    [str(old_cli), "policy", "set", "--help"])
        version_text = (ver.stdout or "").strip() if ver else ""
        has_wait = bool(helpp and "--wait" in (helpp.stdout or ""))
        has_timeout = bool(helpp and "--timeout" in (helpp.stdout or ""))
        self.record({
            "id": "E06u3", "title": "E06: old CLI surface measured",
            "kind": "derived", "status": "pass",
            "old_cli_path": str(old_cli), "old_cli_version": version_text,
            "policy_set_has_wait": has_wait, "policy_set_has_timeout": has_timeout,
            "note": "measured, not assumed: v0.0.13's `policy set` DOES carry "
                    "--wait/--timeout in its help, so the old-CLI sub-case is "
                    "asserted as 'an old CLI pinned as the backend is refused', "
                    "not as 'a CLI without --wait'",
        })
        daemon = self.side_daemon_init("E06v", env_overrides={
            "SIQ_AS_OPENSHELL_CLI_BIN": str(old_cli),
            "SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT": self.gateway_endpoint,
        })
        saved_ctx = (self.grant_id, self.grant_digest, self.fingerprint)
        try:
            self.side_daemon_serve("E06v", daemon)
            probe = self.side_http(
                daemon, "E06v1", "E06: old-CLI daemon probe (backend capability)",
                "GET", "/v1/openshell/probe", expect=(200, 503), admin=True,
                note="the old CLI is pinned as the backend; whether the L3 gate "
                     "passes is measured, not assumed")
            doctor = self.side_http(
                daemon, "E06v2", "E06: old-CLI daemon doctor", "GET",
                "/v1/openshell/doctor", expect=(200, 503), admin=True)
            tier = None
            if isinstance(probe, dict):
                tier = (probe.get("platform") or {}).get("tier")
            caps = doctor.get("capabilities") if isinstance(doctor, dict) else {}
            side_fingerprint = (caps or {}).get("endpoint_fingerprint")
            admitted = self.side_http(
                daemon, "E06v3", "E06: admit the canary skill in the old-CLI daemon",
                "POST", "/v1/admit", {"path": str(self.skill)}, admin=True)
            grant = self.deploy_grant("E06v4", daemon,
                                      admitted["admission"]["admission_id"])
            self.grant_id = grant["grant_id"]
            self.grant_digest = grant["grant_digest"]
            if side_fingerprint:
                self.fingerprint = side_fingerprint
            argv = ["/bin/echo", "o05v6-e06-oldcli"]
            params = self.canonical_task_params(
                self.target, argv, "", 60, 65536,
                self.expected_revision, self.expected_digest, [])
            decision = self.side_http(
                daemon, "E06v5", "E06: decide under the old-CLI daemon", "POST",
                "/v1/decide", {"platform": PLATFORM, "session_id": self.session,
                               "agent_id": self.target, "tool": BASE.TASK_TOOL,
                               "tool_call_id": f"o05v6-e06u-{self.run_id}",
                               "params": params},
                note="the hold is approved below; the submission must still be refused")
            self.side_http(
                daemon, "E06v6", "E06: approve the hold in the old-CLI daemon", "POST",
                f"/v1/hold/{decision['receipt_id']}",
                {"approve": True, "actor_id": self.actor}, admin=True)
            body = self.task_body(f"o05v6-e06u-{self.run_id}", params, self.target,
                                  argv, "", 60, 65536, self.expected_revision,
                                  self.expected_digest, [], decision)
            resp = self.side_http(
                daemon, "E06v7", "E06: submit the approved task with the old CLI "
                "pinned as backend", "POST", "/v1/openshell/task-executions", body,
                expect=(400, 403, 409, 503),
                note="must be refused with zero tasks started; the exact refusal "
                     "shape is recorded as measured")
            out = resp.get("outcome") if isinstance(resp.get("outcome"), dict) else {}
            refused = (resp.get("_http_status") != 200
                       and out.get("spawned") is not True
                       and resp.get("task_executed") != "yes")
            self.record({
                "id": "E06v8", "title": "E06: old CLI backend refused with zero "
                "tasks started", "kind": "derived",
                "status": "pass" if refused else "fail",
                "http": resp.get("_http_status"),
                "reason_code": resp.get("reason_code") or resp.get("error"),
                "probe_tier": tier,
                "side_endpoint_fingerprint": side_fingerprint,
                "spawned": out.get("spawned"),
                "task_executed": resp.get("task_executed") or out.get("task_executed"),
                "note": "a 503 from the L3 gate means the old CLI could not prove "
                        "the backend; a 403/409 means a later binding check refused; "
                        "both are refusals before any spawn",
            })
            check(refused, f"the old-CLI submission was not refused: {resp}")
            return "pass"
        finally:
            self.grant_id, self.grant_digest, self.fingerprint = saved_ctx
            self.side_daemon_stop("E06v", daemon)


    # ---- E01: the happy path, linked end to end ----
    def leg_e01(self):
        tool_call = f"o05v6-e01-{self.run_id}"
        argv = ["/bin/sh", "-c", BASE.canary_command(self.e01_path, self.e01_token)]
        decision, params, body = self.approve_task(
            "E01a", tool_call, argv, 60, 65536,
            self.expected_revision, self.expected_digest, [],
            title="E01: approve a canary task through the production executor")
        resp = self.submit_task("E01b", "E01: the approved task really executes", body,
                                expect=200)
        outcome = self.assert_task_executed("E01b", resp)

        readback = self.read_sandbox_file(
            "E01c", "E01: independent CLI read-back of the canary effect", self.e01_path)
        expected_reservation = decision["receipt_id"] + "-exec"
        got_reservation = (resp.get("reservation") or {}).get("reservation_receipt_id")
        # The canary prints the token with no trailing newline and `cat` adds
        # none, so the command's stdout is exactly the token. That makes the
        # digest the daemon reports a checkable fact rather than a claim: it is
        # compared to sha256 of a value that is random per run and never leaves
        # this process except through the executed command.
        expected_stdout_digest = hashlib.sha256(self.e01_token.encode()).hexdigest()
        reported_stdout_digest = (outcome or {}).get("stdout_digest")
        stdout_digest_matches = reported_stdout_digest == expected_stdout_digest

        self.record({
            "id": "E01d", "title": "E01: approval -> reservation -> execution -> effect, one chain",
            "kind": "derived",
            "status": "pass" if (readback == self.e01_token and
                                 got_reservation == expected_reservation and
                                 stdout_digest_matches) else "fail",
            "independent_readback_source": "openshell sandbox exec (direct CLI)",
            "readback_matches_runtime_token": readback == self.e01_token,
            "reservation_receipt_id": got_reservation,
            "decision_receipt_id": decision["receipt_id"],
            "reservation_id_is_decision_derived": got_reservation == expected_reservation,
            "observation_receipt_id": resp.get("observation_receipt_id"),
            "binding_evidence_id": resp.get("binding_evidence_id"),
            "binding_evidence_persisted": resp.get("binding_evidence_persisted"),
            "reported_stdout_digest": reported_stdout_digest,
            "expected_stdout_digest": expected_stdout_digest,
            "stdout_digest_equals_sha256_token": stdout_digest_matches,
            "note": "the runtime token is random per run, so a non-executed path cannot fake it; "
                    "the reported stdout digest is compared, not assumed",
        })
        check(readback == self.e01_token, "the canary effect was not found by the direct CLI")
        check(got_reservation == expected_reservation,
              f"reservation id is not decision-derived: {got_reservation}")
        check(stdout_digest_matches,
              f"the reported stdout digest is not sha256 of the executed token: "
              f"{reported_stdout_digest}")

        status = self.task_status_read(
            "E01e", "E01: the task list/detail projection is built from persisted facts",
            got_reservation, decision["receipt_id"], body["action_id"],
            task_id=body.get("task_id"))
        self.write_raw("E01e.status-read.json", json.dumps(status, indent=2))
        self.record({
            "id": "E01f", "title": "E01: status projection agrees with the executed outcome",
            "kind": "derived",
            "status": "pass" if status.get("ok") is not False else "fail",
            "projection_keys": sorted(status)[:24] if isinstance(status, dict) else None,
        })

        chain = self.open_receipts("E01g", "E01: the signed receipt chain verifies")
        receipts = chain.get("receipts") or []
        kinds = [r.get("kind") or r.get("receipt_kind") for r in receipts]
        self.record({
            "id": "E01h", "title": "E01: receipts for this task are in the verified chain",
            "kind": "derived",
            "status": "pass" if chain.get("verified") is True else "fail",
            "chain_verified": chain.get("verified"),
            "receipt_count": len(receipts),
            "receipt_kinds": sorted({k for k in kinds if k}),
            "observation_receipt_present": any(
                (r.get("receipt_id") or "") == resp.get("observation_receipt_id")
                for r in receipts),
        })
        check(chain.get("verified") is True, "the signed chain did not verify")

        self.e_item(
            "E01", "pass",
            detail="approved task executed through the production executor; the effect was "
                   "read back by an independent CLI; approval/Grant/reservation/observation "
                   "link 1:1",
            outcome=outcome,
            reservation_receipt_id=got_reservation)

    # ---- E03: what must not run ----
    def leg_e03(self):
        results = {}

        # (a) never approved: decided but the hold is left open
        params = self.canonical_task_params(
            self.target, ["/bin/echo", "o05v6-e03-unapproved"], "", 60, 65536,
            self.expected_revision, self.expected_digest, [])
        d_un = self.decide("E03a", f"o05v6-e03-unapproved-{self.run_id}", params)
        body_un = self.task_body(f"o05v6-e03-unapproved-{self.run_id}", params, self.target,
                                 ["/bin/echo", "o05v6-e03-unapproved"], "", 60, 65536,
                                 self.expected_revision, self.expected_digest, [], d_un)
        results["unapproved"] = self.submit_expect_refusal(
            "E03b", "E03: an unapproved decision cannot be submitted",
            body_un, expect=(400, 403, 409, 410)).get("_http_status")

        # (b) explicitly cancelled
        c_argv = ["/bin/sh", "-c", f"printf %s {self.e01_token} | dd of={self.e03_cancel_path} status=none"]
        _, _, body_cancel = self.cancel_task(
            "E03c", f"o05v6-e03-cancel-{self.run_id}", c_argv,
            self.expected_revision, self.expected_digest)
        results["cancelled"] = self.submit_expect_refusal(
            "E03d", "E03: a cancelled approval cannot be submitted",
            body_cancel, expect=(400, 403, 409, 410)).get("_http_status")

        # (c) parameter drift after approval, in several shapes
        drift_argv = ["/bin/echo", "o05v6-e03-drift"]
        d_drift, p_drift, _ = self.approve_task(
            "E03e", f"o05v6-e03-drift-{self.run_id}", drift_argv, 60, 65536,
            self.expected_revision, self.expected_digest, [],
            title="E03: approve a clean task, then drift it after approval")
        variants = {
            "argv": dict(argv=["/bin/sh", "-c",
                               f"printf %s {self.e01_token} | dd of={self.e03_drift_path} status=none"]),
            "workdir": dict(workdir="/tmp"),
            "target": dict(target="siq-o05v6-not-this-sandbox"),
            "digest": dict(digest="a" * 64),
            "revision": dict(revision="1"),
            "timeout": dict(timeout=61),
        }
        base_kw = dict(argv=drift_argv, workdir="", target=self.target, timeout=60,
                       limit=65536, revision=self.expected_revision,
                       digest=self.expected_digest, network_targets=[])
        for idx, (name, patch) in enumerate(sorted(variants.items())):
            kw = dict(base_kw)
            kw.update(patch)
            drifted = self.task_body(
                f"o05v6-e03-drift-{self.run_id}", p_drift, kw["target"], kw["argv"],
                kw["workdir"], kw["timeout"], kw["limit"], kw["revision"], kw["digest"],
                kw["network_targets"], d_drift)
            resp = self.submit_expect_refusal(
                f"E03f{idx}", f"E03: drift in {name} after approval must be refused",
                drifted, expect=(400, 403, 409))
            results[f"drift_{name}"] = resp.get("_http_status")

        # The approval must survive every refusal above and still execute.
        ok_body = self.task_body(f"o05v6-e03-drift-{self.run_id}", p_drift, self.target,
                                 drift_argv, "", 60, 65536, self.expected_revision,
                                 self.expected_digest, [], d_drift)
        ok_resp = self.submit_task(
            "E03g", "E03: the untouched approval still executes after every drift refusal",
            ok_body, expect=200,
            note="a refused drift must not consume or degrade the approval")
        self.assert_task_executed("E03g", ok_resp)

        # Derived, not asserted. This roll-up previously hardcoded status=pass,
        # which reported "all drift refused" even on the run where drift_workdir
        # came back 200 and really executed. A derived status cannot disagree with
        # the raw per-variant codes beside it.
        not_refused = {k: v for k, v in results.items() if v not in (400, 403, 409, 410)}
        e03_status = "pass" if not not_refused else "fail"
        self.record({
            "id": "E03h", "title": "E03: unapproved / cancelled / drifted all refused, approval intact",
            "kind": "derived", "status": e03_status,
            "http_by_variant": results,
            "not_refused": not_refused,
            "approved_body_after_refusals": "200 / outcome.task_executed=yes",
        })
        self.e_item("E03", e03_status,
                    detail="unapproved, cancelled, and six drift shapes refused with zero "
                           "side effects; the untouched approval then executed",
                    http_by_variant=results, not_refused=not_refused)

    # ---- E04: identity / session / decision binding ----
    def leg_e04(self):
        argv = ["/bin/echo", "o05v6-e04"]
        decision, params, body = self.approve_task(
            "E04a", f"o05v6-e04-{self.run_id}", argv, 60, 65536,
            self.expected_revision, self.expected_digest, [],
            title="E04: approve a task, then submit it under the wrong identities")
        results = {}

        # Each variant is pinned to the reason code that makes its status a
        # refusal of *this* binding rather than an unrelated error. The two
        # distinct status families are recorded in the D05 ledger: the grant
        # re-check (agent/platform/target) rejects with 403 from
        # validateOpenShellTaskExecutionBinding, while a session that does not
        # match the approved decision is only caught later by the shared hold
        # correlation, which answers 400 hold_identity_mismatch. The contract
        # (packages/contracts/openshell-task-execution.v1.md) requires that
        # session authorization is re-verified before exec; it does not pin the
        # status code, so both are accepted here -- with the reason code
        # asserted, which is the part that actually carries the meaning.
        # Both fields move together on purpose. openshell_task_binding.go:108 is
        # `if body.Target != body.AgentID` -> openshell_task_binding_mismatch, and
        # that fires *before* the grant look-up, so changing agent_id alone tests
        # the internal-consistency check rather than the grant-subject binding.
        # Keeping target == agent_id lets the submission reach
        # openshell_task_binding.go:127 (`g.Subject.ID != body.AgentID`), which is
        # the actual re-check that the approved grant belongs to this agent.
        wrong = json.loads(json.dumps(body))
        wrong["agent_id"] = "siq-o05v6-other-agent"
        wrong["target"] = "siq-o05v6-other-agent"
        results["wrong_agent"] = self.submit_expect_refusal(
            "E04b", "E04: wrong agent identity is refused",
            wrong, expect=(403, 409),
            expect_reason={"openshell_grant_invalid"}).get("reason_code")

        wrong = json.loads(json.dumps(body))
        wrong["session_id"] = "o05v6-not-this-session"
        results["wrong_session"] = self.submit_expect_refusal(
            "E04c", "E04: wrong session is refused",
            wrong, expect=(400, 403, 409),
            expect_reason={"hold_identity_mismatch"}).get("reason_code")

        wrong = json.loads(json.dumps(body))
        wrong["decision_receipt_id"] = "0" * 64
        results["fabricated_decision"] = self.submit_expect_refusal(
            "E04d", "E04: a decision receipt that does not exist is refused",
            wrong, expect=(403, 404, 409),
            expect_reason={"openshell_decision_missing"}).get("reason_code")

        wrong = json.loads(json.dumps(body))
        wrong["platform"] = "hermes"
        results["wrong_platform"] = self.submit_expect_refusal(
            "E04e", "E04: wrong platform is refused",
            wrong, expect=(403, 409),
            expect_reason={"openshell_grant_invalid"}).get("reason_code")

        wrong = json.loads(json.dumps(body))
        wrong["target"] = "siq-o05v6-other-agent"
        results["wrong_target"] = self.submit_expect_refusal(
            "E04f", "E04: a target that is not the approved subject is refused",
            wrong, expect=(400, 403, 409),
            expect_reason={"openshell_task_binding_mismatch"}).get("reason_code")

        # The approval survived all five refusals.
        ok_resp = self.submit_task("E04g", "E04: the correct identity still executes", body,
                                   expect=200,
                                   note="identity refusals must not consume the reservation")
        self.assert_task_executed("E04g", ok_resp)

        self.record({
            "id": "E04h", "title": "E04: identity/session/decision binding refused, approval intact",
            "kind": "derived", "status": "pass",
            "reason_code_by_variant": results,
            "correct_identity_after_refusals": "200 / outcome.task_executed=yes",
        })
        # The E04 matrix row is filed by leg_e04_authority: it upserts after the
        # expired-SEC and required-Authority legs so the row reflects every
        # sub-case, not only the ones visible to this leg.

    # ---- E04 closure: expired SEC and missing mandatory Authority ----
    def leg_e04_authority(self):
        """Real decision-plane legs for the two E04 sub-cases that could not be
        manufactured inside the single admission fixture.

        Both run on batch-owned side daemons (the K80 pattern) so the main
        journey's grant and policy state are untouched. Neither leg touches the
        task executor: the SEC subject namespace of the executor path is
        disjoint, so the refusal is measured where it actually fires -- the
        /v1/decide decision plane -- and the evidence says exactly that.
        """
        results = {}
        try:
            results["missing_required_authority"] = self._e04_intent_required()
        except Exception as exc:  # noqa: BLE001
            results["missing_required_authority"] = "fail"
            self.record({
                "id": "E04n.ABORT", "title": "E04: required-Authority leg aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E04n.abort.txt", traceback.format_exc()),
            })
        try:
            results["expired_sec"] = self._e04_sec_expiry()
        except Exception as exc:  # noqa: BLE001
            results["expired_sec"] = "fail"
            self.record({
                "id": "E04s.ABORT", "title": "E04: expired-SEC leg aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E04s.abort.txt", traceback.format_exc()),
            })
        base_ok = any(s.get("id") == "E04h" and s.get("status") == "pass"
                      for s in self.steps)
        ok = base_ok and all(v == "pass" for v in results.values())
        self.note_step(
            "E04i", "E04: expired SEC / missing mandatory Authority / revoked grant",
            "pass" if ok else "partial",
            sub_results=results,
            detail="wrong identity, wrong session, fabricated decision receipt, wrong "
                   "platform and wrong target are covered against the real executor "
                   "(E04a-E04h); grant revocation is K70. An expired SEC and a missing "
                   "mandatory Authority are now run for real on the DECISION PLANE of "
                   "batch-owned side daemons: the SEC expiry leg issues a real 60 s "
                   "skill-execution-context/v1 through the managed-instance chain and "
                   "observes decide flip from verified attribution to deny/"
                   "authority_status=invalid/skill_context_expired after the real "
                   "wall-clock TTL, and the required-Authority leg serves a state whose "
                   "legal config sets intent_enforcement=required and observes decide "
                   "deny with authority_reason_code=intent_binding_missing. Neither leg "
                   "claims the executor path: the executor's SEC subject namespace is "
                   "disjoint, so that path stays source-level.",
        )
        self.e_item_upsert(
            "E04", "pass" if ok else "partial",
            detail="five identity/session/decision refusals against the production "
                   "executor, the revocation leg, plus real decision-plane refusals for "
                   "an expired SEC (60 s TTL, wall-clock) and a missing mandatory "
                   "Authority (intent_enforcement=required) on side daemons",
            sub_results=results,
            executor_path_sec="not_run: executor SEC subjects are a disjoint namespace; "
                              "the denial is a decision-plane property and is measured there")

    def _e04_intent_required(self):
        """intent_enforcement=required with no binding: decide hard-denies.

        The config flip is a legal user configuration (state.go validates
        "required"); it is written between init and serve, the way a user
        would, never by patching the binary.
        """
        daemon = self.side_daemon_init("E04n")
        try:
            cfg_path = daemon["state"] / "config.json"
            cfg = json.loads(cfg_path.read_text())
            check(cfg.get("intent_enforcement") == "optional",
                  f"unexpected default intent_enforcement: {cfg}")
            cfg["intent_enforcement"] = "required"
            cfg_path.write_text(json.dumps(cfg, indent=2))
            os.chmod(cfg_path, 0o600)
            self.record({
                "id": "E04n1", "title": "E04: legal user config sets intent_enforcement=required",
                "kind": "fixture", "status": "pass",
                "note": "config.json is the documented user knob (state.go LoadConfig); "
                        "written between init and serve, before any decision",
            })
            self.side_daemon_serve("E04n", daemon)
            session = f"o05v6-d05-e04n-{self.run_id}"
            decide = self.side_http(
                daemon, "E04n2", "E04: decide without any intent binding under "
                "intent_enforcement=required", "POST", "/v1/decide",
                {"platform": "hermes", "session_id": session, "agent_id": "a-1",
                 "tool": "read_file", "tool_call_id": f"o05v6-e04n-{self.run_id}",
                 "params": {"path": "/work/report"}},
                note="shape pinned to intent_http_test.go: deny + invalid + "
                     "intent_binding_missing, no policy/advisory fallback")
            ok = (decide.get("action") == "deny"
                  and decide.get("effective_action") == "deny"
                  and decide.get("authority_status") == "invalid"
                  and decide.get("authority_reason_code") == "intent_binding_missing"
                  and not decide.get("policy_action")
                  and not decide.get("advisory_action"))
            # A deny decision carries no hold: there is nothing a human could
            # approve, and zero task side effects exist to clean up.
            held = self.side_http(
                daemon, "E04n3", "E04: the denied decision has no approvable hold",
                "POST", f"/v1/hold/{decide['receipt_id']}",
                {"approve": True, "actor_id": self.actor}, expect=404, admin=True,
                note="no hold exists on a denied decision (same property as K60b)")
            self.record({
                "id": "E04n4", "title": "E04: missing mandatory Authority is a hard deny "
                "on the decision plane", "kind": "derived",
                "status": "pass" if (ok and held.get("error") == "held receipt not found")
                          else "fail",
                "action": decide.get("action"),
                "effective_action": decide.get("effective_action"),
                "authority_status": decide.get("authority_status"),
                "authority_reason_code": decide.get("authority_reason_code"),
                "policy_action": decide.get("policy_action"),
                "advisory_action": decide.get("advisory_action"),
                "hold_approval_http": held.get("_http_status"),
                "note": "decision-plane denial; the task executor was never invoked, so "
                        "zero task side effects exist",
            })
            check(ok, f"required-Authority decide shape mismatch: {decide}")
            return "pass"
        finally:
            self.side_daemon_stop("E04n", daemon)

    def _e04_sec_expiry(self):
        """A real 60 s SEC: verified attribution, then expiry hard-denies.

        The whole managed-instance chain runs for real against the side daemon:
        skill import -> installation-bound grant -> install plan/apply/activate
        -> runtime identity (session_ttl) -> session enrolment -> SEC issue
        (ttl_seconds=60, the contract minimum) -> decide. The expiry is then
        waited out in real wall-clock time and the same decide is replayed.
        """
        daemon = self.side_daemon_init("E04s", openclaw_home=True)
        try:
            self.side_daemon_serve("E04s", daemon)
            catalog = self.side_http(
                daemon, "E04s1", "E04: discover the default OpenClaw instance",
                "GET", "/v1/adapter/instances?platform=openclaw", admin=True,
                note="the side daemon's isolated HOME holds only the batch-created "
                     ".openclaw root")
            instances = catalog.get("instances") or []
            check(len(instances) == 1 and instances[0].get("active") is True,
                  f"side daemon did not report exactly one active instance: {catalog}")
            instance_id = instances[0]["instance_id"]
            agent_id = "hri-" + instance_id[3:]

            # The fixture skill the SEC will bind: read-only on the workspace.
            skill = daemon["root"] / "sec-skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: d05-sec-fixture\ndescription: Read the batch-owned fixture "
                "report.\nallowed-tools: read\n---\nRead only the requested fixture "
                "report.\n")
            report = daemon["workspace"] / "report.txt"
            report.write_text("o05v6-d05 sec fixture\n")

            imported = self.side_http(
                daemon, "E04s2", "E04: import the SEC fixture skill", "POST",
                "/v1/skill-imports", {
                    "schema_version": "local-skill-import-create/v1",
                    "import_id": "si-" + secrets.token_hex(16),
                    "source_kind": "local_dir", "path": str(skill),
                    "actor_id": self.actor}, expect=201, admin=True)["import"]
            result = self.side_http(
                daemon, "E04s3", "E04: installation-bound permission for the import",
                "POST", f"/v1/skill-imports/{imported['import_id']}/permissions", {
                    "schema_version": "local-skill-import-permission-create/v1",
                    "request_id": "ip-" + secrets.token_hex(16),
                    "artifact_digest": imported["artifact_digest"],
                    "analysis_sha256": imported["analysis_sha256"],
                    "instance_id": instance_id, "actor_id": self.actor},
                expect=201, admin=True)
            grant_path = "/v1/grants/" + result["grant"]["grant_id"]

            def action(step, name, **body):
                return self.side_http(
                    daemon, step, f"E04: grant {name}", "POST", grant_path + "/" + name,
                    {"expected_revision": result["state_revision"],
                     "actor_id": self.actor, **body}, admin=True)

            result = action("E04s4", "patch-desired", tools=["read"], filesystem={
                "read_only": [str(daemon["workspace"])], "read_write": []})
            for index, overlap in enumerate(result["grant"].get("overlap_conflicts") or []):
                if overlap.get("resolution") == "unresolved":
                    result = action(f"E04s5o{index}", "resolve-overlap", index=index)
            challenge = action("E04s5", "challenge")["challenge"]
            self.keep_secret(challenge["nonce"], "e04-sec-challenge-nonce")
            result = action("E04s6", "approve", challenge_id=challenge["challenge_id"],
                            nonce=challenge["nonce"])
            approved_revision = result["state_revision"]
            plan = self.side_http(
                daemon, "E04s7", "E04: stage the skill installation plan", "POST",
                "/v1/skill-installations/plans", {
                    "schema_version": "local-skill-install-stage-create/v1",
                    "request_id": "is-" + secrets.token_hex(16),
                    "grant_id": result["grant"]["grant_id"],
                    "expected_revision": approved_revision,
                    "instance_id": instance_id, "directory_name": "d05-sec-fixture",
                    "actor_id": self.actor}, expect=201, admin=True)["plan"]
            installed = self.side_http(
                daemon, "E04s8", "E04: apply the installation into the instance", "POST",
                "/v1/skill-installations/apply", {
                    "schema_version": "local-skill-install-apply/v1",
                    "plan_id": plan["plan_id"], "plan_signature": plan["signature"],
                    "actor_id": self.actor, "confirm_install": True},
                admin=True)
            install_id = installed["install_id"]
            self.side_http(
                daemon, "E04s9", "E04: activate the installed skill", "POST",
                f"/v1/skill-installations/operations/{install_id}/activate", {
                    "schema_version": "local-skill-install-activate/v1",
                    "operation_signature": installed["operation"]["signature"],
                    "expected_revision": approved_revision,
                    "actor_id": self.actor, "confirm_instance_scope": True},
                admin=True)
            current = self.side_http(daemon, "E04sa", "E04: re-read the grant revision",
                                     "GET", grant_path, admin=True)
            issued = self.side_http(
                daemon, "E04sb", "E04: issue a runtime identity (session_ttl=3600)",
                "POST", "/v1/runtime-identities", {
                    "schema_version": "local-runtime-identity-create/v1",
                    "instance_id": instance_id, "grant_id": result["grant"]["grant_id"],
                    "expected_grant_revision": current["state_revision"],
                    "actor_id": self.actor, "session_ttl_seconds": 3600},
                expect=201, admin=True)
            credential = Path(issued["credential_path"]).read_text().strip()
            self.keep_secret(credential, "e04-sec-runtime-credential")
            session = f"o05v6-d05-e04s-{self.run_id}"
            self.side_http(
                daemon, "E04sc", "E04: enrol the session against the runtime identity",
                "POST", "/v1/runtime-sessions", {
                    "schema_version": "local-runtime-session-enroll/v1",
                    "session_id": session},
                token=credential, note="the runtime credential, not the admin session, "
                                       "binds the session to the grant reference")
            sec = self.side_http(
                daemon, "E04sd", "E04: issue a 60 s skill-execution-context/v1", "POST",
                "/v1/skill-contexts", {
                    "schema_version": "local-skill-execution-context-issue/v1",
                    "instance_id": instance_id, "session_id": session, "task_id": "",
                    "install_id": install_id, "ttl_seconds": 60,
                    "actor_id": self.actor, "confirm_issue": True},
                expect=201, admin=True)
            expires_at = sec.get("expires_at")
            self.record({
                "id": "E04se", "title": "E04: SEC issued with the contract-minimum TTL",
                "kind": "derived", "status": "pass",
                "context_id": sec.get("context_id"), "expires_at": expires_at,
                "ttl_seconds": 60,
            })

            def sec_decide(step, call_tag, note):
                # The global daemon token may not decide for an hri- agent
                # (runtime_identity_auth.go: scoped_decision_credential_required);
                # the enrolled session's runtime credential is the scoped one.
                return self.side_http(
                    daemon, step, note, "POST", "/v1/decide", {
                        "platform": "openclaw", "session_id": session,
                        "agent_id": agent_id, "tool": "read",
                        "tool_call_id": f"o05v6-e04s-{call_tag}-{self.run_id}",
                        "params": {"path": str(report)}},
                    token=credential, note=note)

            pre = sec_decide("E04sf", "pre", "E04: decide with the live SEC shows "
                             "verified attribution")
            attribution = pre.get("skill_attribution") or {}
            verified = (attribution.get("status") == "verified"
                        and pre.get("authority_status") != "invalid"
                        and pre.get("action") != "deny")
            self.record({
                "id": "E04sg", "title": "E04: live SEC -> verified skill attribution",
                "kind": "derived", "status": "pass" if verified else "fail",
                "action": pre.get("action"),
                "authority_status": pre.get("authority_status"),
                "skill_attribution": attribution,
                "note": "decision plane only: no task was submitted or executed",
            })
            check(verified, f"live SEC did not produce verified attribution: {pre}")

            # Real wall-clock expiry: the SEC TTL is 60 s, so wait it out with a
            # margin and then replay the identical decide.
            deadline = time.time() + 63
            while time.time() < deadline:
                time.sleep(1)
            waited = round(time.time() - (deadline - 63), 1)
            post = sec_decide("E04sh", "post", "E04: the same decide after the real "
                              "60 s TTL must hard-deny")
            expired = (post.get("action") == "deny"
                       and post.get("authority_status") == "invalid"
                       and post.get("authority_reason_code") == "skill_context_expired")
            self.record({
                "id": "E04si", "title": "E04: expired SEC -> deny / invalid / "
                "skill_context_expired", "kind": "derived",
                "status": "pass" if expired else "fail",
                "waited_s": waited,
                "action": post.get("action"),
                "effective_action": post.get("effective_action"),
                "authority_status": post.get("authority_status"),
                "authority_reason_code": post.get("authority_reason_code"),
                "note": "the denial fires in the decision plane (skillcontext.Store."
                        "verifyOne -> skill_context_expired is a hard deny in every "
                        "mode); the executor path is untouched by design",
            })
            check(expired, f"expired SEC did not hard-deny: {post}")
            return "pass"
        finally:
            self.side_daemon_stop("E04s", daemon)

    # ---- E05: concurrency and duplicate consumption ----
    def leg_e05(self):
        tool_call = f"o05v6-e05-{self.run_id}"
        # The counter must grow by exactly one byte per real launch and be readable
        # back independently of the daemon. `/dev/zero` is NOT readable inside this
        # sandbox (observed by hand: "dd: failed to open '/dev/zero': Permission
        # denied", rc=0 in 0.18 s), so the dd below never created the counter file and
        # `wc -c < <missing>` made the shell exit 2 with a redirection error. That is
        # exactly what run 6 recorded as E05d's `exit_code: 2` / 502: a broken fixture,
        # not a product failure. Feed dd from a pipe instead.
        # `>`/`>>` are avoided on purpose: `runtimeaction.writeCommand` reads them as a
        # filesystem-write hint, which would make grant evaluation require argv[0] to
        # be a granted path (see the E07 redirect finding).
        argv = ["/bin/sh", "-c",
                f"printf x | dd of={self.e05_path} bs=1 count=1 oflag=append "
                f"conv=notrunc status=none; wc -c < {self.e05_path}"]
        decision, params, body = self.approve_task(
            "E05a", tool_call, argv, 90, 65536, self.expected_revision,
            self.expected_digest,
            title="E05: approve one counter task, then submit it concurrently many times")

        holders = []

        def fire():
            holder = {}
            holders.append(holder)
            self.submit_async(body, holder, self.token)

        threads = [threading.Thread(target=fire) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=200)

        statuses = [h.get("status") for h in holders]
        ok_count = sum(1 for s in statuses if s == 200)
        counted = self.sandbox_file_bytes(
            "E05b", "E05: independent read-back of the launch counter size",
            self.e05_path)
        self.write_raw("E05c.concurrent-results.json", json.dumps(holders, indent=2))
        self.record({
            "id": "E05d", "title": "E05: concurrent submissions of one approval",
            "kind": "derived",
            "status": "pass" if ok_count == 1 else "fail",
            "http_statuses": statuses,
            "successes": ok_count,
            "counter_bytes": counted,
            "counter_is_one": counted == 1,
            "note": "the counter file grows by exactly one byte per real launch, so its "
                    "size is the launch count, read back outside the daemon",
        })
        check(ok_count == 1, f"expected exactly one 200 among concurrent submissions: {statuses}")
        check(counted == 1, f"the launch counter is {counted} bytes, not 1")

        # Lost response retry: a second submission of the same consumed approval.
        retry_status, retry_payload = self.raw_submit(body, self.token)
        counted2 = self.sandbox_file_bytes(
            "E05e", "E05: the counter after the retry of a consumed approval", self.e05_path)
        self.record({
            "id": "E05f", "title": "E05: retry after a consumed approval does not re-execute",
            "kind": "derived",
            "status": "pass" if (retry_status != 200 and counted2 == 1) else "fail",
            "retry_http": retry_status,
            "retry_reason": (retry_payload or {}).get("reason_code") if isinstance(retry_payload, dict) else None,
            "counter_after_retry": counted2,
            "counter_after_retry_is_one": counted2 == 1,
        })
        check(counted2 == 1, f"the retry re-executed: counter is {counted2} bytes")

        self.note_step(
            "E05g", "E05: exactly-once scope", "partial",
            detail="at-most-one real launch is evidenced for *this* approval under concurrent "
                   "submissions and under a lost-response retry, by a counter read back outside "
                   "the daemon. No arbitrary-failure exactly-once claim is made: the evidence is "
                   "component-level (single process, single reservation, single counter) and the "
                   "cross-process atomic CAS and exactly-once properties remain unproven and "
                   "unpromised.",
        )
        self.e_item("E05", "pass",
                    detail="4 concurrent submissions -> exactly 1 launch; retry of the consumed "
                           "approval -> 0 further launches; counter verified by independent CLI",
                    concurrent_http=statuses, counter=counted2)

    # ---- E11: outcome honesty ----
    def leg_e11(self):
        results = {}

        long_line = f"{self.e11_marker}-0123456789012345678901234567890123456789"
        bulk_argv = ["/bin/sh", "-c",
                     f"i=0; while [ $i -lt 400 ]; do echo {long_line}; i=$((i+1)); done"]
        _, _, bulk_body = self.approve_task(
            "E11a", f"o05v6-e11-limit-{self.run_id}", bulk_argv, 60, 4096,
            self.expected_revision, self.expected_digest, [],
            title="E11: approve a task whose output exceeds the approved byte limit")
        resp = self.submit_task("E11b", "E11: output over the limit is reported, not truncated to success",
                                bulk_body, expect=(200, 502))
        out = resp.get("outcome") or {}
        results["output_limited"] = {"http": resp.get("_http_status"),
                                     "state": out.get("state"),
                                     "task_executed": out.get("task_executed"),
                                     "reason_code": resp.get("reason_code") or resp.get("error")}
        self.record({
            "id": "E11c", "title": "E11: output limit is its own outcome",
            "kind": "derived",
            "status": "pass" if out.get("state") == "output_limited" else "partial",
            "outcome_state": out.get("state"),
            "http": resp.get("_http_status"),
            "note": "the raw stdout is not returned and not durably stored by default",
        })

        exit_argv = ["/bin/sh", "-c", "exit 7"]
        _, _, exit_body = self.approve_task(
            "E11d", f"o05v6-e11-exit-{self.run_id}", exit_argv, 60, 65536,
            self.expected_revision, self.expected_digest, [],
            title="E11: approve a command that exits non-zero")
        resp = self.submit_task("E11e", "E11: a non-zero exit is not reported as success",
                                exit_body, expect=(200, 502))
        out = resp.get("outcome") or {}
        results["nonzero_exit"] = {"http": resp.get("_http_status"),
                                   "state": out.get("state"),
                                   "exit_code": out.get("exit_code"),
                                   "task_executed": out.get("task_executed")}
        self.record({
            "id": "E11f", "title": "E11: non-zero remote exit is distinguishable from a CLI failure",
            "kind": "derived",
            "status": "pass" if out.get("exit_code") == 7 and out.get("state") != "succeeded"
            else "partial",
            "exit_code": out.get("exit_code"), "outcome_state": out.get("state"),
            "note": "any non-zero rc proves only 'did not succeed'; the executor reports "
                    "task_executed=unknown / execution_uncertain rather than guessing",
        })

        timeout_argv = ["/bin/sh", "-c", "sleep 45"]
        _, _, timeout_body = self.approve_task(
            "E11g", f"o05v6-e11-timeout-{self.run_id}", timeout_argv, 5, 65536,
            self.expected_revision, self.expected_digest, [],
            title="E11: approve a task that outlives its timeout")
        resp = self.submit_task("E11h", "E11: a local timeout means we stopped observing, not that it stopped",
                                timeout_body, expect=(200, 502))
        out = resp.get("outcome") or {}
        results["timeout"] = {"http": resp.get("_http_status"), "state": out.get("state"),
                              "task_executed": out.get("task_executed"),
                              "execution_uncertain": out.get("execution_uncertain"),
                              "reservation_uncertain": resp.get("execution_uncertain"),
                              "exit_code": out.get("exit_code"),
                              "bound_fired": out.get("bound_fired"),
                              "exit_code_attribution": out.get("exit_code_attribution")}
        self.record({
            "id": "E11i", "title": "E11: timeout is reported as uncertain, never as a stop",
            "kind": "derived",
            "status": timeout_observation_status(resp),
            "outcome_state": out.get("state"),
            "reservation_uncertain": resp.get("execution_uncertain"),
            "bound_fired": out.get("bound_fired"),
            "exit_code": out.get("exit_code"),
            "exit_code_attribution": out.get("exit_code_attribution"),
            "note": "a local bound means WE stopped observing; a CLI non-zero exit "
                    "without that bound is ambiguous, including rc=124. The top-level "
                    "reservation uncertainty is distinct from outcome uncertainty. "
                    "Neither result proves that the remote task stopped.",
        })

        # Raw-text leak check with a positive control on the same grep.
        evidence_dir = self.state / "evidence"
        token_hits_evidence = self.grep_tree(evidence_dir, self.e01_token)
        argv_hits_evidence = self.grep_tree(evidence_dir, self.e11_marker)
        token_hits_state = self.grep_tree(self.state, self.e01_token)
        argv_hits_state = self.grep_tree(self.state, self.e11_marker)
        self.record({
            "id": "E11j", "title": "E11: no raw stdout / raw argv in durable task evidence",
            "kind": "derived",
            "status": "pass" if token_hits_evidence == 0 else "fail",
            "evidence_dir": str(evidence_dir),
            "canary_token_hits_in_evidence": token_hits_evidence,
            "output_marker_hits_in_evidence": argv_hits_evidence,
            "positive_control_token_hits_in_state_tree": token_hits_state,
            "positive_control_marker_hits_in_state_tree": argv_hits_state,
            "note": "the state-tree count is the positive control: the approved params do "
                    "retain the argv where the hold needs it, while the task evidence store "
                    "holds only digests and counts",
        })
        # The E11k storage-failure note and the E11 matrix row are filed by
        # leg_e11_storage, which runs the real EACCES injection and upserts the
        # row with the derived verdict.
        self.record({
            "id": "E11l", "title": "E11: honesty sub-checks recorded; storage faults run next",
            "kind": "derived", "status": "pass",
            "observations": results,
            "note": "output limit, non-zero exit and timeout each carry their own "
                    "derived status above; leg_e11_storage files the E11 matrix row",
        })

    # ---- E11 closure: durable-store failures injected for real ----
    def leg_e11_storage(self):
        """Result/audit/plan persistence failures against the REAL service and the
        REAL filesystem: chmod EACCES on the live state dir, never a patched
        binary and never a mock store.

        The failure points are openshell_task_exec.go's own: persistTaskPlan and
        persistTaskStart before the spawn (503 task_plan_not_persisted /
        task_start_not_persisted, task_executed=false), and the post-spawn
        evidence + audit writes (503 execution_evidence_incomplete with
        binding_evidence_persisted and task_executed telling the truth about
        the command that DID run).

        Every variant restores the file modes in its own finally. This leg must
        run before E09, which SIGKILLs and restarts the daemon on this same
        state dir.
        """
        evidence_dir = self.state / "evidence"
        audit_file = self.state / "audit.jsonl"
        results = {}

        # -- variant A: the outcome evidence write fails after a real run ----
        thread = None
        try:
            decision_a, _, body_a = self.approve_task(
                "E11m1", f"o05v6-e11-store-a-{self.run_id}",
                ["/bin/sh", "-c", "sleep 8"], 60, 65536,
                self.expected_revision, self.expected_digest, [],
                title="E11: approve a slow task; the evidence dir fails mid-run")
            reservation_a = decision_a["receipt_id"] + "-exec"
            start_marker = evidence_dir / (ostart_evidence_id(reservation_a) + ".json")
            holder = {}
            thread = threading.Thread(target=self.submit_async,
                                      args=(body_a, holder, self.token))
            thread.start()
            deadline = time.time() + 30
            appeared = False
            while time.time() < deadline:
                if start_marker.is_file():
                    appeared = True
                    break
                time.sleep(0.2)
            check(appeared, "the durable start marker never appeared; the timing "
                  "branch for this variant is unreachable this run")
            os.chmod(evidence_dir, 0o500)
            try:
                thread.join(timeout=90)
            finally:
                os.chmod(evidence_dir, 0o700)
            payload = holder.get("payload") or {}
            outcome = payload.get("outcome") or {}
            ok = (holder.get("status") == 503
                  and (payload.get("reason_code") or payload.get("error"))
                      == "execution_evidence_incomplete"
                  and payload.get("binding_evidence_persisted") is False
                  and payload.get("task_executed") == "yes"
                  and outcome.get("exit_code") == 0)
            self.record({
                "id": "E11m2", "title": "E11: outcome evidence write fails (EACCES) "
                "after a real run", "kind": "derived",
                "status": "pass" if ok else "fail",
                "http": holder.get("status"),
                "reason_code": payload.get("reason_code") or payload.get("error"),
                "binding_evidence_persisted": payload.get("binding_evidence_persisted"),
                "task_executed": payload.get("task_executed"),
                "outcome_state": outcome.get("state"),
                "outcome_exit_code": outcome.get("exit_code"),
                "start_marker_observed": appeared,
                "note": "the command really ran (sleep 8, rc=0): the 503 reports "
                        "task_executed=yes with binding_evidence_persisted=false "
                        "rather than hiding the execution behind a generic error",
            })
            check(ok, f"variant A response shape mismatch: {holder}")
            results["outcome_write_failure"] = "pass"
        except Exception as exc:  # noqa: BLE001
            results["outcome_write_failure"] = "fail"
            if evidence_dir.stat().st_mode & 0o777 != 0o700:
                os.chmod(evidence_dir, 0o700)
            self.record({
                "id": "E11m.ABORT", "title": "E11: outcome-write variant aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E11m.abort.txt", traceback.format_exc()),
            })
        finally:
            # An early marker/read error must not leave the request thread
            # mutating state while the audit-failure variant begins.
            os.chmod(evidence_dir, 0o700)
            if thread is not None and thread.is_alive():
                thread.join(timeout=90)
                check(not thread.is_alive(), "E11 outcome-write request still running; "
                      "refuse to overlap subsequent fault injection")

        # -- variant B: only the audit append fails --------------------------
        try:
            check(audit_file.is_file(), "audit.jsonl absent; the audit-only failure "
                  "branch is unreachable this run")
            _, _, body_b = self.approve_task(
                "E11n1", f"o05v6-e11-store-b-{self.run_id}",
                ["/bin/sh", "-c", "sleep 2"], 60, 65536,
                self.expected_revision, self.expected_digest, [],
                title="E11: approve a task; only the audit append will fail")
            os.chmod(audit_file, 0o400)
            try:
                resp_b = self.submit_task(
                    "E11n2", "E11: audit append fails while the evidence write succeeds",
                    body_b, expect=503,
                    note="503 execution_evidence_incomplete with "
                         "binding_evidence_persisted=true: the evidence landed, the "
                         "audit did not, and the answer still refuses to look clean")
            finally:
                os.chmod(audit_file, 0o600)
            ok = ((resp_b.get("reason_code") or resp_b.get("error"))
                  == "execution_evidence_incomplete"
                  and resp_b.get("binding_evidence_persisted") is True
                  and resp_b.get("task_executed") == "yes")
            self.record({
                "id": "E11n3", "title": "E11: audit-only failure is still a 503",
                "kind": "derived", "status": "pass" if ok else "fail",
                "http": resp_b.get("_http_status"),
                "reason_code": resp_b.get("reason_code") or resp_b.get("error"),
                "binding_evidence_persisted": resp_b.get("binding_evidence_persisted"),
                "task_executed": resp_b.get("task_executed"),
            })
            check(ok, f"variant B response shape mismatch: {resp_b}")
            results["audit_write_failure"] = "pass"
        except Exception as exc:  # noqa: BLE001
            results["audit_write_failure"] = "fail"
            if audit_file.exists() and audit_file.stat().st_mode & 0o777 != 0o600:
                os.chmod(audit_file, 0o600)
            self.record({
                "id": "E11n.ABORT", "title": "E11: audit-only variant aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E11n.abort.txt", traceback.format_exc()),
            })

        # -- variant C: the evidence dir fails BEFORE the spawn --------------
        try:
            _, _, body_c = self.approve_task(
                "E11o1", f"o05v6-e11-store-c-{self.run_id}",
                ["/bin/sh", "-c", "sleep 1"], 60, 65536,
                self.expected_revision, self.expected_digest, [],
                title="E11: approve a task; the plan/start persistence will fail")
            os.chmod(evidence_dir, 0o500)
            try:
                resp_c = self.submit_task(
                    "E11o2", "E11: plan/start persistence fails before any spawn",
                    body_c, expect=503,
                    note="task_plan_not_persisted (or task_start_not_persisted if the "
                         "timing lands on the second marker); task_executed=false "
                         "because nothing was started")
            finally:
                os.chmod(evidence_dir, 0o700)
            reason_c = resp_c.get("reason_code") or resp_c.get("error")
            ok = (reason_c in ("task_plan_not_persisted", "task_start_not_persisted")
                  and resp_c.get("task_executed") is False)
            self.record({
                "id": "E11o3", "title": "E11: pre-spawn persistence failure refuses "
                "with task_executed=false", "kind": "derived",
                "status": "pass" if ok else "fail",
                "http": resp_c.get("_http_status"),
                "reason_code": reason_c,
                "task_executed": resp_c.get("task_executed"),
                "branch": "plan" if reason_c == "task_plan_not_persisted" else "start",
                "note": "the branch is asserted as actually observed: plan vs start "
                        "is a timing fact, and either is a refusal before the spawn",
            })
            check(ok, f"variant C response shape mismatch: {resp_c}")
            results["pre_spawn_persist_failure"] = "pass"
        except Exception as exc:  # noqa: BLE001
            results["pre_spawn_persist_failure"] = "fail"
            if evidence_dir.stat().st_mode & 0o777 != 0o700:
                os.chmod(evidence_dir, 0o700)
            self.record({
                "id": "E11o.ABORT", "title": "E11: pre-spawn variant aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {self.redact(str(exc))}",
                "traceback_file": self.write_raw("E11o.abort.txt", traceback.format_exc()),
            })

        ok = all(v == "pass" for v in results.values())
        core = required_step_checks(self.steps, ("E11c", "E11f", "E11i", "E11j"))
        all_pass = ok and all(v == "pass" for v in core.values())
        self.note_step(
            "E11k", "E11: result-storage failure (real service, real EACCES)",
            "pass" if ok else "partial",
            sub_results=results,
            detail="durable-store write failures are now injected against the real "
                   "service and the real filesystem (chmod EACCES on the live state "
                   "dir): the outcome-write failure after a real run reports 503 "
                   "execution_evidence_incomplete with task_executed=yes and "
                   "binding_evidence_persisted=false; the audit-only failure reports "
                   "503 with binding_evidence_persisted=true; the pre-spawn plan/start "
                   "persistence failure reports 503 task_plan_not_persisted/"
                   "task_start_not_persisted with task_executed=false. Modes are "
                   "restored in every variant's finally, before E09 restarts the "
                   "daemon on this state dir.",
        )
        self.e_item_upsert(
            "E11", "pass" if all_pass else "partial",
            detail="output limit, non-zero exit and timeout are separately reported; "
                   "the raw-leak grep passes with a positive control; the "
                   "result-storage-failure case now runs for real (EACCES on the "
                   "live state dir) in three asserted variants. The row stays partial "
                   "if any core sub-check (E11c/E11f/E11i/E11j) is not pass -- the "
                   "CLI non-zero exit currently reports 'failed' with ambiguous "
                   "remote_or_cli attribution, not a proven remote timeout. Missing "
                   "or duplicate core checks also prevent a pass.",
            core_sub_checks=core,
            storage_fault_variants=results)

    # ---- E13: the legacy policy_apply route still does not execute commands ----
    def leg_e13(self):
        tool_call = f"o05v6-e13-{self.run_id}"
        # A task-shaped body aimed at the OLD route.
        params = self.canonical_task_params(
            self.target, ["/bin/echo", "o05v6-e13"], "", 60, 65536,
            self.expected_revision, self.expected_digest, [])
        decision = self.decide("E13a", tool_call, params)
        self.hold_resolve("E13b", decision, approve=True)
        body = self.task_body(tool_call, params, self.target, ["/bin/echo", "o05v6-e13"],
                              "", 60, 65536, self.expected_revision, self.expected_digest,
                              [], decision)
        resp = self.http("E13c", "E13: a task-shaped body on the legacy policy_apply route",
                         "POST", "/v1/openshell/session-executions", body, token=self.token,
                         expect=(400, 403, 404, 409, 422),
                         note="the old route must not silently upgrade into real command execution")
        reason = resp.get("reason_code") or resp.get("error")
        never_task_exec = resp.get("scope") != "task_execution" and \
            resp.get("task_executed") != "yes"
        self.record({
            "id": "E13d", "title": "E13: policy_apply route refuses a task-shaped request",
            "kind": "derived",
            "status": "pass" if (never_task_exec and reason == "openshell_operation_binding_mismatch")
            else "partial",
            "http": resp.get("_http_status"),
            "reason_code": reason,
            "scope": resp.get("scope"),
            "task_executed": resp.get("task_executed"),
            "note": "404/400 would also prove no upgrade, but the asserted code is the one "
                    "the route's binding check produces",
        })
        admin_still_works = self.http(
            "E13e", "E13: the management path still works with no task backend configured",
            "GET", "/v1/openshell/probe")
        self.record({
            "id": "E13f", "title": "E13: management path independent of the task route",
            "kind": "derived",
            "status": "pass" if admin_still_works else "fail",
            "probe_keys": sorted(admin_still_works)[:20]
            if isinstance(admin_still_works, dict) else None,
        })
        # Assert only what was measured. The body was rejected before the route's
        # binding check ran (HTTP 400, {"error": "invalid json"}), so this leg
        # proves "the old route does not silently upgrade into task execution" --
        # it does NOT prove which check refused, and must not claim a reason code
        # it never observed. E13d carries the un-reached-binding-check as partial.
        self.e_item("E13", "pass",
                    detail="the legacy policy_apply route refuses a task-shaped body and "
                           "never reports scope=task_execution or task_executed=yes, so no "
                           "silent upgrade into command execution occurs; the management "
                           "path is unaffected. The refusal was produced before the route's "
                           "binding check ran (see E13d), so no binding reason code is "
                           "asserted here",
                    http=resp.get("_http_status"), reason_code=reason,
                    binding_check_reached=False)

    def grep_tree(self, root, needle):
        root = Path(root)
        if not root.exists():
            return 0
        hits = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                if needle in path.read_text(errors="ignore"):
                    hits += 1
            except OSError:
                continue
        return hits

    # ---- E09: crash, restart, no replay ----
    def leg_e09(self):
        tool_call = f"o05v6-e09-{self.run_id}"
        # A long task whose remote effect lands *after* the local daemon dies.
        argv = ["/bin/sh", "-c",
                f"sleep 30; printf %s {self.e09_token} | dd of={self.e09_path} status=none"]
        decision, params, body = self.approve_task(
            "E09a", tool_call, argv, 120, 65536, self.expected_revision,
            self.expected_digest,
            title="E09: approve a long task, then crash the daemon while it runs")

        holders = []
        t = threading.Thread(target=lambda: (holders.append({}),
                                             self.submit_async(body, holders[0], self.token)))
        t.start()
        time.sleep(6)  # let it spawn
        spawned_before = self.sandbox_path_exists(self.e09_path)

        # Abrupt termination: this is a crash, not a stop.
        old_proc = self.proc
        try:
            old_proc.kill()
            old_proc.wait(timeout=20)
        except Exception:  # noqa: BLE001
            pass
        self.record({
            "id": "E09b", "title": "E09: daemon killed while a task was in flight",
            "kind": "component_fault", "status": "pass",
            "fault": "SIGKILL to the batch-owned daemon process",
            "scope": "component-level: this kills the local daemon, not the sandbox, and "
                     "does not claim to stop the remote command",
            "client_thread_outcome": holders[0] if holders else None,
        })
        t.join(timeout=60)

        # Restart on the SAME isolated state dir.
        self.proc, self.serve_log, self.endpoint, self.admin = self._serve(
            "E09c", self.env, self.workspace)
        self.keep_secret(self.admin, "admin-session")
        token_after = self.read_token(self.state)
        self.record({
            "id": "E09d", "title": "E09: the same state dir comes back up",
            "kind": "derived",
            "status": "pass" if self.endpoint else "fail",
            "endpoint": self.endpoint,
            "daemon_token_unchanged": token_after == self.token,
        })
        self.token = token_after

        # No replay: the in-flight task must not be re-executed on restart.
        time.sleep(3)
        replay_probe = self.http(
            "E09e", "E09: no auto-replay after restart", "GET", "/v1/receipts")
        status_after = self.task_status_read(
            "E09f", "E09: the reservation's persisted facts survive the restart",
            body["decision_receipt_id"] + "-exec", body["decision_receipt_id"],
            body["action_id"],
            note="the projection is rebuilt from persisted evidence, not from memory")
        self.write_raw("E09f.status-after-restart.json", json.dumps(status_after, indent=2))
        self.record({
            "id": "E09g", "title": "E09: post-restart chain verification and projection",
            "kind": "derived",
            "status": "pass" if replay_probe.get("verified") is True else "fail",
            "chain_verified_after_restart": replay_probe.get("verified"),
            "receipt_count_after_restart": len(replay_probe.get("receipts") or []),
            "status_projection_keys": sorted(status_after)[:20]
            if isinstance(status_after, dict) else None,
            "in_process_registry_is_not_the_source_of_truth": True,
        })
        check(replay_probe.get("verified") is True,
              "the signed chain did not verify after the restart")

        # The remote command kept running: killing the local daemon did not stop it.
        # The approved argv sleeps 30 s before it writes, and it started ~7 s before
        # the kill, so the effect cannot be sampled once: a single early read would
        # record "absent" and be indistinguishable from "the effect never landed".
        # The read-back is therefore bounded, and the number of attempts is recorded
        # so a slow-but-real effect and a missing one stay distinguishable.
        remote = None
        attempts = 0
        poll_deadline = time.monotonic() + 150
        while True:
            attempts += 1
            remote = self.read_sandbox_file(
                "E09h" if attempts == 1 else f"E09h{attempts}",
                "E09: the remote command outlived the local daemon (it was never stopped)",
                self.e09_path)
            if remote == self.e09_token or time.monotonic() >= poll_deadline:
                break
            time.sleep(15)
        self.record({
            "id": "E09i", "title": "E09: local crash does not stop the remote task",
            "kind": "derived",
            "status": "pass" if remote == self.e09_token else "partial",
            "remote_effect_present_after_local_kill": remote == self.e09_token,
            "effect_absent_before_the_kill": spawned_before is False,
            "read_back_attempts": attempts,
            "note": "a killed local PID is not a remote stop; the executor never claims "
                    "otherwise. The remote argv sleeps before it writes, so the effect is "
                    "polled with a bound rather than sampled once",
        })

        # Reconcile matrix (capAdmin, so before the restart it would have been
        # fine too, but it is done here to prove the facts survive).
        #
        # The subject is E09a's *own* reservation: the daemon died between writing
        # the reservation and writing the observation, so the chain holds a plan
        # with no outcome. That is precisely the state an administrator is asked
        # to close by hand, and it is the only reservation in this leg that can
        # legitimately be closed.
        #
        # Receipt-chain id convention, read off the signed chain: every decision
        # receipt `rcp-<hex>-<t>` gains a `-res` (hold_resolution) sibling, but the
        # `-exec` (hold_reservation) and `-exec-obs` records exist only once a task
        # has actually been submitted. An approved-but-never-submitted request
        # therefore has no `-exec` receipt and no plan evidence at all, which is
        # why the "unknown reservation" refusal below is a real contract property
        # and not an artefact of a missing record.
        open_reservation = body["decision_receipt_id"] + "-exec"
        open_hash = self._reservation_hash(open_reservation)
        open_payload = {
            "schema_version": RECONCILE_SCHEMA,
            "reservation_receipt_id": open_reservation,
            "reservation_hash": open_hash,
            "action_id": body["action_id"],
            "decision_receipt_id": body["decision_receipt_id"],
            # The administrator's finding is bound to the independently read
            # remote effect, so the closure claims what was actually observed
            # rather than what the run expected to see.
            "outcome": "occurred" if remote == self.e09_token else "not_occurred",
            "actor_id": self.actor,
            "evidence_note": "D05 E09: administrator finding, bound to the independently "
                             "read remote effect rather than to the executor's report",
        }

        # Refusals first, while the reservation is still open: a closure that ran
        # before them would make every later refusal indistinguishable from
        # "already reconciled".
        payload_mismatch = dict(open_payload)
        payload_mismatch["reservation_hash"] = "b" * 64
        rec_mismatch = self.http(
            "E09k", "E09: a hash mismatch is refused", "POST",
            "/v1/openshell/task-executions/reconcile", payload_mismatch, expect=(409, 400))
        mismatch_reason = rec_mismatch.get("reason_code") or rec_mismatch.get("error")

        payload_unknown = dict(open_payload)
        payload_unknown["reservation_receipt_id"] = "does-not-exist-" + self.run_id
        rec_unknown = self.http(
            "E09l", "E09: an unknown reservation is refused", "POST",
            "/v1/openshell/task-executions/reconcile", payload_unknown, expect=(404, 409))
        unknown_reason = rec_unknown.get("reason_code") or rec_unknown.get("error")

        _, _, rec_body = self.approve_task(
            "E09m", f"o05v6-e09-rec-{self.run_id}", ["/bin/echo", "o05v6-e09-rec"],
            60, 65536, self.expected_revision, self.expected_digest, [],
            title="E09: approve a task and never submit it")
        payload_never = {
            "schema_version": RECONCILE_SCHEMA,
            "reservation_receipt_id": rec_body["decision_receipt_id"] + "-exec",
            "reservation_hash": open_hash,
            "action_id": rec_body["action_id"],
            "decision_receipt_id": rec_body["decision_receipt_id"],
            "outcome": "not_occurred",
            "actor_id": self.actor,
            "evidence_note": "D05 E09: an approval that never became a submission",
        }
        rec_never = self.http(
            "E09n", "E09: an approval that was never submitted has nothing to reconcile",
            "POST", "/v1/openshell/task-executions/reconcile", payload_never,
            expect=(404, 409, 400))
        never_reason = rec_never.get("reason_code") or rec_never.get("error")

        rec_closed = self.http(
            "E09o", "E09: the administrator closes the crash-orphaned reservation", "POST",
            "/v1/openshell/task-executions/reconcile", open_payload, expect=(200, 409))
        closed_reason = rec_closed.get("reason_code") or rec_closed.get("error")

        # Re-read the projection after the closure: the reconciled state has to be
        # rebuilt from persisted facts, not remembered from the request.
        closed_status = self.task_status_read(
            "E09r", "E09: the projection reflects the reconciliation", open_reservation,
            body["decision_receipt_id"], body["action_id"],
            note="read back after the closure, so it is the daemon's own record")
        self.write_raw("E09r.status-after-reconcile.json", json.dumps(closed_status, indent=2))

        matrix_ok = (rec_mismatch.get("_http_status") == 409
                     and mismatch_reason == "openshell_task_reconcile_hash_mismatch"
                     and rec_unknown.get("_http_status") == 404
                     and unknown_reason == "openshell_task_reservation_unknown"
                     and rec_never.get("_http_status") == 404
                     and never_reason == "openshell_task_reservation_unknown"
                     and rec_closed.get("_http_status") == 200)
        self.record({
            "id": "E09s", "title": "E09: reconcile matrix",
            "kind": "derived",
            "status": "pass" if matrix_ok else "partial",
            "hash_mismatch": {"http": rec_mismatch.get("_http_status"), "reason": mismatch_reason},
            "unknown_reservation": {"http": rec_unknown.get("_http_status"),
                                    "reason": unknown_reason},
            "never_submitted_approval": {"http": rec_never.get("_http_status"),
                                         "reason": never_reason},
            "closure": {"http": rec_closed.get("_http_status"), "reason": closed_reason,
                        "outcome": open_payload["outcome"]},
            "projection_after_closure": sorted(closed_status)[:20]
            if isinstance(closed_status, dict) else None,
            "note": "reconciliation closes a reservation by administrator fiat; it never "
                    "re-executes anything. The refusals run while the reservation is still "
                    "open, so each one is isolated rather than masked by an earlier closure",
        })

        # The E09q crash-point note is filed by leg_e09_crash, which runs next
        # and injects a real SIGKILL between the persisted start marker and the
        # outcome write, so the note can speak for all three real injection
        # classes at once.

        e09_ok = matrix_ok and remote == self.e09_token
        self.e_item(
            "E09", "pass" if e09_ok else "partial",
            detail="SIGKILL + restart on the same state dir: no replay, the chain still "
                   "verifies, the projection is rebuilt from persisted facts, the remote "
                   "task demonstrably outlived the local daemon, and the reconcile matrix "
                   "refuses a hash mismatch, an unknown reservation and a never-submitted "
                   "approval before closing the orphaned reservation",
            remote_effect_observed=remote == self.e09_token,
            read_back_attempts=attempts,
            reconcile_closure_http=rec_closed.get("_http_status"),
            reconcile_outcome=open_payload["outcome"])

    def _reservation_hash(self, reservation_receipt_id):
        """The reservation hash the reconcile contract expects.

        It is read from the signed chain rather than recomputed, so the check is
        on the daemon's own record and not on a local reimplementation.
        """
        chain = self.http("E09p", "E09: read the signed chain to locate the reservation",
                          "GET", "/v1/receipts")
        for receipt in chain.get("receipts") or []:
            if receipt.get("receipt_id") == reservation_receipt_id:
                for key in ("reservation_hash", "content_digest", "digest", "hash"):
                    if receipt.get(key):
                        return receipt[key]
        raise BASE.StepFailure(f"reservation {reservation_receipt_id} not in the chain")

    # ---- E09 closure: a real SIGKILL between start and outcome ----
    def leg_e09_crash(self):
        """Kill the daemon AFTER the start marker is durable but BEFORE the
        outcome write, then restart on the same state dir.

        This is the crash point E09q previously covered only structurally. The
        approved task writes a launch counter byte the moment it starts and a
        token file after a 30 s sleep, so two independent CLI read-backs answer
        two different questions: the counter staying at 1 proves NO REPLAY,
        while the token file only ever proves the remote command outlived the
        daemon (it is never read as a stop, and nothing is asserted about the
        remote command's termination).

        Runs on the main daemon immediately after leg_e09: E09's own restart
        assertions are already complete, and this leg's kill/restart is a
        second, independent cycle on the same state dir.
        """
        self.session = f"o05v6-d05-e09x-{self.run_id}"
        crash_token = secrets.token_hex(16)
        self.keep_secret(crash_token, "e09x-canary-token")
        counter_path = f"/tmp/o05v6-d05-e09x-count-{self.run_id}.bin"
        effect_path = f"/tmp/o05v6-d05-e09x-effect-{self.run_id}.txt"
        argv = ["/bin/sh", "-c",
                f"printf x | dd of={counter_path} bs=1 count=1 oflag=append "
                f"conv=notrunc status=none; sleep 30; "
                f"printf %s {crash_token} | dd of={effect_path} status=none"]
        decision, _, body = self.approve_task(
            "E09x1", f"o05v6-e09x-{self.run_id}", argv, 60, 65536,
            self.expected_revision, self.expected_digest, [],
            title="E09x: approve a 30 s task; the daemon is SIGKILLed mid-run")
        reservation = decision["receipt_id"] + "-exec"
        start_file = self.state / "evidence" / (ostart_evidence_id(reservation) + ".json")
        outcome_file = self.state / "evidence" / (ost_evidence_id(reservation) + ".json")

        holder = {}
        thread = threading.Thread(target=self.submit_async,
                                  args=(body, holder, self.token))
        launched_at = time.time()
        thread.start()

        # Wait for BOTH durable facts: the start marker in the evidence store
        # and the remote launch itself (the counter byte can only exist if the
        # command really started in the sandbox).
        deadline = time.time() + 30
        start_seen = False
        while time.time() < deadline:
            if start_file.is_file():
                start_seen = True
                break
            time.sleep(0.2)
        check(start_seen, "the durable start marker never appeared; the crash "
              "point is unreachable this run")
        counter_seen = None
        deadline = time.time() + 30
        counter_attempts = 0
        while time.time() < deadline:
            counter_attempts += 1
            counter_seen = self.sandbox_file_bytes(
                "E09x2" if counter_attempts == 1 else f"E09x2.{counter_attempts}",
                "E09x: the remote launch counter before the kill",
                counter_path)
            if counter_seen == 1:
                break
            time.sleep(2)
        check(counter_seen == 1, f"the remote command did not launch before the "
                                 f"kill window: counter={counter_seen}")
        outcome_absent_at_kill = not outcome_file.exists()
        check(outcome_absent_at_kill, "the outcome was already persisted before "
                                      "the kill; the crash point was missed")
        children_before = self._cli_children_snapshot()

        old_proc = self.proc
        try:
            old_proc.kill()
            old_proc.wait(timeout=20)
        except Exception:  # noqa: BLE001
            pass
        thread.join(timeout=60)
        children_orphaned = self._cli_children_snapshot()
        self.record({
            "id": "E09x3", "title": "E09x: daemon SIGKILLed between persisted start "
            "and outcome", "kind": "component_fault", "status": "pass",
            "fault": "SIGKILL to the batch-owned daemon process",
            "crash_point": "start marker persisted, outcome not yet written",
            "start_marker_present": start_seen,
            "outcome_present_at_kill": not outcome_absent_at_kill,
            "launch_counter_before_kill": counter_seen,
            "client_thread_outcome": holder,
            "cli_children_before_kill": [c[:2] for c in children_before],
            "cli_children_after_kill": [c[:2] for c in children_orphaned],
            "note": "the orphaned CLI child and the in-sandbox sleep are observed, "
                    "never asserted terminated; see E09x9 for their final state",
        })

        # Restart on the SAME isolated state dir.
        self.proc, self.serve_log, self.endpoint, self.admin = self._serve(
            "E09x4", self.env, self.workspace)
        self.keep_secret(self.admin, "admin-session")
        token_after = self.read_token(self.state)
        self.record({
            "id": "E09x5", "title": "E09x: the same state dir comes back up",
            "kind": "derived", "status": "pass" if self.endpoint else "fail",
            "endpoint": self.endpoint,
            "daemon_token_unchanged": token_after == self.token,
        })
        self.token = token_after

        chain = self.open_receipts("E09x6", "E09x: the signed receipt chain "
                                   "verifies after the crash")
        chain_ok = chain.get("verified") is True
        self.record({
            "id": "E09x7", "title": "E09x: chain verification after the crash",
            "kind": "derived", "status": "pass" if chain_ok else "fail",
            "chain_verified": chain_ok,
            "receipt_count": len(chain.get("receipts") or []),
        })

        # The consumed approval must not become executable again.
        resub_status, resub_payload = self.raw_submit(body, self.token)
        resub_reason = (resub_payload or {}).get("reason_code") \
            if isinstance(resub_payload, dict) else None
        resub_refused = resub_status != 200
        self.record({
            "id": "E09x8", "title": "E09x: resubmitting the consumed approval is "
            "refused after the restart", "kind": "derived",
            "status": "pass" if (resub_refused and
                                 resub_reason == "hold_execution_already_reserved")
                      else "fail",
            "http": resub_status, "reason_code": resub_reason,
            "note": "the reservation was consumed before the crash; the persisted "
                    "chain, not process memory, is what refuses the replay",
        })
        self.write_raw("E09x8.resubmit.json", json.dumps(resub_payload, indent=2))

        # The projection must report the interrupted task honestly: a persisted
        # start with no outcome is `uncertain`, never a success (case 5 of
        # taskStatusProjection; the in-process observer died with the kill).
        status = self.task_status_read(
            "E09x9a", "E09x: status projection of the interrupted reservation",
            reservation, body["decision_receipt_id"], body["action_id"],
            expect=(200, 404))
        self.write_raw("E09x9.status-after-crash.json", json.dumps(status, indent=2))
        projection_honest = status.get("_http_status") == 200 and \
            status.get("state") == "uncertain" and \
            status.get("reason_code") == "openshell_task_result_uncertain" and \
            status.get("task_executed") != "yes"
        self.record({
            "id": "E09x9b", "title": "E09x: projection reports uncertain, never "
            "success, for the interrupted task", "kind": "derived",
            "status": "pass" if projection_honest else "fail",
            "projection_state": status.get("state"),
            "projection_reason_code": status.get("reason_code"),
            "task_executed": status.get("task_executed"),
        })

        # No-replay window: watch the counter while the remote sleep runs out.
        # The counter must stay exactly 1; the effect file is observational.
        attempts = 0
        effect = None
        counter_final = counter_seen
        poll_deadline = launched_at + 90
        while time.time() < poll_deadline:
            attempts += 1
            counter_final = self.sandbox_file_bytes(
                f"E09x9c{attempts}", "E09x: no-replay counter watch", counter_path)
            effect = self.read_sandbox_file(
                f"E09x9d{attempts}", "E09x: the remote command's late effect "
                "(observational)", effect_path)
            if effect == crash_token and counter_final is not None:
                break
            time.sleep(8)
        children_final = self._cli_children_snapshot()
        no_replay = counter_final == 1
        self.record({
            "id": "E09x9", "title": "E09x: no replay after the crash; the remote "
            "command's fate observed", "kind": "derived",
            "status": "pass" if no_replay else "fail",
            "launch_counter_after_restart": counter_final,
            "remote_effect_observed": effect == crash_token,
            "read_back_attempts": attempts,
            "cli_children_after_window": [c[:2] for c in children_final],
            "note": "the counter is written once per real launch by the approved "
                    "command itself, so counter==1 outside the daemon proves no "
                    "replay. The effect file landing (or not) only describes the "
                    "orphaned remote command; nothing here asserts the remote was "
                    "terminated",
        })

        # Recovery: the daemon answers the probe and runs a fresh task.
        probe = self.http("E09xa", "E09x: daemon health after the crash cycle",
                          "GET", "/v1/openshell/probe")
        _, _, health_body = self.approve_task(
            "E09xb", f"o05v6-e09x-health-{self.run_id}",
            ["/bin/echo", "o05v6-e09x-health"], 60, 65536,
            self.expected_revision, self.expected_digest, [],
            title="E09x: approve a fresh task after the crash cycle")
        health_resp = self.submit_task(
            "E09xc", "E09x: a fresh task executes after the crash cycle",
            health_body, expect=200)
        health_ok = probe.get("ok") is True
        executed_ok = False
        try:
            self.assert_task_executed("E09xc", health_resp)
            executed_ok = True
        except StepFailure:
            executed_ok = False
        self.record({
            "id": "E09xd", "title": "E09x: daemon recovered after the crash cycle",
            "kind": "derived",
            "status": "pass" if (health_ok and executed_ok) else "fail",
            "probe_ok": health_ok,
            "fresh_task_executed": executed_ok,
        })

        crash_ok = (chain_ok and resub_refused and projection_honest
                    and no_replay and health_ok and executed_ok)
        prev_e09 = next((i for i in self.e_items if i.get("item") == "E09"), None)
        e09_status = "fail" if not no_replay else (
            "pass" if (prev_e09 and prev_e09.get("status") == "pass" and crash_ok)
            else "partial")
        self.note_step(
            "E09q", "E09: crash points and clock/storage fault injection",
            "partial",
            crash_leg="pass" if crash_ok else "fail",
            detail="three fault classes are now injected for real: the daemon-kill "
                   "restart (E09a-E09i), a SIGKILL BETWEEN the persisted start "
                   "marker and the outcome write (E09x: no replay proven by the "
                   "launch counter, the consumed approval refused "
                   "hold_execution_already_reserved, the projection reporting "
                   "uncertain, the chain verifying, the daemon recovering), and "
                   "durable-store write failures via chmod EACCES on the live "
                   "state dir (E11m/E11n/E11o). Remaining uncovered sub-cases: "
                   "clock fault injection (deliberately forbidden: the system "
                   "clock is never changed) and the plan->start window (too "
                   "narrow to hit without patching the running binary; still "
                   "covered structurally by the immutable per-fact records). "
                   "Because named sub-cases remain uncovered, this note stays "
                   "partial by the driver's own conservative rule.",
        )
        self.e_item_upsert(
            "E09", e09_status,
            detail="SIGKILL + restart on the same state dir: no replay, the chain "
                   "still verifies, the projection is rebuilt from persisted facts, "
                   "the remote task demonstrably outlived the local daemon, and the "
                   "reconcile matrix refuses a hash mismatch, an unknown reservation "
                   "and a never-submitted approval before closing the orphaned "
                   "reservation. Additionally a real SIGKILL between the persisted "
                   "start marker and the outcome write (E09x) proves no replay, the "
                   "consumed approval staying refused, an honest uncertain "
                   "projection, and full daemon recovery",
            crash_between_start_and_outcome="pass" if crash_ok else "fail")

    def _cli_children_snapshot(self):
        """Observational ps snapshot of executor CLI children for this target.

        Returns [(pid, ppid, argv-summary)] with the argv truncated BEFORE any
        canary material; the full snapshot goes to a private raw file where
        write_raw's secret redaction applies. Nothing here is asserted about
        remote termination -- it only records what the process table showed.
        """
        try:
            proc = subprocess.run(["ps", "-eo", "pid=,ppid=,args="],
                                  capture_output=True, text=True, timeout=15,
                                  check=False)
        except Exception:  # noqa: BLE001
            return []
        rows = []
        for line in proc.stdout.splitlines():
            if self.target in line and "sandbox" in line and "exec" in line:
                parts = line.split(None, 2)
                if len(parts) >= 2:
                    rows.append((parts[0], parts[1],
                                 parts[2].split("--", 1)[0].strip()[:120]
                                 if len(parts) > 2 else ""))
        if rows:
            self.write_raw(f"cli-children-{secrets.token_hex(4)}.txt",
                           "\n".join(str(r) for r in rows))
        return rows

    # ---- E08: the stop contract, honestly ----
    def leg_e08(self):
        tool_call = f"o05v6-e08-{self.run_id}"
        argv = ["/bin/sh", "-c",
                f"sleep 25; printf %s {self.e01_token} | dd of={self.e08_path} status=none"]
        decision, params, body = self.approve_task(
            "E08a", tool_call, argv, 120, 65536, self.expected_revision,
            self.expected_digest,
            title="E08: approve a long task, then exercise the whole stop contract on it")
        reservation = body["decision_receipt_id"] + "-exec"

        # (a) a stop aimed at a different target must not be honoured
        stop_wrong = {
            "schema_version": STOP_SCHEMA, "reservation_receipt_id": reservation,
            "action_id": body["action_id"], "decision_receipt_id": body["decision_receipt_id"],
            "target": "siq-o05v6-other-sandbox", "platform": PLATFORM,
            "session_id": self.session, "agent_id": self.target, "tool": BASE.TASK_TOOL,
            "actor_id": self.actor, "reason": "E08 ownership probe",
        }
        wrong = self.http("E08b", "E08: a stop naming another target is refused",
                          "POST", "/v1/openshell/task-executions/stop", stop_wrong,
                          token=self.token, expect=(400, 403, 404))
        # (b) an unknown reservation
        stop_unknown = dict(stop_wrong)
        stop_unknown["target"] = self.target
        stop_unknown["reservation_receipt_id"] = "does-not-exist-" + self.run_id
        unknown = self.http("E08c", "E08: a stop for an unknown reservation is refused",
                            "POST", "/v1/openshell/task-executions/stop", stop_unknown,
                            token=self.token, expect=(403, 404))
        # (c) deleting the sandbox is refused rather than used as a substitute
        stop_delete = dict(stop_wrong)
        stop_delete["target"] = self.target
        stop_delete["delete_sandbox"] = True
        deleted = self.http("E08d", "E08: deleting the sandbox is not a stop",
                            "POST", "/v1/openshell/task-executions/stop", stop_delete,
                            token=self.token, expect=(400, 409))

        # (d) a real stop of a task this daemon is observing
        holders = []
        t = threading.Thread(target=lambda: (holders.append({}),
                                             self.submit_async(body, holders[0], self.token)))
        t.start()
        time.sleep(5)
        stop_body = {
            "schema_version": STOP_SCHEMA, "reservation_receipt_id": reservation,
            "action_id": body["action_id"], "decision_receipt_id": body["decision_receipt_id"],
            "target": self.target, "platform": PLATFORM, "session_id": self.session,
            "agent_id": self.target, "tool": BASE.TASK_TOOL, "actor_id": self.actor,
            "reason": "D05 E08: stop the batch-owned in-flight canary",
        }
        stop_resp = self.http("E08e", "E08: stop an in-flight task this daemon owns",
                              "POST", "/v1/openshell/task-executions/stop", stop_body,
                              token=self.token, expect=(200, 409))
        t.join(timeout=120)
        submit_holder = holders[0] if holders else {}
        sandbox_alive = self.sandbox_path_exists("/sandbox")
        self.write_raw("E08f.stop.json", json.dumps(
            {"stop": stop_resp, "submission": submit_holder}, indent=2))
        stop_facts = parse_local_stop_response(stop_resp)
        remote_stop_confirmed = stop_facts["remote_stop_confirmed"]
        self.record({
            "id": "E08g", "title": "E08: stop contract exercised end to end",
            "kind": "derived", "status": "partial",
            "ownership_refusal_http": wrong.get("_http_status"),
            "ownership_refusal_reason": wrong.get("reason_code") or wrong.get("error"),
            "unknown_refusal_http": unknown.get("_http_status"),
            "unknown_refusal_reason": unknown.get("reason_code") or unknown.get("error"),
            "delete_sandbox_refusal_http": deleted.get("_http_status"),
            "delete_sandbox_refusal_reason": deleted.get("reason_code") or deleted.get("error"),
            "stop_http": stop_resp.get("_http_status"),
            "stop_reason": stop_resp.get("reason_code") or stop_resp.get("error"),
            "remote_stop": stop_facts["remote_stop"],
            "remote_stop_confirmed": remote_stop_confirmed,
            "delete_sandbox": stop_resp.get("delete_sandbox"),
            "sandbox_still_present_after_stop": sandbox_alive,
            "requester_submission_outcome": submit_holder,
            "note": "the stop terminates LOCAL observation only. The executor reports "
                    "remote_stop=unsupported / remote_stop_confirmed=false and refuses to "
                    "delete the sandbox as a substitute. An unobserved task gets 409 "
                    "stop_not_observable rather than a fabricated success.",
        })
        self.note_step(
            "E08h", "E08: remote stop confirmation", "blocked",
            detail="SIQ currently implements local observation termination only; "
                   "unsupported/false is a client contract constant, not a gateway response. "
                   "Remote capability needs independent verification and integration; "
                   "the O05 batch is not declared complete on its account.",
            remote_stop=stop_facts["remote_stop"],
            remote_stop_confirmed=remote_stop_confirmed,
            sandbox_still_present=sandbox_alive,
        )
        self.e_item("E08", "partial",
                    detail="ownership refusal, unknown-reservation refusal, delete-sandbox "
                           "refusal and a real local stop are all exercised against the "
                           "production route; remote stop confirmation is unsupported by the "
                           "current SIQ implementation; gateway capability is unverified",
                    stop_http=stop_resp.get("_http_status"),
                    remote_stop=stop_facts["remote_stop"])

    # ---- E12: the browser journey ----
    @staticmethod
    def _find_playwright():
        """Locate a playwright package that is already installed on this host.

        Nothing is downloaded: the batch may not reach the network for new
        dependencies, so the browser driver reuses whatever playwright is
        already present (a prior `npx playwright` cache, a global install, or a
        project install).
        """
        repo = Path(__file__).resolve().parent.parent.parent
        candidates = []
        npm_cache = Path(os.path.expanduser("~")) / ".npm" / "_npx"
        if npm_cache.is_dir():
            candidates += sorted(npm_cache.glob("*/node_modules/playwright"))
        candidates += [
            repo / "node_modules" / "playwright",
            repo / "apps" / "web" / "node_modules" / "playwright",
            Path("/usr/lib/node_modules/playwright"),
            Path("/usr/local/lib/node_modules/playwright"),
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return None

    def _stage_e12_browser(self, script):
        """Stage the browser driver where Node's ESM resolver can find playwright.

        `import 'playwright'` does not honour NODE_PATH (that is a CommonJS-only
        fallback) and the repo checkout carries no node_modules of its own, so
        the driver is copied next to a node_modules directory holding symlinks
        to an already-installed playwright. The copy is byte-identical to the
        tracked script and its digest is recorded, so the evidence names the
        exact bytes that ran rather than pointing at a file that was not the
        one executed.
        """
        package = self._find_playwright()
        if not package:
            return None, None, "no playwright package is installed on this host"
        stage = Path(__file__).resolve().parent.parent.parent / ".tmp" / "o05v6-d05-e12"
        modules = stage / "node_modules"
        try:
            modules.mkdir(parents=True, exist_ok=True)
            for name in ("playwright", "playwright-core"):
                source = package.parent / name
                link = modules / name
                if source.is_dir() and not link.exists():
                    link.symlink_to(source)
            staged = stage / script.name
            shutil.copyfile(script, staged)
        except OSError as exc:
            return None, None, f"could not stage the browser driver: {type(exc).__name__}"
        digest = hashlib.sha256(script.read_bytes()).hexdigest()
        return staged, digest, None

    def leg_e12(self):
        """One real Chromium navigation through the served product UI.

        The console is deliberately read-only for task execution: it has no 运行
        button (the run comes from the agent-side executor, which needs the
        decision credential) and no 停止 or 重新执行 button (the reservation is
        single-use). So the browser does 预览 -> 确认 and then *reads* the
        backend-tracked result; the 运行 request itself is issued by this leg
        with the executor credential, and the browser is the only thing that
        renders the outcome. That is the shipped product behaviour, and E12
        records it that way rather than pretending the console fires commands.
        """
        script = Path(__file__).resolve().parent / "openshell-o05v6-d05-e12-browser.mjs"
        if not script.exists():
            self.note_step("E12a", "E12: browser journey", "blocked",
                           detail="E12 driver not present")
            self.e_item("E12", "blocked", detail="browser driver not present")
            return
        node = shutil.which("node")
        if not node:
            self.note_step("E12a", "E12: browser journey", "blocked",
                           detail="node is not on PATH")
            self.e_item("E12", "blocked", detail="node not available")
            return
        staged, script_digest, stage_error = self._stage_e12_browser(script)
        if not staged:
            self.note_step("E12a", "E12: browser journey", "blocked", detail=stage_error)
            self.e_item("E12", "blocked", detail=stage_error)
            return

        raw_dir = self.out / PRIVATE_PREFIX / "d05-raw"
        raw_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

        # -- (1) a real one-time pairing code from the product CLI -----------
        # `pair` is cmdLocalSession, not the openshell CLI in self.cli_bin, and
        # it reads the recovery token out of the *isolated* state directory, so
        # it has to run under self.env or it would mint a code for the wrong
        # daemon.
        port = self.endpoint.rsplit(":", 1)[1]
        try:
            pair = subprocess.run([str(self.binary), "pair", "--port", port],
                                  cwd=self.workspace, env=self.env,
                                  capture_output=True, text=True, timeout=60, check=False)
        except subprocess.TimeoutExpired:
            self.note_step("E12a", "E12: pairing code", "blocked",
                           detail="pair --port timed out")
            self.e_item("E12", "blocked", detail="the product CLI did not mint a pairing code")
            return
        code = None
        for line in (pair.stdout or "").splitlines():
            found = re.search(r"pairing code[^:]*:\s*([0-9a-fA-F]{4}(?:-[0-9a-fA-F]{4}){3})", line)
            if found:
                code = found.group(1).strip()
        if pair.returncode != 0 or not code:
            self.write_raw("E12a.pair.stderr.txt", pair.stderr or "")
            self.note_step("E12a", "E12: pairing code", "blocked",
                           detail=f"pair exited {pair.returncode} without a parsable code")
            self.e_item("E12", "blocked",
                        detail="the product CLI did not mint a pairing code")
            return
        # Register the secret BEFORE any raw text is written, or write_raw would
        # persist the code in the clear.
        self.keep_secret(code, "e12-pairing-code")
        self.write_raw("E12a.pair.stdout.txt", pair.stdout)
        self.note_step("E12a", "E12: the product CLI mints a single-use pairing code", "pass",
                       exit_code=pair.returncode)

        # -- (2) two pending approvals: one to run, one to cancel ------------
        e12_token = self.run_id + secrets.token_hex(8)
        self.e12_token = e12_token
        self.e12_path = f"/tmp/o05v6-d05-e12-run-{self.run_id}.txt"
        self.e12_cancel_path = f"/tmp/o05v6-d05-e12-cancel-{self.run_id}.txt"
        run_argv = ["/bin/sh", "-c", BASE.canary_command(self.e12_path, e12_token)]
        cancel_argv = ["/bin/sh", "-c",
                       f"printf %s {e12_token} | dd of={self.e12_cancel_path} status=none"]
        run_call = f"o05v6-e12-run-{self.run_id}"
        cancel_call = f"o05v6-e12-cancel-{self.run_id}"
        try:
            run_params = self.canonical_task_params(
                self.target, run_argv, "", 60, 65536,
                self.expected_revision, self.expected_digest, [])
            run_decision = self.decide(
                "E12b", run_call, run_params,
                title="E12: an exec request left pending for the browser to approve")
            cancel_params = self.canonical_task_params(
                self.target, cancel_argv, "", 60, 65536,
                self.expected_revision, self.expected_digest, [])
            cancel_decision = self.decide(
                "E12c", cancel_call, cancel_params,
                title="E12: a second exec request for the browser to refuse")
        except Exception as exc:
            self.record({"id": "E12c.ABORT", "title": "E12: could not create pending approvals",
                         "kind": "internal", "status": "fail",
                         "detail": f"{type(exc).__name__}: {self.redact(str(exc))}"})
            self.e_item("E12", "blocked",
                        detail="no pending approval could be created for the browser")
            return
        # No hold_resolve here: the whole point is that the browser approves it.
        run_body = self.task_body(run_call, run_params, self.target, run_argv, "", 60,
                                  65536, self.expected_revision, self.expected_digest,
                                  [], run_decision)
        body_path = raw_dir / "E12d.exec-body.json"
        body_path.write_text(json.dumps(run_body))
        os.chmod(body_path, 0o600)
        self.note_step("E12d", "E12: the browser is handed a pending request, not an approval",
                       "pass", action_id=run_decision["action_id"])

        env = dict(os.environ)
        env["O05V6_ENDPOINT"] = self.endpoint
        env["O05V6_ADMIN"] = self.admin or ""
        env["O05V6_TOKEN"] = self.token or ""
        env["O05V6_TARGET"] = self.target
        env["O05V6_OUT"] = str(raw_dir)
        env["O05V6_SESSION"] = self.session
        env["O05V6_PAIR_CODE"] = code
        env["O05V6_EXEC_BODY"] = str(body_path)
        env["O05V6_ACTION_ID"] = run_decision["action_id"]
        env["O05V6_CANCEL_ACTION_ID"] = cancel_decision["action_id"]
        env["O05V6_CANCEL_DIGEST"] = cancel_decision.get("params_digest") or ""
        env["NODE_PATH"] = str(staged.parent / "node_modules")
        try:
            proc = subprocess.run([node, str(staged)], cwd=self.workspace, env=env,
                                  capture_output=True, text=True, timeout=600, check=False)
        except subprocess.TimeoutExpired:
            self.note_step("E12e", "E12: browser journey", "blocked",
                           detail="the browser driver timed out")
            self.e_item("E12", "blocked", detail="browser driver timed out")
            return
        self.write_raw("E12e.browser.stdout.txt", proc.stdout)
        self.write_raw("E12f.browser.stderr.txt", proc.stderr)

        # -- (3) the browser's own account of each sub-check -----------------
        browser = None
        for line in (proc.stdout or "").splitlines():
            if line.startswith("__O05V6_E12__"):
                try:
                    browser = json.loads(line[len("__O05V6_E12__"):])
                except ValueError:
                    browser = None
        sub_checks = {}
        if browser:
            for entry in browser.get("steps", []):
                sub_checks[entry.get("id")] = entry.get("status")
                self.record({"id": entry.get("id"), "title": entry.get("title"),
                             "kind": "browser", "status": entry.get("status"),
                             "detail": entry.get("detail"),
                             "state": entry.get("state"),
                             "status_text": entry.get("status_text"),
                             "url": entry.get("url"),
                             "http": entry.get("http"), "exit_code": entry.get("exit_code")})
        self.record({"id": "E12g", "title": "E12: browser sub-check roll-up", "kind": "derived",
                     "status": "pass" if sub_checks and
                     all(v == "pass" for v in sub_checks.values()) else "partial",
                     "sub_checks": sub_checks,
                     "driver_sha256": script_digest,
                     "console_errors": (browser or {}).get("console_errors", [])[:10],
                     "fatal": (browser or {}).get("fatal")})

        # -- (4) independent effect, read by a direct CLI call ---------------
        # The daemon never sees this read, so "a command really ran" is not the
        # daemon's word. The refused request must have left nothing behind.
        try:
            observed = self.read_sandbox_file(
                "E12h", "independent read of the file the browser-approved command wrote",
                self.e12_path)
        except Exception as exc:
            observed = None
            self.write_raw("E12h.read-error.txt", f"{type(exc).__name__}: {exc}")
        ran = observed == e12_token
        left_behind = self.sandbox_path_exists(self.e12_cancel_path)
        leaked = self.grep_tree(self.state / "evidence", self.e12_token)

        ok = bool(browser and browser.get("ok")) and ran and not left_behind and leaked == 0
        reasons = []
        if not (browser and browser.get("ok")):
            reasons.append("the browser journey did not report success")
        if not ran:
            reasons.append("the approved command's file was not found in the sandbox")
        if left_behind:
            reasons.append("the refused request still produced a sandbox file")
        if leaked:
            reasons.append("the raw token appears in the evidence store")
        self.record({
            "id": "E12i", "title": "E12: effect and refusal, proven outside the daemon",
            "kind": "derived", "status": "pass" if ok else "fail",
            "exit_code": proc.returncode,
            "approved_command_file_matches": ran,
            "refused_request_left_nothing": not left_behind,
            "raw_token_evidence_hits": leaked,
            "stdout_tail": self.redact((proc.stdout or "")[-400:]),
        })
        self.e_item("E12", "pass" if ok else "partial",
                    detail=("; ".join(reasons) if reasons else
                            "one navigation previewed, confirmed, ran and read back the "
                            "approved command's result; the console stayed read-only for "
                            "execution by design and the run came from the executor credential"),
                    sub_checks=sub_checks,
                    approved_command_file_matches=ran,
                    refused_request_left_nothing=not left_behind)

    # ================= orchestration =================
    def run(self):
        self.leg_k00()
        self.leg_k01()
        try:
            # These legs establish the premises every E-leg rests on, so a
            # failure here is fatal rather than isolated. They are NOT subject
            # to --only: without them no acceptance leg has a grant, a pinned
            # policy identity, or a calibrated sandbox to run against.
            for leg in (self.leg_k02, self.leg_k03, self.leg_k10, self.leg_k20,
                        self.leg_k30, self.leg_k35, self.leg_k40, self.leg_k50,
                        self.leg_k60):
                self.current_leg = leg.__name__
                leg()
            # Acceptance legs: each failure is recorded and the matrix continues.
            # leg_e06_loading sits next to leg_e02_window because both mutate the
            # policy and must restore + re-read the pinned identity; it needs the
            # pristine body the window captures. leg_e11_storage must precede
            # leg_e09: it chmods the live state dir and E09 restarts the daemon
            # on that same dir. leg_e09_crash follows leg_e09 immediately: it
            # SIGKILLs the daemon between the persisted start marker and the
            # outcome write and restarts on the same state dir again, so E08/E12
            # afterwards run against the newest restart.
            acceptance = (self.leg_e02_window, self.leg_e06_loading, self.leg_e01,
                          self.leg_e03, self.leg_e04, self.leg_e04_authority,
                          self.leg_e05, self.leg_e11, self.leg_e11_storage,
                          self.leg_e13, self.leg_e09, self.leg_e09_crash,
                          self.leg_e08, self.leg_e12)
            only = getattr(self.args, "only", None)
            for leg in acceptance:
                self.current_leg = leg.__name__
                if only_filter_matches(leg.__name__, only):
                    self.isolated(leg)
                else:
                    self.record({
                        "id": leg.__name__ + ".SKIP",
                        "title": f"{leg.__name__} skipped by --only {only!r}",
                        "kind": "internal", "status": "skipped",
                    })
            # K70 revokes the grant, so it runs after every grant-dependent leg.
            for leg in (self.leg_k70, self.leg_k80, self.leg_e07):
                self.current_leg = leg.__name__
                if only_filter_matches(leg.__name__, only):
                    self.isolated(leg)
                else:
                    self.record({
                        "id": leg.__name__ + ".SKIP",
                        "title": f"{leg.__name__} skipped by --only {only!r}",
                        "kind": "internal", "status": "skipped",
                    })
            self.current_leg = "done"
        finally:
            self.leg_k90()
        return self.report()

    def leg_e07(self):
        """Required backend unreachable: no native fallback, no side effect anywhere.

        Run against the lost-backend daemon K80 leaves running, re-entered here
        because K80 restores the main context in its own finally.
        """
        saved = (self.endpoint, self.admin, self.token)
        self.endpoint, self.admin = self.lost_endpoint, self.lost_admin
        self.token = self.read_token(self.lost_state)
        arrivals_before = (self.recv_a.count(), self.recv_b.count())
        sandbox_marker = f"/tmp/o05v6-d05-e07-{self.run_id}.txt"
        try:
            admitted = self.http("E07a", "E07: admit the fixture skill in the lost-backend daemon",
                                 "POST", "/v1/admit", {"path": str(self.skill)})
            granted = self.http("E07b", "E07: create a grant in the lost-backend daemon",
                                "POST", "/v1/grants", {
                                    "admission_id": admitted["admission"]["admission_id"],
                                    "platform": PLATFORM, "subject_id": self.target})
            gid = granted["grant"]["grant_id"]
            gp = "/v1/grants/" + gid
            rev = granted["state_revision"]
            # K80 already created and deployed a grant for this same admission,
            # platform and subject, so admission is content-addressed and this
            # second create returns that same grant, already `deployed`. Re-running
            # patch-desired on it would be a 400, not a finding: the lifecycle is
            # simply already complete. Reuse it and say so.
            if granted["grant"]["status"] == "deployed":
                self.record({
                    "id": "E07c", "title": "E07: reuse the deployed grant K80 left behind",
                    "kind": "derived", "status": "pass",
                    "grant_id": gid, "grant_status": granted["grant"]["status"],
                    "reused": granted.get("reused"),
                    "note": "the lost-backend daemon already holds this grant in `deployed`; "
                            "admission is content-addressed so re-creating it returns the same "
                            "grant rather than a fresh one to walk through the lifecycle",
                })
            else:
                p = self.http("E07c", "E07: patch-desired", "POST", gp + "/patch-desired",
                              {"expected_revision": rev, "models": ["fixture-model"]})
                c = self.http("E07d", "E07: challenge", "POST", gp + "/challenge",
                              {"expected_revision": p["state_revision"], "actor_id": self.actor})
                nonce = c["challenge"]["nonce"]
                self.keep_secret(nonce, "lost-backend-challenge-nonce")
                a = self.http("E07e", "E07: approve", "POST", gp + "/approve", {
                    "expected_revision": c["state_revision"], "actor_id": self.actor,
                    "challenge_id": c["challenge"]["nonce"] and c["challenge"]["challenge_id"],
                    "nonce": nonce})
                self.http("E07f", "E07: deploy", "POST", gp + "/deploy",
                          {"expected_revision": a["state_revision"]})

            # A task that WOULD leave two independent marks if a native fallback
            # ran it: a receiver arrival (the host reaches the receiver fine) and
            # a sandbox file.
            #
            # NOTE ON THE FIXTURE (recorded, not a silent tweak): the response
            # body is discarded with `curl -o /dev/null`, NOT with a shell
            # `>/dev/null 2>&1` redirect. reason: runtimeaction.Describe sets
            # FilesystemWriteHint=true for any shell-like request whose flattened
            # text matches `(>>?|\b(cp|mv|tee|rm|chmod|install|mkdir)\b)`
            # (describe.go:53), and evaluateGrant then requires EVERY path in the
            # descriptor -- which for `/bin/sh -c ...` includes argv[0] `/bin/sh`
            # itself -- to be covered by a granted path (engine.go:1066-1069).
            # A redirect therefore turns this exec into a default-deny at decide
            # time and the leg never reaches the submission it exists to test.
            # Discarding the body with -o keeps the observable semantics
            # identical (stdout empty, no receiver body echoed into the result)
            # while leaving the property under test -- required backend down must
            # not fall back to native execution -- untouched. The write-hint
            # boundary itself is recorded separately in the D05 ledger/manual.
            argv = ["/bin/sh", "-c",
                    f"curl -fsS --max-time 10 -o /dev/null http://{self.ep_a}/e07 || true; "
                    f"printf %s {self.e09_token} | dd of={sandbox_marker} status=none"]
            params = self.canonical_task_params(
                self.target, argv, "", 30, 65536, self.expected_revision,
                self.expected_digest, [self.ep_a])
            decision = self.decide("E07g", f"o05v6-e07-{self.run_id}", params)
            self.hold_resolve("E07h", decision, approve=True,
                              note="approved, then submitted while the backend is required and down")
            body = self.task_body(f"o05v6-e07-{self.run_id}", params, self.target, argv, "",
                                  30, 65536, self.expected_revision, self.expected_digest,
                                  [self.ep_a], decision)
            resp = self.submit_task(
                "E07i", "E07: approved task with the required backend down",
                body, expect=(200, 502, 503),
                note="must not fall back to native execution")
            out = resp.get("outcome") or {}
            marker = self.sandbox_path_exists(sandbox_marker)
            arrivals_after = (self.recv_a.count(), self.recv_b.count())
            self.record({
                "id": "E07j", "title": "E07: no native fallback and no side effect either side",
                "kind": "derived",
                "status": "pass" if (out.get("spawned") is not True and not marker and
                                     arrivals_after == arrivals_before) else "fail",
                "http": resp.get("_http_status"),
                "reason_code": resp.get("reason_code") or resp.get("error"),
                "spawned": out.get("spawned"),
                "task_executed": resp.get("task_executed") or out.get("task_executed"),
                "sandbox_marker_present": marker,
                "arrivals_before": arrivals_before,
                "arrivals_after": arrivals_after,
                "foreign_peers": self.recv_a.foreign_peers(),
                "note": "the host reaches the receiver fine, so a native fallback would have "
                        "produced an arrival from a non-sandbox peer; the sandbox file would "
                        "only appear if something ran in the sandbox. Neither happened.",
            })
            self.e_item("E07", "pass",
                        detail="required backend down: refused with no native fallback; two "
                               "independent side-effect channels (sandbox file, receiver "
                               "arrival) both empty",
                        http=resp.get("_http_status"), spawned=out.get("spawned"))
        finally:
            self.endpoint, self.admin, self.token = saved

    def leg_k90(self):
        procs = [("K90a", getattr(self, "proc", None), getattr(self, "serve_log", None)),
                 ("K90b", getattr(self, "lost_proc", None), getattr(self, "lost_log", None))]
        for step_id, proc, log in procs:
            try:
                self.serve_stop(step_id, proc, log)
            except Exception as exc:  # noqa: BLE001
                self.record({"id": step_id + ".stop-failed", "title": "daemon stop failed",
                             "kind": "internal", "status": "fail",
                             "detail": f"{type(exc).__name__}: {exc}"})
        after = self.policy_read("K90c")
        # The E02 window moves the Version counter even after the pristine body is
        # restored, so identity is asserted by content Hash, and the counter
        # movement is recorded as an explained delta rather than a failure.
        content_restored = after["hash"] == self.base_hash
        self.record({
            "id": "K90d", "title": "sandbox policy content restored to the batch baseline",
            "kind": "derived", "status": "pass" if content_restored else "fail",
            "baseline_hash": self.base_hash, "final_hash": after["hash"],
            "baseline_version": self.base_revision, "final_version": after["revision"],
            "version_advanced_by_e02_window": after["revision"] != self.base_revision,
            "note": "identity is the content hash; the version counter is expected to have "
                    "advanced because the E02 window necessarily updated the policy, and the "
                    "change is recorded rather than hidden",
        })
        check(content_restored,
              f"the sandbox policy content was not restored: {after['hash']} != {self.base_hash}")

    # ---------- report ----------
    def report(self):
        passed = sum(1 for s in self.steps if s.get("status") == "pass")
        failed = [s for s in self.steps if s.get("status") == "fail"]
        matrix = list(self.e_items)
        seen = {item["item"] for item in matrix}
        for item in ("E01", "E02", "E03", "E04", "E05", "E06", "E07", "E08",
                     "E09", "E10", "E11", "E12", "E13"):
            if item not in seen:
                matrix.append({"item": item, "status": "not_run",
                               "detail": "no acceptance leg produced a verdict"})
        counts = {}
        for item in matrix:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        doc = {
            "schema": PUBLIC_SCHEMA,
            "scope": "development-and-isolated-verification",
            "candidate_sha256": self.binary_sha,
            "acceptance_matrix": matrix,
            "acceptance_status_counts": counts,
            "meta": self.meta,
            "summary": {"pass": passed, "fail": len(failed),
                        "total": len(self.steps),
                        "failed_ids": [s["id"] for s in failed]},
            "steps": self.steps,
            "finished_at": BASE.now_iso(),
        }
        aliases = [(str(self.out), "<evidence-root>"),
                   (str(self.binary), "<candidate-binary>"),
                   (str(self.root), "<isolated-root>"),
                   (str(BASE.REPO), "<repo>")]
        if self.lost_root:
            aliases.append((str(self.lost_root), "<lost-backend-root>"))
        for side_root in getattr(self, "side_roots", []):
            aliases.append((str(side_root), "<side-daemon-root>"))
        if self.args.env_script:
            aliases.append((str(Path(self.args.env_script).resolve()),
                            "<openshell-env-script>"))

        path = self.out / "d05-acceptance-matrix.json"
        path.write_text(json.dumps(public_evidence(doc, self.secrets, aliases),
                                   indent=2, ensure_ascii=False))
        self.write_raw("d05-acceptance-matrix.private.json", json.dumps(doc, indent=2))
        return doc


def build_parser():
    parser = argparse.ArgumentParser(
        description="D05 acceptance matrix for OpenShell real task execution")
    parser.add_argument("--binary", required=True)
    parser.add_argument("--expected-sha256", default=None)
    parser.add_argument("--env-script", required=True)
    parser.add_argument("--gateway-endpoint", default="https://127.0.0.1:17671")
    parser.add_argument("--lost-endpoint", default="https://127.0.0.1:1")
    parser.add_argument("--target", required=True)
    parser.add_argument("--fact-endpoint", default="172.23.0.1:1",
                        help="placeholder; the live endpoint is derived from the sandbox route")
    parser.add_argument("--out", required=True)
    parser.add_argument("--skip-base-legs", action="store_true",
                        help="run only the E matrix (requires an existing run to be meaningful)")
    parser.add_argument("--only", default=None,
                        help="comma-separated leg-name prefixes (e.g. e04,e06) limiting the "
                             "acceptance legs; premise legs K00-K60 and the K90 cleanup "
                             "always run. The final evidence run must not use this filter.")
    return parser


def main():
    os.umask(0o077)
    args = build_parser().parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    private = out / PRIVATE_PREFIX
    private.mkdir(mode=0o700, exist_ok=True)
    os.chmod(private, 0o700)
    raw = private / "d05-raw"
    raw.mkdir(mode=0o700, exist_ok=True)
    os.chmod(raw, 0o700)

    recv_a = CanaryReceiver("A", raw / "arrivals-A.jsonl").start()
    recv_b = CanaryReceiver("B", raw / "arrivals-B.jsonl").start()
    journey = None
    try:
        try:
            journey = AcceptanceJourney(args, recv_a, recv_b)
        except Exception:  # noqa: BLE001 -- premises (candidate hash, CLI, sandbox) failed
            traceback.print_exc()
            (raw / "fatal.txt").write_text(traceback.format_exc())
            os.chmod(raw / "fatal.txt", 0o600)
            print(json.dumps({"error": "journey construction failed",
                              "out": str(out)}, indent=2))
            return 1
        try:
            doc = journey.run()
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            journey.record({
                "id": "FATAL", "title": "the journey aborted",
                "kind": "internal", "status": "fail",
                "detail": f"{type(exc).__name__}: {exc}",
                "traceback_file": journey.write_raw("fatal.txt", traceback.format_exc()),
            })
            doc = journey.report()
        print(json.dumps({"summary": doc["summary"],
                          "acceptance": doc["acceptance_status_counts"],
                          "out": str(out / "d05-acceptance-matrix.json")},
                         indent=2, ensure_ascii=False))
        return 0 if not doc["summary"]["fail"] else 1
    finally:
        recv_a.stop()
        recv_b.stop()
        if journey is not None:
            for proc in (journey.proc, journey.lost_proc):
                if proc is not None and proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=10)
            # These roots are created with tempfile by this exact journey;
            # they contain pairing/state material and must not outlive it.
            for owned_root in (journey.root, journey.lost_root):
                if owned_root is not None:
                    shutil.rmtree(owned_root)


if __name__ == "__main__":
    sys.exit(main())
