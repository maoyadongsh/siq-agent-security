import asyncio
import json

import anyio
import httpx
import pytest
from services.hermes_client import StreamEvent

from services import (
    agent_chat_runtime as runtime,
    agent_runtime_sessions,
    agent_runtime_streaming,
    hermes_client,
    openshell_pool_recovery,
)


class _Request:
    def __init__(self, disconnected: bool = False):
        self.disconnected = disconnected

    async def is_disconnected(self) -> bool:
        return self.disconnected


async def _collect_events(profile: str, session_id: str, *, offset: int = 0) -> list[dict[str, str]]:
    events = []
    async for event in runtime.stream_active_run_events(
        _Request(),
        profile=profile,
        session_id=session_id,
        offset=offset,
    ):
        events.append(event)
    return events


async def _collect_chat_stream_events(
    profile: str,
    session_id: str,
) -> list[dict[str, str]]:
    events = []
    async for event in runtime.stream_chat_reply(
        "join active run",
        _Request(),
        object(),
        profile=profile,
        session_id=session_id,
        history_limit=1,
    ):
        events.append(event)
    return events


async def _collect_active_events_limit(profile: str, session_id: str, limit: int) -> list[dict[str, str]]:
    events = []
    stream = runtime.stream_active_run_events(
        _Request(),
        profile=profile,
        session_id=session_id,
    )
    try:
        async for event in stream:
            events.append(event)
            if len(events) >= limit:
                break
    finally:
        await stream.aclose()
    return events


def _event_payload(event: dict[str, str]) -> dict:
    return json.loads(event["data"])


def test_active_run_key_uses_canonical_profile_aliases():
    state = runtime.ActiveRunState(
        profile="siq_assistant",
        session_id="alias-key-session",
        run_id="run-alias-key",
    )
    key = runtime._active_key("assistant", state.session_id)
    runtime.ACTIVE_RUNS[key] = state
    try:
        assert key == ("siq_assistant", state.session_id)
        assert runtime.has_active_run("siq_assistant", state.session_id) is True
        assert runtime.has_active_run("assistant", state.session_id) is True
        snapshot = runtime.get_active_run_snapshot("assistant", state.session_id)
    finally:
        runtime.ACTIVE_RUNS.pop(key, None)

    assert snapshot["running"] is True
    assert snapshot["run_id"] == "run-alias-key"


def test_streaming_owner_state_is_shared_by_public_facades():
    assert runtime.ACTIVE_RUNS is agent_runtime_streaming.ACTIVE_RUNS
    assert agent_runtime_sessions.ACTIVE_RUNS is agent_runtime_streaming.ACTIVE_RUNS
    assert runtime.ActiveRunState is agent_runtime_streaming.ActiveRunState
    assert runtime._append_state_event is agent_runtime_streaming._append_state_event
    assert runtime._append_completed_active_run is agent_runtime_streaming._append_completed_active_run
    assert runtime._append_reasoning_active_run is agent_runtime_streaming._append_reasoning_active_run
    assert runtime._append_user_stopped_active_run is agent_runtime_streaming._append_user_stopped_active_run
    assert runtime._clear_active_run is agent_runtime_streaming._clear_active_run
    assert runtime._active_key is agent_runtime_streaming._active_key
    assert runtime.project_tool_started is agent_runtime_streaming.project_tool_started
    assert runtime.project_tool_completed is agent_runtime_streaming.project_tool_completed

    state = agent_runtime_streaming.ActiveRunState(
        profile="siq_assistant",
        session_id="streaming-owner-shared-session",
        run_id="run-streaming-owner-shared",
    )
    key = agent_runtime_streaming._active_key("assistant", state.session_id)
    agent_runtime_streaming.ACTIVE_RUNS[key] = state
    try:
        assert runtime.has_active_run("siq_assistant", state.session_id) is True
        snapshot = runtime.get_active_run_snapshot("assistant", state.session_id)
    finally:
        agent_runtime_streaming.ACTIVE_RUNS.pop(key, None)

    assert snapshot["running"] is True
    assert snapshot["run_id"] == "run-streaming-owner-shared"


def test_streaming_owner_appends_terminal_events_and_clears_active_run():
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="streaming-terminal-owner-session",
            run_id="run-streaming-terminal-owner",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        await runtime._append_completed_active_run(state, {"content": "final", "new_achievements": []})
        completed_snapshot = runtime.get_active_run_snapshot("assistant", state.session_id)
        runtime._clear_active_run(state)
        after_clear = runtime.get_active_run_snapshot("siq_assistant", state.session_id)
        return state, completed_snapshot, after_clear

    state, completed_snapshot, after_clear = anyio.run(run_case)

    assert [event["event"] for event in state.events] == ["progress", "done"]
    assert _event_payload(state.events[0])["status"] == "completed"
    assert _event_payload(state.events[1]) == {"content": "final", "new_achievements": []}
    assert state.status == "completed"
    assert completed_snapshot["running"] is False
    assert completed_snapshot["status"] == "completed"
    assert after_clear == {"running": False}


def test_streaming_owner_appends_user_stopped_terminal_error():
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="streaming-user-stopped-owner-session",
            run_id="run-streaming-user-stopped-owner",
        )
        await runtime._append_user_stopped_active_run(state, runtime.STOPPED_MESSAGE)
        return state

    state = anyio.run(run_case)

    assert [event["event"] for event in state.events] == ["progress", "error"]
    assert state.status == "cancelled"
    assert state.error == runtime.STOPPED_MESSAGE
    assert _event_payload(state.events[0])["status"] == "stopped"
    assert _event_payload(state.events[1])["message"] == runtime.STOPPED_MESSAGE
    assert _event_payload(state.events[1])["reason"] == "user_stop_requested"
    assert _event_payload(state.events[1])["status"] == "cancelled"


def test_streaming_owner_appends_reasoning_event_and_progress():
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="streaming-reasoning-owner-session",
            run_id="run-streaming-reasoning-owner",
        )
        await runtime._append_reasoning_active_run(state, "reasoning detail")
        return state

    state = anyio.run(run_case)

    assert [event["event"] for event in state.events] == ["reasoning", "progress"]
    assert _event_payload(state.events[0]) == {"text": "reasoning detail"}
    assert _event_payload(state.events[1])["status"] == "running"
    assert _event_payload(state.events[1])["title"] == "正在推理"
    assert _event_payload(state.events[1])["detail"] == "reasoning detail"
    assert _event_payload(state.events[1])["source"] == "reasoning"
    assert state.status == "running"
    assert state.content == ""


