"""Only synchronization hook behavior; these tests are not runtime evidence."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def hook(tmp_path, monkeypatch):
    source = Path(__file__).parents[1] / 'fixtures/research_skill_sync.py'
    spec = importlib.util.spec_from_file_location('research_sync_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / 'home'
    skill = home / 'skills/research-permissions-reader/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('Controlled source text.')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'skills': {'research-permissions-reader': {
        'sha256': hashlib.sha256(skill.read_bytes()).hexdigest()}}}))
    module.MANIFEST, module.DIRECTORY = manifest, tmp_path / 'sync'
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('SIQ_AGENT_SECURITY_SESSION_NAMESPACE', 'managed-test')
    monkeypatch.setenv('SIQ_AGENT_SECURITY_RUNTIME_IDENTITY_ID', 'ri-' + 'a' * 32)
    return module, skill


def test_managed_tool_without_context_is_blocked(hook):
    module, _ = hook
    assert module._pre_tool(session_id='s', task_id='t')['action'] == 'block'


@pytest.mark.parametrize('message', ['', 'SIQ_PERMISSION_SKILL=../../escape',
    'SIQ_PERMISSION_SKILL=research-permissions-reader SIQ_PERMISSION_SKILL=research-permissions-writer'])
def test_ambiguous_or_unapproved_selection_is_rejected(hook, message):
    module, _ = hook
    with pytest.raises(RuntimeError, match='selection_missing'):
        module._pre_llm(session_id='s', task_id='t', user_message=message)
    assert module._pre_tool(session_id='s', task_id='t')['action'] == 'block'


def test_drifted_skill_never_reaches_native_loader(hook):
    module, skill = hook
    skill.write_text('Changed after installation.')
    with pytest.raises(RuntimeError, match='content_mismatch'):
        module._pre_llm(session_id='s', task_id='t', user_message='SIQ_PERMISSION_SKILL=research-permissions-reader')
    assert not module.DIRECTORY.exists()


@pytest.mark.parametrize('valid_ack', [True, False])
@pytest.mark.parametrize('control', ['', 'revoke-context', 'drift-installation', 'revoke-grant', 'revoke-business-grant', 'relay-unresponsive', 'tool-utility'])
def test_ack_is_bound_to_loaded_content_and_native_task(hook, monkeypatch, valid_ack, control):
    module, _ = hook
    native = ModuleType('tools.skills_tool')
    calls = []
    def skill_view(**kwargs):
        calls.append(kwargs)
        return json.dumps({'success': True, 'content': 'Actual native loader output.'})
    native.skill_view = skill_view
    monkeypatch.setitem(sys.modules, 'tools.skills_tool', native)
    adapter = ModuleType('controlled_adapter_test')
    adapter._CFG = {}
    adapter._authority_session_id = lambda sid: 'managed:' + sid
    adapter._enroll_runtime_session = lambda sid: sid == 'managed:s'
    monkeypatch.setitem(sys.modules, 'controlled_adapter_test', adapter)
    write = module._write_once
    def write_with_ack(path, value):
        write(path, value)
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        (module.DIRECTORY / 'ack.json').write_text(json.dumps({
            'request_sha256': digest if valid_ack else 'wrong', 'context_id': 'sec-unit-test'}))
    monkeypatch.setattr(module, '_write_once', write_with_ack)
    message = 'SIQ_PERMISSION_SKILL=research-permissions-reader' + (
        ' SIQ_PERMISSION_CONTROL=' + control if control else '')
    if valid_ack:
        result = module._pre_llm(session_id='s', task_id='t', user_message=message)
        assert 'Actual native loader output.' in result['context']
        assert module._controls.get(('s', 't'), '') == control
        assert module._pre_tool(session_id='s', task_id='t') is None
        assert module._pre_tool(session_id='s', task_id='different')['action'] == 'block'
    else:
        with pytest.raises(RuntimeError, match='ack_mismatch'):
            module._pre_llm(session_id='s', task_id='t', user_message=message)
        assert module._pre_tool(session_id='s', task_id='t')['action'] == 'block'
    assert calls == [{'name': 'research-permissions-reader', 'task_id': 't', 'preprocess': False}]


@pytest.mark.parametrize('valid_ack', [True, False])
def test_checkpoint_pauses_after_real_effect_and_binds_ack(hook, monkeypatch, tmp_path, valid_ack):
    module, _ = hook
    module.DIRECTORY.mkdir()
    module._bound.add(('s', 't'))
    module._controls[('s', 't')] = 'revoke-context'
    target = tmp_path / 'permission-result.md'
    target.write_text('AUTHORIZED_STAGE_ONE')
    write = module._write_once
    def write_with_ack(path, value):
        write(path, value)
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        (module.DIRECTORY / 'checkpoint-ack.json').write_text(json.dumps({
            'checkpoint_sha256': digest if valid_ack else 'other checkpoint'}))
    monkeypatch.setattr(module, '_write_once', write_with_ack)
    arguments = dict(tool_name='write_file', args={'path': str(target)}, result={'success': True},
                     session_id='s', task_id='t', tool_call_id='call-1')
    if valid_ack:
        module._post_tool(**arguments)
        module._post_tool(**arguments)  # Exactly one owned checkpoint per task.
    else:
        with pytest.raises(RuntimeError, match='checkpoint_ack_mismatch'):
            module._post_tool(**arguments)
    record = json.loads((module.DIRECTORY / 'checkpoint.json').read_text())
    assert record['file_sha256'] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert record['tool_call_id'] == 'call-1'
    # A valid release lets SIQ decide permission; a mismatched control release
    # is an invalid experiment and must not let tools continue.
    value = module._pre_tool(session_id='s', task_id='t')
    assert value is None if valid_ack else value['action'] == 'block'


def test_failed_write_does_not_become_positive_checkpoint(hook, tmp_path):
    module, _ = hook
    module._controls[('s', 't')] = 'revoke-context'
    target = tmp_path / 'permission-result.md'
    target.write_text('old bytes')
    module._post_tool(tool_name='write_file', args={'path': str(target)}, result={'error': 'denied'},
                      session_id='s', task_id='t')
    assert not module.DIRECTORY.exists()


def test_tool_catalog_observer_records_only_schemas_without_mutating_request(hook):
    import copy
    module, _ = hook
    module.DIRECTORY.mkdir()
    module._controls[('s', 't')] = 'tool-utility'
    request = {'headers': {'Authorization': 'never-record-this'}, 'body': {
        'messages': [{'role': 'user', 'content': 'private-test-message'}],
        'tools': [{'type': 'function', 'function': {'name': 'patch',
            'parameters': {'type': 'object', 'properties': {'path': {'type': 'string'}}}}}]}}
    original = copy.deepcopy(request)
    assert module._pre_api_request(session_id='s', task_id='t', api_request_id='r', request=request) is None
    raw = (module.DIRECTORY / 'tool-catalog.jsonl').read_text()
    assert 'never-record-this' not in raw and 'private-test-message' not in raw and 'headers' not in raw
    assert json.loads(raw)['tools'][0]['name'] == 'patch'
    assert request == original


def test_catalog_control_never_pauses_post_tool(hook, monkeypatch, tmp_path):
    module, _ = hook
    module._controls[('s', 't')] = 'tool-utility'
    def unexpected(_):
        raise AssertionError('catalog observation must not pause execution')
    monkeypatch.setattr(module, '_await_checkpoint', unexpected)
    target = tmp_path / 'result'
    target.write_text('legitimate write')
    module._post_tool(tool_name='write_file', args={'path': str(target)}, result={'success': True}, session_id='s', task_id='t')
    assert not module.DIRECTORY.exists()


@pytest.mark.parametrize('valid_ack', [True, False])
def test_catalog_finalization_exports_before_teardown_and_checks_hash(hook, monkeypatch, valid_ack):
    module, _ = hook
    module.DIRECTORY.mkdir()
    module._controls[('s', 't')] = 'tool-utility'
    raw = b'{"tools":[]}\n'
    (module.DIRECTORY / 'tool-catalog.jsonl').write_bytes(raw)
    def release(_):
        (module.DIRECTORY / 'catalog-ack.json').write_text(json.dumps({
            'catalog_sha256': hashlib.sha256(raw).hexdigest() if valid_ack else 'wrong'}))
    monkeypatch.setattr(module.time, 'sleep', release)
    if valid_ack:
        module._post_llm(session_id='s', task_id='t')
        module._post_llm(session_id='s', task_id='t')
        assert ('s', 't') in module._catalog_finalized
    else:
        with pytest.raises(RuntimeError, match='export_ack_mismatch'):
            module._post_llm(session_id='s', task_id='t')
        assert ('s', 't') not in module._catalog_finalized
    completed = json.loads((module.DIRECTORY / 'catalog-complete.json').read_text())
    assert completed['request_count'] == 1 and completed['native_session_id'] == 's'


@pytest.mark.parametrize('payload', [{'body': {'tools': 'invalid'}}, {'body': {'tools': [{'function': {'name': '../invalid'}}]}}])
def test_invalid_catalog_is_not_exported_as_evidence(hook, payload):
    module, _ = hook
    module.DIRECTORY.mkdir()
    module._controls[('s', 't')] = 'tool-utility'
    module._pre_api_request(session_id='s', task_id='t', request=payload)
    assert not (module.DIRECTORY / 'tool-catalog.jsonl').exists()


@pytest.mark.parametrize('valid_ack', [True, False])
def test_recovery_waits_for_ack_bound_to_actual_pending_bytes(hook, monkeypatch, tmp_path, valid_ack):
    module, _ = hook
    module.DIRECTORY.mkdir()
    module._bound.add(('s', 't'))
    module._controls[('s', 't')] = 'relay-unresponsive'
    module.PENDING = tmp_path / 'pending.jsonl'
    raw = b'{"signed":false,"outcome":"deny"}\n'
    module.PENDING.write_bytes(raw)
    def release(_):
        (module.DIRECTORY / 'recovery-ack.json').write_text(json.dumps({
            'pending_sha256': hashlib.sha256(raw).hexdigest() if valid_ack else 'wrong'}))
    monkeypatch.setattr(module.time, 'sleep', release)
    args = {'path': '/controlled/output', 'content': 'test data not recorded'}
    result = module._pre_tool(session_id='s', task_id='t', tool_name='write_file',
                              tool_call_id='call-2', args=args)
    if valid_ack:
        assert result is None
        trace = (module.DIRECTORY / 'attempts.jsonl').read_text()
        record = json.loads(trace)
        assert record['tool_call_id'] == 'call-2'
        assert record['params_sha256'] == hashlib.sha256(json.dumps(args, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        assert 'test data not recorded' not in trace
    else:
        assert result['action'] == 'block'
        assert not (module.DIRECTORY / 'attempts.jsonl').exists()


@pytest.mark.parametrize('next_hook', ['tool', 'model'])
@pytest.mark.parametrize('valid_ack', [True, False])
@pytest.mark.parametrize('control', ['revoke-business-grant', 'relay-unresponsive', 'drift-installation'])
def test_business_checkpoint_finishes_observers_before_waiting_next_operation(hook, monkeypatch, tmp_path, next_hook, valid_ack, control):
    module, _ = hook
    module.DIRECTORY.mkdir()
    module._bound.add(('s', 't'))
    module._controls[('s', 't')] = control
    target = tmp_path / 'permission-result.md'
    target.write_text('AUTHORIZED_STAGE_ONE')
    calls = []
    def acknowledge(_):
        calls.append('wait')
        checkpoint = json.loads((module.DIRECTORY / 'checkpoint.json').read_text())
        digest = hashlib.sha256(json.dumps(checkpoint, sort_keys=True).encode()).hexdigest()
        (module.DIRECTORY / 'checkpoint-ack.json').write_text(json.dumps({
            'checkpoint_sha256': digest if valid_ack else 'different-checkpoint'}))
    monkeypatch.setattr(module.time, 'sleep', acknowledge)
    module._post_tool(tool_name='write_file', args={'path': str(target)}, result={'success': True},
                      session_id='s', task_id='t', tool_call_id='call-1')
    assert not calls  # Native SIQ post observer can now run; no early blocking.
    if next_hook == 'tool':
        value = module._pre_tool(session_id='s', task_id='t')
        assert value is None if valid_ack else value['action'] == 'block'
    elif valid_ack:
        assert module._pre_llm(session_id='s', task_id='t') is None
    else:
        with pytest.raises(RuntimeError, match='checkpoint_ack_mismatch'):
            module._pre_llm(session_id='s', task_id='t')
    assert calls == ['wait']
    assert (('s', 't') in module._pending_checkpoints) is not valid_ack
