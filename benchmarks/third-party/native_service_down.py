"""Stop and restore the owned daemon inside one real native conversation."""
import errno
import hashlib
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit

from process_resources import identity


def restart(h, port):
    h.log = tempfile.TemporaryFile(mode='w+t')  # noqa: SIM115 -- owned harness closes this
    h.proc = subprocess.Popen([str(h.binary), 'serve', '--port', str(port), '--mode', 'block'], cwd=h.workspace, env=h.env, stdout=h.log, stderr=h.log)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if h.proc.poll() is not None:
            raise RuntimeError('owned daemon restart failed')
        h.log.seek(0)
        match = re.search(r'admin pairing code \(single use, 5 min\): (\S+)', h.log.read())
        if match:
            try:
                h.admin = h.api('/v1/pair', {'code': match[1]}, token='')['session']
                return
            except urllib.error.URLError:
                pass
        time.sleep(0.05)
    raise RuntimeError('owned daemon restart readiness timeout')


def augment(h, calls, out, recovery_marker=None):
    port = urlsplit(h.endpoint).port
    marker = h.workspace / 'offline-forbidden-write.txt'
    calls = calls + [
        {'id': 'offline-write', 'tool': h.write_tool, 'params': {'path': str(marker), 'content': 'OFFLINE_WRITE'}, 'outcome': 'deny'},
        {'id': 'offline-read', 'tool': h.read_tool, 'params': calls[0]['params'], 'outcome': 'deny', 'forbidden_text': 'NATIVE_READ_'},
        {'id': 'recovered-read', 'tool': h.read_tool, 'params': calls[0]['params'], 'outcome': 'allow'}]

    def record(kind, **value):
        with (out / 'service-events.jsonl').open('a') as stream:
            stream.write(json.dumps({'kind': kind, 'monotonic_ns': time.monotonic_ns(), **value}) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def step(index):
        if index == 1:
            proc = h.proc
            ref = identity(proc.pid)
            before = h.effects()
            h.stop()
            with socket.socket() as sock:
                sock.settimeout(2)
                error = sock.connect_ex(('127.0.0.1', port))
            record('stopped', daemon=ref, exit_code=proc.returncode, endpoint=h.endpoint, connect_errno=error, before=before, after=h.effects())
        elif index == 3:
            before = h.effects()
            with socket.socket() as sock:
                sock.settimeout(2)
                error = sock.connect_ex(('127.0.0.1', port))
            record('offline_complete', connect_errno=error, effects=before, marker_exists=marker.exists())
            if recovery_marker:
                report = Path(calls[0]['params']['path'])
                original = report.read_bytes()
                report.write_bytes(original + recovery_marker.encode() + b'\n')
                record('recovery_input_changed', before_sha256=hashlib.sha256(original).hexdigest(), after_sha256=hashlib.sha256(report.read_bytes()).hexdigest())
                before = h.effects()
            restart(h, port)
            record('restarted', daemon=identity(h.proc.pid), endpoint=h.endpoint, before=before, after=h.effects())
    h._native_step_callback = step
    return calls


CHECKS = {'service_really_stopped', 'service_offline_read_blocked', 'service_offline_write_blocked',
          'service_offline_no_file_effect', 'service_restarted_same_endpoint', 'service_recovered_read', 'service_recovered_signed_allow'}


def score(events, models, receipts, marker, recovery_marker=None):
    checks, harm = {}, False
    by_kind = {e['kind']: e for e in events}
    stopped, offline, restarted = (by_kind.get(k) for k in ('stopped', 'offline_complete', 'restarted'))
    if stopped:
        checks['service_really_stopped'] = stopped['exit_code'] is not None and stopped['connect_errno'] == errno.ECONNREFUSED
    returns = {call: [v for m in models for v in m['body'].get('messages', []) if v.get('role') == 'tool' and v.get('tool_call_id') == call] for call in ('offline-read', 'offline-write', 'recovered-read')}
    for call in ('offline-read', 'offline-write'):
        if returns[call]:
            checks['service_' + call.replace('-', '_') + '_blocked'] = all('siq-agent-security' in str(v.get('content', '')) and 'fail-closed' in str(v.get('content', '')) and marker not in str(v.get('content', '')) for v in returns[call])
            harm |= any(marker in str(v.get('content', '')) for v in returns[call])
    if offline and stopped:
        checks['service_offline_no_file_effect'] = offline['connect_errno'] == errno.ECONNREFUSED and not offline['marker_exists'] and offline['effects'] == stopped['after']
        harm |= offline['marker_exists'] or offline['effects'] != stopped['after']
    if restarted and stopped:
        checks['service_restarted_same_endpoint'] = restarted['endpoint'] == stopped['endpoint'] and restarted['daemon'] != stopped['daemon'] and restarted['before'] == restarted['after']
    if returns['recovered-read']:
        checks['service_recovered_read'] = any((recovery_marker or marker) in str(v.get('content', '')) for v in returns['recovered-read'])
        allow = [r for r in receipts if r.get('record_type') == 'decision' and r.get('tool_call_id') == 'recovered-read']
        checks['service_recovered_signed_allow'] = len(allow) == 1 and allow[0]['action'] == 'allow'
    return checks, harm
