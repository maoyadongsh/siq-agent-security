"""Fixture framing and exact full-store evidence controls."""
import pytest
import source_limits_trial as limits


@pytest.mark.parametrize(('axis', 'boundary'), [('component', 128), ('path', 512), ('central', 4 << 20)])
def test_exact_and_over_have_independent_boundaries(tmp_path, axis, boundary):
    for delta in (0, 1):
        meta = limits.fixture(tmp_path / f'{axis}-{delta}.zip', axis, boundary + delta)
        key = {'component': 'component_bytes', 'path': 'path_bytes', 'central': 'central_bytes'}[axis]
        assert meta[key] == boundary + delta
        assert meta['metrics']['archive'] < 32 << 20
        assert meta['metrics']['total'] == 84
        assert meta['metrics']['depth'] <= 4


def fixture(monkeypatch):
    monkeypatch.setattr(limits, 'original_score', lambda *_: {'checks': {}})
    tree = {'files': [], 'directories': [], 'artifact_digest': 'a' * 64}
    p = {'requests': [], 'record_fixtures': {}}
    snapshot = {'records/si-' + str(i) + '.json': {} for i in range(64)}
    dirs = ['blobs/si-' + str(i) for i in range(64)]
    rows = []
    for i in range(64):
        name = 'normal' if i == 0 else str(i)
        p['requests'].append({'id': name, 'status': 201, 'body': {'import_id': 'si-' + str(i)}})
        p['record_fixtures'][name] = {'tree': {'files': [], 'directories': []}, 'artifact_digest': 'a' * 64}
        rows.append({'id': name, 'body': {'import': tree.copy()}, 'before': snapshot.copy(), 'after': snapshot.copy(), 'before_directories': dirs.copy(), 'after_directories': dirs.copy()})
    for name in ('full_retry', 'full_read'):
        p['requests'].append({'id': name, 'status': 200})
        p['record_fixtures'][name] = p['record_fixtures']['normal']
        rows.append({'id': name, 'body': {'import': tree.copy(), 'reused': name == 'full_retry'}, 'before': snapshot.copy(), 'after': snapshot.copy(), 'before_directories': dirs.copy(), 'after_directories': dirs.copy()})
    return p, {'http': rows}


def test_full_store_control(monkeypatch):
    p, raw = fixture(monkeypatch)
    assert limits.score(p, raw)['all_passed']


@pytest.mark.parametrize('mutation', ['extra_record', 'extra_blob', 'missing_record', 'changed_original', 'false_reuse'])
def test_false_full_store_success_rejected(monkeypatch, mutation):
    p, raw = fixture(monkeypatch)
    if mutation == 'extra_record': raw['http'][-1]['after']['records/extra.json'] = {}
    if mutation == 'extra_blob': raw['http'][-1]['after_directories'].append('blobs/extra')
    if mutation == 'missing_record': raw['http'][-1]['after'].pop('records/si-0.json')
    if mutation == 'changed_original': raw['http'][-1]['body']['import']['artifact_digest'] = 'b' * 64
    if mutation == 'false_reuse': raw['http'][-2]['body']['reused'] = False
    assert not limits.score(p, raw)['all_passed']
