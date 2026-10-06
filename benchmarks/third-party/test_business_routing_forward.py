"""Verify byte-preserving real HTTP forwarding and a slow-reader total deadline."""
import json
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from business_routing_transport import forward


class ForwardTests(unittest.TestCase):
    def run_forward(self, slow=False):
        observed, stopping = [], threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                observed.append({'path': self.path, 'body': self.rfile.read(int(self.headers['Content-Length'])),
                                 'authenticated': self.headers.get('Authorization') == 'Bearer synthetic-only'})
                self.send_response(200)
                self.send_header('Content-Length', '1000' if slow else '2')
                self.end_headers()
                try:
                    if slow:
                        while not stopping.wait(0.02):
                            self.wfile.write(b' ')
                            self.wfile.flush()
                    else:
                        self.wfile.write(b'{}')
                except OSError:
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                key = Path(directory) / 'synthetic.key'
                key.write_text('synthetic-only')
                key.chmod(0o600)
                upstream = {'endpoint': f'http://127.0.0.1:{server.server_port}/v1', 'credential_file': str(key)}
                body = json.dumps({'source': '合成资料', 'exact': '<&>'}, ensure_ascii=True).encode()
                if slow:
                    started = time.monotonic()
                    with self.assertRaises(subprocess.TimeoutExpired):
                        forward(upstream, body, 0.2)
                    self.assertLess(time.monotonic() - started, 4)
                else:
                    self.assertEqual(forward(upstream, body, 5), (200, b'{}'))
                self.assertEqual(observed, [{'path': '/v1/chat/completions', 'body': body, 'authenticated': True}])
        finally:
            stopping.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())

    def test_forward_preserves_exact_request_bytes(self):
        self.run_forward()

    def test_slow_response_is_killed_within_total_deadline(self):
        self.run_forward(slow=True)


if __name__ == '__main__':
    unittest.main()
