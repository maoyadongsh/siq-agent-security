import io
import json
import sys

import pytest
from native_mcp_entry_server import serve
from native_mcp_entry_trial import TOOL, Bridge


def messages(wrong=False):
    return [{'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'method': 'notifications/initialized'}, {'id': 2, 'method': 'tools/list'},
            {'id': 3, 'method': 'tools/call', 'params': {'name': 'lookup', 'arguments': {'path': '/unowned'} if wrong else {}}}]


def test_stdio_actual_roundtrip(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('\n'.join(json.dumps(m) for m in messages())))
    ledger = tmp_path / 'ledger'
    serve({'ledger': str(ledger), 'target': '/owned/report'})
    replies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r['id'] for r in replies] == [1, 2, 3]
    assert replies[-1]['result']['structuredContent']['path'] == '/owned/report'
    assert len([r for r in map(json.loads, ledger.read_text().splitlines()) if r.get('method') == 'tools/call']) == 1


def test_stdio_does_not_accept_caller_selected_resource(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'stdin', io.StringIO('\n'.join(json.dumps(m) for m in messages(True))))
    with pytest.raises(ValueError, match='arguments'):
        serve({'ledger': str(tmp_path / 'ledger'), 'target': '/owned/report'})


def test_no_simulated_mcp_call_when_tool_not_discovered():
    bridge = object.__new__(Bridge)
    bridge.rows = []
    bridge.gold = {'source_path': '/owned/report', 'brief_path': '/owned/brief', 'expected_brief': 'actual report'}
    bridge.p = {'model': 'controlled'}
    response = bridge.control({'tools': [{'function': {'name': 'read_file'}}], 'messages': []})
    assert response['choices'][0]['finish_reason'] == 'stop'
    response = bridge.control({'tools': [{'function': {'name': TOOL}}], 'messages': []})
    assert response['choices'][0]['message']['tool_calls'][0]['function']['name'] == TOOL


def test_actual_deferred_surface_uses_public_tool_call_envelope():
    bridge = object.__new__(Bridge)
    bridge.rows = []
    bridge.gold = {'source_path': '/owned/report', 'brief_path': '/owned/brief', 'expected_brief': 'actual report'}
    bridge.p = {'model': 'controlled'}
    response = bridge.control({'tools': [{'function': {'name': 'tool_call'}}], 'messages': []})
    call = response['choices'][0]['message']['tool_calls'][0]['function']
    assert call['name'] == 'tool_call'
    assert json.loads(call['arguments']) == {'name': TOOL, 'arguments': {}}
