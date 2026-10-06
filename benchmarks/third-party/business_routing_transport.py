"""Independent loopback request capture for original model clients and optional live forwarding."""
import copy
import hashlib
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common import canonical
from model_smoke import read_key


class RoutingBudget:
    """Reject excess requests before forwarding; reservations include failed calls."""
    def __init__(self, *, calls, seconds, reservation):
        self.limit, self.deadline, self.reservation_limit = calls, time.monotonic() + seconds, reservation
        self.requests, self.reserved, self.units = 0, 0, {}
        self.lock = threading.Lock()

    def take(self, unit, body, size):
        maximum = body.get('max_tokens')
        if type(maximum) is not int or not 1 <= maximum <= 4096 or size > 65536:
            raise ValueError('generation_or_request_limit')
        # A conservative byte reservation, not a claim about provider billing/tokenization.
        reserve = size + maximum
        with self.lock:
            if (time.monotonic() >= self.deadline or self.requests >= self.limit
                    or self.units.get(unit, 0) >= 3 or self.reserved + reserve > self.reservation_limit):
                raise ValueError('routing_budget_exhausted')
            self.requests += 1
            self.units[unit] = self.units.get(unit, 0) + 1
            self.reserved += reserve
        return {'request_number': self.requests, 'unit_request_number': self.units[unit], 'byte_plus_output_token_reservation': reserve}

    def snapshot(self):
        return {'requests': self.requests, 'by_unit': self.units, 'reserved': self.reserved,
                'call_limit': self.limit, 'reservation_limit': self.reservation_limit}


def forward(upstream, raw, timeout):
    """A killable subprocess gives even a slow streaming server a total time limit."""
    message = json.dumps({'upstream': upstream, 'request': raw.decode(), 'timeout': timeout})
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--forward'],
                            input=message, capture_output=True, text=True, timeout=timeout + 2, check=True)
    value = json.loads(result.stdout)
    return value['status'], value['response'].encode()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('provider redirect rejected')


def operation(body):
    content = json.loads(body['messages'][-1]['content'])
    if 'task' in content:
        return 'plan', content
    if 'sources' in content:
        return 'research', content
    if 'candidates' in content:
        return 'recipient', content
    raise ValueError('unexpected original provider request')


def proposal(kind, content):
    if kind == 'plan':
        task = content['task']
        count = {'research': 1, 'report': 2, 'delivery': 3}[task['requested_output']]
        return {'goal': task['prompt'], 'skills': [
            {'name': 'secure-research', 'input': {k: task[k] for k in ('repository', 'question', 'scope')}},
            {'name': 'secure-report', 'input': {'path': task['report_path']}},
            {'name': 'secure-delivery', 'input': {'contact': task['contact']}},
        ][:count]}
    if kind == 'research':
        return {'findings': [s['path'] + ': controlled review of supplied source.' for s in content['sources']],
                'summary': 'Controlled routing review, not model inference.'}
    return {'candidate_index': 0}


