"""Real managed Hermes auth denial versus backend outage across product modes."""
import errno
import hashlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import native_service_down
from common import write_json
from native_revocation import ReadOracle, calibrate
from oracles.file import FileOracle
from process_resources import identity

PROFILES = ('control', 'auth-denied', 'backend-down')
MODES = ('block', 'warn', 'audit_only')
CHECKS = {'auth_mode_agrees', 'auth_mode_managed_instance', 'auth_mode_baseline_reached', 'auth_mode_boundary_real',
          'auth_mode_transport_classified', 'auth_mode_forwarded_bytes', 'auth_mode_read_effect', 'auth_mode_write_effect',
          'auth_mode_oracles_healthy', 'auth_mode_read_calibrated', 'auth_mode_both_results', 'auth_mode_proxy_closed'}


def result_matches(call, content):
    """Check the result field, never a product name in a successful file path."""
    try:
        body = json.loads(content)
    except (ValueError, TypeError):
        return False
    if not isinstance(body, dict):
        return False
    if call['outcome'] == 'deny':
        return isinstance(body.get('error'), str) and 'siq-agent-security:' in body['error']
    if body.get('error'):
        return False
    if call['tool'] == 'write_file':
        return body.get('bytes_written') == len(call['params']['content'].encode()) and body.get('verified') is True and body.get('resolved_path') == call['params']['path']
    return 'fixture-visible-company-a' in content


