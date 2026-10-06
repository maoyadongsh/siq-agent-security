import json

import pytest
from native_business_mcp_fixture import digest
from native_business_mcp_selection import requests
from verify_native_business_mcp_selection import verify_selection


def test_diagnostics_preserve_signed_string_and_separate_parsing():
    content = json.dumps({'structuredContent': {'report_key': 'synthetic'}})
    scope = {'platform': 'hermes', 'session_id': 'session', 'agent_id': 'agent', 'task_id': 'task'}
    rows = requests('real-parent', scope, content)
    assert len(rows) == 5
    assert rows[1][2]['content'] == content
    assert rows[2][2]['content'] == json.loads(content)
    assert digest(rows[1][2]['content']) != digest(rows[2][2]['content'])
    assert rows[3][2]['content'] == content + ' '
    assert {row[1] for row in rows} == {'/v1/provenance-select', '/v1/provenance-resolve'}
    assert all(row[2]['parent_id'] == 'real-parent' for row in rows[1:])


def test_different_native_result_type_must_not_be_silently_recast():
    with pytest.raises(TypeError, match='shape differs'):
        requests('parent', {}, {'structuredContent': {'report_key': 'synthetic'}})


def test_selection_verifier_rejects_unbound_observer_data():
    with pytest.raises(ValueError, match='original events differ'):
        verify_selection({'selection_observation': {'probes': [], 'error_type': None}}, [])
