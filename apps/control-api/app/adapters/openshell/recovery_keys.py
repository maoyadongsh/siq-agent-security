"""Read independently provisioned recovery keys without generating a fallback."""

from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path

from app.adapters.openshell.sealed_snapshot import SnapshotCipher, SnapshotError


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def load_recovery_cipher(path: str | None = None) -> SnapshotCipher:
    configured = path if path is not None else os.environ.get("SIQ_AS_OPENSHELL_RECOVERY_KEYRING_FILE", "")
    if not configured or not Path(configured).is_absolute() or not hasattr(os, "O_NOFOLLOW"):
        raise SnapshotError("snapshot_key_file_unavailable")
    fd = None
    try:
        fd = os.open(configured, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid not in {0, os.geteuid()}
            or stat.S_IMODE(before.st_mode) not in {0o400, 0o600} or not 0 < before.st_size <= 8192):
            raise ValueError
        chunks = []
        count = 0
        while count <= 8192:
            part = os.read(fd, 8193 - count)
            if not part:
                break
            chunks.append(part)
            count += len(part)
        after = os.fstat(fd)
        if count > 8192 or (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        ):
            raise ValueError
        document = json.loads(b"".join(chunks), object_pairs_hook=_unique_object)
        if (not isinstance(document, dict) or set(document) != {"active_key_id", "keys"}
            or not isinstance(document["active_key_id"], str) or not isinstance(document["keys"], dict)):
            raise ValueError
        keys = {}
        for key_id, encoded in document["keys"].items():
            if not isinstance(encoded, str):
                raise ValueError
            keys[key_id] = base64.b64decode(encoded, validate=True)
        return SnapshotCipher(keys, document["active_key_id"])
    except (OSError, ValueError, TypeError, RecursionError, SnapshotError):
        raise SnapshotError("snapshot_key_file_unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)
