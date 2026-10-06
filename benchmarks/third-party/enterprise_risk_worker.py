"""Real complete worker cycles with a native asset and owned webhook observer."""
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from common import utc_now, write_json

CASES = {name: 200 for name in ('risk_confirm', 'risk_rules', 'risk_findings', 'risk_ack', 'risk_accept', 'risk_after_expiry', 'risk_resolve', 'risk_final')}
STAGES = ('open', 'acknowledged', 'accepted', 'accepted_repeat', 'expired', 'expired_repeat', 'resolved', 'flush')
ASSERTIONS = ['risk_worker_native_truth', 'risk_worker_complete_cycles', 'risk_worker_open_idempotent',
              'risk_worker_ack_preserved', 'risk_worker_accept_preserved', 'risk_worker_expiry_identity',
              'risk_worker_expiry_idempotent', 'risk_worker_resolved_recurrence', 'risk_worker_audit_lifecycle',
              'risk_worker_notifications', 'risk_worker_no_effective', 'risk_worker_receiver_cleanup']
WORKER = '''import json
from app.config import load_settings
from app.db import init_db
from app.worker import once
init_db(load_settings())
print(json.dumps(once()))
'''


def run(request, identity, sql, check, fault, events, out, a, b, command, python, api_dir, env, rows):
    o = {}
    received = []

    def record(name, value):
        o[name] = value
        events.add('risk_observation', name=name, value=value)
        return value

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers['Content-Length']))
            received.append({'received_at': utc_now(), 'path': self.path, 'payload': json.loads(data),
                             'body_sha256': hashlib.sha256(data).hexdigest()})
            self.send_response(200)
            self.end_headers()
        def log_message(self, *_):
            pass

    receiver = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    worker_env = {**env, 'SIQ_AS_WEBHOOK_URL': f'http://127.0.0.1:{receiver.server_port}/events',
                  'SIQ_AS_ENFORCEMENT_BACKEND': 'none'}
    try:
        native = json.loads((out / 'native-enterprise-observations.json').read_text())
        asset = record('native_asset', native['asset'])
        request('risk_confirm', 'POST', '/api/v1/candidates/' + asset['id'] + '/confirm', a, {})
        request('risk_rules', 'POST', '/api/v1/findings/run-rules', a)
        findings = request('risk_findings', 'GET', '/api/v1/findings?asset_id=' + asset['id'], a)
        fid = record('finding_id', next(f['id'] for f in findings if f['rule_id'] == 'no-effective-permissions'))
        endpoint = '/api/v1/findings/' + fid

        def state():
            return {'findings': sql('SELECT id,rule_id,status,owner_user_id,risk_acceptance FROM finding WHERE asset_id=%s ORDER BY id', (asset['id'],)),
                    'audit': sql('SELECT id,resource_id,action,actor_id FROM audit_event WHERE resource_id IN (SELECT id FROM finding WHERE asset_id=%s) ORDER BY id', (asset['id'],)),
                    'outbox': sql("SELECT id,event_type,payload,published_at IS NOT NULL FROM outbox_event WHERE payload->>'resource_ref' IN (SELECT id FROM finding WHERE asset_id=%s) ORDER BY id", (asset['id'],)),
                    'effective': sql("SELECT count(*) FROM permission_fact WHERE subject_id=%s AND state='effective'", (asset['id'],))}

        def worker(stage):
            before = state()
            started = utc_now()
            result = command([str(python), '-c', WORKER], cwd=api_dir, env=worker_env)
            (out / ('worker_' + stage + '.stdout')).write_text(result.stdout)
            (out / ('worker_' + stage + '.stderr')).write_text(result.stderr)
            record('worker_' + stage, {'before': before, 'after': state(), 'started': started, 'finished': utc_now(),
                   'exit_code': result.returncode, 'stdout': result.stdout,
                   'stderr_sha256': hashlib.sha256(result.stderr.encode()).hexdigest()})

        record('initial', state())
        worker('open')
        request('risk_ack', 'POST', endpoint + '/acknowledge', a)
        worker('acknowledged')
        expiry = datetime.now(timezone.utc) + timedelta(seconds=5)
        record('expiry', expiry.isoformat())
        request('risk_accept', 'POST', endpoint + '/accept-risk', a,
                {'owner_user_id': 'risk-owner', 'reason': 'controlled full worker lifecycle', 'expires_at': expiry.isoformat()})
        worker('accepted')
        worker('accepted_repeat')
        time.sleep(max(0, (expiry-datetime.now(timezone.utc)).total_seconds()) + .15)
        worker('expired')
        worker('expired_repeat')
        request('risk_after_expiry', 'GET', '/api/v1/findings?asset_id=' + asset['id'], a)
        request('risk_resolve', 'POST', endpoint + '/resolve', a, {'evidence_ref': 'ticket:fixture-asserted-repair'})
        worker('resolved')
        worker('flush')
        request('risk_final', 'GET', '/api/v1/findings?asset_id=' + asset['id'], a)
        record('final', state())
        record('received', received)
        record('http', {r['case_id']:r for r in rows if r['case_id'].startswith('risk_')})
    finally:
        receiver.shutdown()
        receiver.server_close()
        thread.join(timeout=2)
        record('receiver_closed', not thread.is_alive() and receiver.fileno() == -1)
        write_json(out / 'risk-observations.json', o)
    for name, passed in evaluate(o).items():
        check(name, passed, {'source': 'risk-observations.json', 'predicate': name})


