"""Frozen P06 real HTTP journeys; synthetic owned state, never host configuration."""
import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from http.cookies import SimpleCookie
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from common import canonical, safe_path, sha256, utc_now, write_json
from lifecycle import Journal, process_identity, project, summarize
from management_scoring import score, specs
from process_resources import identity, members, stop_owned
from product_samples import clone_contract


class Client:
    def __init__(self, h, record):
        self.h = h
        self.record = record
        self.tokens = {"admin": h.admin, "none": "", "decision": (h.state / "token").read_text().strip(),
                       "recovery": (h.state / "admin-recovery.token").read_text().strip()}
        self.secrets = [v for v in self.tokens.values() if v]
        self.rows = []
        self.cookie = ""

    def snapshot(self):
        return {p.name: sha256(p) for p in sorted((self.h.state / "intents").glob("*.json"))}

    def scrub(self, value):
        text = json.dumps(value, ensure_ascii=False)
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        return json.loads(text)

    def request(self, name, path, *, credential="admin", body=None, headers=None, cookie=False, issuance=False):
        endpoint = urlsplit(self.h.endpoint)
        request_headers = {"Content-Type": "application/json", **(headers or {})}
        if self.tokens[credential]:
            request_headers["Authorization"] = "Bearer " + self.tokens[credential]
        if cookie:
            request_headers["Cookie"] = self.cookie
        before = self.snapshot()
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=10)
        try:
            connection.request("POST" if body is not None else "GET", path,
                               body=canonical(body) if body is not None else None, headers=request_headers)
            response = connection.getresponse()
            raw = response.read(2 * 1024 * 1024)
            status, response_headers = response.status, dict(response.getheaders())
        finally:
            connection.close()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw.decode(errors="replace")
        reflection = any(secret.encode() in raw for secret in self.secrets) and not issuance
        if issuance and isinstance(payload, dict):
            self.secrets += [payload[key] for key in ("session", "code") if isinstance(payload.get(key), str)]
        cookies = SimpleCookie()
        cookies.load(response_headers.get("Set-Cookie", ""))
        attrs = []
        for name_cookie, morsel in cookies.items():
            if morsel.value:
                self.secrets.append(morsel.value)
                self.cookie = name_cookie + "=" + morsel.value
                self.tokens["refresh"] = morsel.value
            attrs.append({"httponly": bool(morsel["httponly"]), "samesite": morsel["samesite"], "path": morsel["path"],
                          "secure": bool(morsel["secure"]), "max-age": morsel["max-age"]})
        row = {"request_id": name, "method": "POST" if body is not None else "GET", "path": path,
               "credential_ref": credential, "cookie_present": cookie, "request_headers": headers or {},
               "request_body": self.scrub(body), "status": status, "response_body": self.scrub(payload),
               "response_headers": {k.lower(): v for k, v in response_headers.items() if k.lower() in ("cache-control", "content-type")},
               "cookie_attributes": attrs, "unexpected_credential_reflection": reflection,
               "authority_before": before, "authority_after": self.snapshot(), "utc": utc_now(),
               "matches_paired_session": isinstance(payload, dict) and bool(self.tokens.get("paired")) and payload.get("session") == self.tokens.get("paired")}
        self.rows.append(row)
        self.record(row)
        return payload


