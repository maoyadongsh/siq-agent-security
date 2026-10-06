import json
from pathlib import Path

import pytest
from native_personal_onboarding import (
    discovered_asset,
    installed_payload_matches,
    public_read_matches,
)


def test_same_name_cannot_substitute_for_discovered_exact_source():
    wrong = {'id': 'wrong', 'source_type': 'skill_dir', 'source_locator': 'local://skills//other/intent-fixture'}
    right = {'id': 'right', 'source_type': 'skill_dir', 'source_locator': 'local://skills//owned/intent-fixture'}
    assert discovered_asset([wrong, right], Path('/owned/intent-fixture'))['id'] == 'right'
    with pytest.raises(ValueError, match='missing or ambiguous'):
        discovered_asset([wrong], Path('/owned/intent-fixture'))


def test_duplicate_discovery_identity_is_not_silently_selected():
    row = {'id': 'first', 'source_type': 'skill_dir', 'source_locator': 'local://skills//owned/intent-fixture'}
    with pytest.raises(ValueError, match='missing or ambiguous'):
        discovered_asset([row, {**row, 'id': 'second'}], Path('/owned/intent-fixture'))


def test_numbered_public_result_requires_exact_bytes_and_complete_metadata():
    source = 'one\ntwo\n'
    data = {'content': '1|one\n2|two\n3|', 'total_lines': 2, 'file_size': 8, 'truncated': False, 'is_binary': False, 'is_image': False}
    assert public_read_matches(json.dumps(data), source)
    for change in ({'truncated': True}, {'content': '1|one\n1|two\n3|'}, {'file_size': 9}, {'content': '1|one\n2|extra\n3|'}):
        assert not public_read_matches(json.dumps({**data, **change}), source)


def test_owner_files_do_not_hide_changed_payload_or_unexpected_extras():
    payload = {'SKILL.md': {'sha256': 'fixed', 'bytes': 7, 'executable': False}}
    obs = {'sources_before': {'normal': payload}, 'installed_snapshot': {**payload, '.siq-install-owner': {}}, 'owner_records': {'.siq-install-owner': {}}}
    assert installed_payload_matches(obs)
    obs['installed_snapshot']['unexpected.txt'] = {}
    assert not installed_payload_matches(obs)
    del obs['installed_snapshot']['unexpected.txt']
    obs['installed_snapshot']['SKILL.md'] = {**payload['SKILL.md'], 'executable': True}
    assert not installed_payload_matches(obs)
