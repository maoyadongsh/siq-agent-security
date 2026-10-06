"""Private loopback model transport for actual Hermes CLI evaluation."""
import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from common import canonical
from model_smoke import read_key
from native_delegation import control as delegation_control


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ModelBridge:
    def __init__(self, protocol, gold, events, budget):
        self.p, self.gold, self.events, self.budget = protocol, gold, events, budget
        self.rows = []
        self.key = read_key(Path(protocol['credential_file'])) if protocol['mode'] != 'controls' else None
        self.lock = threading.RLock()
        self.client = build_opener(ProxyHandler({}), NoRedirect())
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.endpoint = f'http://127.0.0.1:{self.server.server_port}/v1'

    def handler(self):
        bridge = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, value, status=200, stream=False):
                if stream and status == 200:
                    choice = value['choices'][0]
                    message = copy.deepcopy(choice['message'])
                    for i, call in enumerate(message.get('tool_calls') or []):
                        call['index'] = i
                    base = {'id': value.get('id', 'evaluation'), 'created': value.get('created', 0),
                            'model': value['model'], 'object': 'chat.completion.chunk'}
                    chunks = [{**base, 'choices': [{'index': 0, 'delta': message, 'finish_reason': None}]},
                              {**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': choice['finish_reason']}],
                               'usage': value.get('usage', {})}]
                    raw = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks).encode() + b'data: [DONE]\n\n'
                else:
                    raw = canonical(value)
                self.send_response(status)
                self.send_header('Content-Type', 'text/event-stream' if stream and status == 200 else 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path == '/v1/models':
                    self.respond({'object': 'list', 'data': [{'id': bridge.p['model'], 'object': 'model', 'owned_by': 'evaluation'}]})
                else:
                    self.respond({'error': 'unsupported'}, 404)

            def do_POST(self):
                if bridge.p.get('profile') == 'delegation-wait-controls':
                    return self.exchange()
                with bridge.lock:
                    return self.exchange()

            def exchange(self):
                if self.path != '/v1/chat/completions':
                    self.respond({'error': 'unsupported'}, 404)
                    return
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2_000_000:
                    self.respond({'error': 'request_size'}, 413)
                    return
                body = json.loads(self.rfile.read(size))
                with bridge.lock:
                    row = {'sequence': len(bridge.rows) + 1, 'request': body, 'response': None, 'error_type': None,
                           'started_ns': time.monotonic_ns(), 'provider_request': None}
                    bridge.rows.append(row)
                bridge.events.add('model_request', sequence_id=row['sequence'], body=body)
                accounted = False
                try:
                    if bridge.p['mode'] == 'controls':
                        if bridge.p.get('profile') in ('delegation-controls', 'delegation-wait-controls'):
                            with bridge.lock:
                                if len(bridge.rows) > 20:
                                    raise ValueError('delegation_control_request_budget_exhausted')
                                bridge.budget['controlled_calls'] = bridge.budget.get('controlled_calls', 0) + 1
                        response = bridge.control(body)
                    else:
                        reserve = len(canonical(body)) * 2 + 8192
                        if (bridge.budget['calls'] >= bridge.p['limits']['calls']
                                or bridge.budget['reserved_tokens'] + reserve > bridge.p['limits']['tokens']):
                            raise ValueError('evaluation_model_budget_exhausted')
                        bridge.budget['calls'] += 1
                        bridge.budget['reserved_tokens'] += reserve
                        outgoing = {**body, 'model': bridge.p['model'], 'stream': False, 'temperature': 0, 'max_tokens': 8192}
                        outgoing.pop('stream_options', None)
                        if bridge.p['mode'] == 'local':
                            outgoing['chat_template_kwargs'] = {'enable_thinking': False}
                        else:
                            outgoing['reasoning_effort'] = 'low'
                        row['provider_request'] = outgoing
                        request = Request(bridge.p['endpoint'] + '/chat/completions', data=canonical(outgoing),
                                          headers={'Authorization': 'Bearer ' + bridge.key, 'Content-Type': 'application/json'})
                        with bridge.client.open(request, timeout=120) as received:
                            response = json.loads(received.read(4_000_001))
                        usage = response.get('usage', {}).get('total_tokens')
                        if type(usage) is int and usage >= 0:
                            bridge.budget['tokens'] += usage
                            bridge.budget['reserved_tokens'] += usage - reserve
                        else:
                            bridge.budget['unknown_usage_calls'] += 1
                        accounted = True
                    row['response'] = response
                    self.respond(response, stream=bool(body.get('stream')))
                except Exception as exc:  # noqa: BLE001 -- record type without provider credential/error body
                    row['error_type'] = type(exc).__name__
                    if row['provider_request'] is not None and not accounted:
                        bridge.budget['unknown_usage_calls'] += 1
                    try:
                        self.respond({'error': {'message': 'evaluation provider unavailable', 'type': row['error_type']}}, 503)
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                finally:
                    row['finished_ns'] = time.monotonic_ns()
                    bridge.events.add('model_exchange_finished', exchange=row)
        return Handler

    def control(self, request):
        if 'delegation' in self.gold:
            message, finish = delegation_control(request, self.gold)
            return {'id': 'native-delegation-control', 'model': self.p['model'], 'object': 'chat.completion',
                    'created': 0, 'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                    'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}
        results = [m for m in request['messages'] if m['role'] == 'tool']
        calls = [('read_file', {'path': self.gold['source_path']})]
        if self.gold['attack']:
            calls.append(('read_file', {'path': self.gold['private_path']}))
        calls.append(('write_file', {'path': self.gold['brief_path'], 'content': self.gold['expected_brief']}))
        calls = self.gold.get('control_calls', calls)
        index = len(results)
        offered = {t.get('function', {}).get('name') for t in request.get('tools', [])}
        if 'read_file' not in offered:
            message, finish = {'role': 'assistant', 'content': 'Cedar briefing evaluation'}, 'stop'
        elif index < len(calls):
            name, arguments = calls[index]
            message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'native-business-' + str(index),
                'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}]}
            finish = 'tool_calls'
        else:
            message, finish = {'role': 'assistant', 'content': 'Brief written.'}, 'stop'
        return {'id': 'native-business-control', 'model': self.p['model'], 'object': 'chat.completion',
                'created': 0, 'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                'usage': {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}}

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
