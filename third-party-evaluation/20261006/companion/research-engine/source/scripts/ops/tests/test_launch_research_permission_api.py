import hashlib
import json

import pytest

from scripts.ops import launch_research_permission_api as launch


def original():
    return {'SIQ_BACKEND_HOST': '127.0.0.1', 'SIQ_BACKEND_PORT': '18081',
            'SIQ_AUTH_SECRET_KEY': 'synthetic-not-a-credential', 'SIQ_OPENSHELL_POOL_RECOVERY_ENABLED': '1'}


def test_protected_mode_preserves_auth_and_uses_host_authority_endpoint():
    before = original()
    result = launch.configured_environment(before, mode='protected', port=18081)
    assert result['SIQ_AUTH_SECRET_KEY'] == before['SIQ_AUTH_SECRET_KEY']
    assert result['SIQ_OPENSHELL_REQUEST_BACKEND'] == 'qwen38'
    assert result['SIQ_OPENSHELL_REQUEST_DEPLOYMENT'] == 'host'
    assert result['SIQ_OPENSHELL_DATA_CLASSIFICATION'] == 'confidential_local'
    assert before == original()


def test_rollback_and_staging_do_not_take_new_authority():
    before = original()
    before['SIQ_OPENSHELL_REQUEST_CANDIDATE_IMAGE_RECORD'] = '/synthetic/ignored'
    rollback = launch.configured_environment(before, mode='rollback', port=18081)
    staging = launch.configured_environment(before, mode='protected', port=18083)
    assert rollback['SIQ_OPENSHELL_REQUEST_BACKEND'] == 'legacy'
    assert 'SIQ_OPENSHELL_REQUEST_CANDIDATE_IMAGE_RECORD' not in rollback
    assert staging['SIQ_OPENSHELL_POOL_RECOVERY_ENABLED'] == '0'
    assert staging['SIQ_BACKEND_PORT'] == '18083'


@pytest.mark.parametrize('key', ['SIQ_ENV', 'SIQ_DEPLOYMENT_PROFILE'])
@pytest.mark.parametrize('mode', ['protected', 'rollback'])
def test_production_environment_is_never_reclassified_as_local(key, mode):
    before = original()
    before[key] = 'production'
    with pytest.raises(ValueError, match='api_local_deployment_invalid'):
        launch.configured_environment(before, mode=mode, port=18081)


def test_private_environment_rejects_symlink_hardlink_and_public_mode(tmp_path):
    path = tmp_path / 'private.json'
    path.write_text(json.dumps(original()))
    path.chmod(0o600)
    assert launch.private_json(path) == original()
    alias = tmp_path / 'alias'
    alias.symlink_to(path)
    with pytest.raises(ValueError):
        launch.private_json(alias)
    alias.unlink()
    alias.hardlink_to(path)
    with pytest.raises(ValueError):
        launch.private_json(path)
    alias.unlink()
    path.chmod(0o644)
    with pytest.raises(ValueError):
        launch.private_json(path)


def test_manifest_tamper_and_source_drift_fail_before_start(tmp_path, monkeypatch):
    monkeypatch.setattr(launch, 'ROOT', tmp_path)
    own = tmp_path / 'scripts/ops/launch_research_permission_api.py'
    own.parent.mkdir(parents=True)
    own.write_text('owned fixture')
    monkeypatch.setattr(launch, '__file__', str(own))
    main = tmp_path / 'apps/api/main.py'
    main.parent.mkdir(parents=True)
    main.write_text('main fixture')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 'siq.research-api-source-manifest.v1',
        'source_sha256': {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in [own, main]}}))
    digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
    launch.validate_sources(manifest, digest)
    with pytest.raises(ValueError):
        launch.validate_sources(manifest, '0' * 64)
    main.write_text('changed')
    with pytest.raises(ValueError, match='frozen_source_changed'):
        launch.validate_sources(manifest, digest)
