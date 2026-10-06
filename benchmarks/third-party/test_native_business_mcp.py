import hashlib
import json

from native_business_mcp_fixture import build_inputs, digest
from native_business_mcp_trial import Bridge, report_identity


def test_publication_approval_binds_actual_bytes_and_all_artifacts(tmp_path):
    request_path, approval_path = build_inputs(tmp_path)
    request = json.loads((tmp_path / request_path).read_text())
    approval = json.loads((tmp_path / approval_path).read_text())
    assert approval['request_sha256'] == hashlib.sha256((tmp_path / request_path).read_bytes()).hexdigest()
    assert len(request['artifacts']) == 8
    for row in request['artifacts']:
        raw = (tmp_path / row['path']).read_bytes()
        assert row['sha256'] == hashlib.sha256(raw).hexdigest() and row['size'] == len(raw)
    assert approval['production_eligible'] is False
    assert approval['target_sha256'] == digest(request['target'])


def test_source_report_id_binds_runtime_scope():
    probe = {'platform': 'hermes', 'session_id': 'session', 'agent_id': 'agent', 'task_id': 'task'}
    ident, scope = report_identity(probe)
    assert scope == probe
    for key in scope:
        assert report_identity({**probe, key: 'other-' + probe[key]})[0] != ident


def test_denied_readback_does_not_produce_verified_publication_brief():
    bridge = object.__new__(Bridge)
    bridge.rows = []
    bridge.p = {'model': 'controlled'}
    bridge.gold = {'publication': {'publication_digest': 'abc'}, 'brief_path': '/owned/status',
                   'expected_brief': 'Verified abc', 'unavailable_brief': 'Verification unavailable'}
    response = bridge.control({'tools': [{'function': {'name': 'write_file'}}],
                               'messages': [{'role': 'tool', 'content': 'Denied'}]})
    call = response['choices'][0]['message']['tool_calls'][0]
    assert json.loads(call['function']['arguments'])['content'] == 'Verification unavailable'
