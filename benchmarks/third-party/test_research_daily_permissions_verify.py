import base64
import copy
import hashlib
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from research_daily_permissions_verify import canonical, verify_effect_path, verify_records


def fixture_records():
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()

    def sign(seq, previous):
        record = {'receipt_id': 'receipt-' + str(seq), 'chain_id': 'shared', 'seq': seq,
            'prev_hash': previous, 'record_type': 'decision', 'action': 'deny'}
        record['hash'] = hashlib.sha256(canonical(record)).hexdigest()
        record['sig'] = key.sign(record['hash'].encode()).hex()
        return record

    first = sign(30, 'a' * 64)
    return [first, sign(31, first['hash'])], public, sign


def test_subset_signatures_verified_without_inventing_genesis():
    records, public, sign = fixture_records()
    result = verify_records(records, public)
    assert result['records'] == 2 and result['inter_record_gaps'] == 0
    assert 'no complete' in result['scope']
    records.append(sign(35, 'b' * 64))
    assert verify_records(records, public)['inter_record_gaps'] == 1


def test_record_tamper_bad_signature_duplicate_and_false_adjacent_link_rejected():
    records, public, sign = fixture_records()
    bad = copy.deepcopy(records)
    bad[0]['action'] = 'allow'
    with pytest.raises(ValueError, match='hash_mismatch'):
        verify_records(bad, public)
    bad = copy.deepcopy(records)
    bad[0]['sig'] = '00' * 64
    with pytest.raises(InvalidSignature):
        verify_records(bad, public)
    with pytest.raises(ValueError, match='duplicate'):
        verify_records(records + [records[0]], public)
    with pytest.raises(ValueError, match='link_invalid'):
        verify_records([records[0], sign(31, '0' * 64)], public)


def test_file_oracle_cannot_read_other_company_or_follow_symlink(tmp_path):
    company = '600000-SyntheticDaily' + 'a' * 16
    directory = tmp_path / 'data/wiki/companies' / company / 'analysis/runs' / ('qwen-request-' + 'b' * 16)
    directory.mkdir(parents=True)
    path = directory / 'permission-result.md'
    verify_effect_path(tmp_path, company, path)
    with pytest.raises(ValueError):
        verify_effect_path(tmp_path, company, Path('/another/private.txt'))
    outside = tmp_path / 'outside.txt'
    outside.write_text('not owned')
    path.symlink_to(outside)
    with pytest.raises(ValueError, match='not_owned'):
        verify_effect_path(tmp_path, company, path)
