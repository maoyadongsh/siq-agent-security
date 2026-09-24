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
    attach: ClassVar[dict | None] = None
    enroll: ClassVar[dict | None] = None
    responses: ClassVar[dict[str, dict]] = {}
    raw_capture: ClassVar[dict] = {
        "schema_version": "local-raw-task-content-capture-result/v1",
        "record_id": "raw-" + "a" * 32,
        "task_ref": "sha256:" + "b" * 64,
        "kind": "output",
        "created_at": "2026-09-13T15:00:00Z",
        "expires_at": "2026-09-13T16:00:00Z",
        "plaintext_sha256": "c" * 64,
        "plaintext_bytes": 64,
        "omitted_secret_count": 0,
    }

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        _Fake.seen.append((self.path, self.headers.get("Authorization"), body))
        created = self.path in ("/v1/raw-task-content/native-captures", "/v1/hold-executions/reserve")
        status = 201 if created and _Fake.status == 200 else _Fake.status
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        value = _Fake.responses.get(self.path)
        if value is None:
            value = _Fake.attach if self.path == "/v1/runtime-checks/attach" else _Fake.decision
        if self.path == "/v1/runtime-sessions":
            value = _Fake.enroll
        elif self.path == "/v1/raw-task-content/native-captures":
            value = _Fake.raw_capture
        self.wfile.write(json.dumps(value).encode())

    def log_message(self, *a):  # silence
        pass


@pytest.fixture()
def server(tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Fake)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    token = tmp_path / "token"
    token.write_text("t" * 64)
    token.chmod(0o600)
    _Fake.seen = []
    _Fake.status = 200
    _Fake.decision = {"action": "allow", "reason": "ok", "receipt_id": "rcp-1"}
    _Fake.attach = None
    _Fake.enroll = None
    _Fake.responses = {}
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


def test_native_task_is_separate_from_trusted_intent_task(server, monkeypatch):
    srv, token = server
    check_id = "rc-" + "a" * 32
    instance_id = "hi-" + "b" * 32
    credential = "c" * 64
    monkeypatch.setenv("SIQ_RUNTIME_CHECK_ID", check_id)
    monkeypatch.setenv("SIQ_RUNTIME_CHECK_INSTANCE", instance_id)
    monkeypatch.setenv("SIQ_RUNTIME_CHECK_TOKEN", credential)
    monkeypatch.setenv("AGENTSHIELD_AGENT_ID", "rca-" + "a" * 32)
    _Fake.attach = {
        "schema_version": "local-runtime-check-attached/v1",
        "check_id": check_id,
        "session_id": "native-session",
        "attached": True,
    }
    _Fake.decision = {"action": "allow", "reason": "ok", "receipt_id": "rcp-1"}
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._pre_tool_call(
        "read_file", {"path": "/tmp/a"}, task_id="hermes-random-turn",
        session_id="native-session", tool_call_id="tc-runtime-check",
    ) is None
    decide = next(body for path, _, body in _Fake.seen if path == "/v1/decide")
    assert decide["task_id"] == ""
    assert decide["runtime_task_id"] == "hermes-random-turn"

    for name in ("SIQ_RUNTIME_CHECK_ID", "SIQ_RUNTIME_CHECK_INSTANCE", "SIQ_RUNTIME_CHECK_TOKEN"):
        monkeypatch.delenv(name)
    _Fake.seen = []
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    assert mod._pre_tool_call(
        "read_file", {"path": "/tmp/a"}, task_id="managed-task",
        session_id="managed-session", tool_call_id="tc-managed",
    ) is None
    decide = next(body for path, _, body in _Fake.seen if path == "/v1/decide")
    assert decide["task_id"] == ""
    assert decide["runtime_task_id"] == "managed-task"


