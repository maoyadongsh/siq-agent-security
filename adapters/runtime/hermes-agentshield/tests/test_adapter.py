"""Hermes adapter tests: hook → HTTP mapping and the fail-closed table.

stdlib only. A fake decision service stands in for `agentshield serve`; the
real end-to-end run against the Go binary is documented in README.md.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ADAPTER = Path(__file__).resolve().parents[1] / "__init__.py"


class _Fake(BaseHTTPRequestHandler):
    decision: dict = {"action": "allow", "reason": "ok", "receipt_id": "rcp-1"}
    status = 200
    seen: list = []

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Fake.seen.append((self.path, self.headers.get("Authorization"), body))
        self.send_response(_Fake.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(_Fake.decision).encode())

    def log_message(self, *a):  # silence
        pass


@pytest.fixture()
def server(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    token = tmp_path / "token"
    token.write_text("t" * 64)
    _Fake.seen = []
    _Fake.status = 200
    yield srv, token
    srv.shutdown()


def load(mode: str, endpoint: str, token_path: Path):
    os.environ["AGENTSHIELD_ENDPOINT"] = endpoint
    os.environ["AGENTSHIELD_MODE"] = mode
    os.environ["AGENTSHIELD_STATE_DIR"] = str(token_path.parent)
    spec = importlib.util.spec_from_file_location("agentshield_hermes_adapter", ADAPTER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.pop("agentshield_hermes_adapter", None)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_allow_returns_none_and_sends_bearer(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._pre_tool_call("read_file", {"path": "/tmp/a"}, session_id="s1", tool_call_id="tc") is None
    path, auth, body = _Fake.seen[0]
    assert path == "/v1/decide" and auth == "Bearer " + "t" * 64
    assert body["tool"] == "read_file" and body["platform"] == "hermes" and body["session_id"] == "s1"


@pytest.mark.parametrize(
    "decision,expect",
    [
        ({"action": "deny", "reason": "not granted", "receipt_id": "r"}, "denied"),
        ({"action": "hold", "reason": "approval", "receipt_id": "r"}, "Approve in the console"),
        ({"action": "redact", "reason": "x", "receipt_id": "r"}, "secret literal"),
    ],
)
def test_non_allow_actions_block(server, decision, expect):
    srv, token = server
    _Fake.decision = decision
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    out = mod._pre_tool_call("exec", {"command": "ls"})
    assert out["action"] == "block" and expect in out["message"]


def test_fail_closed_when_service_down_in_block_mode(tmp_path):
    token = tmp_path / "token"
    token.write_text("t" * 64)
    mod = load("block", "http://127.0.0.1:9", token)  # nothing listens
    out = mod._pre_tool_call("exec", {"command": "ls"})
    assert out["action"] == "block" and "fail-closed" in out["message"]
    pending = (tmp_path / "pending" / "decisions.jsonl").read_text(encoding="utf-8")
    assert '"schema":"pending_decision/v1"' in pending or '"schema": "pending_decision/v1"' in pending
    assert '"signed":false' in pending or '"signed": false' in pending
    assert "decision service unavailable" in pending


def test_fail_open_when_service_down_in_audit_mode(tmp_path, capsys):
    token = tmp_path / "token"
    token.write_text("t" * 64)
    mod = load("audit_only", "http://127.0.0.1:9", token)
    assert mod._pre_tool_call("exec", {"command": "ls"}) is None
    assert "unavailable" in capsys.readouterr().err
    pending = (tmp_path / "pending" / "decisions.jsonl").read_text(encoding="utf-8")
    assert '"outcome":"allow"' in pending or '"outcome": "allow"' in pending


def test_warn_mode_allows_when_service_down(tmp_path, capsys):
    token = tmp_path / "token"
    token.write_text("t" * 64)
    mod = load("warn", "http://127.0.0.1:9", token)
    assert mod._pre_tool_call("exec", {"command": "ls"}) is None
    assert "warn" in capsys.readouterr().err


def test_401_and_malformed_are_fail_closed(server):
    srv, token = server
    _Fake.status = 401
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._pre_tool_call("exec", {"command": "ls"})["action"] == "block"
    _Fake.status = 200
    _Fake.decision = {"action": "maybe"}
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._pre_tool_call("exec", {"command": "ls"})["action"] == "block"


def test_missing_token_is_fail_closed(tmp_path):
    mod = load("block", "http://127.0.0.1:9", tmp_path / "missing-token")
    assert mod._pre_tool_call("exec", {})["action"] == "block"


def test_post_tool_call_observes_and_truncates(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    mod._post_tool_call("web_fetch", {"url": "u"}, result="x" * (70 * 1024), session_id="s")
    path, _, body = _Fake.seen[-1]
    assert path == "/v1/observe" and len(body["result"]) == 64 * 1024 and body["tool"] == "web_fetch"


def test_register_wires_both_hooks(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    calls = []

    class Ctx:
        def register_hook(self, name, cb):
            calls.append(name)

    mod.register(Ctx())
    assert calls == ["pre_tool_call", "post_tool_call"]
