"""Do not infer native discovery from a CLI exit code or unrelated asset."""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enterprise_native_edge import ASSET_NAME, CONFIG, evaluate


def fixture():
    return {'register': {'exit_code': 0}, 'tasks': {'exit_code': 0}, 'state_mode': 0o600, 'device_identity': 'native-device', 'environment_id': 'env-a', 'secret_sha256': 'a' * 64,
            'device_rows': [['edge-1', 'native-device', 'env-a', 'a' * 64]], 'scan': {'task_id': 'task-1'}, 'scope': {'roots': ['/owned/fixture']},
            'scan_status': {'id': 'task-1', 'status': 'delivered', 'payload': {'target_device_identity': 'native-device', 'scope': {'roots': ['/owned/fixture']}}},
            'asset': {'name': ASSET_NAME, 'framework': 'hermes'}, 'asset_evidence_ids': ['ev-1'], 'evidence': [{'id': 'ev-1'}], 'evidence_rows': [['ev-1', 'native-device', hashlib.sha256(CONFIG).hexdigest(), 'signature']],
            'source_before': hashlib.sha256(CONFIG).hexdigest(), 'source_after': hashlib.sha256(CONFIG).hexdigest()}


def test_native_chain_control():
    assert all(evaluate(fixture()).values())


@pytest.mark.parametrize('mutation', ['cli_failed', 'world_readable', 'other_device', 'task_not_delivered', 'unrelated_evidence', 'changed_source'])
def test_native_chain_missing_evidence_rejected(mutation):
    o = fixture()
    if mutation == 'cli_failed': o['tasks']['exit_code'] = 1
    if mutation == 'world_readable': o['state_mode'] = 0o644
    if mutation == 'other_device': o['device_rows'][0][1] = 'other'
    if mutation == 'task_not_delivered': o['scan_status']['status'] = 'pending'
    if mutation == 'unrelated_evidence': o['evidence_rows'][0][0] = 'ev-other'
    if mutation == 'changed_source': o['source_after'] = 'b' * 64
    assert not all(evaluate(o).values())
