from types import SimpleNamespace

import httpx
import pytest

from scripts.openshell import prove_research_skill_replacement as subject


@pytest.mark.parametrize('status,reason,accepted', [
    (401, 'runtime_identity_required', True),
    (200, 'runtime_identity_required', False),
    (503, 'runtime_identity_required', False),
    (401, 'unrelated_error', False),
    (409, 'runtime_identity_authority_conflict', False),
])
def test_denial_requires_exact_authentication_boundary(monkeypatch, status, reason, accepted):
    real_client = httpx.Client
    def handler(request):
        assert request.headers['authorization'] == 'Bearer old-test-token'
        return httpx.Response(status, json={'error': reason})
    monkeypatch.setattr(subject.httpx, 'Client', lambda **kw: real_client(
        transport=httpx.MockTransport(handler), **kw))
    authority = SimpleNamespace(endpoint='http://127.0.0.1:1', admin='admin-test-token')
    def call():
        return subject.denied(authority, '/v1/runtime-sessions', {'session_id': 'old-session'},
            bearer='old-test-token', status=401, reasons={'runtime_identity_required'})
    if accepted:
        out = call()
        assert out['observation_layer'] == 'public_SIQ_API_not_native_tool'
        assert 'token' not in repr(out)
    else:
        with pytest.raises(RuntimeError, match='replacement_rejection_unconfirmed'):
            call()
