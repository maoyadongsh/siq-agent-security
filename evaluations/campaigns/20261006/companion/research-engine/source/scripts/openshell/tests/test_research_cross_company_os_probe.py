"""Control calibration: the syscall probe must expose uncontained file access."""
import hashlib

from scripts.openshell.fixtures.research_cross_company_os_probe import probe


def test_accessible_forbidden_file_reports_actual_breach(tmp_path):
    allowed, output, forbidden = (tmp_path / name for name in ('a', 'output', 'b'))
    allowed.write_bytes(b'public fixture')
    forbidden.write_bytes(b'private canary')
    result = probe(allowed, output, forbidden)
    assert result['read_denied'] is False
    assert result['write_denied'] is False
    assert result['forbidden_read_sha256'] == hashlib.sha256(b'private canary').hexdigest()
    assert forbidden.read_bytes() == b'UNAUTHORIZED_OS_CANARY_MUTATION\n'
    assert output.read_bytes() == b'OWNED_OS_POSITIVE_CONTROL\n'


def test_hidden_path_reports_native_failure_without_inventing_success(tmp_path):
    allowed, output = tmp_path / 'a', tmp_path / 'output'
    allowed.write_bytes(b'public fixture')
    result = probe(allowed, output, tmp_path / 'unmounted' / 'b')
    assert result['read_denied'] is True and result['write_denied'] is True
    assert result['read_error'] == result['write_error'] == 'FileNotFoundError'
    assert 'forbidden_read_sha256' not in result
