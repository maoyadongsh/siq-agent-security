"""Owned bound, non-listening TCP destination; observe original Python connect attempts."""
import errno
import socket
import sys

_active = []
_installed = False


def _audit(event, args):
    if event == 'socket.connect':
        for observer in _active:
            if args[1] == observer.address:
                observer.attempts.append({'phase': observer.phase, 'address': list(args[1])})
                observer.events.add('refused_tcp_connect', phase=observer.phase, address=list(args[1]))


class RefusedEndpoint:
    def __init__(self, events):
        self.events = events
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.bind(('127.0.0.1', 0))
        self.address = self.socket.getsockname()
        self.endpoint = f'http://127.0.0.1:{self.address[1]}/v1'
        self.attempts, self.probes = [], []
        self.phase, self.closed = 'before', False

    def probe(self, phase):
        self.phase = phase
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            result = client.connect_ex(self.address)
        self.probes.append({'phase': phase, 'errno': result})
        self.events.add('refused_tcp_probe', phase=phase, errno=result)
        if result != errno.ECONNREFUSED:
            raise ValueError('reserved destination is not connection refused')

    def __enter__(self):
        global _installed
        if not _installed:
            sys.addaudithook(_audit)
            _installed = True
        _active.append(self)
        try:
            self.probe('before')
        except BaseException:
            _active.remove(self)
            self.socket.close()
            raise
        self.phase = 'application'
        return self

    def __exit__(self, *_args):
        try:
            self.probe('after')
        finally:
            _active.remove(self)
            self.socket.close()
            self.closed = True

    def snapshot(self):
        return {'address': list(self.address), 'endpoint': self.endpoint, 'probes': self.probes,
                'attempts': self.attempts, 'closed': self.closed,
                'scope': 'Python socket audit attempts plus owned non-listening socket and refused probes; no packet capture or global network coverage'}
