import hashlib
import os

import pytest

from scripts.openshell import research_permission_skill_image as image


def test_installer_hardlink_is_read_only_verified_content(tmp_path):
    source, installed = tmp_path / 'source', tmp_path / 'SKILL.md'
    source.write_bytes(b'Owned installed Skill.')
    source.chmod(0o444)
    os.link(source, installed)
    assert installed.stat().st_nlink == 2
    assert image.installed_bytes(installed, hashlib.sha256(source.read_bytes()).hexdigest()) == source.read_bytes()


def test_installed_content_drift_rejected(tmp_path):
    source = tmp_path / 'SKILL.md'
    source.write_bytes(b'changed')
    with pytest.raises(image.images.CandidateImageError, match='source_changed'):
        image.installed_bytes(source, hashlib.sha256(b'approved').hexdigest())


def test_installed_symlink_rejected(tmp_path):
    source, link = tmp_path / 'source', tmp_path / 'SKILL.md'
    source.write_bytes(b'approved')
    link.symlink_to(source)
    with pytest.raises(image.images.CandidateImageError, match='path_invalid'):
        image.installed_bytes(link, hashlib.sha256(b'approved').hexdigest())


def test_installed_fifo_rejected_without_waiting_for_writer(tmp_path):
    source = tmp_path / 'SKILL.md'
    os.mkfifo(source)
    with pytest.raises(image.images.CandidateImageError, match='file_invalid'):
        image.installed_bytes(source, hashlib.sha256(b'approved').hexdigest())
