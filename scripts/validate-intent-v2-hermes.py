#!/usr/bin/env python3
"""Exercise installed Hermes native tool dispatch against a temporary SIQ daemon.

No model calls, real user configuration, or published capability claims. The
operator and files are synthetic fixtures. stdout/report contain no credentials,
tool contents, or raw daemon logs. Native Hermes is an explicit prerequisite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
AGENT = "intent-v2-fixture-agent"
SESSION = "intent-v2-fixture-session"


def require(condition, label):
    if not condition:
        raise RuntimeError(label)


def worker(spec_path):
    """Use the platform's actual loader and dispatcher, without patched hooks."""
    spec = json.loads(Path(spec_path).read_text())
    sys.path.insert(0, spec["hermes_root"])
    from hermes_cli.plugins import discover_plugins
    from model_tools import handle_function_call

    discover_plugins()
    results = []
    for call in spec["calls"]:
        result = handle_function_call(
            call["tool"],
            call["params"],
            task_id="fixture-terminal-task",
            session_id=call.get("session_id", SESSION),
            tool_call_id=call["id"],
            turn_id="fixture-turn",
            api_request_id="fixture-request",
            enabled_tools=["read_file", "write_file"],
        )
        results.append({"id": call["id"], "result": result})
    Path(spec["result_path"]).write_text(json.dumps(results))


