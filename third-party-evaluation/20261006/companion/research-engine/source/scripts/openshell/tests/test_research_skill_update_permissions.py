"""An HTTP error alone cannot count as the required unapproved rejection."""
from types import SimpleNamespace

import httpx
import pytest

from scripts.openshell import prove_research_skill_update_permissions as proof


@pytest.mark.parametrize('status,error,accepted', [(409, 'skill_install_changed', True),
    (200, 'skill_install_changed', False), (409, 'other_reason', False),
    (401, 'unauthorized', False), (503, 'unavailable', False)])
def test_rejection_requires_the_exact_product_conflict(monkeypatch, status, error, accepted):
    original = httpx.Client
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'error': error})
    monkeypatch.setattr(proof.httpx, 'Client', lambda **kw: original(**kw, transport=httpx.MockTransport(handle)))
    authority = SimpleNamespace(endpoint='http://127.0.0.1:47811', admin='unit-test-token')
    if accepted:
        assert proof.rejected(authority, '/v1/skill-installations/plans', {})['HTTP_status'] == 409
    else:
        with pytest.raises(RuntimeError, match='candidate_update_rejection_unconfirmed'):
            proof.rejected(authority, '/v1/skill-installations/plans', {})
    assert len(calls) == 1 and calls[0].method == 'POST'