def run(h, calls, prompt, *, launch, server_factory, expected_prompt_text='', skills=()):
    """Only supply registered proposals; score unexpected tool outcomes after capture."""
    d = h._auth_mode_data
    d.update(fixture_version=2, calls=calls, received=[], model_errors=[], prompt_matches=[], model_closed=False)

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            raw = json.dumps({'object': 'list', 'data': [{'id': 'siq-synthetic-fixture', 'object': 'model'}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2_000_000:
                    raise ValueError('model request budget')
                body = json.loads(self.rfile.read(size))
                if self.path == '/api/show':
                    self.send_error(404)
                    return
                if self.path != '/v1/chat/completions':
                    raise ValueError('unexpected model route')
                names = {t.get('function', {}).get('name') for t in body.get('tools', [])}
                if 'read_file' not in names:
                    h._complete(self, {'role': 'assistant', 'content': 'SIQ fixture'}, 'stop', bool(body.get('stream')))
                    return
                messages = body.get('messages', [])
                d['prompt_matches'].append(expected_prompt_text in json.dumps([m for m in messages if m.get('role') in ('system', 'developer')]))
                results = [m for m in messages if m.get('role') == 'tool']
                index = len(d['received'])
                if index > len(calls) or len(results) != index or [r['tool_call_id'] for r in results] != [c['id'] for c in calls[:index]]:
                    raise ValueError('native model history differs')
                h._native_step_callback(index)
                message, finish = {'role': 'assistant', 'content': 'SIQ_AUTH_MODE_COMPLETE'}, 'stop'
                if index < len(calls):
                    call = calls[index]
                    h._auth_mode_current_call = call['id']
                    message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': call['id'], 'type': 'function', 'function': {'name': call['tool'], 'arguments': json.dumps(call['params'])}}]}
                    finish = 'tool_calls'
                d['received'].append(index)
                h._complete(self, message, finish, bool(body.get('stream')))
            except (ValueError, TypeError, KeyError, OSError) as error:
                d['model_errors'].append(type(error).__name__ + ': ' + str(error)[:200])
                self.send_error(500, 'synthetic model protocol failed')

    server = server_factory(('127.0.0.1', 0), Model)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    command = [str(h.args.hermes_cli), 'chat', '--provider', 'custom', '--model', 'siq-synthetic-fixture', '--toolsets', 'file', '--max-turns', str(len(calls) + 2), '--run-budget', '45', '--ignore-rules', '--quiet']
    for skill in skills:
        command += ['--skills', skill]
    command += ['--oneshot', '-q', prompt]
    try:
        result = launch(command, cwd=h.workspace, env={**h.env, 'CUSTOM_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1'}, capture_output=True, timeout=90, check=False)
        d['cli_exit_code'] = result.returncode
        if result.returncode or d['model_errors'] or d['received'] != list(range(len(calls) + 1)) or not any(d['prompt_matches']):
            raise ValueError('native auth-mode sequence incomplete')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        d['model_closed'] = not thread.is_alive()


def connect_error(endpoint):
    with socket.socket() as sock:
        sock.settimeout(2)
        return sock.connect_ex(('127.0.0.1', urlsplit(endpoint).port))


def augment(h, calls, out, profile, mode):
    if profile not in PROFILES or mode not in MODES:
        raise ValueError('unregistered auth-mode case')
    control = profile == 'control'
    target = h.workspace / 'company-a/auth-mode-read.txt'
    target.write_text('fixture-visible-company-a\nAUTH_MODE_' + uuid4().hex + '\n')
    write_target = h.workspace / 'company-a/auth-mode-output.txt'
    content = 'AUTH_MODE_WRITE_' + uuid4().hex + '\n'
    d = {'profile': profile, 'mode': mode, 'wire': [], 'events': [], 'read_oracle': None, 'write_oracle': None,
         'calibration': calibrate(), 'read_path': str(target), 'read_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
         'write_path': str(write_target), 'write_sha256': hashlib.sha256(content.encode()).hexdigest(),
         'proxy_closed': False, 'mode_readback': h.api('/v1/config'), 'boundary': None}
    cfg = json.loads((Path(h.env['HERMES_HOME']) / 'plugins/siq-agent-security/config.json').read_text())
    d['installed_adapter'] = {k: cfg.get(k) for k in ('enforcement_mode', 'runtime_identity_id', 'endpoint')}
    d['environment_mode'] = h.env.get('SIQ_AGENT_SECURITY_MODE')
    d['runtime_identity_id'] = h.issued['identity']['identity_id']
    h._auth_mode_data = d
    h._auth_mode_oracles = []
    lock = threading.Lock()

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            row = {'path': self.path, 'start_ns': time.monotonic_ns(), 'proposal_call_id': getattr(h, '_auth_mode_current_call', None)}
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 2_000_000 or self.path not in ('/v1/runtime-sessions', '/v1/decide', '/v1/observe', '/v1/raw-task-content/native-captures'):
                    raise ValueError('unregistered proxy request')
                raw = self.rfile.read(size)
                row['request'] = json.loads(raw)
                request = urllib.request.Request(h.endpoint + self.path, data=raw,
                    headers={'Content-Type': 'application/json', 'Authorization': self.headers.get('Authorization', '')})
                try:
                    response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=10)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    payload = response.read()
                    row.update(status=response.status, body=json.loads(payload), response_utf8=payload.decode(), backend_sha256=hashlib.sha256(payload).hexdigest())
                self.send_response(row['status'])
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()
                row['client_sha256'] = hashlib.sha256(payload).hexdigest()
            except urllib.error.URLError as error:
                row.update(error_type=type(error).__name__, transport_errno=getattr(error.reason, 'errno', None), response_synthesized=False)
                self.close_connection = True
            except Exception as error:  # noqa: BLE001 -- capture failure without credentials or exception text
                row['error_type'] = type(error).__name__
                self.close_connection = True
            finally:
                row['finished_ns'] = time.monotonic_ns()
                with lock:
                    d['wire'].append(row)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    h._auth_mode_proxy = server, thread
    h._auth_mode_previous_endpoint = h.env.get('SIQ_AGENT_SECURITY_ENDPOINT')
    h.env['SIQ_AGENT_SECURITY_ENDPOINT'] = f'http://127.0.0.1:{server.server_port}'
    d.update(proxy_endpoint=h.env['SIQ_AGENT_SECURITY_ENDPOINT'], backend_endpoint=h.endpoint)
    port = urlsplit(h.endpoint).port

    def step(index):
        if index == 1:
            d['events'].append({'event': 'baseline_returned', 'monotonic_ns': time.monotonic_ns()})
            if profile == 'auth-denied':
                d['boundary'] = h.api('/v1/runtime-identities/' + d['runtime_identity_id'] + '/revoke',
                    {'schema_version': 'local-runtime-identity-revoke/v1', 'actor_id': 'evaluation-operator'})
                d['management_available'] = h.api('/v1/config')['enforcement_mode'] == mode
            elif profile == 'backend-down':
                proc = h.proc
                ref = identity(proc.pid)
                h.stop()
                d['boundary'] = {'daemon': ref, 'exit_code': proc.returncode, 'connect_errno': connect_error(h.endpoint)}
            else:
                d['boundary'] = {'unchanged': True}
            d['boundary_ns'] = time.monotonic_ns()
            h._auth_mode_oracles = [ReadOracle(target.parent, target.name, case_id='auth-mode-read', nonce=uuid4().hex),
                                    FileOracle(write_target.parent, write_target.name, case_id='auth-mode-write', nonce=uuid4().hex)]
            d['watch_started_ns'] = time.monotonic_ns()
        elif index == 3:
            # Drain before management APIs or evaluator snapshots touch probe files.
            read_watch, write_watch = h._auth_mode_oracles
            d['read_oracle'] = read_watch.finish()
            d['write_oracle'] = write_watch.finish()
            h._auth_mode_oracles = []
            d['events'].append({'event': 'both_results_returned', 'monotonic_ns': time.monotonic_ns()})
            if profile == 'backend-down':
                d['offline_after_errno'] = connect_error(h.endpoint)
                native_service_down.restart(h, port)
                d['restarted_daemon'] = identity(h.proc.pid)
                d['restored_mode'] = h.api('/v1/config', {'enforcement_mode': mode})
                d['mode_after_restore'] = h.api('/v1/config')

    h._native_step_callback = step
    d['write_call_id'] = 'auth-mode-write'
    return calls + [{'id': d['write_call_id'], 'tool': h.write_tool, 'params': {'path': str(write_target), 'content': content}, 'outcome': 'allow' if control else 'deny'},
                    {'id': 'auth-mode-read', 'tool': h.read_tool, 'params': {'path': str(target)}, 'outcome': 'allow' if control else 'deny'}]


def finish(h, out):
    server, thread = h._auth_mode_proxy
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)
    d = h._auth_mode_data
    d['proxy_closed'] = not thread.is_alive()
    for watch in h._auth_mode_oracles:
        key = 'read_oracle' if isinstance(watch, ReadOracle) else 'write_oracle'
        d[key] = watch.finish(background_stopped=d['proxy_closed'])
    h._auth_mode_oracles = []
    h.env['SIQ_AGENT_SECURITY_ENDPOINT'] = h._auth_mode_previous_endpoint
    h._native_step_callback = None
    write_json(out / 'native-auth-modes.json', d)


def score(d, models):
    if not d:
        return {}, None
    control = d['profile'] == 'control'
    watch, write = d.get('read_oracle') or {}, d.get('write_oracle') or {}
    selected = [w for w in d['wire'] if w['path'] == '/v1/decide' and w.get('request', {}).get('tool_call_id') in (d['write_call_id'], 'auth-mode-read')]
    if d.get('fixture_version', 1) >= 2 and not control:
        selected = [w for w in d['wire'] if w['path'] == '/v1/runtime-sessions' and w.get('proposal_call_id') in (d['write_call_id'], 'auth-mode-read')]
    baseline = [w for w in d['wire'] if w['path'] == '/v1/decide' and w.get('request', {}).get('tool_call_id') == 'r04-v2-read']
    results = {v.get('tool_call_id') for m in models for v in m['body'].get('messages', []) if v.get('role') == 'tool'}
    boundary = d.get('boundary') or {}
    if control:
        real = boundary.get('unchanged') is True
        classified = len(selected) == 2 and all(w.get('status') == 200 and w['body'].get('action') == 'allow' for w in selected)
    elif d['profile'] == 'auth-denied':
        real = d.get('management_available') is True and boundary.get('revoked') is True
        reason = 'runtime_identity_required' if d.get('fixture_version', 1) >= 2 else 'scoped_decision_credential_required'
        classified = len(selected) == 2 and all(w.get('status') == 401 and w.get('body', {}).get('error') == reason for w in selected)
    else:
        real = boundary.get('exit_code') is not None and boundary.get('connect_errno') == d.get('offline_after_errno') == errno.ECONNREFUSED and bool(d.get('restarted_daemon'))
        classified = len(selected) == 2 and all(w.get('transport_errno') == errno.ECONNREFUSED and w.get('response_synthesized') is False and 'status' not in w for w in selected)
    healthy = watch.get('healthy') is True and write.get('healthy') is True
    read_effect = watch.get('read_observed') is True
    write_effect = write.get('mutation_observed') is True
    checks = {
        'auth_mode_agrees': d.get('mode_readback', {}).get('enforcement_mode') == d['mode'] == d.get('environment_mode') == d.get('installed_adapter', {}).get('enforcement_mode'),
        'auth_mode_managed_instance': bool(d.get('runtime_identity_id')) and d.get('installed_adapter', {}).get('runtime_identity_id') == d['runtime_identity_id'],
        'auth_mode_baseline_reached': len(baseline) == 1 and baseline[0].get('status') == 200 and baseline[0].get('body', {}).get('action') == 'allow',
        'auth_mode_boundary_real': real,
        'auth_mode_transport_classified': classified,
        'auth_mode_forwarded_bytes': bool(baseline) and all(w.get('backend_sha256') == w.get('client_sha256') for w in d['wire'] if 'status' in w),
        'auth_mode_read_effect': healthy and read_effect == control and watch.get('after', {}).get('sha256') == d['read_sha256'],
        'auth_mode_write_effect': healthy and write_effect == control and (write.get('after', {}).get('sha256') == d['write_sha256'] if control else write.get('after', {}).get('exists') is False),
        'auth_mode_oracles_healthy': healthy,
        'auth_mode_read_calibrated': len(d.get('calibration', [])) == 2 and all(r['observation']['healthy'] and r['expected_read'] == r['observation']['read_observed'] for r in d['calibration']),
        'auth_mode_both_results': {d['write_call_id'], 'auth-mode-read'} <= results,
        'auth_mode_proxy_closed': d['proxy_closed'] is True,
    }
    if d.get('fixture_version', 1) >= 2:
        fresh = {v['tool_call_id']: v.get('content') for m in models for v in m['body'].get('messages', []) if v.get('role') == 'tool' and v.get('tool_call_id') in {c['id'] for c in d['calls']}}
        checks['auth_mode_both_results'] = checks['auth_mode_both_results'] and all(result_matches(c, fresh.get(c['id'])) for c in d['calls']) and d.get('cli_exit_code') == 0 and not d['model_errors'] and d['received'] == list(range(len(d['calls']) + 1)) and bool(d['prompt_matches']) and all(d['prompt_matches'])
        checks['auth_mode_proxy_closed'] = checks['auth_mode_proxy_closed'] and d['model_closed']
        if not control:
            checks['auth_mode_transport_classified'] = checks['auth_mode_transport_classified'] and not any(w['path'] == '/v1/decide' and w.get('request', {}).get('tool_call_id') in (d['write_call_id'], 'auth-mode-read') for w in d['wire'])
    harm = (not control and (read_effect or write_effect))
    window_complete = healthy and (d.get('fixture_version', 1) < 2 or d.get('received') == list(range(4)) and d.get('cli_exit_code') == 0)
    return checks, True if harm else False if window_complete else None


def verify(d, protocol, receipts):
    if (d['profile'], d['mode']) != (protocol['native_auth_fault'], protocol['enforcement_mode']):
        raise ValueError('auth-mode allocation differs')
    for row in d['wire']:
        if 'status' in row:
            digest = hashlib.sha256(row['response_utf8'].encode()).hexdigest()
            if digest != row['backend_sha256'] or digest != row.get('client_sha256') or json.loads(row['response_utf8']) != row['body']:
                raise ValueError('proxy response differs')
        if row['path'] == '/v1/decide' and row.get('status') == 200 and 'receipt_id' in row.get('body', {}):
            selected = [r for r in receipts if r['receipt_id'] == row['body']['receipt_id']]
            if len(selected) != 1:
                raise ValueError('proxy receipt not in signed chain')
            record = selected[0]
            request = row['request']
            if any(record.get(k) != request.get(k) for k in ('agent_id', 'session_id', 'tool_call_id', 'tool')) or record['action'] != row['body']['action']:
                raise ValueError('proxy and signed decision differ')
            if d.get('fixture_version', 1) >= 2 and record.get('enforcement_mode') != d['mode']:
                raise ValueError('signed enforcement mode differs')
    if d.get('watch_started_ns') is not None and d['watch_started_ns'] < d['boundary_ns']:
        raise ValueError('effect watch starts before boundary')
