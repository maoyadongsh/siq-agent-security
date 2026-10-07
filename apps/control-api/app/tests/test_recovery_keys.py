import base64
import json
import os

import pytest

from app.adapters.openshell.recovery_keys import load_recovery_cipher
from app.adapters.openshell.sealed_snapshot import SnapshotError
from app.tests.test_sealed_snapshot import ORIGIN, POLICY


def provision(path):
    path.write_text(json.dumps({"active_key_id": "test", "keys": {"test": base64.b64encode(b"x" * 32).decode()}}))
    path.chmod(0o600)
    return path


def test_explicit_key_file_and_environment_roundtrip(tmp_path, monkeypatch):
    path = provision(tmp_path / "synthetic-keys.json")
    envelope = load_recovery_cipher(str(path)).seal(ORIGIN, POLICY)
    monkeypatch.setenv("SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE", str(path))
    assert load_recovery_cipher().open(ORIGIN, envelope) == POLICY


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o700, 0o4600])
def test_key_file_permissions_reject_exposure_or_execution(tmp_path, mode):
    path = provision(tmp_path / "synthetic-keys.json")
    path.chmod(mode)
    with pytest.raises(SnapshotError, match="snapshot_key_file_unavailable"):
        load_recovery_cipher(str(path))


def test_no_fallback_for_missing_path_symlink_or_fifo(tmp_path, monkeypatch):
    monkeypatch.delenv("SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE", raising=False)
    real = provision(tmp_path / "synthetic-keys.json")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    pipe = tmp_path / "pipe"
    os.mkfifo(pipe, 0o600)
    for path in (None, "relative.json", str(tmp_path / "missing"), str(link), str(pipe)):
        with pytest.raises(SnapshotError, match="snapshot_key_file_unavailable"):
            load_recovery_cipher(path)


@pytest.mark.parametrize("contents", [
    b"x" * 8193, b"", b"\xff", b"[]", b'{"active_key_id":"test","keys":{},"extra":1}',
    b'{"active_key_id":"test","keys":{"test":"??"}}',
    b'{"active_key_id":"test","keys":{"test":null}}',
    b'{"active_key_id":"test","keys":{"test":"eA=="}}',
    b'{"active_key_id":"first","active_key_id":"second","keys":{}}',
])
def test_malformed_key_file_is_fixed_failure_without_content(tmp_path, contents):
    path = tmp_path / "synthetic-keys.json"
    path.write_bytes(contents)
    path.chmod(0o600)
    with pytest.raises(SnapshotError) as exc:
        load_recovery_cipher(str(path))
    assert str(exc.value) == "snapshot_key_file_unavailable"


def test_in_place_change_during_read_refused(tmp_path, monkeypatch):
    import app.adapters.openshell.recovery_keys as module

    path = provision(tmp_path / "synthetic-keys.json")
    original_read = module.os.read

    def changing_read(fd, size):
        data = original_read(fd, size)
        path.write_text("changed")
        return data

    monkeypatch.setattr(module.os, "read", changing_read)
    with pytest.raises(SnapshotError, match="snapshot_key_file_unavailable"):
        load_recovery_cipher(str(path))