def journey(h, unit, record):
    client = Client(h, record)
    origin = h.endpoint
    issued = None
    name = unit["unit_id"]
    if name in ("capabilities", "origin-host"):
        h.setup_authority()
        contract = clone_contract(h, task="management-" + name, tool=h.read_tool, effect="file.read")
        contract["schema_version"] = "intent/v2"  # This management probe preserves the original valid contract schema.
        issued = contract["intent_id"]
        if name == "capabilities":
            for credential, label in (("none", "anonymous"), ("decision", "decision"), ("recovery", "recovery")):
                client.request(label + "-read", "/v1/intents", credential=credential)
            for credential, label in (("none", "anonymous"), ("decision", "decision"), ("recovery", "recovery")):
                client.request(label + "-write", "/v1/intents", credential=credential, body=contract)
            client.request("admin-write", "/v1/intents", body=contract)
            client.request("admin-readback", "/v1/intents/" + issued)
        else:
            port = urlsplit(origin).port
            variations = [("foreign-host", {"Host": f"attacker.invalid:{port}"}),
                          ("wrong-port", {"Host": "127.0.0.1:1"}),
                          ("foreign-origin", {"Origin": "http://attacker.invalid"}), ("null-origin", {"Origin": "null"}),
                          ("wrong-origin-port", {"Origin": "http://127.0.0.1:1"}),
                          ("https-origin", {"Origin": origin.replace("http:", "https:")}),
                          ("userinfo-origin", {"Origin": origin.replace("//", "//user@")}),
                          ("origin-path", {"Origin": origin + "/attack"}),
                          ("cross-site", {"Sec-Fetch-Site": "cross-site"}),
                          ("origin-query", {"Origin": origin + "?attack=1"})]
            for label, headers in variations:
                client.request(label, "/v1/intents", body=contract, headers=headers)
            client.request("same-origin-write", "/v1/intents", body=contract, headers={"Origin": origin, "Sec-Fetch-Site": "same-origin"})
            client.request("same-origin-readback", "/v1/intents/" + issued)
    elif name == "session":
        cli = {"X-SIQ-Local-CLI": "1"}
        for credential in ("admin", "decision"):
            client.request(credential + "-cannot-renew", "/v1/session/pairing", credential=credential, body={}, headers=cli)
        client.request("recovery-needs-cli", "/v1/session/pairing", credential="recovery", body={})
        client.request("browser-cannot-renew", "/v1/session/pairing", credential="recovery", body={}, headers={**cli, "Origin": origin})
        renewed = client.request("renew", "/v1/session/pairing", credential="recovery", body={}, headers=cli, issuance=True)
        body = {"code": renewed["code"], "remember": True}
        client.request("remember-needs-header", "/v1/pair", credential="none", body=body)
        browser = {"X-SIQ-Session": "1", "Origin": origin}
        paired = client.request("remember-pair", "/v1/pair", credential="none", body=body, headers=browser, issuance=True)
        client.tokens["paired"] = paired["session"]
        client.request("pair-replay", "/v1/pair", credential="none", body=body, headers=browser)
        client.request("restore-needs-header", "/v1/session/restore", credential="none", body={}, cookie=True)
        client.request("restore", "/v1/session/restore", credential="none", body={}, cookie=True, headers=browser, issuance=True)
        client.request("cookie-is-not-admin", "/v1/status", credential="none", cookie=True)
        client.request("refresh-is-not-bearer", "/v1/status", credential="refresh")
        client.request("paired-admin-works", "/v1/status", credential="paired")
        client.request("logout", "/v1/session/logout", credential="paired", body={}, headers=browser)
        client.request("logged-out-admin", "/v1/status", credential="paired")
        client.request("logged-out-restore", "/v1/session/restore", credential="none", body={}, cookie=True, headers=browser)
    elif name == "bootstrap":
        for label, path in (("ui-config", "/ui-config.json"), ("health", "/healthz"), ("ui-index", "/")):
            client.request(label, path, credential="none")
    elif name == "restart":
        client.request("before-restart", "/v1/status")
        h.stop()
        h.start()
        client.tokens["new-admin"] = h.admin
        client.secrets.append(h.admin)
        client.request("old-session-after-restart", "/v1/status")
        client.request("new-session-after-restart", "/v1/status", credential="new-admin")
    else:
        raise ValueError("unregistered management journey")
    observations = {"http": client.rows, "issued_intent_id": issued,
                    "public_key": h.command([str(h.binary), "pubkey"]).strip()}
    raw = canonical(observations)
    if any(secret.encode() in raw for secret in client.secrets if secret):
        raise ValueError("credential in exportable observations")
    return observations


