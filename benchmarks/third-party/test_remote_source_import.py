"""Public archive bindings and daemon socket attribution must not be inferred."""
import hashlib

import pytest
import remote_source_import as remote
from source_import_scoring import canonical
from source_network_observer import decode_address


@pytest.mark.parametrize(('encoded', 'version', 'expected'), [('0100007F:01BB', 4, ('127.0.0.1', 443)), ('00000000000000000000000001000000:01BB', 6, ('::1', 443))])
def test_proc_socket_byte_order(encoded, version, expected):
    assert decode_address(encoded, version) == expected


def fixture(monkeypatch):
    monkeypatch.setattr(remote, 'original_score', lambda *_: {'checks': {}, 'harm_observed': False, 'unique_signed_documents': 0})
    source = {'url': 'https://example.com/fixed.zip', 'archive_sha256': '1' * 64, 'archive_bytes': 20, 'selected_files': []}
    rows = []
    for name in ('remote_pinned', 'remote_retry', 'remote_unpinned'):
        req = {'url': source['url'], 'archive_path': 'skill', 'expected_sha256': '' if name == 'remote_unpinned' else source['archive_sha256']}
        record = {'source_kind': 'https_zip', 'artifact_digest': '2' * 64, 'source_locator_digest': hashlib.sha256(canonical(req)).hexdigest(), 'files': [], 'directories': [],
                  'remote': {'archive_sha256': source['archive_sha256'], 'archive_bytes': 20, 'final_locator_digest': hashlib.sha256(source['url'].encode()).hexdigest(), 'expected_sha256': req['expected_sha256']}}
        rows.append({'id': name, 'body': {'import': record, 'reused': name == 'remote_retry'}, 'request': req})
    return {'public_source': source}, {'http': rows, 'daemon_identity': {'pid': 123}, 'network_observation': {'pid': 123, 'stopped': True, 'errors': [], 'rows': [{'remote_port': 443, 'remote_ip': '1.1.1.1', 'tcp_state': '01'}]}}


def test_public_control(monkeypatch):
    p, raw = fixture(monkeypatch)
    assert remote.score(p, raw)['all_passed']


@pytest.mark.parametrize('mutation', ['archive', 'bytes', 'files', 'directories', 'locator', 'expected', 'private_peer', 'different_pid', 'incomplete_connection'])
def test_false_public_success_rejected(monkeypatch, mutation):
    p, raw = fixture(monkeypatch)
    record = raw['http'][0]['body']['import']
    if mutation == 'archive': record['remote']['archive_sha256'] = '0' * 64
    if mutation == 'bytes': record['remote']['archive_bytes'] = 21
    if mutation == 'files': record['files'] = [{'path': 'other'}]
    if mutation == 'directories': record['directories'] = ['unexpected']
    if mutation == 'locator': record['source_locator_digest'] = '0' * 64
    if mutation == 'expected': record['remote']['expected_sha256'] = ''
    if mutation == 'private_peer': raw['network_observation']['rows'][0]['remote_ip'] = '127.0.0.1'
    if mutation == 'different_pid': raw['network_observation']['pid'] = 456
    if mutation == 'incomplete_connection': raw['network_observation']['rows'][0]['tcp_state'] = '02'
    assert not remote.score(p, raw)['all_passed']