class Harness:
    platform = "hermes"
    read_tool = "read_file"
    write_tool = "write_file"

    def __init__(self, root, args):
        self.root, self.args = root, args
        self.state = root / "state"
        self.state.mkdir(mode=0o700)
        self.workspace = root / "workspace"
        self.workspace.mkdir()
        for company in ("company-a", "company-b", "company-a-evil"):
            target = self.workspace / company
            target.mkdir()
            (target / "report.txt").write_text(f"fixture-visible-{company}\n")
        self.binary = root / "siq-agent-security"
        self.proc = None
        self.log = None
        self.admin = ""
        self.checks = []
        self.env = {
            k: v
            for k, v in os.environ.items()
            if k
            in (
                "PATH",
                "HOME",
                "LANG",
                "LC_ALL",
                "TZ",
                "SYSTEMROOT",
                "TMPDIR",
            )
        }
        self.env.update(
            {
                "SIQ_AGENT_SECURITY_STATE_DIR": str(self.state),
                "SIQ_AGENT_SECURITY_AGENT_ID": AGENT,
                "SIQ_AGENT_SECURITY_MODE": "block",
                "HERMES_HOME": str(root / "hermes"),
                "HERMES_BUNDLED_PLUGINS": str(root / "empty-plugins"),
                "HERMES_ENABLE_PROJECT_PLUGINS": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
                "TERMINAL_ENV": "local",
                "TERMINAL_CWD": str(self.workspace),
            }
        )
        self.build_env = self.env.copy()
        self.install_evidence = {"method": "fixture_copy"}
        if getattr(args, "installer_managed_profile", False):
            isolated_home = root / "home"
            isolated_home.mkdir(mode=0o700)
            self.env.update(
                {
                    "HOME": str(isolated_home),
                    "USERPROFILE": str(isolated_home),
                    "LOCALAPPDATA": str(isolated_home / "AppData/Local"),
                    "HERMES_HOME": str(root / "hermes/profiles/work"),
                    "SIQ_AGENT_SECURITY_HERMES_CLI": str(args.hermes_cli),
                }
            )
        (root / "empty-plugins").mkdir()
        hermes_home = Path(self.env["HERMES_HOME"])
        hermes_home.mkdir(parents=True, exist_ok=True)
        if getattr(args, "installer_managed_profile", False):
            (hermes_home / "config.yaml").write_text("terminal:\n  env: local\nfixture_setting: retain\n")
            (root / "hermes/config.yaml").write_text("fixture_default: unchanged\n")
            self.config("required")
            return
        plugin = hermes_home / "plugins" / "siq-agent-security"
        plugin.mkdir(parents=True)
        for name in ("__init__.py", "plugin.yaml"):
            shutil.copyfile(REPO / "adapters/runtime/hermes-agentshield" / name, plugin / name)
        (hermes_home / "config.yaml").write_text("plugins:\n  enabled: [siq-agent-security]\nterminal:\n  env: local\n")
        # A short timeout bounds the disconnected native hook scenario.
        (plugin / "config.json").write_text(json.dumps({"timeout_s": 1}))
        self.config("required")

    def config(self, enforcement):
        (self.state / "config.json").write_text(
            json.dumps(
                {
                    "intent_enforcement": enforcement,
                    "enforcement_mode": "block",
                }
            )
        )

    def command(self, args, *, cwd=None, timeout=120, env=None):
        p = subprocess.run(
            args,
            cwd=cwd or self.workspace,
            env=env or self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        require(p.returncode == 0, "subprocess failed: " + Path(args[0]).name)
        return p.stdout

    def build(self):
        self.command(
            ["go", "build", "-trimpath", "-o", str(self.binary), "./cmd/agentshield"],
            cwd=REPO / "apps/agentshield",
            timeout=180,
            env=self.build_env,
        )

    def install_profile(self):
        catalog = self.api("/v1/adapter/instances?platform=hermes")
        target = next(item for item in catalog["instances"] if item["active"])
        require(target["name"] == "work", "named native fixture was not resolved")
        config = Path(self.env["HERMES_HOME"]) / "config.yaml"
        before = config.read_bytes()
        plan = self.api(
            "/v1/adapter/preview",
            {
                "platform": "hermes",
                "action": "install",
                "instance_id": target["instance_id"],
                "native_enable": True,
            },
        )
        require(config.read_bytes() == before, "native preview changed host config")
        require(plan["schema_version"] == "local-adapter-plan/v2", "instance plan contract missing")
        self.api(
            "/v1/adapter/install",
            {
                "platform": "hermes",
                "instance_id": target["instance_id"],
                "plan_id": plan["plan_id"],
                "plan_digest": plan["plan_digest"],
            },
        )
        require("fixture_setting: retain" in config.read_text(), "native enable lost user settings")
        require(
            (self.root / "hermes/config.yaml").read_text() == "fixture_default: unchanged\n", "default profile changed"
        )
        catalog = self.api("/v1/adapter/instances?platform=hermes")
        diagnosis = next(
            item["diagnosis"] for item in catalog["instances"] if item["instance_id"] == target["instance_id"]
        )
        require(diagnosis["runtime_state"] == "unverified", "configuration must not claim runtime proof")
        self.checks.append("instance_preview_native_enable_and_default_isolation")
        self.install_evidence = {
            "method": "instance_preview_apply_with_public_native_cli",
            "plan_schema": plan["schema_version"],
            "changed_file_count": len(plan["changes"]),
            "native_cli_sha256": hashlib.sha256(self.args.hermes_cli.read_bytes()).hexdigest(),
            "runtime_before_test": diagnosis["runtime_state"],
        }

    def start(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.endpoint = f"http://127.0.0.1:{port}"
        self.env["SIQ_AGENT_SECURITY_ENDPOINT"] = self.endpoint
        self.log = tempfile.TemporaryFile(mode="w+t")  # noqa: SIM115 -- closed in stop/finally
        self.proc = subprocess.Popen(
            [str(self.binary), "serve", "--port", str(port), "--mode", "block"],
            cwd=self.workspace,
            env=self.env,
            stdout=self.log,
            stderr=self.log,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            require(self.proc.poll() is None, "daemon exited before readiness")
            self.log.seek(0)
            found = re.search(r"admin pairing code \(single use, 5 min\): (\S+)", self.log.read())
            if found:
                try:
                    pair = self.api("/v1/pair", {"code": found[1]}, token="")
                    self.admin = pair["session"]
                    return
                except urllib.error.URLError:
                    pass
            time.sleep(0.05)
        raise RuntimeError("daemon readiness timeout")

    def stop(self, *, kill=False):
        if self.proc is not None:
            if self.proc.poll() is None:
                self.proc.kill() if kill else self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(timeout=10)
            self.proc = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def api(self, path, body=None, *, token=None, expected=200):
        bearer = self.admin if token is None else token
        headers = {"Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        request = urllib.request.Request(
            self.endpoint + path,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            response = urllib.request.urlopen(request, timeout=10)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            payload = json.loads(response.read())
            require(
                response.status == expected,
                f"HTTP {path}: expected {expected}, got {response.status}; "
                + str(payload.get("reason_code", payload.get("error", ""))),
            )
            return payload

    def setup_authority(self):
        skill = self.root / "fixture-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text(
            "---\nname: intent-fixture\ndescription: Read a synthetic report.\n"
            f"allowed-tools: {self.read_tool} {self.write_tool}\n---\nRead the fixture report.\n"
        )
        adm = self.api("/v1/admit", {"path": str(skill)})["admission"]
        require(adm["verdict"] != "quarantine", "benign fixture quarantined")
        result = self.api(
            "/v1/grants",
            {
                "admission_id": adm["admission_id"],
                "platform": self.platform,
                "subject_id": AGENT,
                "subject_type": "agent_instance",
                "redact_secrets": True,
            },
        )
        grant_path = "/v1/grants/" + result["grant"]["grant_id"]

        def action(name, **body):
            nonlocal result
            result = self.api(
                grant_path + "/" + name,
                {
                    "expected_revision": result["state_revision"],
                    "actor_id": "automated-fixture-operator",
                    **body,
                },
            )
            return result

        action(
            "patch-desired",
            tools=[self.read_tool, self.write_tool],
            **(
                {"network": [{"endpoint": host, "effect": "allow"} for host in self.network_endpoints]}
                if hasattr(self, "network_endpoints")
                else {}
            ),
            filesystem={
                "read_only": [str(self.workspace)],
                "read_write": [str(self.workspace)],
            },
        )
        for index, overlap in enumerate(result["grant"]["overlap_conflicts"]):
            if overlap["resolution"] == "unresolved":
                action("resolve-overlap", index=index)
        challenge = action("challenge")["challenge"]
        action("approve", challenge_id=challenge["challenge_id"], nonce=challenge["nonce"])
        require(result["grant"]["status"] == "approved", "grant approval did not transition")
        action("deploy")
        now = datetime.now(UTC)

        def stamp(t):
            return t.strftime("%Y-%m-%dT%H:%M:%SZ")

        intent = self.api(
            "/v1/intents",
            {
                "schema_version": "intent/v2",
                "intent_id": "int-native-fixture",
                "task_id": "task-native-fixture",
                "principal": {"type": "user", "id": "fixture"},
                "agent": {"id": AGENT, "platform": self.platform},
                "purpose": "read fixture company-a",
                "allowed_tools": [self.read_tool],
                "allowed_effects": ["file.read"],
                "resource_constraints": [
                    {
                        "domain": "filesystem",
                        "operator": "prefix",
                        "value": str(self.workspace / "company-a"),
                    }
                ],
                "parameter_constraints": [],
                "issued_at": stamp(now - timedelta(minutes=1)),
                "valid_from": stamp(now - timedelta(minutes=1)),
                "expires_at": stamp(now + timedelta(hours=1)),
                "authority": {
                    "issuer": "local-admin",
                    "revision": "r1",
                    "evidence_ids": [],
                },
            },
            expected=201,
        )
        self.digest = intent["digest"]
        self.api(
            "/v1/intent-bindings",
            {
                "platform": self.platform,
                "session_id": SESSION,
                "agent_id": AGENT,
                "intent_id": intent["intent_id"],
            },
            expected=201,
        )
        decision_token = (self.state / "token").read_text().strip()
        self.api("/v1/intents", token=decision_token, expected=403)
        self.checks.append("decision_token_cannot_read_authority")

    def native(self, calls):
        spec = self.root / "worker-input.json"
        result = self.root / "worker-result.json"
        result.unlink(missing_ok=True)
        spec.write_text(
            json.dumps(
                {
                    "hermes_root": str(self.args.hermes_root),
                    "calls": calls,
                    "result_path": str(result),
                }
            )
        )
        self.command(
            [
                str(self.args.hermes_python),
                str(Path(__file__).resolve()),
                "--worker",
                str(spec),
            ]
        )
        return json.loads(result.read_text())

    def read(self, call_id, company="company-a", session=SESSION):
        return {
            "id": call_id,
            "tool": self.read_tool,
            "session_id": session,
            "params": {"path": str(self.workspace / company / "report.txt")},
        }

    def receipts(self):
        records, since = [], -1
        while True:
            page = self.api(f"/v1/receipts?since_seq={since}")
            require(page["verified"], "receipt chain verification failed")
            if not page["receipts"]:
                return records
            records.extend(page["receipts"])
            next_seq = records[-1]["seq"]
            require(next_seq > since, "receipt pagination did not advance")
            since = next_seq

    def assert_call(self, records, call_id, outcome, *, bound=True):
        own = [r for r in records if r.get("tool_call_id") == call_id]
        decisions = [r for r in own if r.get("record_type") == "decision"]
        observations = [r for r in own if r.get("record_type") == "observation"]
        require(len(decisions) == 1, call_id + ": missing/duplicate decision")
        decision = decisions[0]
        require(
            decision["action"] == outcome,
            call_id + ": unexpected action " + str(decision.get("reason_code")),
        )
        require(
            decision["intent_binding"] == ("bound" if bound else "unbound"),
            call_id + ": unexpected binding",
        )
        if bound:
            require(decision["intent_digest"] == self.digest, call_id + ": wrong authority")
            require(
                decision["intent_id"] == "int-native-fixture"
                and decision["task_id"] == "task-native-fixture"
                and decision["authority_revision"] == "r1"
                and decision["principal"] == {"type": "user", "id": "fixture"},
                call_id + ": trusted authority metadata missing",
            )
        expected_reason = {
            "foreign-company": "intent_resource_not_allowed",
            "prefix-collision": "intent_resource_not_allowed",
            "write-denied": "intent_tool_not_allowed",
            "missing-binding": "intent_binding_missing",
            "bound-still-denied": "intent_resource_not_allowed",
        }.get(call_id)
        if expected_reason:
            require(
                decision["reason_code"] == expected_reason,
                call_id + ": wrong denial layer",
            )
        require(
            len(observations) == (1 if outcome == "allow" else 0),
            call_id + ": missing/unauthorized observation",
        )
        if observations:
            observation = observations[0]
            require(
                observation["action_id"] == decision["action_id"]
                and observation["decision_receipt_id"] == decision["receipt_id"],
                call_id + ": observation detached from decision",
            )
            for field in (
                "task_id",
                "intent_id",
                "intent_digest",
                "authority_revision",
                "principal",
            ):
                require(
                    observation.get(field) == decision.get(field),
                    call_id + ": observation authority changed",
                )
        return decision

    def run(self):
        self.build()
        self.start()
        if getattr(self.args, "installer_managed_profile", False):
            self.install_profile()
        self.setup_authority()
        forbidden_write = self.workspace / "company-a" / "must-not-exist.txt"
        calls = [
            self.read("allowed"),
            self.read("foreign-company", "company-b"),
            self.read("prefix-collision", "company-a-evil"),
            {
                "id": "write-denied",
                "tool": self.write_tool,
                "params": {
                    "path": str(forbidden_write),
                    "content": "fixture must not execute",
                },
            },
            self.read("missing-binding", session="unbound-fixture"),
        ]
        outputs = self.native(calls)
        require(
            "fixture-visible-company-a" in outputs[0]["result"],
            "native read did not execute",
        )
        require(not forbidden_write.exists(), "denied native write executed")
        for output in outputs[1:]:
            require("fixture-visible-" not in output["result"], "denied read leaked fixture")
            require(
                "siq-agent-security" in output["result"],
                "native rejection missing adapter reason",
            )
        records = self.receipts()
        allowed = self.assert_call(records, "allowed", "allow")
        for call_id in ("foreign-company", "prefix-collision", "write-denied"):
            self.assert_call(records, call_id, "deny")
        self.assert_call(records, "missing-binding", "deny", bound=False)
        self.checks.extend(
            [
                "native_read_and_bound_observation",
                "resource_scope_denied",
                "path_prefix_boundary_denied",
                "native_write_not_executed",
                "required_missing_binding_denied",
            ]
        )

        # Kill the actual daemon, then invoke the same platform dispatcher offline.
        self.stop(kill=True)
        offline = self.native([self.read("offline")])[0]["result"]
        require(
            "fail-closed" in offline and "fixture-visible-" not in offline,
            "offline native hook did not block",
        )
        pending = self.state / "pending" / "decisions.jsonl"
        require(pending.exists(), "offline pending evidence missing")
        self.checks.append("native_offline_block_with_pending")
        self.start()
        restarted = self.native([self.read("after-restart")])[0]["result"]
        require("fixture-visible-company-a" in restarted, "native read failed after restart")
        records = self.receipts()
        self.assert_call(records, "after-restart", "allow")
        promoted = [r for r in records if "pending" in str(r.get("matched_rule_ids"))]
        require(
            len(promoted) == 1 and promoted[0]["action"] == "deny",
            "offline denial not promoted exactly once after restart",
        )
        self.checks.append("daemon_kill_restart_binding_and_pending_recovery")

        # Retry the exact native post result after both adapter and daemon restart.
        token = (self.state / "token").read_text().strip()
        observe = {
            "platform": self.platform,
            "session_id": SESSION,
            "agent_id": AGENT,
            "tool": self.read_tool,
            "tool_call_id": "allowed",
            "params": calls[0]["params"],
            "action_id": allowed["action_id"],
            "decision_receipt_id": allowed["receipt_id"],
            "result": outputs[0]["result"],
        }
        self.api("/v1/observe", observe, token=token)
        self.api(
            "/v1/observe",
            {**observe, "result": "different fixture result"},
            token=token,
            expected=409,
        )
        self.assert_call(self.receipts(), "allowed", "allow")
        self.checks.append("http_post_replay_idempotent_and_conflict_after_restart")
        with ThreadPoolExecutor(max_workers=8) as pool:
            replayed = list(pool.map(lambda _: self.api("/v1/observe", observe, token=token), range(32)))
        require(
            all(r == replayed[0] for r in replayed),
            "concurrent replay returned different receipts",
        )
        self.assert_call(self.receipts(), "allowed", "allow")
        self.checks.append("http_concurrent_post_restart_replay_single_observation")
        measurements = self.load(token)

        self.stop()
        self.config("optional")
        self.start()
        legacy = self.native([self.read("optional-unbound", session="unbound-fixture")])[0]["result"]
        require("fixture-visible-company-a" in legacy, "optional unbound native read failed")
        self.assert_call(self.receipts(), "optional-unbound", "allow", bound=False)
        self.native([self.read("bound-still-denied", "company-b")])
        self.assert_call(self.receipts(), "bound-still-denied", "deny")
        self.checks.extend(
            [
                "optional_unbound_native_compatibility",
                "bound_cannot_downgrade_in_optional",
            ]
        )
        records = self.receipts()
        self.stop()
        verified = json.loads(self.command([str(self.binary), "verify"]))
        require(verified["verified"], "offline CLI chain verification failed")
        self.checks.append("offline_cli_receipt_chain_verified")
        return {
            "schema": f"intent-v2-native-{self.platform}-validation/v1",
            "passed": True,
            "recorded_at": datetime.now(UTC).isoformat(),
            "siq_commit": self.command(["git", "rev-parse", "HEAD"], cwd=REPO).strip(),
            "siq_dirty": bool(self.command(["git", "status", "--porcelain"], cwd=REPO).strip()),
            "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "server_sha256": hashlib.sha256(
                (REPO / "apps/agentshield/internal/server/server.go").read_bytes()
            ).hexdigest(),
            "binary_sha256": hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            **self.runtime_evidence(),
            "go_version": self.command(["go", "version"]).strip(),
            "os": platform.system(),
            "architecture": platform.machine(),
            "checks": self.checks,
            "receipt_count": len(records),
            "installation": self.install_evidence,
            "measurements": measurements,
            "scope": "installed native plugin loader and tool dispatcher; actual Go HTTP and signed receipt chain",
            "limitations": [
                "synthetic calls and operator; no LLM session or human approval proof",
                "no Hermes native approval/hold journey",
                "no OpenClaw or CodeBuddy runtime",
                "no OS isolation or full platform support claim",
            ],
        }

    def runtime_evidence(self):
        sources = [
            "model_tools.py",
            "hermes_cli/plugins.py",
            "hermes_cli/lifecycle.py",
            "tools/file_tools.py",
        ]
        return {
            "adapter_sha256": hashlib.sha256(
                (REPO / "adapters/runtime/hermes-agentshield/__init__.py").read_bytes()
            ).hexdigest(),
            "hermes_source_sha256": {
                p: hashlib.sha256((self.args.hermes_root / p).read_bytes()).hexdigest() for p in sources
            },
            "hermes_commit": self.command(["git", "rev-parse", "HEAD"], cwd=self.args.hermes_root).strip(),
            "hermes_dirty": bool(self.command(["git", "status", "--porcelain"], cwd=self.args.hermes_root).strip()),
            "hermes_python_version": self.command([str(self.args.hermes_python), "--version"]).strip(),
        }

    def load(self, token):
        """Bounded HTTP load includes Intent resolution, signing and receipt IO.

        Calls here are synthetic HTTP clients, separately labelled from native
        dispatch. No time thresholds or full-system durability claim are implied.
        """

        def one(index):
            call_id = f"load-{index}"
            request = {
                "platform": self.platform,
                "session_id": SESSION,
                "agent_id": AGENT,
                "tool": self.read_tool,
                "tool_call_id": call_id,
                "params": self.read(call_id)["params"],
            }
            start = time.perf_counter()
            decision = self.api("/v1/decide", request, token=token)
            decided = time.perf_counter()
            require(decision["action"] == "allow", "load decision was not allowed")
            self.api(
                "/v1/observe",
                {
                    **request,
                    "action_id": decision["action_id"],
                    "decision_receipt_id": decision["receipt_id"],
                    "result": "synthetic HTTP load result",
                },
                token=token,
            )
            return (decided - start) * 1000, (time.perf_counter() - decided) * 1000

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=self.args.concurrency) as pool:
            samples = list(pool.map(one, range(self.args.load_samples)))
        elapsed = time.perf_counter() - start
        records = self.receipts()
        for index in range(self.args.load_samples):
            self.assert_call(records, f"load-{index}", "allow")
        self.checks.append("bounded_http_load_all_actions_correlated")

        def percentiles(values):
            ordered = sorted(values)
            return {f"p{q}_ms": ordered[max(0, math.ceil(len(ordered) * q / 100) - 1)] for q in (50, 95, 99)}

        return {
            "samples": len(samples),
            "concurrency": self.args.concurrency,
            "elapsed_seconds": elapsed,
            "pairs_per_second": len(samples) / elapsed,
            "decide": percentiles([s[0] for s in samples]),
            "observe": percentiles([s[1] for s in samples]),
            "thresholds": None,
            "scope": "loopback HTTP, binding validation, signing, receipt persistence; synthetic results",
            "limitations": "bounded run, not long-duration soak, native tool latency or SLA",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-root", type=Path)
    parser.add_argument("--hermes-python", type=Path)
    parser.add_argument("--hermes-cli", type=Path)
    parser.add_argument(
        "--installer-managed-profile",
        action="store_true",
        help="install an isolated named profile through SIQ preview/apply and the public Hermes CLI",
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--load-samples", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    require(args.hermes_root is not None, "--hermes-root is required")
    require(1 <= args.load_samples <= 4000, "--load-samples must be 1..4000")
    require(1 <= args.concurrency <= 32, "--concurrency must be 1..32")
    args.hermes_root = args.hermes_root.resolve()
    args.hermes_python = args.hermes_python or args.hermes_root / "venv/bin/python"
    args.hermes_cli = (args.hermes_cli or args.hermes_python.parent / "hermes").resolve()
    if args.installer_managed_profile:
        require(args.hermes_cli.is_file(), "installed Hermes CLI not found; use --hermes-cli")
    require(
        args.hermes_python.is_file(),
        "installed Hermes Python not found; use --hermes-python",
    )
    # All fixture credentials and logs are removed even when validation fails.
    with tempfile.TemporaryDirectory(prefix="siq-intent-native-") as tmp:
        harness = Harness(Path(tmp), args)
        try:
            report = harness.run()
        finally:
            harness.stop()
    raw = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(raw)
    print(raw, end="")


if __name__ == "__main__":
    try:
        main()
    except (
        RuntimeError,
        OSError,
        ValueError,
        KeyError,
        subprocess.SubprocessError,
    ) as exc:
        # Subprocess output may contain pairing codes or tool data; never echo it.
        print(f"native validation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
