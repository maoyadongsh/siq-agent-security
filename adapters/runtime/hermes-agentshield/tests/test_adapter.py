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
from typing import ClassVar

import pytest

ADAPTER = Path(__file__).resolve().parents[1] / "__init__.py"


class _Fake(BaseHTTPRequestHandler):
    decision: ClassVar[dict] = {"action": "allow", "reason": "ok", "receipt_id": "rcp-1"}
    status = 200
    seen: ClassVar[list] = []

    def do_POST(self):
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


def test_correlation_is_bounded_and_conflict_safe(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    decision = {"action": "allow", "action_id": "act-1", "receipt_id": "rcp-1"}
    assert mod._remember_decision("s", "read_file", "c1", decision)
    assert not mod._remember_decision("s", "read_file", "c1", {**decision, "action_id": "act-2"})
    assert mod._decision_reference("s", "read_file", "c1") == {}
    assert mod._decision_reference("other", "read_file", "c1") == {}
    mod._CORRELATION_MAX = 1
    assert not mod._remember_decision("s", "read_file", "c2", decision)
    mod._CORRELATIONS[("s", "read_file", "c1")] = (0, "act-1", "rcp-1")
    assert mod._decision_reference("s", "read_file", "c1") == {}
    assert mod._remember_decision("s", "read_file", "c2", decision)


def test_hooks_forward_decision_identity(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.decision = {"action": "allow", "action_id": "act-1", "receipt_id": "rcp-1"}
    assert mod._pre_tool_call("read_file", {}, session_id="s", tool_call_id="c") is None
    mod._post_tool_call("read_file", {}, result="ok", session_id="s", tool_call_id="c")
    path, _, body = _Fake.seen[-1]
    assert path == "/v1/observe"
    assert body["action_id"] == "act-1" and body["decision_receipt_id"] == "rcp-1"


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
def test_authority_references_forwarded_without_claim_inference(server, mode):
    srv, token = server
    _Fake.decision = {"action": "allow", "receipt_id": "r"}
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    refs = [{"parameter_path": "/path", "provenance_refs": ["signed-reference"]}]
    args = {"path": "/work/report", "parameter_provenance": [{"trust": "authoritative"}]}
    assert mod._pre_tool_call("read_file", args, parameter_provenance=refs,
                              context_assertion_id="signed-context") is None
    body = _Fake.seen[-1][2]
    assert body["parameter_provenance"] == refs
    assert body["context_assertion_id"] == "signed-context"
    assert body["params"] == args
    assert "intent" not in body and "trust" not in body
    assert mod._pre_tool_call("read_file", args) is None
    assert "parameter_provenance" not in _Fake.seen[-1][2]
    assert "context_assertion_id" not in _Fake.seen[-1][2]


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
@pytest.mark.parametrize("status,decision", [(400, {}), (503, {}), (200, {"action": "invalid"}),
                                               (200, {"action": "deny", "reason": "provenance_not_found"})])
def test_reference_validation_failure_never_becomes_advisory_allow(server, mode, status, decision):
    srv, token = server
    _Fake.status, _Fake.decision = status, decision
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    out = mod._pre_tool_call("read_file", {"path": "/work/report"},
                             parameter_provenance=[{"parameter_path": "/path", "provenance_refs": ["missing"]}])
    assert out["action"] == "block"


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
@pytest.mark.parametrize("invalid", [object(), float("nan"), "x" * ((1 << 20) + 1)],
                         ids=["object", "nan", "over-budget"])
def test_unencodable_or_oversized_authority_reference_blocks_without_http(server, mode, invalid):
    srv, token = server
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    out = mod._pre_tool_call("read_file", {"path": "/work/report"}, context_assertion_id=invalid)
    assert out["action"] == "block"
    assert _Fake.seen == []


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
def test_cyclic_authority_reference_blocks_without_hook_exception(server, mode):
    srv, token = server
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    refs = []
    refs.append(refs)
    out = mod._pre_tool_call("read_file", {"path": "/work/report"}, parameter_provenance=refs)
    assert out["action"] == "block"
    assert _Fake.seen == []


def test_response_budget_is_enforced_before_authority_allow(server):
    srv, token = server
    mod = load("warn", f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.decision = {"action": "allow", "padding": "x" * (1 << 20)}
    out = mod._pre_tool_call("read_file", {"path": "/work/report"}, context_assertion_id="ctx")
    assert out["action"] == "block"


def test_request_budget_accepts_exact_limit_and_rejects_next_byte(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.decision = {"action": "allow"}
    size = (1 << 20) - len(json.dumps({"payload": ""}).encode())
    assert mod._post("/v1/decide", {"payload": "x" * size})["action"] == "allow"
    assert mod._post("/v1/decide", {"payload": "x" * (size + 1)}) is None
    assert len(_Fake.seen) == 1
