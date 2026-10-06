"""Owned target servers plus a bounded self-hosted extraction API fixture."""
import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('owned extraction fixture forbids redirects')


class Services:
    def __init__(self):
        self.servers, self.threads, self.records, self.calibration = {}, {}, [], []
        self.bodies = {'allowed': '', 'restricted': ''}
        self.lock = threading.Lock()
        owner = self
        for role in ('allowed', 'restricted', 'backend'):
            def handler(role=role):
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *_args):
                        pass

                    def respond(self, status, raw):
                        self.send_response(status)
                        self.send_header('Content-Length', str(len(raw)))
                        self.send_header('Content-Type', 'application/json' if role == 'backend' else 'text/plain')
                        self.end_headers(); self.wfile.write(raw)

                    def do_GET(self):
                        if self.path == '/health':
                            self.respond(200, b'alive'); return
                        if self.path == '/calibration':
                            raw = b'owned network calibration'
                            with owner.lock:
                                owner.calibration.append({'role': role, 'sha256': hashlib.sha256(raw).hexdigest()})
                            self.respond(200, raw); return
                        if role == 'backend' or self.path != '/report':
                            self.respond(404, b'not found'); return
                        raw = owner.bodies[role].encode()
                        with owner.lock:
                            owner.records.append({'role': role, 'method': 'GET', 'path': self.path, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)})
                        self.respond(200, raw)

                    def do_POST(self):
                        if role != 'backend' or self.path != '/v2/scrape':
                            self.respond(404, b'{}'); return
                        size = int(self.headers.get('Content-Length', 0))
                        if not 0 < size <= 65536:
                            self.respond(400, b'{}'); return
                        body = json.loads(self.rfile.read(size)); target = body.get('url')
                        # The fixture cannot access any destination outside its two targets.
                        if target not in [owner.url(x) for x in ('allowed', 'restricted')]:
                            self.respond(403, b'{}'); return
                        with owner.lock:
                            owner.records.append({'role': 'backend', 'method': 'POST', 'path': self.path, 'target': target, 'body': body})
                        with build_opener(ProxyHandler({}), NoRedirect()).open(Request(target), timeout=5) as response:
                            text = response.read(16385).decode()
                        self.respond(200, json.dumps({'success': True, 'data': {'markdown': text,
                            'metadata': {'sourceURL': target, 'title': 'Synthetic owned source', 'statusCode': 200}}}).encode())
                return Handler
            self.servers[role] = ThreadingHTTPServer(('127.0.0.1', 0), handler())
            self.threads[role] = threading.Thread(target=self.servers[role].serve_forever, daemon=True)

    def url(self, role, path='/report'):
        return f'http://127.0.0.1:{self.servers[role].server_port}' + path

    def __enter__(self):
        for thread in self.threads.values(): thread.start()
        for role in self.servers:
            with build_opener(ProxyHandler({})).open(self.url(role, '/health'), timeout=5) as response:
                if response.read() != b'alive': raise ValueError('observer health failed')
        for role in ('allowed', 'restricted'):
            with build_opener(ProxyHandler({})).open(self.url(role, '/calibration'), timeout=5) as response:
                if response.read() != b'owned network calibration': raise ValueError('positive calibration failed')
        if self.records: raise ValueError('calibration contaminated measurement')
        return self

    def __exit__(self, *_args):
        self.health_after = True
        try:
            for role in self.servers:
                with build_opener(ProxyHandler({})).open(self.url(role, '/health'), timeout=5) as response:
                    self.health_after = self.health_after and response.read() == b'alive'
        finally:
            for server in self.servers.values(): server.shutdown(); server.server_close()
            for thread in self.threads.values(): thread.join(timeout=5)
        self.closed = all(not t.is_alive() for t in self.threads.values())

    def snapshot(self):
        return {'urls': {r: self.url(r) for r in self.servers}, 'bodies': self.bodies, 'records': self.records,
                'calibration': self.calibration, 'healthy_after': self.health_after, 'closed': self.closed,
                'scope': 'Hermes -> original Firecrawl SDK -> owned extraction API -> actual owned HTTP target; no public Internet extraction'}
