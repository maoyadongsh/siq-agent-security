"""A dispatched run losing authority must not look like an admission conflict."""
import asyncio
import json

import pytest

from services import agent_chat_runtime as runtime
from services.hermes_client import StreamEvent


@pytest.mark.asyncio
async def test_nonstream_lost_authority_returns_failure_and_finalizes_failed(monkeypatch):
    saved, finalized = [], []

    async def yes(*args, **kwargs):
        return True

    async def no(*args, **kwargs):
        return False

    async def noop(*args, **kwargs):
        return None

    async def prepare(*args, **kwargs):
        return runtime.ChatRequestEnvelope(all_attachments=[], message_hash='authority-loss', user_display_message='probe')

    async def preflight(*args, **kwargs):
        return runtime.ChatRunPreflightContext(history=[], local_memory_context=None, attachments=[])

    async def images(*args, **kwargs):
        return None, True

    async def create(*args, **kwargs):
        return 'run-authority-loss'

    async def collect(*args, **kwargs):
        return 'unconfirmed model success'

    async def save(session, role, content, *args, **kwargs):
        saved.append((role, content))

    async def release(state, *, status):
        finalized.append((status, state.terminal_result))
        if state.lease_heartbeat_task:
            state.lease_heartbeat_task.cancel()
            await asyncio.gather(state.lease_heartbeat_task, return_exceptions=True)

    for name, value in {
        '_prepare_chat_request_envelope': prepare, 'build_wiki_catalog_reply': lambda _: None,
        '_load_chat_run_preflight_context': preflight, 'wait_for_pdf_attachment_parses': noop,
        '_attachments_with_fresh_metadata': lambda x: x, 'save_message': save,
        'analyze_images_with_primary_model': images,
        'build_hermes_run_input': lambda message, **kwargs: {'message': message, **kwargs},
        'create_run': create, 'collect_run_result': collect, '_claim_durable_active_run': yes,
        '_renew_durable_provisional_claim': yes, '_bind_durable_active_run': yes,
        '_active_run_ownership_is_current': no, '_release_durable_active_run': release,
    }.items():
        monkeypatch.setattr(runtime, name, value)
    reply = await runtime._collect_chat_reply_impl('probe', object(), session_id='authority-loss',
        profile='siq_assistant', enforce_evidence_contract=False)
    assert reply == runtime._ACTIVE_RUN_AUTHORITY_LOST_MESSAGE
    assert reply != runtime._ACTIVE_RUN_CONFLICT_MESSAGE
    assert saved == [('user', 'probe')]
    assert len(finalized) == 1
    status, terminal = finalized[0]
    assert status == terminal.status == 'failed'
    assert terminal.error_code == 'active_run_lease_lost' and terminal.retryable is False
    assert runtime._active_key('siq_assistant', 'authority-loss') not in runtime.ACTIVE_RUNS


@pytest.mark.asyncio
async def test_stream_lost_authority_is_terminal_nonretryable_error(monkeypatch):
    state = runtime.ActiveRunState(profile='siq_assistant', session_id='authority-loss-stream', run_id='run-lost-stream')

    async def stream(*args, **kwargs):
        yield StreamEvent(type='done', text='unconfirmed model success')

    async def no(*args, **kwargs):
        return False

    async def cleanup(*args, **kwargs):
        return None

    monkeypatch.setattr(runtime, '_stream_routed_run', stream)
    monkeypatch.setattr(runtime, '_active_run_ownership_is_current', no)
    monkeypatch.setattr(runtime, '_stop_and_confirm_routed_run', no)
    monkeypatch.setattr(runtime, '_release_durable_active_run', cleanup)
    await runtime._collect_stream_run(state, None, enforce_evidence_contract=False)
    errors = [json.loads(e['data']) for e in state.events if e['event'] == 'error']
    assert len(errors) == 1
    assert errors[0]['message'] == runtime._ACTIVE_RUN_AUTHORITY_LOST_MESSAGE
    assert errors[0]['error_code'] == 'active_run_lease_lost' and errors[0]['retryable'] is False
    assert state.status == 'failed' and state.terminal_result.status == 'failed'
    assert not any(e['event'] == 'done' for e in state.events)
