"""Host service for container clients. Each admitted connection runs real bwrap."""
from __future__ import annotations

import argparse
import os
import signal
import socket
import threading
import time
from pathlib import Path

from app.scan_isolation import command
from app.scan_service_transport import TIMEOUT, peer_uid, read_frame, remaining, validate_endpoint, write_frame
from app.scan_transport import ScanFailure, exchange
from app.scan_worker import MAX_OUTPUT


class ScanService:
    def __init__(self, path, client_uid, concurrency=2):
        if (os.geteuid() == 0 or type(client_uid) is not int or not 1 <= client_uid < 2**32 - 1
                or type(concurrency) is not int or not 1 <= concurrency <= 8):
            raise ScanFailure("threat_scan_service_configuration_invalid")
        self.path, self.client_uid = Path(path), client_uid
        self.slots = threading.BoundedSemaphore(concurrency)
        self.stopping = threading.Event()
        self.threads = set()
        self.lock = threading.Lock()
        self.listener = None
        self.identity = None

    def open(self):
        # Directory is pre-created by the operator; never adopt/remove a stale socket.
        validate_endpoint(str(self.path.parent), os.geteuid(), directory=True)
        if self.path.parent.stat().st_mode & 0o777 != 0o710:
            raise ScanFailure("threat_scan_endpoint_invalid")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.path))
            info = self.path.lstat()
            self.identity = (info.st_dev, info.st_ino)
            self.path.chmod(0o660)
            listener.listen(8)
            listener.settimeout(.1)
            self.listener = listener
        except BaseException:
            listener.close()
            self._remove_owned_socket()
            raise

    def _remove_owned_socket(self):
        try:
            info = self.path.lstat()
            if self.identity == (info.st_dev, info.st_ino):
                self.path.unlink()
        except FileNotFoundError:
            pass

    def _handle(self, connection):
        deadline = time.monotonic() + TIMEOUT
        try:
            with connection:
                try:
                    _, payload = read_frame(connection, deadline)
                except (ScanFailure, OSError):
                    write_frame(connection, 3, b"", deadline)
                    return
                try:
                    output = exchange(command("bwrap"), payload, timeout=min(5.0, remaining(deadline)))
                    if not 1 <= len(output) <= MAX_OUTPUT:
                        raise ScanFailure("threat_scan_output_limit")
                except ScanFailure:
                    write_frame(connection, 2, b"", deadline)
                    return
                write_frame(connection, 0, output, deadline)
        except (ScanFailure, OSError):
            # Fixed failure only, never sample text, rules or untrusted exception strings.
            pass
        finally:
            self.slots.release()
            with self.lock:
                self.threads.discard(threading.current_thread())

    def serve(self):
        if self.listener is None:
            raise ScanFailure("threat_scan_service_not_open")
        try:
            while not self.stopping.is_set():
                try:
                    connection, _ = self.listener.accept()
                except TimeoutError:
                    continue
                try:
                    if peer_uid(connection) != self.client_uid:
                        connection.close()
                        continue
                    if not self.slots.acquire(blocking=False):
                        try:
                            write_frame(connection, 1, b"", time.monotonic() + .2)
                        finally:
                            connection.close()
                        continue
                    thread = threading.Thread(target=self._handle, args=(connection,))
                    with self.lock:
                        self.threads.add(thread)
                    try:
                        thread.start()
                    except BaseException:
                        with self.lock:
                            self.threads.discard(thread)
                        self.slots.release()
                        connection.close()
                        raise
                except (ScanFailure, OSError):
                    connection.close()
        finally:
            self.listener.close()
            with self.lock:
                threads = tuple(self.threads)
            for thread in threads:
                thread.join(TIMEOUT + 2)
            if any(thread.is_alive() for thread in threads):
                raise ScanFailure("threat_scan_cleanup_failed")
            self._remove_owned_socket()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--client-uid", type=int, required=True)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    if args.client_uid == os.geteuid():
        parser.error("service and container client must use distinct non-root UIDs")
    service = ScanService(args.socket, args.client_uid, args.concurrency)
    for kind in (signal.SIGTERM, signal.SIGINT):
        signal.signal(kind, lambda *_: service.stopping.set())
    try:
        service.open()
        service.serve()
    except (ScanFailure, OSError):
        raise SystemExit("threat_scan_service_failed") from None


if __name__ == "__main__":
    main()
