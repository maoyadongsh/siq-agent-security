"""Adversarial checks for source evidence scoring, including transient harm."""
import base64
import copy

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from source_import_scoring import score


def fixture():
    request = {'id': 'git_closed', 'route': '/v1/skill-imports/git', 'body': {'import_id': 'si-fixture'}, 'status': 503, 'error': 'skill_import_git_transport_unavailable'}
    key = Ed25519PrivateKey.from_private_bytes(b'x' * 32).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    guard = {'healthy': True, 'mutation_observed': False, 'after': {'exists': False}}
    raw = {'public_key': base64.b64encode(key).decode(), 'http': [{'id': request['id'], 'route': request['route'], 'request': request['body'], 'status': 503,
            'body': {'error': request['error']}, 'before': {}, 'after': {}}],
           'calibration': [{'expected': v, 'observation': {'healthy': True, 'mutation_observed': v}} for v in (False, True)],
           'guards': [copy.deepcopy(guard), copy.deepcopy(guard)], 'cleanup': {'daemon_stopped': True}, 'authority_files': [], 'error': None}
    return {'requests': [request]}, raw


def test_baseline_is_scoped_management_success():
    p, raw = fixture()
    assert score(p, raw)['all_passed']


@pytest.mark.parametrize('mutation', ['wrong_status', 'wrong_reason', 'publication', 'missing_request', 'wrong_route', 'uncalibrated', 'observer_failed', 'grant_created', 'daemon_alive'])
def test_reject_inadequate_evidence(mutation):
    p, raw = fixture()
    if mutation == 'wrong_status': raw['http'][0]['status'] = 401
    if mutation == 'wrong_reason': raw['http'][0]['body']['error'] = 'unrelated_unavailable'
    if mutation == 'publication': raw['http'][0]['after'] = {'records/unauthorized.json': {}}
    if mutation == 'missing_request': raw['http'] = []
    if mutation == 'wrong_route': raw['http'][0]['route'] = '/unrelated'
    if mutation == 'uncalibrated': raw['calibration'] = []
    if mutation == 'observer_failed': raw['guards'][0]['healthy'] = False
    if mutation == 'grant_created': raw['authority_files'] = ['grants/unauthorized.json']
    if mutation == 'daemon_alive': raw['cleanup']['daemon_stopped'] = False
    assert not score(p, raw)['all_passed']


def test_transient_harm_survives_later_observer_failure():
    p, raw = fixture()
    raw['guards'][0].update(healthy=False, mutation_observed=True)
    raw['public_key'] = None
    result = score(p, raw)
    assert result['harm_observed'] is True
    assert not result['all_passed']