class ModelEndpoint:
    def __init__(self, role, events, *, failure=None, upstream=None, capture_loss=False, budget=None, unit='test', timeout=45, plan_override=None):
        self.role, self.events, self.failure = role, events, failure
        self.upstream, self.capture_loss = upstream, capture_loss
        self.budget, self.unit, self.timeout = budget, unit, timeout
        if plan_override and upstream:
            raise ValueError('controlled plan substitution cannot alter live responses')
        self.plan_override = plan_override
        self.records, self.calibration = [], []
        self.seen, self.active, self.closed = 0, 0, False
        self.condition = threading.Condition()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def respond(self, status, data):
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                with owner.condition:
                    owner.active += 1
                row = None
                try:
                    size = int(self.headers.get('Content-Length', 0))
                    if self.path != '/v1/chat/completions' or not 0 < size <= 1 << 20:
                        self.respond(400, b'{}')
                        return
                    raw = self.rfile.read(size)
                    body = json.loads(raw)
                    if set(body) == {'calibration'}:
                        owner.calibration.append({'nonce': body['calibration'], 'request_sha256': hashlib.sha256(raw).hexdigest()})
                        self.respond(200, b'{"calibrated":true}')
                        return
                    kind, content = operation(body)
                    with owner.condition:
                        owner.seen += 1
                    row = {'role': role, 'operation': kind, 'body': body, 'content': content,
                           'request_sha256': hashlib.sha256(raw).hexdigest(), 'status': None,
                           'upstream': None, 'error_type': None, 'response': None}
                    row['budget'] = owner.budget.take(owner.unit, body, len(raw)) if owner.budget else None
                    if kind == owner.failure:
                        status, response = 503, b'{"error":{"type":"controlled_failure"}}'
                    elif owner.upstream:
                        destination = owner.upstream['endpoint'].rstrip('/') + '/chat/completions'
                        row['upstream'] = {'endpoint': destination, 'request_sha256': hashlib.sha256(raw).hexdigest()}
                        status, response = forward(owner.upstream, raw, owner.timeout)
                    else:
                        status = 200
                        proposed = proposal(kind, content)
                        if kind == 'plan' and owner.plan_override:
                            index, field, value = owner.plan_override
                            proposed['skills'][index]['input'][field] = copy.deepcopy(value)
                        response = canonical({'model': body['model'], 'choices': [{'finish_reason': 'stop', 'message': {
                            'role': 'assistant', 'content': json.dumps(proposed)}}],
                            'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}})
                    row['status'] = status
                    row['response_wire'] = response.decode()
                    row['response_sha256'] = hashlib.sha256(response).hexdigest()
                    row['response'] = json.loads(response)
                    self.respond(status, response)
                except Exception as exc:  # noqa: BLE001 -- never expose provider credentials or error bodies
                    if row is not None:
                        row['error_type'] = type(exc).__name__
                    try:
                        self.respond(502, b'{"error":{"type":"capture_transport_error"}}')
                    except OSError:
                        pass
                finally:
                    with owner.condition:
                        if row is not None and not owner.capture_loss:
                            owner.records.append(copy.deepcopy(row))
                            owner.events.add('model_endpoint_request', record=copy.deepcopy(row))
                        owner.active -= 1
                        owner.condition.notify_all()

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = False
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/v1'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        from uuid import uuid4
        nonce = uuid4().hex
        before = len(self.calibration)
        try:
            with build_opener(ProxyHandler({})).open(Request(self.endpoint + '/chat/completions',
                    data=canonical({'calibration': nonce}), headers={'Content-Type': 'application/json'}), timeout=5) as response:
                result = json.loads(response.read())
            if result != {'calibrated': True} or before != 0 or self.calibration != [
                {'nonce': nonce, 'request_sha256': hashlib.sha256(canonical({'calibration': nonce})).hexdigest()}]:
                raise ValueError('model request observer calibration failed')
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_args):
        with self.condition:
            self.drained = self.condition.wait_for(lambda: self.active == 0, timeout=self.timeout + 5)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.closed = not self.thread.is_alive()

    def snapshot(self):
        return {'role': self.role, 'endpoint': self.endpoint, 'records': self.records,
                'seen': self.seen, 'calibration': self.calibration, 'drained': getattr(self, 'drained', False),
                'closed': self.closed, 'capture_loss_requested': self.capture_loss}


if __name__ == '__main__':
    if sys.argv[1:] != ['--forward']:
        raise SystemExit(2)
    value = json.load(sys.stdin)
    upstream = value['upstream']
    request = Request(upstream['endpoint'].rstrip('/') + '/chat/completions', data=value['request'].encode(),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + read_key(Path(upstream['credential_file']))})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=value['timeout']) as response:
            status, raw = response.status, response.read((1 << 20) + 1)
    except HTTPError as exc:
        status, raw = exc.code, b'{"error":{"type":"upstream_http_error"}}'
    if len(raw) > 1 << 20:
        raise ValueError('provider response exceeds limit')
    print(json.dumps({'status': status, 'response': raw.decode()}))
