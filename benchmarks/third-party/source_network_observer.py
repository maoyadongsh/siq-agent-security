"""Read-only Linux observation of sockets actually owned by the product daemon."""
import ipaddress
import os
import threading
import time
from pathlib import Path


def decode_address(value, version):
    address, port = value.split(':')
    raw = bytes.fromhex(address)
    raw = b''.join(raw[i:i + 4][::-1] for i in range(0, len(raw), 4))
    return str(ipaddress.ip_address(raw)), int(port, 16)


class NetworkObserver:
    def __init__(self, pid):
        self.pid = pid
        self.rows, self.errors = [], []
        self.stop = threading.Event()
        self.started_ns = time.monotonic_ns()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        seen = set()
        while not self.stop.is_set():
            try:
                inodes = set()
                for entry in Path(f'/proc/{self.pid}/fd').iterdir():
                    try:
                        target = os.readlink(entry)
                    except FileNotFoundError:
                        continue
                    if target.startswith('socket:['):
                        inodes.add(target[8:-1])
                for version in (4, 6):
                    path = Path(f'/proc/{self.pid}/net/tcp' + ('6' if version == 6 else ''))
                    for line in path.read_text().splitlines()[1:]:
                        fields = line.split()
                        if fields[9] not in inodes:
                            continue
                        host, port = decode_address(fields[2], version)
                        local_host, local_port = decode_address(fields[1], version)
                        key = (fields[9], fields[3], host, port, local_host, local_port)
                        if key in seen:
                            continue
                        seen.add(key)
                        self.rows.append({'inode': fields[9], 'tcp_state': fields[3], 'remote_ip': host, 'remote_port': port,
                                          'local_ip': local_host, 'local_port': local_port, 'monotonic_ns': time.monotonic_ns()})
            except FileNotFoundError:
                if not Path(f'/proc/{self.pid}').exists():
                    break
            except (OSError, ValueError, IndexError) as error:
                self.errors.append(type(error).__name__)
                break
            self.stop.wait(.02)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=3)
        return {'pid': self.pid, 'started_ns': self.started_ns, 'finished_ns': time.monotonic_ns(),
                'rows': self.rows, 'errors': self.errors, 'stopped': not self.thread.is_alive(),
                'scope': 'sampled daemon-owned TCP sockets, not packet capture, TLS transcript, DNS proof or exhaustive absence evidence'}
