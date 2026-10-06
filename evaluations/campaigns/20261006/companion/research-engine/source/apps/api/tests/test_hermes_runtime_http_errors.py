import json
from types import SimpleNamespace

import main
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from services.hermes_client import HermesRuntimeSelectionError
from services.qwen38_request_selector import RequestSelectionError


@pytest.mark.parametrize('code,status', [
    ('hermes_runtime_request_override_forbidden', 403),
    ('openshell_canary_session_not_authorized', 403),
    ('openshell_canary_company_not_authorized', 403),
    ('openshell_canary_company_context_required', 400),
    ('openshell_canary_not_active', 503),
    ('private-secret-and-path', 503),
])
def test_registered_handler_returns_bounded_permission_or_availability_error(code, status):
    app = FastAPI()
    app.add_exception_handler(HermesRuntimeSelectionError, main.app.exception_handlers[HermesRuntimeSelectionError])

    @app.get('/probe')
    def denied():
        raise HermesRuntimeSelectionError(code) from ValueError('private-cause')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/probe')
    assert response.status_code == status and response.headers['cache-control'] == 'no-store'
    assert response.json()['retryable'] is False
    assert 'private-' not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize('error,code', [
    (HermesRuntimeSelectionError('hermes_runtime_request_override_forbidden'), 'runtime_access_denied'),
    (HermesRuntimeSelectionError('private-secret-and-path'), 'runtime_selection_unavailable'),
    (RequestSelectionError('qwen_request_selection_denied'), 'request_access_denied'),
])
async def test_stream_preflight_error_is_terminal_and_iterator_is_closed(monkeypatch, error, code):
    from services import agent_chat_runtime_impl as runtime

    monkeypatch.setenv('SIQ_OPENSHELL_REQUEST_BACKEND', 'legacy')
    monkeypatch.setenv('SIQ_OPENSHELL_DATA_CLASSIFICATION', 'public_research')
    state = {'attempts': 0, 'closed': False}

    async def rejected(*args, **kwargs):
        state['attempts'] += 1
        try:
            raise error
            yield  # Retain async-generator shape; no success event is emitted.
        finally:
            state['closed'] = True

    monkeypatch.setattr(runtime, '_stream_chat_reply_impl', rejected)
    events = [e async for e in runtime.stream_chat_reply('synthetic', SimpleNamespace(), SimpleNamespace(),
        profile='siq_analysis', session_id='user-17-analysis-probe', tenant_id='default', user_id='17')]
    assert state == {'attempts': 1, 'closed': True}
    assert [e['event'] for e in events] == ['error']
    body = json.loads(events[0]['data'])
    assert body['error_code'] == code and body['retryable'] is False
    assert 'private-secret-and-path' not in events[0]['data']
