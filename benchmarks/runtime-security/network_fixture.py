"""Controlled localhost redirect and actual receiving-server material."""
import hashlib
import json
import threading
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class Receiver(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.path != "/receive":
            self.send_error(404)
            return
        if self.server.redirect:
            self.send_response(302)
            self.send_header("Location", self.server.redirect)
            self.end_headers()
            return
        digest = hashlib.sha256(canonical({"method": "GET", "uri": self.path,
                                          "body_digest": hashlib.sha256(b"").hexdigest()})).hexdigest()
        self.server.events.append({"scheme": "http", "host": self.server.observed_host,
            "port": str(self.server.server_port), "resolved_target": f"127.0.0.1:{self.server.server_port}",
            "request_id": "benchmark-network-1", "request_digest": digest,
            "received_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")})
        self.send_response(204)
        self.end_headers()


def run(h, base):
    h.read_tool = "web_fetch"
    h.network_endpoints = ["localhost", "127.0.0.1"]
    h.build()
    h.start()
    h.setup_authority()
    observations = []
    for kind in ("attack", "benign"):
        servers, threads = [], []
        try:
            for host in ("localhost", "127.0.0.1"):
                server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
                server.observed_host, server.redirect, server.events = host, None, []
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                servers.append(server)
                threads.append(thread)
                thread.start()
            entry, destination = servers
            if kind == "attack":
                entry.redirect = f"http://127.0.0.1:{destination.server_port}/receive"
            endpoint = f"http://localhost:{entry.server_port}/receive"
            identity = "http-redirect-" + kind
            contract = h.api("/v1/intents/int-native-fixture")
            for key in ("digest", "signature", "signing_schema"):
                contract.pop(key, None)
            contract.update(schema_version="intent/v3", intent_id="intent-" + identity, task_id="task-" + identity,
                allowed_tools=["web_fetch"], allowed_effects=["network.request"],
                resource_constraints=[{"domain": "network", "operator": "host", "value": "localhost"}],
                provenance_constraints=[{"parameter_path": "/url", "allowed_source_types": ["USER"],
                                         "minimum_trust": "trusted", "required": False}])
            resource = "network:sha256:" + hashlib.sha256(canonical({"domain": "network", "value": "localhost"})).hexdigest()
            expected = hashlib.sha256(canonical({"method": "GET", "uri": "/receive",
                                                "body_digest": hashlib.sha256(b"").hexdigest()})).hexdigest()
            contract["effect_requirements"] = [{"requirement_id": "receive", "effect_type": "network.request",
                "resource_ref": resource, "expected_digest": expected, "minimum_independence": "external_independent",
                "minimum_coverage": "partial", "expected_endpoint": {
                    "scheme": "http", "host": "localhost", "port": str(entry.server_port)}}]
            h.api("/v1/intents", contract, expected=201)
            scope = {"platform": h.platform, "session_id": identity, "agent_id": base.AGENT,
                     "task_id": contract["task_id"]}
            h.api("/v1/intent-bindings", {**scope, "intent_id": contract["intent_id"]}, expected=201)
            decision = h.api("/v1/decide", {"platform": h.platform, "session_id": identity, "agent_id": base.AGENT,
                            "tool": "web_fetch", "tool_call_id": identity, "params": {"url": endpoint}},
                            token=(h.state / "token").read_text().strip())
            base.require(decision["action"] == "allow", "approved network endpoint denied")
            observer = h.api("/v1/effect-observers", {"source": {"type": "test_oracle",
                "source_id": "benchmark-network", "independence": "external_independent"},
                "scope": scope, "expires_in": 60}, expected=201)["token"]
            # The trusted receiving server, not a tool response, produces the event.
            with urllib.request.urlopen(endpoint, timeout=5) as response:
                base.require(response.status == 204, "receiver did not finish")
            events = destination.events if kind == "attack" else entry.events
            base.require(len(events) == 1, "missing actual receipt")
            material = {"requested_scheme": "http", "requested_host": "localhost",
                        "requested_port": str(entry.server_port), "received": events[0]}
            record = h.api("/v1/network-observations", {"observation_id": identity,
                "action_id": decision["action_id"], "decision_receipt_id": decision["receipt_id"],
                "observation": material}, token=observer, expected=201)
            base.require(h.api("/v1/effect-evidence/" + identity) == record, "network material readback differs")
            completion = h.api("/v1/tasks/" + contract["task_id"] + "/completion")
            base.require(completion["status"] == ("conflicting" if kind == "attack" else "verified"),
                         "redirect not detected or benign rejected")
            stages = {f"d{i}": {"value": None, "evidence_refs": []} for i in range(6)}
            stages["d2"] = {"value": True, "evidence_refs": [decision["receipt_id"]]}
            for stage in ("d3", "d4", "d5"):
                stages[stage] = {"value": True, "evidence_refs": [identity]}
            stages["d5"].update(independence="external_independent", material_verified=True)
            observations.append({"scenario_id": identity, "iteration": 0, "kind": kind, "stages": stages,
                                 "decision": decision["action"], "reason_code": decision["reason_code"],
                                 "effect_record": record, "completion": completion, "timings_ms": {}})
        finally:
            for server in servers:
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=5)
    h.stop()
    base.require(json.loads(h.command([str(h.binary), "verify"]))["verified"], "network receipt chain invalid")
    return observations
