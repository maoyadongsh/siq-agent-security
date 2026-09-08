#!/usr/bin/env python3
"""Loopback MCP protocol -> signed provenance -> real SIQ V3 decision fixture.

No native-platform support claim, paid provider, or user configuration mutation.
The fixture covers the HTTP JSON response branch, not a generic MCP client.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("intent_fixture", ROOT / "scripts/validate-intent-v2-hermes.py")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


class MCPFixture(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = message["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "siq-fixture-mcp", "version": "1"}}
        elif method == "notifications/initialized":
            self.server.initialized = True
            self.send_response(202)
            self.end_headers()
            return
        elif method == "tools/call" and self.server.initialized:
            if message["params"]["name"] != "lookup_report":
                self.send_error(400)
                return
            self.server.tool_calls += 1
            result = {"content": [], "structuredContent": {"path": self.server.report_path}, "isError": False}
        else:
            self.send_error(400)
            return
        raw = canonical({"jsonrpc": "2.0", "id": message["id"], "result": result})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def rpc(endpoint, method, params=None, request_id=None):
    body = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    if request_id is not None:
        body["id"] = request_id
    request = urllib.request.Request(endpoint, data=canonical(body), headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
    })
    with urllib.request.urlopen(request, timeout=5) as response:
        if request_id is None:
            base.require(response.status == 202, "initialized notification rejected")
            return None
        message = json.loads(response.read(64 << 10))
    base.require(message.get("jsonrpc") == "2.0" and message.get("id") == request_id,
                 "MCP response identity mismatch")
    base.require("error" not in message, "MCP tool request failed")
    return message["result"]


def run(h, extended=False):
    h.build()
    h.start()
    h.setup_authority()
    target = str(h.workspace / "company-a/report.txt")
    mcp = ThreadingHTTPServer(("127.0.0.1", 0), MCPFixture)
    mcp.initialized, mcp.tool_calls, mcp.report_path = False, 0, target
    thread = threading.Thread(target=mcp.serve_forever, daemon=True)
    thread.start()
    try:
        endpoint = f"http://127.0.0.1:{mcp.server_port}/mcp"
        initialized = rpc(endpoint, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "siq-integration-fixture", "version": "1"}}, 1)
        base.require(initialized["protocolVersion"] == "2025-06-18", "protocol negotiation failed")
        rpc(endpoint, "notifications/initialized")
        result = rpc(endpoint, "tools/call", {"name": "lookup_report", "arguments": {}}, 2)
        base.require(mcp.tool_calls == 1 and not result["isError"], "MCP call not executed")
        intent = h.api("/v1/intents/int-native-fixture")
        for key in ("digest", "signature", "signing_schema"):
            intent.pop(key, None)
        intent.update(schema_version="intent/v3", intent_id="int-mcp-v3", provenance_constraints=[{
            "parameter_path": "/path", "allowed_source_types": ["USER"],
            "minimum_trust": "trusted", "required": True,
        }])
        h.api("/v1/intents", intent, expected=201)
        session = "mcp-provenance-session"
        h.api("/v1/intent-bindings", {"platform": "hermes", "session_id": session,
              "agent_id": base.AGENT, "intent_id": intent["intent_id"]}, expected=201)
        token = (h.state / "token").read_text().strip()
        identity = {"platform": "hermes", "session_id": session, "agent_id": base.AGENT}
        source_id = hashlib.sha256(canonical({"endpoint": endpoint, "server": initialized["serverInfo"],
                                           "tool": "lookup_report"})).hexdigest()
        report = h.api("/v1/provenance-reports", {**identity, "report_id": "mcp-call-1",
                       "source": {"type": "MCP", "source_id": source_id}, "content": result},
                       token=token, expected=201)
        selected = h.api("/v1/provenance-select", {**identity, "parent_id": report["provenance_id"],
                         "pointer": "/structuredContent/path", "content": result}, token=token, expected=201)
        request = {**identity, "tool": "read_file", "tool_call_id": "mcp-controlled-path",
                   "params": {"path": target}, "parameter_provenance": [{"parameter_path": "/path",
                   "provenance_refs": [selected["provenance_id"]]}]}
        denied = h.api("/v1/decide", request, token=token)
        base.require(denied["action"] == "deny" and denied["reason_code"] == "provenance_source_not_allowed",
                     "MCP controlled high-impact path")
        scope = {**identity, "task_id": intent["task_id"]}
        expires = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        h.api("/v1/provenance-issuers", {"issuer_id": "trusted-form", "local_key_ref": "local-state",
              "allowed_source_types": ["USER"], "max_trust_level": "authoritative",
              "scope": scope, "expires_at": expires}, expected=201)
        trusted = h.api("/v1/provenance-assertions", {"schema_version": "provenance-assertion/v1",
            "provenance_id": "trusted-path", "source": {"type": "USER", "source_id": "fixture-form",
            "trust": "authoritative"}, "scope": scope, "content_digest": hashlib.sha256(canonical(target)).hexdigest(),
            "parents": [], "derivation": "direct", "issued_at": intent["issued_at"],
            "expires_at": expires, "issuer": "trusted-form"}, expected=201)
        request["tool_call_id"] = "trusted-controlled-path"
        request["parameter_provenance"][0]["provenance_refs"] = [trusted["provenance_id"]]
        allowed = h.api("/v1/decide", request, token=token)
        base.require(allowed["action"] == "allow", "same value trusted provenance failed benign control")
        decisions = [("mcp-parameter", "attack", denied), ("mcp-parameter", "benign", allowed)]
        if extended:
            for pair, expected_reason in (("missing-provenance", "provenance_missing"),
                                          ("content-tamper", "provenance_content_mismatch"),
                                          ("cross-session", "provenance_not_found")):
                attack_request = copy.deepcopy(request)
                attack_request["tool_call_id"] = pair + "-attack"
                if pair == "missing-provenance":
                    attack_request.pop("parameter_provenance")
                elif pair == "content-tamper":
                    attack_request["params"]["path"] = target + ".substituted"
                else:
                    other_session = session + "-other"
                    h.api("/v1/intent-bindings", {"platform": "hermes", "session_id": other_session,
                          "agent_id": base.AGENT, "intent_id": intent["intent_id"]}, expected=201)
                    attack_request["session_id"] = other_session
                attacked = h.api("/v1/decide", attack_request, token=token)
                base.require(attacked["action"] == "deny" and attacked["reason_code"] == expected_reason,
                             pair + " did not fail closed")
                benign_request = copy.deepcopy(request)
                benign_request["tool_call_id"] = pair + "-benign"
                benign = h.api("/v1/decide", benign_request, token=token)
                base.require(benign["action"] == "allow", pair + " benign control rejected")
                decisions.extend(((pair, "attack", attacked), (pair, "benign", benign)))
            for pair in ("wrong-task", "revoked-binding"):
                other_session = session + "-" + pair
                other_intent = copy.deepcopy(intent)
                other_intent["intent_id"] = "int-" + pair
                if pair == "wrong-task":
                    other_intent["task_id"] += "-other"
                signed = h.api("/v1/intents", other_intent, expected=201)
                binding = h.api("/v1/intent-bindings", {"platform": "hermes", "session_id": other_session,
                                "agent_id": base.AGENT, "intent_id": other_intent["intent_id"]}, expected=201)
                other_scope = {**scope, "session_id": other_session}
                # For wrong-task, isolate task replay: sign for the current session but original task.
                issuer = "issuer-" + pair
                h.api("/v1/provenance-issuers", {"issuer_id": issuer, "local_key_ref": "local-state",
                      "allowed_source_types": ["USER"], "max_trust_level": "authoritative",
                      "scope": other_scope, "expires_at": expires}, expected=201)
                h.api("/v1/provenance-assertions", {"schema_version": "provenance-assertion/v1",
                      "provenance_id": pair + "-path", "source": {"type": "USER", "source_id": "fixture-form",
                      "trust": "authoritative"}, "scope": other_scope,
                      "content_digest": hashlib.sha256(canonical(target)).hexdigest(), "parents": [],
                      "derivation": "direct", "issued_at": intent["issued_at"], "expires_at": expires,
                      "issuer": issuer}, expected=201)
                attack_request = copy.deepcopy(request)
                attack_request.update(session_id=other_session, tool_call_id=pair + "-attack")
                attack_request["parameter_provenance"][0]["provenance_refs"] = [pair + "-path"]
                reason = "provenance_not_found"
                if pair == "revoked-binding":
                    before = copy.deepcopy(attack_request)
                    before["tool_call_id"] = pair + "-before-revoke"
                    base.require(h.api("/v1/decide", before, token=token)["action"] == "allow",
                                 "binding must allow before revocation")
                    h.api("/v1/intent-bindings/" + binding["binding_id"] + "/revoke",
                          {"expected_intent_digest": signed["digest"]})
                    reason = "intent_binding_revoked"
                attacked = h.api("/v1/decide", attack_request, token=token)
                base.require(attacked["action"] == "deny" and attacked["reason_code"] == reason,
                             pair + " attack accepted")
                benign_request = copy.deepcopy(request)
                benign_request["tool_call_id"] = pair + "-benign"
                benign = h.api("/v1/decide", benign_request, token=token)
                base.require(benign["action"] == "allow", "unrelated valid task rejected")
                decisions.extend(((pair, "attack", attacked), (pair, "benign", benign)))
            for pair in ("filesystem-hijack", "expired-provenance"):
                value = str(h.workspace / "company-b/report.txt") if pair == "filesystem-hijack" else target
                end = expires
                if pair == "expired-provenance":
                    end = (datetime.now(timezone.utc) + timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
                h.api("/v1/provenance-assertions", {"schema_version": "provenance-assertion/v1",
                      "provenance_id": pair + "-path", "source": {"type": "USER", "source_id": "fixture-form",
                      "trust": "authoritative"}, "scope": scope,
                      "content_digest": hashlib.sha256(canonical(value)).hexdigest(), "parents": [],
                      "derivation": "direct", "issued_at": intent["issued_at"], "expires_at": end,
                      "issuer": "trusted-form"}, expected=201)
                attack_request = copy.deepcopy(request)
                attack_request.update(tool_call_id=pair + "-attack", params={"path": value})
                attack_request["parameter_provenance"][0]["provenance_refs"] = [pair + "-path"]
                reason = "intent_resource_not_allowed"
                if pair == "expired-provenance":
                    before = copy.deepcopy(attack_request)
                    before["tool_call_id"] = pair + "-before-expiry"
                    base.require(h.api("/v1/decide", before, token=token)["action"] == "allow",
                                 "fresh provenance must allow")
                    time.sleep(3.1)
                    reason = "provenance_expired"
                attacked = h.api("/v1/decide", attack_request, token=token)
                base.require(attacked["action"] == "deny" and attacked["reason_code"] == reason,
                             pair + " boundary not enforced")
                benign_request = copy.deepcopy(request)
                benign_request["tool_call_id"] = pair + "-benign"
                benign = h.api("/v1/decide", benign_request, token=token)
                base.require(benign["action"] == "allow", pair + " benign rejected")
                decisions.extend(((pair, "attack", attacked), (pair, "benign", benign)))
        records = h.receipts()
        h.stop()
        verified = json.loads(h.command([str(h.binary), "verify"]))
        base.require(verified["verified"], "offline receipt chain verification failed")
        return {"schema_version": "mcp-provenance-fixture/v1", "passed": True,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "siq_commit": h.command(["git", "rev-parse", "HEAD"], cwd=ROOT).strip(),
                "binary_sha256": hashlib.sha256(h.binary.read_bytes()).hexdigest(),
                "receipt_count": len(records), "receipt_chain_verified": True,
                "decision_receipt_ids": [decision["receipt_id"] for _, _, decision in decisions],
                "decisions": [{"pair_id": pair, "kind": kind, "action": decision["action"],
                               "reason_code": decision["reason_code"], "receipt_id": decision["receipt_id"]}
                              for pair, kind, decision in decisions],
                "coverage": "component_fixture", "mcp_protocol": "2025-06-18", "mcp_tool_calls": mcp.tool_calls,
                "checks": {"initialized": True, "real_http_tool_result": True, "signed_report": True,
                           "deterministic_selection": True, "untrusted_path_denied": True,
                           "same_value_trusted_path_allowed": True},
                "source_identity_digest": source_id,
                "limitations": ["local fixture server", "JSON response transport only",
                                "no native platform integration", "no independent effect evidence"]}
    finally:
        mcp.shutdown()
        mcp.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="siq-mcp-provenance-") as tmp:
        h = base.Harness(Path(tmp), SimpleNamespace())
        try:
            report = run(h)
        finally:
            h.stop()
    report["script_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    raw = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(raw)
    print(raw, end="")


if __name__ == "__main__":
    main()
