"""Self-check launch capabilities cannot become general decision authority."""

import pytest
from test_adapter import _Fake, load
from test_adapter import server as server


def configure(monkeypatch, mod):
    monkeypatch.setenv("SIQ_RUNTIME_CHECK_ID", "rc-" + "a" * 32)
    monkeypatch.setenv("SIQ_RUNTIME_CHECK_INSTANCE", "hi-" + "b" * 32)
    monkeypatch.setenv("SIQ_RUNTIME_CHECK_TOKEN", "c" * 64)
    mod._CFG["agent_id"] = "rca-" + "a" * 32
    _Fake.attach = {
        "schema_version": "local-runtime-check-attached/v1",
        "check_id": "rc-" + "a" * 32,
        "session_id": "host-generated",
        "attached": True,
    }


def test_attach_precedes_normal_decision_with_separate_credential(server, monkeypatch):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    configure(monkeypatch, mod)
    _Fake.decision = {"action": "deny", "reason": "outside intent", "receipt_id": "r"}
    out = mod._pre_tool_call("write_file", {}, session_id="host-generated")
    assert out["action"] == "block"
    assert [r[0] for r in _Fake.seen] == ["/v1/runtime-checks/attach", "/v1/decide"]
    assert _Fake.seen[0][1] == "Bearer " + "c" * 64
    assert _Fake.seen[1][1] == "Bearer " + "c" * 64
    assert "c" * 64 not in str(_Fake.seen[1][2])
    assert _Fake.seen[0][2]["session_id"] == "host-generated"


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
@pytest.mark.parametrize("bad", ["missing", "wrong_session", "numeric_true", "unknown_field", "unavailable"])
def test_unverified_check_attach_blocks_before_decision(server, monkeypatch, mode, bad):
    srv, token = server
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    configure(monkeypatch, mod)
    if bad == "missing":
        monkeypatch.delenv("SIQ_RUNTIME_CHECK_TOKEN")
    elif bad == "wrong_session":
        _Fake.attach["session_id"] = "other"
    elif bad == "numeric_true":
        _Fake.attach["attached"] = 1
    elif bad == "unknown_field":
        _Fake.attach["token"] = "unexpected"
    else:
        _Fake.status = 503
    out = mod._pre_tool_call("read_file", {}, session_id="host-generated")
    assert out["action"] == "block" and "could not be verified" in out["message"]
    assert not any(row[0] == "/v1/decide" for row in _Fake.seen)
    assert not (token.parent / "pending" / "decisions.jsonl").exists()


def test_check_cannot_bind_fallback_task_or_remote_endpoint(server, monkeypatch):
    srv, token = server
    mod = load("warn", f"http://127.0.0.1:{srv.server_port}", token)
    configure(monkeypatch, mod)
    assert mod._pre_tool_call("read_file", {}, task_id="not-session")["action"] == "block"
    for endpoint in ["https://example.invalid", "http://user@127.0.0.1", "http://127.0.0.1/path"]:
        mod._CFG["endpoint"] = endpoint
        assert mod._pre_tool_call("read_file", {}, session_id="host-generated")["action"] == "block"
    assert not _Fake.seen


def test_check_redirect_is_never_followed(server, monkeypatch):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._NoCheckRedirect().redirect_request(None, None, 307, "", {}, "http://other") is None