def test_collect_stream_run_success_uses_streaming_terminal_owner(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-success-session",
            run_id="run-collect-success",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-success", "siq_assistant")
            assert timeout == 1
            yield StreamEvent(type="delta", text="hello")
            yield StreamEvent(type="done", text="hello")

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        async def fake_done_payload(reply):
            return {"new_achievements": ["ok"], "reply_length": len(reply)}

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._append_state_event(state, "run", {"run_id": state.run_id, "session_id": state.session_id})
        await runtime._collect_stream_run(state, fake_done_payload)
        return state, saved_messages, key in runtime.ACTIVE_RUNS

    state, saved_messages, still_active = anyio.run(run_case)

    assert still_active is False
    assert [event["event"] for event in state.events] == ["run", "progress", "delta", "progress", "done"]
    assert _event_payload(state.events[1])["status"] == "running"
    assert _event_payload(state.events[3])["status"] == "completed"
    assert _event_payload(state.events[4]) == {
        "new_achievements": ["ok"],
        "reply_length": 5,
        "content": "hello",
        "terminal": state.terminal_result.to_payload(),
        "runtime_provenance": {"runtime_target": "host"},
    }
    assert saved_messages == [("assistant", "hello", "collect-success-session", "siq_assistant")]
    assert state.status == "completed"


def test_collect_stream_run_replaces_external_tool_loop_reply_with_recovery(monkeypatch):
    async def run_case():
        raw_reply = (
            "I stopped retrying terminal because it hit the tool-call guardrail "
            "(same_tool_failure_halt) after 5 repeated non-progressing attempts."
        )
        recovered_reply = "## 运行状态\n- 已改用后端验证的商誉证据。"
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="tool-loop-recovery-session",
            run_id="run-tool-loop-recovery",
        )
        state.original_message = "分析美的集团的商誉"
        state.context = {"company": "美的集团"}
        saved_messages: list[str] = []

        async def fake_stream_run(*_args, **_kwargs):
            yield StreamEvent(type="delta", text="I stopped retrying ")
            yield StreamEvent(type="delta", text=raw_reply[len("I stopped retrying "):])
            yield StreamEvent(type="done", text=raw_reply)

        async def fake_save_message(_role, content, _session_id, **_kwargs):
            saved_messages.append(content)

        async def fake_trusted_runs(*_args, **_kwargs):
            return ()

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        monkeypatch.setattr(runtime, "recover_financial_tool_loop_reply", lambda *_args: recovered_reply)
        monkeypatch.setattr(runtime, "deterministic_pdf_market_reply", lambda *_args: None)
        monkeypatch.setattr(runtime, "normalize_evidence_trace_for_display", lambda reply: reply)
        monkeypatch.setattr(runtime, "_trusted_financial_receipts_after_run", fake_trusted_runs)
        monkeypatch.setattr(runtime, "_record_answer_audit_trace_compat", lambda **_kwargs: None)
        monkeypatch.setattr(runtime, "_remember_completed_run", lambda *_args: None)

        await runtime._collect_stream_run(state, None, enforce_evidence_contract=False)
        return state, raw_reply, recovered_reply, saved_messages

    state, raw_reply, recovered_reply, saved_messages = anyio.run(run_case)

    assert state.content == recovered_reply
    assert state.done_payload is not None
    assert state.done_payload["content"] == recovered_reply
    assert saved_messages == [recovered_reply]
    assert raw_reply not in state.content
    delta_content = "".join(
        _event_payload(event).get("content", "")
        for event in state.events
        if event["event"] == "delta"
    )
    assert "I stopped retrying terminal" not in delta_content
    assert "same_tool_failure_halt" not in delta_content
    assert "replace" in [event["event"] for event in state.events]
    assert state.status == "completed"


def test_collect_stream_run_sanitizes_external_tool_loop_exception_events(monkeypatch):
    async def run_case():
        raw_error = (
            "I stopped retrying terminal because it hit same_tool_failure_halt "
            "after repeated non-progressing attempts."
        )
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="tool-loop-exception-session",
            run_id="run-tool-loop-exception",
        )

        async def fake_stream_run(*_args, **_kwargs):
            raise RuntimeError(raw_error)
            yield  # pragma: no cover

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)

        await runtime._collect_stream_run(state, None, enforce_evidence_contract=False)
        return state, raw_error

    state, raw_error = anyio.run(run_case)

    serialized_events = json.dumps(state.events, ensure_ascii=False)
    assert raw_error not in serialized_events
    assert "I stopped retrying terminal" not in serialized_events
    assert "same_tool_failure_halt" not in serialized_events
    assert runtime.TOOL_FAILURE_STOP_MESSAGE in serialized_events
    assert state.terminal_result is not None
    assert state.terminal_result.diagnostic == "Hermes upstream tool loop guard stopped the run"


def test_collect_chat_reply_replaces_external_tool_loop_reply_before_history(monkeypatch):
    async def run_case():
        raw_reply = "I stopped retrying terminal after same_tool_failure_halt."
        recovered_reply = "## 运行状态\n- 已返回后端验证的商誉证据。"
        saved_messages: list[tuple[str, str]] = []
        retained_replies: list[str] = []

        async def retain_terminal(state, **_kwargs):
            retained_replies.append(state.content)

        async def fake_prepare(*_args, **_kwargs):
            return runtime.ChatRequestEnvelope(
                all_attachments=[],
                message_hash="tool-loop-recovery-hash",
                user_display_message="分析美的集团的商誉",
            )

        async def fake_preflight(*_args, **_kwargs):
            return runtime.ChatRunPreflightContext(history=[], local_memory_context=None, attachments=[])

        async def fake_save(_session, role, content, _session_id, **_kwargs):
            saved_messages.append((role, content))

        async def fake_noop(*_args, **_kwargs):
            return None

        async def fake_true(*_args, **_kwargs):
            return True

        async def fake_images(*_args, **_kwargs):
            return None, True

        async def fake_create(*_args, **_kwargs):
            return "run-non-stream-tool-loop-recovery"

        async def fake_collect(*_args, **_kwargs):
            return raw_reply

        async def fake_trusted_runs(*_args, **_kwargs):
            return ()

        monkeypatch.setattr(runtime, "_prepare_chat_request_envelope", fake_prepare)
        monkeypatch.setattr(runtime, "build_wiki_catalog_reply", lambda _message: None)
        monkeypatch.setattr(runtime, "_load_chat_run_preflight_context", fake_preflight)
        monkeypatch.setattr(runtime, "wait_for_pdf_attachment_parses", fake_noop)
        monkeypatch.setattr(runtime, "_attachments_with_fresh_metadata", lambda attachments: attachments)
        monkeypatch.setattr(runtime, "save_message", fake_save)
        monkeypatch.setattr(runtime, "refresh_session_memory", fake_noop)
        monkeypatch.setattr(runtime, "analyze_images_with_primary_model", fake_images)
        monkeypatch.setattr(runtime, "build_hermes_run_input", lambda message, **kwargs: {"message": message, **kwargs})
        monkeypatch.setattr(runtime, "create_run", fake_create)
        monkeypatch.setattr(runtime, "collect_run_result", fake_collect)
        monkeypatch.setattr(runtime, "_claim_durable_active_run", fake_true)
        monkeypatch.setattr(runtime, "_renew_durable_provisional_claim", fake_true)
        monkeypatch.setattr(runtime, "_bind_durable_active_run", fake_true)
        monkeypatch.setattr(runtime, "_active_run_ownership_is_current", fake_true)
        monkeypatch.setattr(runtime, "_release_durable_lease", fake_noop)
        monkeypatch.setattr(runtime, "_trusted_financial_receipts_after_run", fake_trusted_runs)
        monkeypatch.setattr(runtime, "recover_financial_tool_loop_reply", lambda *_args: recovered_reply)
        monkeypatch.setattr(runtime, "deterministic_pdf_market_reply", lambda *_args: None)
        monkeypatch.setattr(runtime, "normalize_evidence_trace_for_display", lambda reply: reply)
        monkeypatch.setattr(runtime, "_record_answer_audit_trace_compat", lambda **_kwargs: None)
        monkeypatch.setattr(runtime, "_record_financial_llm_provenance_if_needed", lambda **_kwargs: None)
        monkeypatch.setattr(runtime, "_remember_completed_run", lambda *_args: None)

        monkeypatch.setattr(runtime, "_retain_terminal_business_result", retain_terminal)

        reply = await runtime._collect_chat_reply_impl(
            "分析美的集团的商誉",
            object(),
            session_id="non-stream-tool-loop-recovery-session",
            profile="siq_assistant",
            enforce_evidence_contract=False,
        )
        assert retained_replies == [recovered_reply]
        return raw_reply, recovered_reply, reply, saved_messages

    raw_reply, recovered_reply, reply, saved_messages = anyio.run(run_case)

    assert reply == recovered_reply
    assert saved_messages == [
        ("user", "分析美的集团的商誉"),
        ("assistant", recovered_reply),
    ]
    assert all(raw_reply not in content for _role, content in saved_messages)


