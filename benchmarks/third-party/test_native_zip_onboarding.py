"""Reject wrong ZIP/source lineage and false independent read claims."""
import base64
import copy
import hashlib
import io
import stat
import zipfile

import pytest
from native_zip_onboarding import extra_checks
from zip_source_authority import verify_archive_source


def fixture():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        info = zipfile.ZipInfo('SKILL.md', (2026, 1, 1, 0, 0, 0))
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o600) << 16
        z.writestr(info, b'fixture')
    raw = buffer.getvalue()
    digest = hashlib.sha256(raw).hexdigest()
    capture = {'path': '/owned/candidate.zip', 'archive_base64': base64.b64encode(raw).decode(), 'archive_sha256': digest, 'archive_after_sha256': digest}
    obs = {'zip_sources': {'normal': capture}, 'sources_before': {'normal': {'SKILL.md': {'bytes': 7, 'executable': False, 'sha256': hashlib.sha256(b'fixture').hexdigest()}}}}
    record = {'source_kind': 'local_zip', 'source_locator_digest': hashlib.sha256(capture['path'].encode()).hexdigest()}
    return obs, record


def test_exact_archive_joins_source():
    obs, record = fixture()
    assert verify_archive_source(obs, 'normal', record) == '/owned/candidate.zip'


@pytest.mark.parametrize('mutation', ['source_bytes', 'source_mode', 'archive_digest', 'archive_after', 'source_kind', 'locator'])
def test_reject_substitution(mutation):
    obs, record = fixture()
    if mutation == 'source_bytes': obs['sources_before']['normal']['SKILL.md']['sha256'] = '0' * 64
    if mutation == 'source_mode': obs['sources_before']['normal']['SKILL.md']['executable'] = True
    if mutation == 'archive_digest': obs['zip_sources']['normal']['archive_sha256'] = '0' * 64
    if mutation == 'archive_after': obs['zip_sources']['normal']['archive_after_sha256'] = '0' * 64
    if mutation == 'source_kind': record['source_kind'] = 'local_dir'
    if mutation == 'locator': record['source_locator_digest'] = '0' * 64
    with pytest.raises(ValueError):
        verify_archive_source(obs, 'normal', record)


def test_no_read_claim_needs_healthy_capture():
    obs, _ = fixture()
    obs['zip_sources']['quarantined'] = copy.deepcopy(obs['zip_sources']['normal'])
    obs['stages'] = {k: {'import': {'source_kind': 'local_zip'}} for k in ('good_import', 'bad_import')}
    obs['zip_read_calibration'] = [{'expected_read': v, 'observation': {'healthy': True, 'read_observed': v}} for v in (False, True)]
    obs['zip_read_observations'] = {'public': {'healthy': True, 'read_observed': True}, 'private': {'healthy': True, 'read_observed': False}}
    assert all(extra_checks(obs).values())
    obs['zip_read_observations']['private']['healthy'] = False
    assert not all(extra_checks(obs).values())
