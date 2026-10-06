from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.openshell import agentshield_runtime_binding as binding  # noqa: E402

SCOPE = "7" * 24
IDENTITY = "ri-" + "1" * 32
INSTANCE = "hi-" + "2" * 32
AGENT = "hri-" + "2" * 32


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    project = tmp_path / "project"
    secret_dir = project / binding.DEFAULT_RELATIVE.parent
    secret_dir.mkdir(parents=True, mode=0o700)
    credential = tmp_path / "credential"
    credential.write_text(IDENTITY + "." + "3" * 64 + "\n", encoding="ascii")
    credential.chmod(0o600)
    relay = tmp_path / "relay"
    relay.write_bytes(b"relay")
    relay.chmod(0o700)
    document = {
        "schema_version": binding.SCHEMA_VERSION,
        "runtime_identity_id": IDENTITY,
        "instance_id": INSTANCE,
        "agent_id": AGENT,
        "grant_id": "grt-" + "4" * 24,
        "grant_revision": 3,
        "credential_path": str(credential),
        "scope_id": SCOPE,
        "relay_binary": str(relay),
        "relay_sha256": hashlib.sha256(relay.read_bytes()).hexdigest(),
        "helper_image_ref": "python:3.12-slim",
        "helper_image_id": "sha256:" + "5" * 64,
    }
    authority = project / binding.DEFAULT_RELATIVE
    authority.write_text(json.dumps(document), encoding="utf-8")
    authority.chmod(0o600)
    return project, authority, credential


def test_load_binds_private_credential_binary_and_scope(tmp_path: Path) -> None:
    project, authority, credential = _fixture(tmp_path)
    result = binding.load(project, expected_scope_id=SCOPE)
    assert result.runtime_identity_id == IDENTITY
    assert result.agent_id == AGENT
    assert result.credential_path == credential
    assert result.binding_sha256 == hashlib.sha256(authority.read_bytes()).hexdigest()


def test_load_accepts_public_installed_skill_grant_identity(tmp_path: Path) -> None:
    project, authority, _ = _fixture(tmp_path)
    document = json.loads(authority.read_text())
    document['grant_id'] = 'grt-si-' + 'a' * 64
    authority.write_text(json.dumps(document))
    assert binding.load(project, expected_scope_id=SCOPE).grant_id == document['grant_id']


@pytest.mark.parametrize('grant_id', ['grt-si-' + 'a' * 63, 'grt-si-' + 'a' * 65,
                                     'grt-si-' + 'z' * 64, 'grt-si-../escape'])
def test_load_rejects_malformed_installed_skill_grant(tmp_path: Path, grant_id: str) -> None:
    project, authority, _ = _fixture(tmp_path)
    document = json.loads(authority.read_text())
    document['grant_id'] = grant_id
    authority.write_text(json.dumps(document))
    with pytest.raises(binding.AuthorityBindingError):
        binding.load(project, expected_scope_id=SCOPE)


def test_load_prefers_exact_scope_binding_over_legacy_file(tmp_path: Path) -> None:
    project, authority, _credential = _fixture(tmp_path)
    scoped_root = project / binding.SCOPED_RELATIVE
    scoped_root.mkdir(mode=0o700)
    scoped = scoped_root / f"{SCOPE}.json"
    scoped.write_bytes(authority.read_bytes())
    scoped.chmod(0o600)
    authority.chmod(0o644)

    result = binding.load(project, expected_scope_id=SCOPE)

    assert result.binding_sha256 == hashlib.sha256(scoped.read_bytes()).hexdigest()


def test_load_rejects_unsafe_scoped_binding_directory(tmp_path: Path) -> None:
    project, _authority, _credential = _fixture(tmp_path)
    scoped_root = project / binding.SCOPED_RELATIVE
    scoped_root.mkdir(mode=0o755)

    with pytest.raises(binding.AuthorityBindingError, match="authority_file_unsafe"):
        binding.load(project, expected_scope_id=SCOPE)


@pytest.mark.parametrize("mutation", ["scope", "credential", "mode", "binary"])
def test_load_fails_closed_for_changed_authority(tmp_path: Path, mutation: str) -> None:
    project, authority, credential = _fixture(tmp_path)
    if mutation == "scope":
        expected_scope = "8" * 24
    else:
        expected_scope = SCOPE
    if mutation == "credential":
        credential.write_text(IDENTITY + "." + "f" * 63 + "x\n", encoding="ascii")
    elif mutation == "mode":
        authority.chmod(0o644)
    elif mutation == "binary":
        document = json.loads(authority.read_text(encoding="utf-8"))
        Path(document["relay_binary"]).write_bytes(b"changed")
    with pytest.raises(binding.AuthorityBindingError):
        binding.load(project, expected_scope_id=expected_scope)


def test_load_rejects_symlinked_credential(tmp_path: Path) -> None:
    project, authority, credential = _fixture(tmp_path)
    real = tmp_path / "real-credential"
    credential.rename(real)
    credential.symlink_to(real)
    assert os.path.islink(credential)
    with pytest.raises(binding.AuthorityBindingError, match="authority_file_unsafe"):
        binding.load(project, expected_scope_id=SCOPE)