def test_collect_stream_run_reasoning_uses_streaming_event_owner(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-reasoning-session",
            run_id="run-collect-reasoning",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-reasoning", "siq_assistant")
            assert timeout == 1
            yield StreamEvent(type="reasoning", text="thinking through evidence")
            yield StreamEvent(type="delta", text="answer")
            yield StreamEvent(type="done", text="answer")

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._collect_stream_run(state, None)
        return state, saved_messages, key in runtime.ACTIVE_RUNS

    state, saved_messages, still_active = anyio.run(run_case)

    assert still_active is False
    assert [event["event"] for event in state.events] == [
        "progress",
        "reasoning",
        "progress",
        "delta",
        "progress",
        "done",
    ]
    assert _event_payload(state.events[1]) == {"text": "thinking through evidence"}
    assert _event_payload(state.events[2])["source"] == "reasoning"
    assert _event_payload(state.events[2])["detail"] == "thinking through evidence"
    assert _event_payload(state.events[3]) == {"content": "answer", "source": "model"}
    assert _event_payload(state.events[-1]) == {
        "new_achievements": [],
        "content": "answer",
        "terminal": state.terminal_result.to_payload(),
        "runtime_provenance": {"runtime_target": "host"},
    }
    assert saved_messages == [("assistant", "answer", "collect-reasoning-session", "siq_assistant")]
    assert state.status == "completed"


def test_collect_stream_run_user_stop_uses_streaming_terminal_owner(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-user-stop-session",
            run_id="run-collect-user-stop",
        )
        state.user_stop_requested = True
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-user-stop", "siq_assistant")
            yield StreamEvent(type="cancelled", text="")

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._collect_stream_run(state, None)
        return state, saved_messages, key in runtime.ACTIVE_RUNS

    state, saved_messages, still_active = anyio.run(run_case)

    assert still_active is False
    assert "done" not in [event["event"] for event in state.events]
    assert any(event["event"] == "replace" and _event_payload(event) == {"content": runtime.STOPPED_MESSAGE} for event in state.events)
    assert _event_payload(state.events[-1])["message"] == runtime.STOPPED_MESSAGE
    assert _event_payload(state.events[-1])["reason"] == "user_stop_requested"
    assert _event_payload(state.events[-1])["status"] == "cancelled"
    assert saved_messages == []
    assert state.status == "cancelled"


def test_collect_stream_run_cancelled_without_user_stop_does_not_save_success_history(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-cancelled-session",
            run_id="run-collect-cancelled",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-cancelled", "siq_assistant")
            yield StreamEvent(type="cancelled", text="cancel detail")

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._collect_stream_run(state, None)
        return state, saved_messages, key in runtime.ACTIVE_RUNS

    state, saved_messages, still_active = anyio.run(run_case)

    assert still_active is False
    assert "done" not in [event["event"] for event in state.events]
    assert runtime.RUN_CANCELLED_MESSAGE in _event_payload(state.events[1])["content"]
    assert _event_payload(state.events[-1])["reason"] == "hermes_run_cancelled"
    assert saved_messages == []
    assert state.status == "cancelled"


def test_collect_stream_run_failed_partial_and_protocol_eof_never_persist_success_history(monkeypatch):
    async def run_case(events):
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id=f"terminal-contract-{events[0].type}",
            run_id=f"run-terminal-contract-{events[0].type}",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []

        async def fake_stream_run(_run_id, *, profile, timeout):
            assert profile == "siq_assistant"
            for event in events:
                yield event

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._collect_stream_run(state, None)
        return state, saved_messages, key in runtime.ACTIVE_RUNS

    failed_state, failed_saved, failed_active = anyio.run(
        run_case,
        [
            StreamEvent(type="delta", text="partial answer"),
            StreamEvent(type="failed", text="gateway failed", status="failed", error=True),
        ],
    )
    eof_state, eof_saved, eof_active = anyio.run(
        run_case,
        [StreamEvent(type="delta", text="partial before EOF")],
    )

    assert failed_active is False
    assert failed_saved == []
    failed_deltas = [_event_payload(event) for event in failed_state.events if event["event"] == "delta"]
    assert any(value.get("source") == "model" and "partial answer" in value["content"] for value in failed_deltas)
    assert any(runtime.RUN_FAILED_MESSAGE in value["content"] and value.get("source") != "model"
               for value in failed_deltas)
    assert failed_state.terminal_result is not None
    assert failed_state.terminal_result.status == "failed"
    assert "gateway failed" in _event_payload(failed_state.events[-1])["terminal"]["diagnostic"]
    assert "done" not in [event["event"] for event in failed_state.events]

    assert eof_active is False
    assert eof_saved == []
    assert eof_state.terminal_result is not None
    assert eof_state.terminal_result.status == "protocol_eof"
    assert _event_payload(eof_state.events[-1])["error_code"] == "hermes_protocol_eof"
    assert "done" not in [event["event"] for event in eof_state.events]


def test_collect_stream_run_idle_timeout_stops_run_and_clears_active(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-idle-timeout-session",
            run_id="run-collect-idle-timeout",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []
        stop_calls = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-idle-timeout", "siq_assistant")
            raise asyncio.TimeoutError()
            yield StreamEvent(type="delta", text="unreachable")

        async def fake_stop_run(run_id, *, profile):
            stop_calls.append((run_id, profile))
            return {"id": run_id, "status": "stopped"}

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 0.001)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        with anyio.fail_after(1):
            await runtime._collect_stream_run(state, None)
        return state, saved_messages, stop_calls, key in runtime.ACTIVE_RUNS

    state, saved_messages, stop_calls, still_active = anyio.run(run_case)

    assert still_active is False
    assert stop_calls == [("run-collect-idle-timeout", "siq_assistant")]
    assert [event["event"] for event in state.events] == ["progress", "progress", "delta", "error"]
    assert _event_payload(state.events[1])["status"] == "error"
    assert runtime.IDLE_TIMEOUT_MESSAGE in _event_payload(state.events[2])["content"]
    assert _event_payload(state.events[-1])["status"] == "timed_out"
    assert saved_messages == []
    assert state.status == "timed_out"


def test_collect_stream_run_http_timeout_stops_run_and_clears_active(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-http-timeout-session",
            run_id="run-collect-http-timeout",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []
        stop_calls = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-http-timeout", "siq_assistant")
            raise httpx.TimeoutException("stream timed out")
            yield StreamEvent(type="delta", text="unreachable")

        async def fake_stop_run(run_id, *, profile):
            stop_calls.append((run_id, profile))
            return {"id": run_id, "status": "stopped"}

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._collect_stream_run(state, None)
        return state, saved_messages, stop_calls, key in runtime.ACTIVE_RUNS

    state, saved_messages, stop_calls, still_active = anyio.run(run_case)

    assert still_active is False
    assert stop_calls == [("run-collect-http-timeout", "siq_assistant")]
    assert [event["event"] for event in state.events] == ["progress", "progress", "delta", "error"]
    assert _event_payload(state.events[1])["status"] == "error"
    assert runtime.TIMEOUT_MESSAGE in _event_payload(state.events[2])["content"]
    assert runtime.TIMEOUT_MESSAGE in _event_payload(state.events[2])["content"]
    assert _event_payload(state.events[-1])["status"] == "timed_out"
    assert saved_messages == []
    assert state.status == "timed_out"


def test_collect_stream_run_repeated_tool_call_stops_run(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-repeated-tool-session",
            run_id="run-collect-repeated-tool",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []
        stop_calls = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-repeated-tool", "siq_assistant")
            for _index in range(runtime.REPEATED_TOOL_CALL_LIMIT):
                yield StreamEvent(type="tool.started", tool="terminal", preview="python loop.py")

        async def fake_stop_run(run_id, *, profile):
            stop_calls.append((run_id, profile))
            return {"id": run_id, "status": "stopped"}

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._collect_stream_run(state, None)
        return state, saved_messages, stop_calls, key in runtime.ACTIVE_RUNS

    state, saved_messages, stop_calls, still_active = anyio.run(run_case)

    assert still_active is False
    assert stop_calls == [("run-collect-repeated-tool", "siq_assistant")]
    assert "done" not in [event["event"] for event in state.events]
    assert _event_payload(state.events[-1])["reason"] == "repeated_tool_calls_without_delta"
    assert saved_messages == []
    assert state.status == "failed"


def test_collect_stream_run_consecutive_tool_errors_stop_run(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="collect-tool-errors-session",
            run_id="run-collect-tool-errors",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        saved_messages = []
        stop_calls = []

        async def fake_stream_run(run_id, *, profile, timeout):
            assert (run_id, profile) == ("run-collect-tool-errors", "siq_assistant")
            yield StreamEvent(type="tool.started", tool="terminal", preview="missing-file")
            for _index in range(runtime.CONSECUTIVE_TOOL_ERROR_LIMIT):
                yield StreamEvent(type="tool.completed", tool="terminal", duration=0.1, error=True)

        async def fake_stop_run(run_id, *, profile):
            stop_calls.append((run_id, profile))
            return {"id": run_id, "status": "stopped"}

        async def fake_save_message(role, content, session_id, *, profile=None, audit_trace_id=None):
            saved_messages.append((role, content, session_id, profile))

        monkeypatch.setattr(runtime, "stream_run", fake_stream_run)
        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        monkeypatch.setattr(runtime, "hermes_timeout", lambda: 1)
        monkeypatch.setattr(runtime, "stream_idle_timeout", lambda _profile: 1)
        monkeypatch.setattr(runtime, "save_message_in_background", fake_save_message)
        await runtime._collect_stream_run(state, None)
        return state, saved_messages, stop_calls, key in runtime.ACTIVE_RUNS

    state, saved_messages, stop_calls, still_active = anyio.run(run_case)

    assert still_active is False
    assert stop_calls == [("run-collect-tool-errors", "siq_assistant")]
    assert "done" not in [event["event"] for event in state.events]
    assert _event_payload(state.events[-1])["reason"] == "consecutive_tool_errors"
    assert saved_messages == []
    assert state.status == "failed"


@pytest.mark.parametrize('failure_kind', ['terminal', 'transport', 'remote_protocol'])
@pytest.mark.parametrize('stop_confirmed', [False, True])
def test_collect_chat_reply_non_stream_terminal_failure_does_not_persist_assistant(
    monkeypatch, failure_kind, stop_confirmed,
):
    async def run_case():
        saved: list[tuple[str, str, str]] = []
        stopped = []
        terminal_states = []

        async def fake_stop(run_id, **_kwargs):
            stopped.append(run_id)
            return stop_confirmed

        def capture_event(state, *, event_type, **_kwargs):
            if event_type == 'agent_run.terminal':
                terminal_states.append(state)

        async def fake_prepare(*_args, **_kwargs):
            return runtime.ChatRequestEnvelope(
                all_attachments=[],
                message_hash="non-stream-failure-hash",
                user_display_message="请查询收入",
            )

        async def fake_preflight(*_args, **_kwargs):
            return runtime.ChatRunPreflightContext(history=[], local_memory_context=None, attachments=[])

        async def fake_save(_session, role, content, session_id, **_kwargs):
            saved.append((role, content, session_id))

        async def fake_wait(_attachments):
            return None

        async def fake_images(*_args, **_kwargs):
            return None, True

        async def fake_create(*_args, **_kwargs):
            return "run-non-stream-failure"

        async def fake_collect(*_args, **_kwargs):
            if failure_kind != 'terminal':
                error = httpx.TransportError if failure_kind == 'transport' else httpx.RemoteProtocolError
                raise error('private-upstream-detail-must-not-leak')
            raise runtime.RunTerminalError(
                runtime.RunTerminalResult(
                    run_id="run-non-stream-failure",
                    status="failed",
                    received_text="partial answer",
                    error_code="hermes_run_failed",
                    retryable=True,
                    diagnostic="gateway failed",
                )
            )

        monkeypatch.setattr(runtime, "_prepare_chat_request_envelope", fake_prepare)
        monkeypatch.setattr(runtime, "build_wiki_catalog_reply", lambda _message: None)
        monkeypatch.setattr(runtime, "_load_chat_run_preflight_context", fake_preflight)
        monkeypatch.setattr(runtime, "wait_for_pdf_attachment_parses", fake_wait)
        monkeypatch.setattr(runtime, "_attachments_with_fresh_metadata", lambda attachments: attachments)
        monkeypatch.setattr(runtime, "save_message", fake_save)
        monkeypatch.setattr(runtime, "analyze_images_with_primary_model", fake_images)
        monkeypatch.setattr(runtime, "build_hermes_run_input", lambda message, **kwargs: {"message": message, **kwargs})
        monkeypatch.setattr(runtime, "create_run", fake_create)
        monkeypatch.setattr(runtime, "collect_run_result", fake_collect)
        monkeypatch.setattr(runtime, '_stop_and_confirm_routed_run', fake_stop)
        monkeypatch.setattr(runtime.siq_security_export, 'emit_run_event', capture_event)

        reply = await runtime._collect_chat_reply_impl(
            "请查询收入",
            object(),
            session_id="non-stream-failure-session",
            profile="siq_assistant",
        )
        return reply, saved, stopped, terminal_states

    reply, saved, stopped, terminal_states = anyio.run(run_case)

    assert reply == (runtime.RUN_FAILED_MESSAGE if failure_kind == 'terminal' else runtime.TRANSPORT_FAILURE_MESSAGE)
    assert saved == [("user", "请查询收入", "non-stream-failure-session")]
    assert len(terminal_states) == 1
    assert terminal_states[0].status == 'failed'
    if failure_kind != 'terminal':
        assert stopped == ['run-non-stream-failure']
        state = terminal_states[0]
        assert state.runtime_terminal_confirmed is stop_confirmed
        assert state.error == 'hermes_transport_interrupted'
        assert state.terminal_result.retryable is False
        assert 'private-upstream-detail' not in state.terminal_result.diagnostic


def test_stream_active_run_events_replays_from_offset_and_drains_terminal_done():
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="offset-replay-session",
            run_id="run-offset-replay",
        )
        runtime.ACTIVE_RUNS[runtime._active_key(state.profile, state.session_id)] = state
        try:
            await runtime._append_state_event(state, "delta", {"content": "first"})
            await runtime._append_state_event(state, "progress", {"status": "running"})
            await runtime._append_state_event(state, "done", {"content": "final"})
            return await _collect_events(state.profile, state.session_id, offset=1), state
        finally:
            runtime.ACTIVE_RUNS.pop(runtime._active_key(state.profile, state.session_id), None)

    events, state = anyio.run(run_case)

    assert [event["event"] for event in events] == ["progress", "done"]
    assert state.status == "completed"
    assert state.done_payload == {"content": "final"}


def test_stream_active_run_events_drains_terminal_error_status():
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="terminal-error-session",
            run_id="run-terminal-error",
        )
        runtime.ACTIVE_RUNS[runtime._active_key(state.profile, state.session_id)] = state
        try:
            await runtime._append_state_event(state, "delta", {"content": "partial"})
            await runtime._append_state_event(state, "error", {"message": "Hermes failed"})
            return await _collect_events(state.profile, state.session_id, offset=0), state
        finally:
            runtime.ACTIVE_RUNS.pop(runtime._active_key(state.profile, state.session_id), None)

    events, state = anyio.run(run_case)

    assert [event["event"] for event in events] == ["delta", "error"]
    assert state.status == "failed"
    assert state.error == "Hermes failed"


def test_stream_active_run_events_returns_without_yielding_when_request_disconnects():
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="disconnect-session",
            run_id="run-disconnect",
        )
        runtime.ACTIVE_RUNS[runtime._active_key(state.profile, state.session_id)] = state
        try:
            await runtime._append_state_event(state, "delta", {"content": "already buffered"})
            events = []
            async for event in runtime.stream_active_run_events(
                _Request(disconnected=True),
                profile=state.profile,
                session_id=state.session_id,
            ):
                events.append(event)
            return events
        finally:
            runtime.ACTIVE_RUNS.pop(runtime._active_key(state.profile, state.session_id), None)

    assert anyio.run(run_case) == []


def test_stream_active_run_events_emits_heartbeat_without_buffering(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="heartbeat-session",
            run_id="run-heartbeat",
        )
        key = runtime._active_key(state.profile, state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        monkeypatch.setattr(runtime, "STREAM_EVENT_HEARTBEAT_SECONDS", 0.01)

        stream = runtime.stream_active_run_events(
            _Request(),
            profile="assistant",
            session_id=state.session_id,
        )
        try:
            event = await stream.__anext__()
            snapshot = runtime.get_active_run_snapshot("siq_assistant", state.session_id)
            return event, snapshot, list(state.events)
        finally:
            await stream.aclose()
            runtime.ACTIVE_RUNS.pop(key, None)

    event, snapshot, buffered_events = anyio.run(run_case)

    assert event["event"] == "progress"
    payload = _event_payload(event)
    assert payload["status"] == "running"
    assert payload["title"] == "等待模型或工具返回"
    assert payload["detail"] == "后台 Hermes run 仍在运行；本地模型可能正在生成首轮输出，或工具正在执行。"
    assert payload["source"] == "runtime"
    assert payload["updated_at"]
    assert buffered_events == []
    assert snapshot["event_count"] == 0
    assert snapshot["progress"] is None


def test_stream_chat_reply_joins_existing_active_run_snapshot(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="join-existing-session",
            run_id="run-join-existing",
        )
        key = runtime._active_key(state.profile, state.session_id)
        runtime.ACTIVE_RUNS[key] = state

        async def fail_create_run(*_args, **_kwargs):
            raise AssertionError("join path must not create a second Hermes run")

        monkeypatch.setattr(runtime, "create_run", fail_create_run)
        try:
            await runtime._append_state_event(state, "run", {"run_id": state.run_id, "session_id": state.session_id})
            await runtime._append_state_event(state, "delta", {"content": "already running"})
            before = runtime.get_active_run_snapshot("assistant", state.session_id)

            async def finish_run():
                await anyio.sleep(0)
                await runtime._append_state_event(state, "done", {"content": "already running"})

            async with anyio.create_task_group() as tg:
                tg.start_soon(finish_run)
                events = await _collect_chat_stream_events("assistant", state.session_id)
            after = runtime.get_active_run_snapshot("siq_assistant", state.session_id)
            return events, before, after
        finally:
            runtime.ACTIVE_RUNS.pop(key, None)

    events, before, after = anyio.run(run_case)

    assert [event["event"] for event in events] == ["run", "delta", "done"]
    assert _event_payload(events[0]) == {
        "run_id": "run-join-existing",
        "session_id": "join-existing-session",
    }
    assert before["running"] is True
    assert before["content"] == "already running"
    assert before["event_count"] == 2
    assert after["running"] is False
    assert after["status"] == "completed"
    assert after["content"] == "already running"


def test_session_default_contexts_are_isolated_by_profile_and_session(monkeypatch):
    touched_keys = [
        runtime._active_key("assistant", "default-context-a"),
        runtime._active_key("assistant", "default-context-b"),
        runtime._active_key("siq_analysis", "default-context-a"),
    ]
    for key in touched_keys:
        runtime.SESSION_DEFAULT_CONTEXTS.pop(key, None)

    def fake_format_context(context):
        return f"ctx:{context['company']}" if context else None

    monkeypatch.setattr(runtime, "format_chat_context", fake_format_context)
    try:
        assistant_a = runtime.get_session_default_context(
            "assistant",
            "default-context-a",
            {"company": "A"},
            allow_initialize=True,
        )
        assistant_b = runtime.get_session_default_context(
            "siq_assistant",
            "default-context-b",
            {"company": "B"},
            allow_initialize=True,
        )
        assistant_a_again = runtime.get_session_default_context(
            "siq_assistant",
            "default-context-a",
            {"company": "ignored"},
            allow_initialize=True,
        )
        analysis_a = runtime.get_session_default_context(
            "siq_analysis",
            "default-context-a",
            {"company": "analysis"},
            allow_initialize=True,
        )
    finally:
        for key in touched_keys:
            runtime.SESSION_DEFAULT_CONTEXTS.pop(key, None)

    assert assistant_a == "ctx:A"
    assert assistant_b == "ctx:B"
    assert assistant_a_again == "ctx:A"
    assert analysis_a == "ctx:analysis"


def test_stop_by_profile_alias_can_be_streamed_from_canonical_profile(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="alias-stop-stream-session",
            run_id="run-alias-stop-stream",
        )
        key = runtime._active_key(state.profile, state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        stop_calls = []

        async def fake_stop_run(run_id, *, profile):
            stop_calls.append((run_id, profile))
            return {"id": run_id, "status": "stopped", "profile": profile}

        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        try:
            result = await runtime.stop_active_run("assistant", state.session_id)
            events = await _collect_active_events_limit("siq_assistant", state.session_id, 2)
            return result, events, state, stop_calls
        finally:
            runtime.ACTIVE_RUNS.pop(key, None)

    result, events, state, stop_calls = anyio.run(run_case)

    assert result["stopped"] is True
    assert result["run_id"] == "run-alias-stop-stream"
    assert stop_calls == [("run-alias-stop-stream", "siq_assistant")]
    assert state.user_stop_requested is True
    assert [event["event"] for event in events] == ["progress", "replace"]
    assert _event_payload(events[-1]) == {"content": runtime.STOPPED_MESSAGE}


def test_terminal_snapshot_is_stable_after_stream_drain():
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="terminal-snapshot-session",
            run_id="run-terminal-snapshot",
        )
        key = runtime._active_key(state.profile, state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        try:
            await runtime._append_state_event(state, "delta", {"content": "final answer"})
            await runtime._append_state_event(state, "done", {"content": "final answer", "new_achievements": []})
            before = runtime.get_active_run_snapshot("assistant", state.session_id)
            events = await _collect_events("siq_assistant", state.session_id)
            after = runtime.get_active_run_snapshot("assistant", state.session_id)
            return events, before, after, state
        finally:
            runtime.ACTIVE_RUNS.pop(key, None)

    events, before, after, state = anyio.run(run_case)

    assert [event["event"] for event in events] == ["delta", "done"]
    assert before == after
    assert before["running"] is False
    assert before["status"] == "completed"
    assert before["content"] == "final answer"
    assert before["event_count"] == 2
    assert state.done_payload == {"content": "final answer", "new_achievements": []}


def test_stop_active_run_marks_user_stop_and_emits_replace(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="stop-replace-session",
            run_id="run-stop-replace",
        )
        runtime.ACTIVE_RUNS[runtime._active_key(state.profile, state.session_id)] = state

        async def fake_stop_run(run_id, *, profile):
            return {"id": run_id, "status": "stopped", "profile": profile}

        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        try:
            result = await runtime.stop_active_run(state.profile, state.session_id)
            return result, state
        finally:
            runtime.ACTIVE_RUNS.pop(runtime._active_key(state.profile, state.session_id), None)

    result, state = anyio.run(run_case)

    assert result == {
        "stopped": True,
        "run_id": "run-stop-replace",
        "hermes": {"id": "run-stop-replace", "status": "stopped", "profile": "siq_assistant"},
    }
    assert state.stop_requested is True
    assert state.user_stop_requested is True
    assert [event["event"] for event in state.events] == ["progress", "replace"]
    assert _event_payload(state.events[-1]) == {"content": runtime.STOPPED_MESSAGE}


def test_stop_active_run_is_idempotent_after_user_stop_request(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="assistant",
            session_id="stop-idempotent-session",
            run_id="run-stop-idempotent",
        )
        key = runtime._active_key("siq_assistant", state.session_id)
        runtime.ACTIVE_RUNS[key] = state
        stop_calls = []

        async def fake_stop_run(run_id, *, profile):
            stop_calls.append((run_id, profile))
            return {"id": run_id, "status": "stopped", "profile": profile}

        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        try:
            first = await runtime.stop_active_run("assistant", state.session_id)
            second = await runtime.stop_active_run("siq_assistant", state.session_id)
            return first, second, state, stop_calls
        finally:
            runtime.ACTIVE_RUNS.pop(key, None)

    first, second, state, stop_calls = anyio.run(run_case)

    assert first == {
        "stopped": True,
        "run_id": "run-stop-idempotent",
        "hermes": {"id": "run-stop-idempotent", "status": "stopped", "profile": "siq_assistant"},
    }
    assert second == {
        "stopped": True,
        "run_id": "run-stop-idempotent",
        "detail": "Stop already requested",
    }
    assert stop_calls == [("run-stop-idempotent", "siq_assistant")]
    assert state.profile == "siq_assistant"
    assert [event["event"] for event in state.events] == ["progress", "replace"]


def test_streaming_stop_active_run_keeps_public_call_shape(monkeypatch):
    async def run_case():
        state = agent_runtime_streaming.ActiveRunState(
            profile="assistant",
            session_id="streaming-stop-public-shape-session",
            run_id="run-streaming-stop-public-shape",
        )
        key = agent_runtime_streaming._active_key("siq_assistant", state.session_id)
        agent_runtime_streaming.ACTIVE_RUNS[key] = state
        stop_calls = []

        async def fake_stop_run(run_id, *, profile):
            stop_calls.append((run_id, profile))
            return {"id": run_id, "status": "stopped", "profile": profile}

        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        try:
            result = await agent_runtime_streaming.stop_active_run("assistant", state.session_id)
            return result, state, stop_calls
        finally:
            agent_runtime_streaming.ACTIVE_RUNS.pop(key, None)

    result, state, stop_calls = anyio.run(run_case)

    assert result == {
        "stopped": True,
        "run_id": "run-streaming-stop-public-shape",
        "hermes": {"id": "run-streaming-stop-public-shape", "status": "stopped", "profile": "siq_assistant"},
    }
    assert stop_calls == [("run-streaming-stop-public-shape", "siq_assistant")]
    assert state.user_stop_requested is True
    assert [event["event"] for event in state.events] == ["progress", "replace"]


def test_stop_active_run_404_orphan_emits_error_and_cleans_active_run(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="orphan-cleanup-session",
            run_id="run-orphan-cleanup",
        )
        key = runtime._active_key(state.profile, state.session_id)
        runtime.ACTIVE_RUNS[key] = state

        async def fake_stop_run(_run_id, *, profile):
            request = httpx.Request("POST", f"https://hermes.example/runs/{_run_id}/stop")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        result = await runtime.stop_active_run(state.profile, state.session_id)
        return result, state, key in runtime.ACTIVE_RUNS

    result, state, still_active = anyio.run(run_case)

    assert result == {
        "stopped": True,
        "run_id": "run-orphan-cleanup",
        "detail": runtime.ORPHANED_RUN_MESSAGE,
        "hermes": {"error": "run_not_found"},
    }
    assert still_active is False
    assert [event["event"] for event in state.events] == ["progress", "replace", "progress", "replace", "error"]
    assert _event_payload(state.events[-1]) == {
        "message": runtime.ORPHANED_RUN_MESSAGE,
        "reason": "hermes_run_not_found",
    }


def test_stop_active_run_404_orphan_drains_existing_active_stream(monkeypatch):
    async def run_case():
        state = runtime.ActiveRunState(
            profile="siq_assistant",
            session_id="orphan-stream-drain-session",
            run_id="run-orphan-stream-drain",
        )
        key = runtime._active_key(state.profile, state.session_id)
        runtime.ACTIVE_RUNS[key] = state

        async def fake_stop_run(_run_id, *, profile):
            request = httpx.Request("POST", f"https://hermes.example/runs/{_run_id}/stop")
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError("not found", request=request, response=response)

        monkeypatch.setattr(runtime, "stop_run", fake_stop_run)
        stream = runtime.stream_active_run_events(
            _Request(),
            profile="assistant",
            session_id=state.session_id,
        )
        events = []

        async def collect_stream():
            async for event in stream:
                events.append(event)

        async with anyio.create_task_group() as tg:
            tg.start_soon(collect_stream)
            await anyio.sleep(0)
            result = await runtime.stop_active_run("assistant", state.session_id)

        return result, events, key in runtime.ACTIVE_RUNS

    result, events, still_active = anyio.run(run_case)

    assert result["hermes"] == {"error": "run_not_found"}
    assert still_active is False
    assert [event["event"] for event in events] == ["progress", "replace", "progress", "replace", "error"]
    assert _event_payload(events[-1]) == {
        "message": runtime.ORPHANED_RUN_MESSAGE,
        "reason": "hermes_run_not_found",
    }


def test_stop_active_run_without_state_returns_not_stopped():
    result = anyio.run(runtime.stop_active_run, "siq_assistant", "missing-active-run")

    assert result == {"stopped": False, "detail": "No active Hermes run"}


def test_collect_chat_durable_conflict_leaves_no_orphan_user_message_or_pool_lease(monkeypatch):
    calls: list[str] = []

    async def fake_prepare(*_args, **_kwargs):
        calls.append("prepare")
        return runtime.ChatRequestEnvelope(
            all_attachments=[],
            message_hash="collect-conflict-hash",
            user_display_message="分析收入增长",
        )

    async def fake_claim(*_args, **_kwargs):
        calls.append("durable_claim")
        return None

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a losing session request must not write history or touch the pool")

    monkeypatch.setattr(runtime, "_prepare_chat_request_envelope", fake_prepare)
    monkeypatch.setattr(runtime, "build_wiki_catalog_reply", lambda _message: None)
    monkeypatch.setattr(runtime, "_acquire_durable_provisional_claim", fake_claim)
    monkeypatch.setattr(runtime, "save_message", forbidden)
    monkeypatch.setattr(runtime, "_load_chat_run_preflight_context", forbidden)
    monkeypatch.setattr(runtime, "analyze_images_with_primary_model", forbidden)
    monkeypatch.setattr(runtime, "_acquire_pool_route", forbidden)
    monkeypatch.setattr(runtime, "create_run", forbidden)

    async def run_case():
        return await runtime._collect_chat_reply_impl(
            "分析收入增长",
            object(),
            session_id="collect-durable-conflict-session",
            profile="siq_analysis",
        )

    assert anyio.run(run_case) == runtime._ACTIVE_RUN_CONFLICT_MESSAGE
    assert calls == ["prepare", "durable_claim"]


def test_stream_chat_durable_conflict_leaves_no_orphan_user_message_or_pool_lease(monkeypatch):
    calls: list[str] = []

    async def fake_prepare(*_args, **_kwargs):
        calls.append("prepare")
        return runtime.ChatRequestEnvelope(
            all_attachments=[],
            message_hash="stream-conflict-hash",
            user_display_message="分析现金流",
        )

    async def fake_claim(*_args, **_kwargs):
        calls.append("durable_claim")
        return None

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a losing session request must not write history or touch the pool")

    monkeypatch.setattr(runtime, "_prepare_chat_request_envelope", fake_prepare)
    monkeypatch.setattr(runtime, "build_wiki_catalog_reply", lambda _message: None)
    monkeypatch.setattr(runtime, "_acquire_durable_provisional_claim", fake_claim)
    monkeypatch.setattr(runtime, "save_message", forbidden)
    monkeypatch.setattr(runtime, "_load_chat_run_preflight_context", forbidden)
    monkeypatch.setattr(runtime, "analyze_images_with_primary_model", forbidden)
    monkeypatch.setattr(runtime, "_acquire_pool_route", forbidden)
    monkeypatch.setattr(runtime, "create_run", forbidden)

    async def run_case():
        return [
            event
            async for event in runtime._stream_chat_reply_impl(
                "分析现金流",
                _Request(),
                object(),
                session_id="stream-durable-conflict-session",
                profile="siq_analysis",
            )
        ]

    events = anyio.run(run_case)

    assert calls == ["prepare", "durable_claim"]
    assert [event["event"] for event in events] == ["error"]
    assert _event_payload(events[0]) == {
        "message": runtime._ACTIVE_RUN_CONFLICT_MESSAGE,
        "error_code": "active_run_conflict",
        "retryable": True,
    }


def test_pool_lease_heartbeat_continues_through_postprocessing(monkeypatch):
    state = runtime.ActiveRunState(
        profile="siq_analysis",
        session_id="postprocessing-heartbeat",
        run_id="run-postprocessing-heartbeat",
        status="postprocessing",
    )
    state.run_route = hermes_client.HermesRunRoute(
        target="openshell",
        base="http://127.0.0.1:28652/v1/runs",
        model="siq_analysis",
        authorization="Bearer test",
        session_namespace="scope",
        pool_binding=object(),
        pool_lease_id="lease-postprocessing",
        pool_owner_token="owner-" + "3" * 64,
        pool_owner_generation=3,
    )
    calls = []

    async def fake_sleep(_seconds):
        calls.append("sleep")

    async def fake_renew(current):
        calls.append("durable")
        return True

    async def fake_pool_heartbeat(route, *, session_id):
        calls.append("pool")
        state.status = "succeeded"
        return True

    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(runtime, "_renew_durable_active_run", fake_renew)
    monkeypatch.setattr(runtime, "_heartbeat_pool_route", fake_pool_heartbeat)

    anyio.run(runtime._active_run_lease_heartbeat, state)

    assert calls == ["sleep", "durable", "pool"]


def test_postprocessing_fence_rejects_stale_durable_owner(monkeypatch):
    state = runtime.ActiveRunState(
        profile="siq_analysis",
        session_id="postprocessing-fence",
        run_id="run-postprocessing-fence",
        status="postprocessing",
        owner_id="old-api-owner",
    )
    state.run_route = hermes_client.HermesRunRoute(
        target="openshell",
        base="http://127.0.0.1:28652/v1/runs",
        model="siq_analysis",
        authorization="Bearer test",
        session_namespace="scope",
        pool_binding=object(),
        pool_lease_id="lease-postprocessing-fence",
        pool_owner_token="owner-" + "4" * 64,
        pool_owner_generation=4,
    )

    async def stale_owner(_state):
        return False

    async def forbidden_pool_heartbeat(*_args, **_kwargs):
        raise AssertionError("stale DB owner must not touch the rotated pool owner")

    monkeypatch.setattr(runtime, "_renew_durable_active_run", stale_owner)
    monkeypatch.setattr(runtime, "_heartbeat_pool_route", forbidden_pool_heartbeat)

    assert anyio.run(runtime._active_run_ownership_is_current, state) is False


def _openshell_release_state(
    *,
    runtime_terminal_confirmed: bool,
    runtime_children_terminal_confirmed: bool,
) -> runtime.ActiveRunState:
    state = runtime.ActiveRunState(
        profile="siq_analysis",
        session_id="release-reconcile-session",
        run_id="run-release-reconcile",
        owner_id="api-owner-release-reconcile",
    )
    state.runtime_terminal_confirmed = runtime_terminal_confirmed
    state.runtime_children_terminal_confirmed = runtime_children_terminal_confirmed
    state.run_route = hermes_client.HermesRunRoute(
        target="openshell",
        base="http://127.0.0.1:28652/v1/runs",
        model="siq_analysis",
        authorization="Bearer test",
        session_namespace="scope-release-reconcile",
        canary_run_id="canary-123456789abc",
        pool_binding=object(),
        pool_lease_id="lease-release-reconcile",
        pool_owner_token="owner-" + "5" * 64,
        pool_owner_generation=5,
    )
    return state


@pytest.mark.parametrize(
    ("runtime_terminal_confirmed", "pool_released"),
    ((True, False), (False, False)),
)
def test_pool_release_failure_or_unquiesced_main_keeps_durable_row_running(
    monkeypatch,
    runtime_terminal_confirmed,
    pool_released,
):
    state = _openshell_release_state(
        runtime_terminal_confirmed=runtime_terminal_confirmed,
        runtime_children_terminal_confirmed=True,
    )
    calls = []

    async def fake_pool_release(route, *, session_id, terminal_confirmed):
        calls.append(("pool", route, session_id, terminal_confirmed))
        return pool_released

    async def forbidden_db_release(*_args, **_kwargs):
        raise AssertionError("the durable row must remain running until exact pool release")

    def fake_schedule(current, *, status):
        calls.append(("schedule", current, status))

    monkeypatch.setattr(runtime, "_release_pool_route", fake_pool_release)
    monkeypatch.setattr(runtime, "_release_durable_lease", forbidden_db_release)
    monkeypatch.setattr(runtime, "_schedule_orphan_reconciliation", fake_schedule)

    async def run_case():
        await runtime._release_durable_active_run(state, status="failed")

    anyio.run(run_case)

    assert calls == [
        (
            "pool",
            state.run_route,
            state.session_id,
            runtime_terminal_confirmed,
        ),
        ("schedule", state, "failed"),
    ]


def test_unconfirmed_children_do_not_schedule_same_process_reconciler(monkeypatch):
    state = _openshell_release_state(
        runtime_terminal_confirmed=True,
        runtime_children_terminal_confirmed=False,
    )
    pool_calls = []

    async def fake_pool_release(route, *, session_id, terminal_confirmed):
        pool_calls.append((route, session_id, terminal_confirmed))
        return False

    async def forbidden_db_release(*_args, **_kwargs):
        raise AssertionError("children uncertainty must keep the durable row running")

    def forbidden_reconciler(*_args, **_kwargs):
        raise AssertionError("children uncertainty must not start the main-run reconciler")

    monkeypatch.setattr(runtime, "_release_pool_route", fake_pool_release)
    monkeypatch.setattr(runtime, "_release_durable_lease", forbidden_db_release)
    monkeypatch.setattr(runtime, "_schedule_orphan_reconciliation", forbidden_reconciler)

    async def run_case():
        await runtime._release_durable_active_run(state, status="failed")

    anyio.run(run_case)

    assert pool_calls == [(state.run_route, state.session_id, False)]


def test_confirmed_children_reconciler_waits_for_quiescence_then_releases_pool_before_db(
    monkeypatch,
):
    state = _openshell_release_state(
        runtime_terminal_confirmed=False,
        runtime_children_terminal_confirmed=True,
    )
    statuses = [
        hermes_client.HermesRunStatus(
            run_id=state.run_id,
            status="running",
            quiesced=False,
        ),
        hermes_client.HermesRunStatus(
            run_id=state.run_id,
            status="completed",
            quiesced=True,
        ),
    ]
    calls = []

    async def fake_renew(current):
        assert current is state
        calls.append("renew")
        return True

    async def fake_status(run_id, *, profile, route):
        assert (run_id, profile, route) == (state.run_id, state.profile, state.run_route)
        current = statuses.pop(0)
        calls.append(("status", current.write_quiesced))
        return current

    async def fake_pool_release(route, *, session_id, terminal_confirmed):
        assert route is state.run_route
        assert session_id == state.session_id
        assert terminal_confirmed is True
        calls.append("pool_release")
        return True

    async def fake_db_release(profile, session_id, run_id, owner_id, *, status):
        assert (profile, session_id, run_id, owner_id, status) == (
            state.profile,
            state.session_id,
            state.run_id,
            state.owner_id,
            "succeeded",
        )
        calls.append("db_release")
        return True

    async def fake_sleep(_seconds):
        calls.append("sleep")

    monkeypatch.setattr(runtime, "_renew_durable_active_run", fake_renew)
    monkeypatch.setattr(runtime, "_get_routed_run_status", fake_status)
    monkeypatch.setattr(runtime, "_release_pool_route", fake_pool_release)
    monkeypatch.setattr(runtime, "_release_durable_lease", fake_db_release)
    monkeypatch.setattr(runtime.asyncio, "sleep", fake_sleep)

    async def run_case():
        await runtime._reconcile_orphaned_main_run(state, status="succeeded")

    anyio.run(run_case)

    assert statuses == []
    assert calls == [
        "renew",
        ("status", False),
        "sleep",
        "renew",
        ("status", True),
        "pool_release",
        "sleep",
        "renew",
        "db_release",
    ]


def test_required_recovery_not_ready_rejects_before_pool_acquire(monkeypatch):
    state = _openshell_release_state(
        runtime_terminal_confirmed=False,
        runtime_children_terminal_confirmed=True,
    )

    async def forbidden_acquire(*_args, **_kwargs):
        raise AssertionError("readiness gate must run before pool admission")

    monkeypatch.setattr(openshell_pool_recovery, "recovery_required", lambda: True)
    monkeypatch.setattr(openshell_pool_recovery, "recovery_ready", lambda: False)
    monkeypatch.setattr(runtime.openshell_pool_adapter, "acquire_wait_async", forbidden_acquire)

    async def run_case():
        with pytest.raises(RuntimeError, match="^openshell_pool_recovery_not_ready$"):
            await runtime._acquire_pool_route(
                state.run_route,
                session_id="user-1-analysis-recovery-not-ready",
                tenant_id="default",
                user_id="1",
            )

    anyio.run(run_case)
