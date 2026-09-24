"""Managed instances require identity enrollment even in advisory modes."""

import hashlib
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from test_adapter import _Fake, load


def managed(mod, token):
    identity = "ri-" + "a" * 32
    agent = "hri-" + "b" * 32
    token.write_text(identity + "." + "c" * 64)
    token.chmod(0o600)
    mod._CFG.update(runtime_identity_id=identity, agent_id=agent, token_path=str(token))
    mod._TOKEN = None
    _Fake.enroll = {
        "schema_version": "local-runtime-session-enrolled/v1", "identity_id": identity,
        "platform": "hermes", "agent_id": agent, "session_id": "native-session",
        "binding_id": "bind-" + "d" * 64, "intent_id": "int-ri-" + "e" * 64,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    return identity


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
def test_managed_enrollment_precedes_decision_and_observation(server, mode):
    srv, token = server
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    _Fake.decision = {"action": "allow", "reason": "ok", "receipt_id": "r", "action_id": "act-1"}
    assert mod._pre_tool_call("read_file", {}, session_id="native-session", tool_call_id="call-1") is None
    mod._post_tool_call("read_file", {}, result="ok", session_id="native-session", tool_call_id="call-1")
    assert [row[0] for row in _Fake.seen] == [
        "/v1/runtime-sessions",
        "/v1/decide",
        "/v1/raw-task-content/native-captures",
        "/v1/observe",
        "/v1/raw-task-content/native-captures",
    ]
    assert all(row[1] == "Bearer " + token.read_text() for row in _Fake.seen)
    assert _Fake.seen[0][2] == {
        "schema_version": "local-runtime-session-enroll/v1", "session_id": "native-session",
    }
    assert "c" * 64 not in str([row[2] for row in _Fake.seen])


def test_openshell_session_namespace_is_opaque_and_bound_on_every_route(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    namespace = (
        "siq:openshell:pool:" + "1" * 24
        + ":run-001:siq_analysis"
    )
    expected = namespace + ":" + hashlib.sha256(b"native-session").hexdigest()
    mod._CFG["session_namespace"] = namespace
    _Fake.enroll["session_id"] = expected
    _Fake.decision = {
        "action": "allow", "reason": "ok", "receipt_id": "r", "action_id": "act-ns",
    }

    assert mod._pre_tool_call(
        "read_file", {}, session_id="native-session", tool_call_id="call-ns"
    ) is None
    mod._post_tool_call(
        "read_file", {}, result="ok", session_id="native-session", tool_call_id="call-ns"
    )

    assert _Fake.seen
    assert all(row[2].get("session_id") == expected for row in _Fake.seen)
    assert "native-session" not in json.dumps([row[2] for row in _Fake.seen])


@pytest.mark.parametrize(
    "namespace",
    ["unscoped", "siq:openshell:pool:" + "1" * 23 + ":run:siq_analysis"],
)
def test_managed_invalid_session_namespace_fails_closed_without_upstream(server, namespace):
    srv, token = server
    mod = load("warn", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    mod._CFG["session_namespace"] = namespace

    result = mod._pre_tool_call("read_file", {}, session_id="native-session")
    assert result["action"] == "block"
    assert _Fake.seen == []


def test_openshell_environment_supplies_only_scoped_runtime_identity(server, monkeypatch):
    srv, token = server
    identity = "ri-" + "a" * 32
    agent = "hri-" + "b" * 32
    namespace = "siq:openshell:pool:" + "1" * 24 + ":run-001:siq_analysis"
    authority_session = namespace + ":" + hashlib.sha256(b"native-session").hexdigest()
    token.write_text(identity + "." + "c" * 64)
    token.chmod(0o600)
    monkeypatch.setenv("SIQ_AGENT_SECURITY_RUNTIME_IDENTITY_ID", identity)
    monkeypatch.setenv("SIQ_AGENT_SECURITY_AGENT_ID", agent)
    monkeypatch.setenv("SIQ_AGENT_SECURITY_TOKEN_PATH", str(token))
    monkeypatch.setenv("SIQ_AGENT_SECURITY_SESSION_NAMESPACE", namespace)
    _Fake.enroll = {
        "schema_version": "local-runtime-session-enrolled/v1",
        "identity_id": identity,
        "platform": "hermes",
        "agent_id": agent,
        "session_id": authority_session,
        "binding_id": "bind-" + "d" * 64,
        "intent_id": "int-ri-" + "e" * 64,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    _Fake.decision = {
        "action": "allow", "reason": "ok", "receipt_id": "r", "action_id": "act-env",
    }

    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._CFG["runtime_identity_id"] == identity
    assert mod._pre_tool_call(
        "read_file", {}, session_id="native-session", tool_call_id="env-call"
    ) is None
    assert all(row[2]["session_id"] == authority_session for row in _Fake.seen)


def test_posix_runtime_token_must_remain_private_regular_file(server):
    if os.name == "nt":
        pytest.skip("POSIX mode contract")
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    token.chmod(0o644)
    mod._TOKEN = None
    assert mod._pre_tool_call("read_file", {}, session_id="native-session")["action"] == "block"
    assert _Fake.seen == []


def test_managed_native_raw_capture_is_scoped_flattened_and_best_effort(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    _Fake.decision = {"action": "allow", "reason": "ok", "receipt_id": "r", "action_id": "act-raw"}
    arguments = {
        "path": "/work/report.md",
        "api_key": "PRIVATE_API_KEY",
        "nested": {"authorization": "Bearer " + "A" * 32, "safe": "keep"},
    }
    assert mod._pre_tool_call(
        "read_file", arguments, session_id="native-session", tool_call_id="raw-call"
    ) is None
    capture = [row for row in _Fake.seen if row[0] == "/v1/raw-task-content/native-captures"][-1]
    assert capture[1] == "Bearer " + token.read_text()
    body = capture[2]
    assert set(body) == {"schema_version", "platform", "agent_id", "session_id", "kind", "fields"}
    assert body["kind"] == "parameters" and body["session_id"] == "native-session"
    fields = {field["path"]: field["value"] for field in body["fields"]}
    assert fields["/tool/arguments/path"] == '"/work/report.md"'
    assert fields["/tool/arguments/api_key"] == '"PRIVATE_API_KEY"'
    assert fields["/tool/arguments/nested/safe"] == '"keep"'
    assert "task_id" not in body and "grant_id" not in body and "permit" not in body

    _Fake.status = 503
    mod._post_tool_call(
        "read_file", arguments, result={"result": "kept", "token": "PRIVATE_TOKEN"},
        session_id="native-session", tool_call_id="raw-call",
    )
    assert _Fake.seen[-1][0] == "/v1/raw-task-content/native-captures"

    unmanaged = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.status = 200
    _Fake.seen = []
    _Fake.decision = {"action": "allow", "reason": "ok", "receipt_id": "r"}
    assert unmanaged._pre_tool_call("read_file", {}, session_id="legacy") is None
    unmanaged._post_tool_call("read_file", {}, result="ok", session_id="legacy")
    assert not any(row[0] == "/v1/raw-task-content/native-captures" for row in _Fake.seen)


def test_managed_blocked_post_result_is_not_captured(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    _Fake.decision = {"action": "deny", "reason": "blocked", "receipt_id": "r"}
    assert mod._pre_tool_call(
        "write_file", {"path": "/blocked"}, session_id="native-session", tool_call_id="blocked-call"
    )["action"] == "block"
    mod._post_tool_call(
        "write_file", {"path": "/blocked"}, result="siq-agent-security blocked",
        session_id="native-session", tool_call_id="blocked-call",
    )
    assert not any(row[0] == "/v1/raw-task-content/native-captures" for row in _Fake.seen)


@pytest.mark.parametrize("flow", ["duplicate_post", "duplicate_pre", "missing_reference"])
def test_native_output_requires_single_unused_allow_reference(server, flow):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    _Fake.decision = {"action": "allow", "reason": "ok", "receipt_id": "r"}
    if flow != "missing_reference":
        _Fake.decision["action_id"] = "act-1"
    kwargs = {"session_id": "native-session", "tool_call_id": "one-call"}
    assert mod._pre_tool_call("read_file", {}, **kwargs) is None
    if flow == "duplicate_pre":
        _Fake.decision = {"action": "deny", "reason": "denied", "receipt_id": "r2"}
        assert mod._pre_tool_call("read_file", {}, **kwargs)["action"] == "block"
    mod._post_tool_call("read_file", {}, result="first", **kwargs)
    mod._post_tool_call("read_file", {}, result="duplicate", **kwargs)
    outputs = [row for row in _Fake.seen if row[0] == "/v1/raw-task-content/native-captures" and row[2]["kind"] == "output"]
    assert len(outputs) == (1 if flow == "duplicate_post" else 0)


def test_native_raw_flattening_rejects_partial_or_unbounded_values(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._raw_content_fields("tool", "/tool/arguments", {str(i): i for i in range(1024)}) is None
    value = {}
    cursor = value
    for index in range(34):
        cursor[str(index)] = {}
        cursor = cursor[str(index)]
    assert mod._raw_content_fields("tool", "/tool/arguments", value) is None
    assert mod._raw_content_fields("tool", "/tool/arguments", {"bad\nkey": "value"}) is None


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
@pytest.mark.parametrize(
    "bad", ["agent", "identity", "session", "binding", "extra", "unavailable", "no_native_session"]
)
def test_managed_enrollment_failure_blocks_all_modes(server, mode, bad):
    srv, token = server
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    session = "native-session"
    if bad in ("agent", "identity", "session", "binding"):
        field = {"agent": "agent_id", "identity": "identity_id", "session": "session_id", "binding": "binding_id"}[bad]
        _Fake.enroll[field] = "wrong"
    elif bad == "extra":
        _Fake.enroll["unexpected"] = True
    elif bad == "unavailable":
        _Fake.status = 401
    else:
        session = ""
    result = mod._pre_tool_call("write_file", {}, session_id=session, task_id="not-native-session")
    assert result["action"] == "block"
    assert not any(row[0] == "/v1/decide" for row in _Fake.seen)
    pending = (token.parent / "pending/decisions.jsonl").read_text()
    assert '"outcome":"deny"' in pending and token.read_text() not in pending


@pytest.mark.parametrize("mode", ["warn", "audit_only"])
def test_managed_authority_loss_after_enrollment_cannot_fail_open(server, mode, monkeypatch):
    srv, token = server
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    original = mod._post
    monkeypatch.setattr(
        mod, "_post", lambda path, body, **kw: None if path == "/v1/decide" else original(path, body, **kw)
    )
    assert mod._pre_tool_call("read_file", {}, session_id="native-session")["action"] == "block"


def test_checkpoint_style_resume_revalidates_revoked_runtime_identity(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    _Fake.decision = {
        "action": "allow",
        "reason": "fixture",
        "receipt_id": "rcp-before-resume",
        "action_id": "act-before-resume",
    }
    assert (
        mod._pre_tool_call(
            "read_file",
            {"path": "/approved/checkpoint"},
            session_id="native-session",
            task_id="resume-task",
            tool_call_id="before-resume",
        )
        is None
    )
    decide_count = sum(path == "/v1/decide" for path, _, _ in _Fake.seen)

    # A restored conversation may reuse its native session id, but every tool
    # boundary must enroll against current authority again. Simulate revocation
    # after the checkpoint and before the next tool call.
    _Fake.status = 401
    result = mod._pre_tool_call(
        "read_file",
        {"path": "/approved/checkpoint"},
        session_id="native-session",
        task_id="resume-task",
        tool_call_id="after-resume",
    )

    assert result["action"] == "block"
    assert sum(path == "/v1/decide" for path, _, _ in _Fake.seen) == decide_count


def test_managed_config_locks_agent_and_corruption_blocks(server, tmp_path, monkeypatch):
    srv, token = server
    mod = load("warn", f"http://127.0.0.1:{srv.server_port}", token)
    managed(mod, token)
    monkeypatch.setattr(mod, "__file__", str(tmp_path / "__init__.py"))
    config = tmp_path / "config.json"
    config.write_text(json.dumps(mod._CFG))
    monkeypatch.setenv("SIQ_AGENT_SECURITY_AGENT_ID", "borrowed-agent")
    assert mod._load_config()["agent_id"] == "hri-" + "b" * 32
    for text in ["broken", "[]", "x" * 65537]:
        config.write_text(text)
        mod._CFG = mod._load_config()
        assert mod._pre_tool_call("read_file", {}, session_id="native-session")["action"] == "block"
    assert not _Fake.seen


def test_decision_credentials_never_follow_redirect_or_proxy(server, monkeypatch):
    srv, token = server
    seen = []

    class Target(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        do_POST = do_GET

        def log_message(self, *_):
            pass

    target = HTTPServer(("127.0.0.1", 0), Target)
    thread = threading.Thread(target=target.serve_forever, daemon=True)
    thread.start()

    class Redirect(Target):
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/destination")
            self.end_headers()

    redirect = HTTPServer(("127.0.0.1", 0), Redirect)
    redirect_thread = threading.Thread(target=redirect.serve_forever, daemon=True)
    redirect_thread.start()
    try:
        mod = load("block", f"http://127.0.0.1:{redirect.server_port}", token)
        assert mod._post("/v1/decide", {}) is None
        assert seen == []
        monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{target.server_port}")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("NO_PROXY", "")
        mod._CFG["endpoint"] = f"http://127.0.0.1:{srv.server_port}"
        _Fake.decision = {"action": "allow"}
        assert mod._post("/v1/decide", {}) == {"action": "allow"}
        assert seen == [] and len(_Fake.seen) == 1
    finally:
        redirect.shutdown()
        redirect.server_close()
        target.shutdown()
        target.server_close()
        redirect_thread.join(timeout=2)
        thread.join(timeout=2)


def test_localhost_credential_transport_is_pinned(server):
    srv, token = server
    mod = load("block", f"http://localhost:{srv.server_port}", token)
    assert mod._local_endpoint() == f"http://127.0.0.1:{srv.server_port}"
    _Fake.decision = {"action": "allow"}
    assert mod._post("/v1/decide", {}) == {"action": "allow"}
    for endpoint in ["http://localhost", "http://localhost:0", "http://localhost:65536", "http://user@localhost:80"]:
        mod._CFG["endpoint"] = endpoint
        assert mod._local_endpoint() is None


@pytest.mark.parametrize("endpoint,allowed", [
    ("http://host.openshell.internal:47611", True),
    ("http://host.openshell.internal:47710", True),
    ("http://host.openshell.internal:47711", False),
    ("http://host.openshell.internal:47610", False),
    ("http://host.openshell.internal:047611", False),
    ("http://host.openshell.internal:47611/", False),
    ("http://host.openshell.internal:47611?", False),
    ("http://host.openshell.internal:47611#x", False),
    ("http://user@host.openshell.internal:47611", False),
    ("https://host.openshell.internal:47611", False),
    ("http://other.internal:47611", False),
])
def test_openshell_transport_requires_exact_managed_endpoint(server, endpoint, allowed):
    _srv, token = server
    mod = load("block", endpoint, token)
    managed(mod, token)
    mod._CFG['session_namespace'] = 'siq:openshell:pool:' + '1' * 24 + ':run:siq_analysis'
    mod._CFG['openshell_proxy'] = 'http://10.200.0.1:3128'
    assert mod._local_endpoint() == (endpoint if allowed else None)


@pytest.mark.parametrize("patch", [
    {'session_namespace': ''}, {'session_namespace': 'unscoped'},
    {'runtime_identity_id': ''}, {'agent_id': 'default'}, {'_config_error': True},
    {'openshell_proxy': ''}, {'openshell_proxy': 'http://attacker.invalid:3128'},
])
def test_openshell_transport_rejects_missing_or_malformed_authority(server, patch):
    _srv, token = server
    mod = load("block", 'http://host.openshell.internal:47710', token)
    managed(mod, token)
    mod._CFG['session_namespace'] = 'siq:openshell:pool:' + '1' * 24 + ':run:siq_analysis'
    mod._CFG['openshell_proxy'] = 'http://10.200.0.1:3128'
    mod._CFG.update(patch)
    assert mod._local_endpoint() is None
    assert mod._pre_tool_call('read_file', {}, session_id='native-session')['action'] == 'block'
    assert _Fake.seen == []


def test_openshell_uses_only_explicit_policy_proxy_ignoring_environment(server, monkeypatch):
    import io
    _srv, token = server
    mod = load('block', 'http://host.openshell.internal:47710', token)
    managed(mod, token)
    mod._CFG.update(session_namespace='siq:openshell:pool:' + '1' * 24 + ':run:siq_analysis',
                    openshell_proxy='http://10.200.0.1:3128')
    monkeypatch.setenv('HTTP_PROXY', 'http://attacker.invalid:8080')
    monkeypatch.setenv('NO_PROXY', '*')
    seen = []
    class Response(io.BytesIO):
        status = 200
    class Opener:
        def open(self, request, **kwargs):
            seen.append(request)
            return Response(b'{"action":"allow"}')
    monkeypatch.setattr(mod.urllib.request, 'build_opener', lambda *handlers: Opener())
    assert mod._post('/v1/decide', {}) == {'action': 'allow'}
    assert seen[0].host == '10.200.0.1:3128'
    assert seen[0].selector == 'http://host.openshell.internal:47710/v1/decide'
    assert seen[0].origin_req_host == 'host.openshell.internal'
