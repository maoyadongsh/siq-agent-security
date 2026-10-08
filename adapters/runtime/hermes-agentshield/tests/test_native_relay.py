"""Real channel/HTTP relay checks; Authority and kernel guard are explicit fixtures."""

import concurrent.futures
import http.server
import json
import os
import threading

import pytest
from test_native_online import callbacks, channel, native, online, setup  # noqa: F401

CREDENTIAL = "ri-" + "d" * 32 + "." + "e" * 64


@pytest.fixture
def relay(setup):  # noqa: F811 - pytest fixture imported for registration
    _root, config, _value, subject, guard = setup
    received = []
    reply = {"status": 200, "raw": None, "action": "allow", "close_guard": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, self.headers["Authorization"], body))
            if self.path == "/v1/native-host/events":
                status, raw = 200, json.dumps({"schema_version": "native-host-published/v1", "accepted": True}).encode()
            else:
                status = reply["status"]
                raw = reply["raw"]
                if raw is None:
                    raw = json.dumps({"action": reply["action"], "receipt_id": "fixture-receipt", "irrelevant": "not-forwarded"}).encode()
                if reply["close_guard"]:
                    guard.close()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Location", "/should-not-follow")
            self.end_headers()
            self.wfile.write(raw)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    worker.start()
    publisher = online.Publisher(config, f"http://127.0.0.1:{server.server_port}", subject, guard)
    try:
        yield online.DecisionRelay(publisher, CREDENTIAL), reply, received, setup
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()


@pytest.mark.parametrize("action", ["allow", "deny", "hold"])
def test_same_channel_lifecycle_and_fixed_scoped_decision(relay, action):
    host_relay, reply, received, (root, _, config, subject, _) = relay
    reply["action"] = action
    effect = root / "relay-effect"
    with channel.ProcessPin(os.getpid(), os.getuid()) as pin, channel.HostChannel(root, pin, timeout=3) as host:
        client = channel.HermesChannel(host.path, timeout=3,
            server_credentials=(os.getpid(), os.getuid(), os.getgid()))
        mapped = callbacks.Callbacks.via_host(client)
        runtime = native.Runtime(subject["agent_id"], "online", mapped.observe, mapped.authorize, mapped.observe)

        def serve():
            for _ in range(5 if action == "allow" else 4):
                host.serve_once(host_relay.dispatch)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            waiter = pool.submit(serve)

            def execute():
                with runtime.task("relay-task", "native"), runtime.call("write_file", {"path": str(effect)}, "relay-task", "native", "call"):
                    effect.write_text("allowed handler")

            if action == "allow":
                execute()
            else:
                with pytest.raises(native.DispatchError):
                    execute()
            waiter.result(timeout=5)
    assert effect.exists() is (action == "allow")
    decisions = [r for r in received if r[0] == "/v1/decide"]
    assert len(decisions) == 1 and decisions[0][1] == "Bearer " + CREDENTIAL
    assert decisions[0][2]["runtime_task_id"] == "relay-task"
    assert all(r[1] == "Bearer " + config["credential"] for r in received if r[0] != "/v1/decide")


def event_for(subject):
    return {"schema_version": "native-decision-relay/v1", "request": {
        "platform": "hermes", "agent_id": subject["agent_id"], "session_id": subject["session_id"],
        "runtime_task_id": "actual-task", "tool": "read_file", "tool_call_id": "call", "params": {"path": "/synthetic"}}}


@pytest.mark.parametrize("change", [
    {"agent_id": "other"}, {"platform": "openclaw"}, {"session_id": "other"},
    {"runtime_task_id": ""}, {"tool_call_id": "x" * 257}, {"tool": "read\nfile"},
    {"runtime_task_id": True}, {"params": []}, {"credential": CREDENTIAL},
    {"endpoint": "http://example.invalid"}, {"params": {"body": "x" * 65536}},
])
def test_untrusted_relay_changes_never_reach_http(relay, change):
    host_relay, _, received, (_, _, _, subject, _) = relay
    event = event_for(subject)
    event["request"].update(change)
    assert host_relay.dispatch(event) == {"error": "native_host_unavailable"}
    assert received == []


@pytest.mark.parametrize("change", [
    {"status": 503}, {"status": 307}, {"raw": b"not-json"}, {"raw": b" " * 65537},
    {"raw": b'{"action":"allow","receipt_id":"r","params":{}}'},
    {"raw": b'{"action":"allow","receipt_id":""}'},
    {"raw": b'{"action":"allow","receipt_id":"r","action":"deny"}'},
    {"raw": b'{"action":"allow","receipt_id":NaN}'}, {"close_guard": True},
])
def test_relay_transport_or_guard_failure_never_returns_allow_or_retries(relay, change):
    host_relay, reply, received, (_, _, _, subject, _) = relay
    reply.update(change)
    assert host_relay.dispatch(event_for(subject)) == {"error": "native_host_unavailable"}
    assert len(received) == 1 and received[0][0] == "/v1/decide"


def test_relay_projects_only_real_decision_identifiers(relay):
    host_relay, _, _, (_, _, _, subject, _) = relay
    assert host_relay.dispatch(event_for(subject)) == {"action": "allow", "receipt_id": "fixture-receipt"}
    for credential in ("admin-credential", host_relay.publisher.config["credential"], "ri-invalid", ""):
        with pytest.raises(online.OnlineError):
            online.DecisionRelay(host_relay.publisher, credential)
