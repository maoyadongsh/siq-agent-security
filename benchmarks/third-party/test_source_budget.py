"""Reject false capacity evidence and check exact ZIP framing independently."""
import hashlib

import pytest
import source_budget_trial as budget
from source_import_scoring import canonical


def fixture(monkeypatch):
    monkeypatch.setattr(budget, 'original_score', lambda *_: {'checks': {}})
    tree = {'files': [{'path': 'SKILL.md', 'bytes': 1, 'sha256': 'a' * 64, 'executable': False}], 'directories': []}
    digest = hashlib.sha256(canonical(tree)).hexdigest()
    p, raw = {'boundary_fixtures': {}}, {'http': []}
    for axis in budget.LIMITS:
        for suffix in ('limit', 'over', 'recovery'):
            name = axis + '_' + suffix
            p['boundary_fixtures'][name] = {'tree': tree, 'artifact_digest': digest}
            raw['http'].append({'id': name, 'body': {'import': {**tree, 'artifact_digest': digest}}, 'request': {'import_id': axis if suffix != 'limit' else axis + '-control'}, 'before_directories': [], 'after_directories': []})
    return p, raw


def test_budget_evidence_control(monkeypatch):
    p, raw = fixture(monkeypatch)
    assert budget.score(p, raw)['all_passed']


@pytest.mark.parametrize('mutation', ['empty_directory_residue', 'missing_directory_observation', 'missing_row', 'different_recovery_id', 'wrong_tree', 'wrong_digest'])
def test_budget_evidence_rejects_missing_or_wrong_evidence(monkeypatch, mutation):
    p, raw = fixture(monkeypatch)
    if mutation == 'empty_directory_residue': raw['http'][1]['after_directories'] = ['blobs/partial/payload']
    if mutation == 'missing_directory_observation': raw['http'][1].pop('before_directories')
    if mutation == 'missing_row': raw['http'].pop(0)
    if mutation == 'different_recovery_id': raw['http'][2]['request']['import_id'] = 'unrelated'
    if mutation == 'wrong_tree': raw['http'][0]['body']['import']['directories'] = ['unexpected']
    if mutation == 'wrong_digest': raw['http'][0]['body']['import']['artifact_digest'] = '0' * 64
    assert not budget.score(p, raw)['all_passed']


def test_exact_archive_size_has_valid_end_record(tmp_path):
    path = tmp_path / 'stored.zip'
    metadata = budget.create_fixture(path, 'archive', 32768)
    assert metadata['metrics']['archive'] == 32768
    raw = path.read_bytes()
    # Empty ZIP comment: EOCD must end exactly at the physical file boundary.
    assert raw[-22:-18] == b'PK\x05\x06'
    assert raw[-2:] == b'\0\0'


def test_implicit_directory_depth_is_counted(tmp_path):
    metadata = budget.create_fixture(tmp_path / 'depth.zip', 'depth', 16)
    assert metadata['metrics']['depth'] == 16
    assert metadata['metrics']['directories'] == 15
    assert metadata['metrics']['files'] == 2