def execute(protocol_path):
    p = json.loads(protocol_path.read_text())
    if (p["schema_version"] != "siq-evaluation-protocol/v2" or p["operation"] != "management_http" or
            not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", p["run_id"]) or p["max_attempts"] != 1 or p["model_calls_enabled"] is not False):
        raise ValueError("unregistered management execution")
    if {u["unit_id"]: u["requests"] for u in p["allocation"]} != json.loads(json.dumps(specs())) or len(p["allocation"]) != len(specs()):
        raise ValueError("management allocation differs")
    Path(p["candidate_root"]).resolve().relative_to(Path(p["campaign_root"]).resolve() / "private/candidates")
    source = Path(__file__).parent
    for name, digest in p["harness_sources"].items():
        if sha256(safe_path(source, name)) != digest:
            raise ValueError("frozen management harness differs")
    candidate = Path(p["candidate_root"])
    for name, digest in p["candidate_sources"].items():
        if sha256(safe_path(candidate, name)) != digest:
            raise ValueError("candidate source differs")
    if sha256(Path(p["binary"])) != p["candidate_digest"]:
        raise ValueError("candidate binary differs")
    if os.getpgrp() != os.getpid():
        os.setsid()
    os.umask(0o077)
    out = Path(p["campaign_root"]) / "private/runs" / p["run_id"]
    journal = Journal(out, p)
    spec = importlib.util.spec_from_file_location("management_fixture", candidate / "scripts/validate-mcp-provenance.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    try:
        for unit in p["allocation"]:
            key = unit["unit_id"] + "#1"
            prefix = "attempts/" + unit["unit_id"] + "/1"
            directory = out / prefix
            directory.mkdir(parents=True)
            state = out / "state-private" / unit["unit_id"]
            state.mkdir(parents=True, mode=0o700)

            class OwnedHarness(fixture.base.Harness):
                def start(self, directory=directory):
                    super().start()
                    number = len(list(directory.glob("daemon-*.json"))) + 1
                    write_json(directory / f"daemon-{number}.json", {"owner": process_identity(), "daemon": identity(self.proc.pid),
                               "command_sha256": hashlib.sha256(Path(f"/proc/{self.proc.pid}/cmdline").read_bytes()).hexdigest()})

            h = OwnedHarness(state, SimpleNamespace(binary=Path(p["binary"])))
            journal.transition(key, "started", execution_status="running", process_ref=process_identity())
            error, result = None, None
            partial_harm, partial_fail = False, False
            request_index = 0

            def record(row, directory=directory, unit=unit, key=key, prefix=prefix):
                nonlocal partial_harm, partial_fail, request_index
                expected_name, status = unit["requests"][request_index]
                if row["request_id"] != expected_name:
                    raise ValueError("request allocation differs")
                request_index += 1
                with (directory / "http.jsonl").open("ab") as stream:
                    stream.write(canonical(row) + b"\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                changed = row["authority_before"] != row["authority_after"]
                partial_harm |= (status >= 400 and (row["status"] < 400 or changed)) or row["unexpected_credential_reflection"]
                partial_fail |= row["status"] != status or changed != (status == 201) or partial_harm
                journal.transition(key, "observed", tool_executed=True,
                                   harm_observed=True if partial_harm else None, harm_unknown_reason=None if partial_harm else "journey_in_progress",
                                   harm_evidence_refs=[prefix + "/http.jsonl"] if partial_harm else [],
                                   assertion_status="fail" if partial_fail else "not_evaluated")
            try:
                h.build()
                h.start()
                observations = journey(h, unit, record)
                write_json(directory / "observations.json", observations)
                result = score(unit, observations)
                write_json(directory / "score.json", result)
                journal.transition(key, "observed", harm_observed=result["harm_observed"], harm_unknown_reason=None,
                                   harm_evidence_refs=[prefix + "/http.jsonl", prefix + "/observations.json"], utility_completed=result["utility_completed"],
                                   utility_unknown_reason=None, utility_evidence_refs=[prefix + "/observations.json"],
                                   assertion_status="fail" if result["assertion_status"] == "fail" else "not_evaluated",
                                   tool_executed=True, oracle={"source": "evaluator_http_and_authority_file_snapshots", "healthy": True,
                                   "coverage": "full", "window_start": observations["http"][0]["utc"], "window_end": observations["http"][-1]["utc"],
                                   "materials": [prefix + "/observations.json"]})
            except Exception as exc:  # noqa: BLE001 -- retain allocated errors; never expose credential-bearing exceptions
                error = {"type": type(exc).__name__, "detail": "management journey incomplete; no inferred pass"}
            finally:
                h.stop()
                remaining = members(os.getpid(), exclude=(os.getpid(),))
                write_json(directory / "cleanup.json", {"remaining_group_members": remaining, "confirmed": not remaining})
            if remaining and not error:
                error = {"type": "cleanup_incomplete", "detail": "owned group contains remaining processes"}
            journal.transition(key, "finished", execution_status="error" if error else "completed",
                               measurement_status="indeterminate" if error else "determinate", error=error,
                               assertion_status="fail" if partial_fail or (result and result["assertion_status"] == "fail") else "inconclusive" if error else result["assertion_status"], cleanup_confirmed=not remaining,
                               event_trace_refs=[prefix + "/cleanup.json"])
        _, states, _, _ = project(out)
        summary = summarize(states)
        with (out / "cases.jsonl").open("x") as stream:
            for row in states.values():
                stream.write(json.dumps(row) + "\n")
        write_json(out / "summary.json", summary)
        names = ["protocol.json", "journal.jsonl", "cases.jsonl", "summary.json"]
        names += [str(f.relative_to(out)) for f in (out / "attempts").rglob("*.json")]
        names += [str(f.relative_to(out)) for f in (out / "attempts").rglob("*.jsonl")]
        write_json(out / "manifest.json", {"schema_version": "siq-management-http-manifest/v1", "relationship": "author_run",
                   "artifacts": {name: sha256(out / name) for name in names}})
        print(json.dumps({**summary, "manifest_sha256": sha256(out / "manifest.json")}), flush=True)
        return summary["outcome_exit_code"]
    finally:
        journal.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", type=Path)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.execute:
        return execute(args.execute)
    if not args.campaign or not args.run_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,96}", args.run_id):
        raise ValueError("campaign and fresh valid run ID required")
    campaign = args.campaign.resolve()
    old = json.loads((campaign / "protocols/product-journal-recovery-002-protocol/protocol.json").read_text())
    root = campaign / "protocols" / (args.run_id + "-protocol")
    root.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    names = ["management_trial.py", "management_scoring.py", "common.py", "lifecycle.py", "process_resources.py", "product_samples.py", "schemas/case.v1.schema.json"]
    names += [str(f.relative_to(source)) for d in ("analysis", "oracles", "product_observers") for f in (source / d).glob("*.py")]
    for name in names:
        target = root / "harness-source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    allocation = [{"unit_id": name, "case_id": "P06." + name, "pair_id": name, "task_block_id": name, "track": "B", "group": "B2",
                   "family_id": "P06", "claim_ids": ["C6"], "product_group_ids": ["P06"], "requests": requests} for name, requests in specs().items()]
    p = {"schema_version": "siq-evaluation-protocol/v2", "operation": "management_http", "run_id": args.run_id,
         "campaign_root": str(campaign), "candidate_root": old["candidate_root"], "candidate_sources": old["candidate_sources"],
         "binary": old["binary"], "candidate_digest": old["candidate_digest"], "allocation": allocation,
         "max_attempts": 1, "model_calls_enabled": False, "relationship": "author_run", "frozen_at": utc_now(),
         "signed_intent_verification": True,
         "harness_sources": {name: sha256(root / "harness-source" / name) for name in names},
         "limits": {"http_timeout_seconds": 10, "supervisor_seconds": 240, "scope": "owned loopback daemon only"}}
    write_json(root / "protocol.json", p)
    write_json(root / "local-anchor.json", {"sha256": sha256(root / "protocol.json")})
    command = [sys.executable, str(root / "harness-source/management_trial.py"), "--execute", str(root / "protocol.json")]
    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = child.communicate(timeout=240)
    except subprocess.TimeoutExpired:
        child.kill()
        stdout, stderr = child.communicate(timeout=10)
    out = campaign / "private/runs" / args.run_id
    for resource in (out / "attempts").rglob("daemon-*.json"):
        value = json.loads(resource.read_text())
        stop_owned(value["daemon"], value["command_sha256"])
    write_json(campaign / "reports" / (args.run_id + "-execution.json"), {"argv": command, "exit_code": child.returncode, "stdout": stdout, "stderr": stderr})
    print(stdout, end="")
    return child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
