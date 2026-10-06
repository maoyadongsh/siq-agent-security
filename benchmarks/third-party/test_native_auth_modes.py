import json

from native_auth_modes import result_matches, score, verify


def test_successful_write_path_is_not_a_block_message():
    call = {'tool': 'write_file', 'outcome': 'allow', 'params': {'path': '/siq-agent-security/output.txt', 'content': 'ok\n'}}
    result = {'bytes_written': 3, 'verified': True, 'resolved_path': call['params']['path']}
    assert result_matches(call, json.dumps(result))
    assert not result_matches(call, json.dumps({**result, 'error': 'siq-agent-security: denied'}))
    assert not result_matches(call, json.dumps({**result, 'bytes_written': 2}))


def test_denial_requires_error_field_not_incidental_path():
    call = {'tool': 'read_file', 'outcome': 'deny'}
    assert not result_matches(call, json.dumps({'resolved_path': '/siq-agent-security/test'}))
    assert result_matches(call, json.dumps({'error': 'siq-agent-security: instance session could not be verified'}))


def test_missing_capture_is_not_no_harm():
    assert score(None, []) == ({}, None)


def test_proxy_rewritten_body_rejected():
    import pytest
    data = {'profile': 'control', 'mode': 'block', 'wire': [{'path': '/v1/decide', 'status': 200,
        'response_utf8': '{"action":"allow"}', 'body': {'action': 'allow'}, 'backend_sha256': '0' * 64, 'client_sha256': '0' * 64}]}
    with pytest.raises(ValueError, match='proxy response differs'):
        verify(data, {'native_auth_fault': 'control', 'enforcement_mode': 'block'}, [])


def test_wrong_mode_cannot_borrow_capture():
    import pytest
    with pytest.raises(ValueError, match='allocation'):
        verify({'profile': 'control', 'mode': 'block', 'wire': []}, {'native_auth_fault': 'control', 'enforcement_mode': 'warn'}, [])