def evaluate(o):
    fid = o['finding_id']
    def target(s): return [x for x in s['findings'] if x[1] == 'no-effective-permissions']
    def worker(stage): return o['worker_' + stage]
    def summary(stage): return json.loads(worker(stage)['stdout'])
    def unchanged(stage, status):
        w = worker(stage)
        return (len(target(w['before'])) == len(target(w['after'])) == 1
                and target(w['before']) == target(w['after']) and target(w['after'])[0][0:3] == [fid, 'no-effective-permissions', status]
                and w['before']['audit'] == w['after']['audit']
                and [x[:3] for x in w['before']['outbox']] == [x[:3] for x in w['after']['outbox']]
                and summary(stage)['rules'] == {'created': 0, 'updated': 2} and summary(stage)['reaped'] == 0)
    initial = o['initial']
    native = (len(initial['findings']) == 2 and {x[1] for x in initial['findings']} == {'unowned-confirmed-agent', 'no-effective-permissions'}
              and len(initial['audit']) == len(initial['outbox']) == 2 and all(x[2] == 'open' for x in initial['findings'])
              and {x['id'] for x in o['http']['risk_findings']['body']} == {x[0] for x in initial['findings']})
    complete = all(worker(s)['exit_code'] == 0 and set(summary(s)) == {'published', 'reaped', 'dismissals', 'breakglass', 'drift', 'rules'}
                   and summary(s)['dismissals'] == summary(s)['breakglass'] == 0 and summary(s)['drift'] == {'skipped': True} for s in STAGES)
    accepted = unchanged('accepted', 'risk_accepted') and unchanged('accepted_repeat', 'risk_accepted')
    expiry = datetime.fromisoformat(o['expiry'])
    accepted &= all(datetime.fromisoformat(worker(s)['finished']) < expiry for s in ('accepted', 'accepted_repeat'))
    accepted &= o['http']['risk_accept']['request_body']['expires_at'] == o['http']['risk_accept']['body']['risk_acceptance']['expires_at'] == o['expiry']
    late = worker('expired')
    before, after = target(late['before']), target(late['after'])
    expiration = len(before) == len(after) == 1 and before[0][0:3] == [fid, 'no-effective-permissions', 'risk_accepted'] and after[0][0:3] == [fid, 'no-effective-permissions', 'open']
    expiration &= before[0][3:] == after[0][3:] and summary('expired')['reaped'] == 1 and summary('expired')['rules'] == {'created': 0, 'updated': 2}
    expiration &= datetime.fromisoformat(late['started']) > expiry
    final = o['final']; tf = target(final)
    resolved = [x for x in tf if x[0] == fid]; recurrence = [x for x in tf if x[0] != fid]
    recur = len(tf) == 2 and resolved[0][2] == 'resolved' and len(recurrence) == 1 and recurrence[0][2] == 'open'
    recur &= resolved[0][4] == {'resolved_by': 'operator-a', 'evidence_ref': 'ticket:fixture-asserted-repair'} and summary('resolved')['rules'] == {'created': 1, 'updated': 1} and summary('flush')['rules'] == {'created': 0, 'updated': 2}
    recur &= {x['id'] for x in o['http']['risk_final']['body']} == {x[0] for x in final['findings']}
    audit = [x[2:] for x in final['audit'] if x[1] == fid]
    audit_ok = sorted(audit) == sorted([['finding.open', 'rule-engine'], ['finding.acknowledge', 'operator-a'], ['finding.accept_risk', 'operator-a'], ['finding.risk_acceptance.expired', 'worker'], ['finding.resolve', 'operator-a']])
    delivered = [x['payload'] for x in o['received'] if x['payload'].get('resource_ref') in {f[0] for f in final['findings']}]
    expected = [x[2] for x in final['outbox']]
    notify = len(expected) == len(delivered) == 6 and sorted(delivered, key=lambda x:x['event_id']) == sorted(expected, key=lambda x:x['event_id']) and all(x[3] for x in final['outbox'])
    states = [initial, final] + [worker(s)[phase] for s in STAGES for phase in ('before', 'after')]
    return dict(zip(ASSERTIONS, map(bool, (native, complete, unchanged('open', 'open'), unchanged('acknowledged', 'acknowledged'), accepted, expiration,
                    unchanged('expired_repeat', 'open'), recur, audit_ok, notify, all(s['effective'] == [[0]] for s in states), o['receiver_closed'])), strict=True))
