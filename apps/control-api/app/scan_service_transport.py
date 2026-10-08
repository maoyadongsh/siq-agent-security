"""Bounded, peer-authenticated local transport; no sample parsing or logging."""
from __future__ import annotations

import os
import socket
import stat
import struct
import sys
import time
from pathlib import Path

from app.scan_transport import ScanFailure
from app.scan_worker import MAX_INPUT, MAX_OUTPUT

MAGIC = b"SIQSCAN1"
HEADER = struct.Struct("!8sBI")
TIMEOUT = 8.0


def peer_uid(connection):
    if sys.platform != "linux":
        raise ScanFailure("threat_scan_isolation_unavailable")
    return struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[1]


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise ScanFailure("threat_scan_timeout")
    return value


def read_exact(connection, size, deadline):
    output = bytearray()
    while len(output) < size:
        connection.settimeout(remaining(deadline))
        chunk = connection.recv(min(65536, size - len(output)))
        if not chunk:
            raise ScanFailure("threat_scan_transport_failed")
        output.extend(chunk)
    return bytes(output)


def read_frame(connection, deadline, *, response=False):
    magic, status, size = HEADER.unpack(read_exact(connection, HEADER.size, deadline))
    limit = MAX_OUTPUT if response else MAX_INPUT
    if (magic != MAGIC or status not in ({0, 1, 2, 3} if response else {0})
            or (status == 0 and not 1 <= size <= limit) or (status != 0 and size != 0)):
        raise ScanFailure("threat_scan_transport_failed")
    body = read_exact(connection, size, deadline)
    connection.settimeout(remaining(deadline))
    if connection.recv(1):
        raise ScanFailure("threat_scan_transport_failed")
    return status, body


def write_frame(connection, status, body, deadline):
    connection.settimeout(remaining(deadline))
    connection.sendall(HEADER.pack(MAGIC, status, len(body)) + body)
    connection.shutdown(socket.SHUT_WR)


def validate_endpoint(path, owner, *, directory=False):
    """Only trusted root/service owners can replace an endpoint or an ancestor."""
    if (type(owner) is not int or not 1 <= owner < 2**32 - 1 or not isinstance(path, str)
            or not path.startswith("/") or "\x00" in path or len(os.fsencode(path)) > 107
            or any(part in {"", ".", ".."} for part in path.split("/")[1:])):
        raise ScanFailure("threat_scan_endpoint_invalid")
    target = Path(path)
    for current in reversed((target, *target.parents)):
        info = current.lstat()
        endpoint = current == target and not directory
        if endpoint:
            valid = stat.S_ISSOCK(info.st_mode) and info.st_uid == owner and stat.S_IMODE(info.st_mode) == 0o660
        else:
            # Root-owned sticky /tmp is safe only with a protected owned descendant.
            sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX) and current != target
            valid = (stat.S_ISDIR(info.st_mode) and info.st_uid in {0, owner}
                     and (not info.st_mode & 0o022 or sticky_root))
        if not valid:
            raise ScanFailure("threat_scan_endpoint_invalid")
    if directory and target.lstat().st_uid != owner:
        raise ScanFailure("threat_scan_endpoint_invalid")


def service_exchange(path, owner, payload):
    if not 1 <= len(payload) <= MAX_INPUT:
        raise ScanFailure("threat_scan_input_limit")
    deadline = time.monotonic() + TIMEOUT
    try:
        validate_endpoint(path, owner)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(remaining(deadline))
            connection.connect(path)
            if peer_uid(connection) != owner:
                raise ScanFailure("threat_scan_peer_invalid")
            write_frame(connection, 0, payload, deadline)
            status, output = read_frame(connection, deadline, response=True)
            if status:
                category = {1: "threat_scan_busy", 2: "threat_scan_worker_failed", 3: "threat_scan_transport_failed"}
                raise ScanFailure(category[status])
            return output
    except TimeoutError:
        raise ScanFailure("threat_scan_timeout") from None
    except (OSError, ValueError, TypeError):
        raise ScanFailure("threat_scan_transport_failed") from None