@pytest.mark.parametrize(
    "decision,expect",
    [
        ({"action": "deny", "reason": "not granted", "receipt_id": "r"}, "denied"),
        ({"action": "hold", "reason": "approval", "receipt_id": "r", "action_id": "a"}, "Approve in the console"),
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


def test_approved_hold_retry_is_reserved_once_before_execution(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.decision = {"action": "hold", "reason": "approval", "action_id": "act-hold",
                      "receipt_id": "rcp-hold", "task_id": "trusted-task",
                      "runtime_task_id": "task-1"}
    args = {"command": "printf once"}
    blocked = mod._pre_tool_call("exec", args, task_id="task-1", session_id="s1", tool_call_id="original")
    assert blocked["action"] == "block" and "Approve" in blocked["message"]

    _Fake.responses["/v1/hold-status"] = {"schema_version": "hold-status/v1", "status": "pending"}
    pending = mod._pre_tool_call("exec", args, task_id="task-1", session_id="s1", tool_call_id="retry-1")
    assert pending["action"] == "block" and "pending" in pending["message"]

    _Fake.responses["/v1/hold-status"] = {"schema_version": "hold-status/v1", "status": "approved"}
    _Fake.responses["/v1/hold-executions/reserve"] = {
        "schema_version": "hold-execution-status/v1", "status": "reserved",
        "action_id": "act-hold", "decision_receipt_id": "rcp-hold",
        "reservation_receipt_id": "rcp-hold-exec", "expires_at": "2026-09-14T18:00:00Z",
        "reason_code": "hold_execution_reserved",
    }
    assert mod._pre_tool_call("exec", args, task_id="task-1", session_id="s1", tool_call_id="retry-2") is None
    reserve = [body for path, _, body in _Fake.seen if path == "/v1/hold-executions/reserve"]
    assert len(reserve) == 1
    assert reserve[0]["original_tool_call_id"] == "original"
    assert reserve[0]["retry_tool_call_id"] == "retry-2"
    assert reserve[0]["task_id"] == "trusted-task" and reserve[0]["runtime_task_id"] == "task-1"
    assert reserve[0]["params"] == args

    mod._post_tool_call("exec", args, result="done", task_id="task-1", session_id="s1",
                        tool_call_id="retry-2")
    observe = [body for path, _, body in _Fake.seen if path == "/v1/observe"][-1]
    assert observe["action_id"] == "act-hold"
    assert observe["decision_receipt_id"] == "rcp-hold-exec"


def test_controlled_business_mcp_retry_binds_tool_task_and_exact_digests(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    tool = "mcp__siq_business__research_publish_report"
    args = {
        "task_id": "bu01-task-001",
        "request_sha256": "a" * 64,
        "approval_sha256": "b" * 64,
    }
    _Fake.decision = {
        "action": "hold",
        "reason": "approval",
        "action_id": "act-bu01",
        "receipt_id": "rcp-bu01",
        "task_id": "trusted-bu01-task",
        "runtime_task_id": "bu01-task-001",
    }
    blocked = mod._pre_tool_call(
        tool,
        args,
        task_id="bu01-task-001",
        session_id="bu01-session",
        tool_call_id="bu01-original",
    )
    assert blocked["action"] == "block"

    _Fake.responses["/v1/hold-status"] = {
        "schema_version": "hold-status/v1",
        "status": "approved",
    }
    _Fake.responses["/v1/hold-executions/reserve"] = {
        "schema_version": "hold-execution-status/v1",
        "status": "reserved",
        "action_id": "act-bu01",
        "decision_receipt_id": "rcp-bu01",
        "reservation_receipt_id": "rcp-bu01-exec",
        "expires_at": "2026-09-22T00:00:00Z",
        "reason_code": "hold_execution_reserved",
    }

    changed = mod._pre_tool_call(
        tool,
        {**args, "request_sha256": "c" * 64},
        task_id="bu01-task-001",
        session_id="bu01-session",
        tool_call_id="bu01-changed",
    )
    assert changed["action"] == "block"
    assert not any(path == "/v1/hold-executions/reserve" for path, _, _ in _Fake.seen)

    assert (
        mod._pre_tool_call(
            tool,
            args,
            task_id="bu01-task-001",
            session_id="bu01-session",
            tool_call_id="bu01-approved-retry",
        )
        is None
    )
    reserve = [body for path, _, body in _Fake.seen if path == "/v1/hold-executions/reserve"]
    assert len(reserve) == 1
    assert reserve[0]["tool"] == tool
    assert reserve[0]["runtime_task_id"] == "bu01-task-001"
    assert reserve[0]["params"] == args


@pytest.mark.parametrize(
    "retry_args,retry_task,retry_session",
    [
        ({"command": "printf changed"}, "task-1", "s1"),
        ({"command": "printf approved"}, "task-2", "s1"),
        ({"command": "printf approved"}, "task-1", "s2"),
    ],
)
def test_approved_hold_cannot_authorize_changed_params_task_or_session(
    server, retry_args, retry_task, retry_session
):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.decision = {
        "action": "hold",
        "reason": "approval",
        "action_id": "act-bound",
        "receipt_id": "rcp-bound",
        "task_id": "trusted-task",
        "runtime_task_id": "task-1",
    }
    approved_args = {"command": "printf approved"}
    assert mod._pre_tool_call(
        "exec",
        approved_args,
        task_id="task-1",
        session_id="s1",
        tool_call_id="original",
    )["action"] == "block"

    _Fake.responses["/v1/hold-status"] = {
        "schema_version": "hold-status/v1",
        "status": "approved",
    }
    result = mod._pre_tool_call(
        "exec",
        retry_args,
        task_id=retry_task,
        session_id=retry_session,
        tool_call_id="changed-retry",
    )

    assert result["action"] == "block"
    assert not any(path == "/v1/hold-executions/reserve" for path, _, _ in _Fake.seen)


def test_lost_reservation_response_never_allows_blind_retry(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.decision = {"action": "hold", "reason": "approval", "action_id": "act-lost",
                      "receipt_id": "rcp-lost"}
    args = {"command": "printf maybe"}
    assert mod._pre_tool_call("exec", args, task_id="task-1", session_id="s1",
                              tool_call_id="original")["action"] == "block"
    _Fake.responses["/v1/hold-status"] = {"status": "approved"}
    _Fake.responses["/v1/hold-executions/reserve"] = {"status": "malformed"}
    failed = mod._pre_tool_call("exec", args, task_id="task-1", session_id="s1", tool_call_id="retry")
    assert failed["action"] == "block" and "fail-closed" in failed["message"]
    # The local hint was consumed before the request. A later invocation starts
    # a new hold; it cannot reuse the potentially durable reservation.
    again = mod._pre_tool_call("exec", args, task_id="task-1", session_id="s1", tool_call_id="retry-2")
    assert again["action"] == "block"
    assert len([path for path, _, _ in _Fake.seen if path == "/v1/hold-executions/reserve"]) == 1


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


def test_configured_mcp_result_capture_uses_exact_tool_and_low_trust(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    mod._CFG["mcp_sources"] = {"mcp__a__lookup": "https://fixture.invalid/mcp"}
    _Fake.status, _Fake.decision = 200, {"action": "allow", "reason": "ok", "receipt_id": "r1", "action_id": "a1"}
    assert mod._pre_tool_call("mcp__a__lookup", session_id="s1", tool_call_id="c1") is None
    _Fake.status, _Fake.decision = 201, {"provenance_id": "rep-fixture"}
    result = {"path": "/work/report", "source": {"type": "USER", "trust": "authoritative"}}
    mod._post_tool_call("mcp__a__lookup", result=result, session_id="s1", tool_call_id="c1")
    reports = [body for path, _, body in _Fake.seen if path == "/v1/provenance-reports"]
    assert len(reports) == 1
    assert reports[0]["source"]["type"] == "MCP" and reports[0]["source"]["trust"] == "untrusted"
    assert "https://fixture.invalid/mcp" not in json.dumps(reports[0])
    assert reports[0]["content"] == result
    assert mod.provenance_reference("s1", "mcp__a__lookup", "c1") == "rep-fixture"
    assert mod.provenance_reference("other-session", "mcp__a__lookup", "c1") is None
    mod._post_tool_call("mcp__a__lookup_unregistered", result=result, session_id="s1", tool_call_id="c2")
    assert len([path for path, _, _ in _Fake.seen if path == "/v1/provenance-reports"]) == 1


def test_mcp_capture_failure_and_capacity_do_not_create_or_replace_refs(server):
    srv, token = server
    mod = load("block", f"http://127.0.0.1:{srv.server_port}", token)
    mod._CFG["mcp_sources"] = {"mcp__a__lookup": "fixture-server"}
    _Fake.status, _Fake.decision = 201, {"provenance_id": "rep-original"}
    mod._capture_mcp_result("s1", "mcp__a__lookup", "c1", "original")
    mod._CORRELATION_MAX = 1
    mod._capture_mcp_result("s1", "mcp__a__lookup", "c2", "another")
    assert mod.provenance_reference("s1", "mcp__a__lookup", "c1") == "rep-original"
    assert mod.provenance_reference("s1", "mcp__a__lookup", "c2") is None
    _Fake.status = 409
    mod._capture_mcp_result("s1", "mcp__a__lookup", "c1", "changed")
    assert mod.provenance_reference("s1", "mcp__a__lookup", "c1") is None
    count = len(_Fake.seen)
    mod._capture_mcp_result("s1", "mcp__a__lookup", "c3", "x" * (64 * 1024))
    mod._capture_mcp_result("s1", "mcp__a__lookup", "", "no stable call")
    assert len(_Fake.seen) == count


@pytest.mark.parametrize("mode", ["block", "warn", "audit_only"])
@pytest.mark.parametrize("failure", ["conflict", "capacity"])
@pytest.mark.parametrize("reference", ["context", "provenance"])
def test_authority_correlation_failure_blocks(server, mode, failure, reference):
    srv, token = server
    mod = load(mode, f"http://127.0.0.1:{srv.server_port}", token)
    _Fake.decision = {"action": "allow", "action_id": "act-1", "receipt_id": "rcp-1"}
    mod._CORRELATION_MAX = 1
    refs = ({"context_assertion_id": "ctx-1"} if reference == "context" else
            {"parameter_provenance": [{"parameter_path": "/path", "provenance_refs": ["p-1"]}]})
    assert mod._pre_tool_call("read_file", {}, session_id="s", tool_call_id="c1", **refs) is None
    call_id = "c1" if failure == "conflict" else "c2"
    result = mod._pre_tool_call("read_file", {}, session_id="s", tool_call_id=call_id, **refs)
    assert result is not None and result["action"] == "block"
    assert mod._decision_reference("s", "read_file", call_id) == {}
