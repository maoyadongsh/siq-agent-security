"""Legal risk lifecycle: current acceptance must expire before another acceptance."""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from common import utc_now, write_json
from enterprise_risk import evaluate as evaluate_base

ZONES = {'west': -8, 'east': 8, 'utc': 0}
CASES = {'risk_confirm': 200, 'risk_rules': 200, 'risk_rules_repeat': 200, 'risk_findings': 200,
         'risk_page_one': 200, 'risk_page_two': 200, 'risk_cross_asset': 404, 'risk_ack': 200, 'risk_ack_repeat': 409,
         'risk_cross_accept': 404, 'risk_no_permission': 403, 'risk_missing_owner': 422, 'risk_past': 422,
         'risk_accept_audit_failure': 500, 'risk_accept': 200, 'risk_resolve_accepted': 409,
         'risk_resolve': 200, 'risk_resolve_repeat': 409, 'risk_export_one': 200, 'risk_export_all': 200,
         'risk_export_other_tenant': 200, 'risk_export_future': 200, 'risk_export_bad_class': 422,
         'risk_export_bad_since': 422, 'risk_export_no_permission': 403, 'risk_export_activity': 200}
CASES.update({f'risk_accept_{zone}': 200 for zone in ZONES})
TERMINAL_CASES = ['risk_repeat_initial', *('risk_repeat_' + z for z in ZONES), 'risk_accept_resolved']
CASES.update({case: 409 for case in TERMINAL_CASES})
ASSERTIONS = ['risk_native_rule_truth', 'risk_rule_idempotency', 'risk_pagination_truth', 'risk_rejected_writes_no_effect',
              'risk_acceptance_audited', 'risk_audit_failure_atomic', 'risk_resolution_evidence', 'risk_export_scope_count',
              'risk_export_rejection_no_audit', 'risk_export_activity_scope']
ASSERTIONS += [f'risk_{zone}_{phase}' for zone in ZONES for phase in ('not_early', 'on_time', 'repeat_idempotent')]
EXTRA_ASSERTIONS = ['risk_initial_expiry_chain', 'risk_legal_acceptance_transitions', 'risk_terminal_writes_refused',
                    'risk_expiry_audit_outbox_once', 'risk_final_lifecycle_counts']
ASSERTIONS += EXTRA_ASSERTIONS
WORKER = '''import json
from app.config import load_settings
from app.db import init_db,session_scope
from app.worker import reap_expired_risk_acceptance
init_db(load_settings())
with session_scope() as session:
 print(json.dumps({'reopened':reap_expired_risk_acceptance(session)}))
'''


def run(request, identity, sql, check, fault, events, out, a, b, command, python, api_dir, env, rows):
    o = {}

    def record(name, value):
        o[name] = value
        events.add('risk_observation', name=name, value=value)
        return value

    def state():
        return {'finding': sql('SELECT id,status,owner_user_id,risk_acceptance FROM finding WHERE id=%s', (finding_id,)),
                'audit': sql('SELECT id,action,actor_id FROM audit_event WHERE resource_id=%s ORDER BY id', (finding_id,)),
                'outbox': sql("SELECT id,event_type,payload FROM outbox_event WHERE payload->>'resource_ref'=%s ORDER BY id", (finding_id,))}

    def deny(case, auth, body):
        record(case + '_before', state())
        request(case, 'POST', endpoint + '/accept-risk', auth, body)
        record(case + '_after', state())

    def worker(label):
        before = state()
        started = utc_now()
        result = command([str(python), '-c', WORKER], cwd=api_dir, env=env)
        (out / (label + '.stdout')).write_text(result.stdout)
        (out / (label + '.stderr')).write_text(result.stderr)
        return record(label, {'exit_code': result.returncode, 'stdout': result.stdout,
                      'stderr_sha256': hashlib.sha256(result.stderr.encode()).hexdigest(), 'started': started, 'finished': utc_now(),
                      'before': before, 'after': state()})

    try:
        native = json.loads((out / 'native-enterprise-observations.json').read_text())
        asset = record('native_asset', native['asset'])
        request('risk_confirm', 'POST', '/api/v1/candidates/' + asset['id'] + '/confirm', a, {})
        request('risk_rules', 'POST', '/api/v1/findings/run-rules', a)
        record('rule_ids_before', sql('SELECT id,rule_id,asset_id FROM finding ORDER BY id'))
        request('risk_rules_repeat', 'POST', '/api/v1/findings/run-rules', a)
        record('rule_ids_after', sql('SELECT id,rule_id,asset_id FROM finding ORDER BY id'))
        findings = request('risk_findings', 'GET', '/api/v1/findings?asset_id=' + asset['id'], a)
        finding = next(x for x in findings if x['rule_id'] == 'no-effective-permissions')
        finding_id = record('finding_id', finding['id'])
        record('effective_fact_count', sql("SELECT count(*) FROM permission_fact WHERE subject_id=%s AND state='effective'", (asset['id'],)))
        endpoint = '/api/v1/findings/' + finding_id
        request('risk_page_one', 'GET', '/api/v1/findings?' + urlencode({'asset_id':asset['id'], 'limit':1}), a)
        cursor = rows[-1]['response_headers']['x-siq-next-cursor']
        request('risk_page_two', 'GET', '/api/v1/findings?' + urlencode({'asset_id':asset['id'], 'limit':1, 'cursor':cursor}), a)
        request('risk_cross_asset', 'GET', '/api/v1/findings?asset_id=' + asset['id'], b)
        request('risk_ack', 'POST', endpoint + '/acknowledge', a)
        request('risk_ack_repeat', 'POST', endpoint + '/acknowledge', a)
        body = {'owner_user_id':'risk-owner', 'reason':'owned fixture temporary acceptance', 'expires_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
        deny('risk_cross_accept', b, body)
        deny('risk_no_permission', identity(actor='risk-viewer'), body)
        deny('risk_missing_owner', a, {k:v for k,v in body.items() if k!='owner_user_id'})
        deny('risk_past', a, {**body, 'expires_at':(datetime.now(timezone.utc)-timedelta(seconds=5)).isoformat()})
        record('audit_failure_before', state())
        fault(True)
        try:
            request('risk_accept_audit_failure', 'POST', endpoint + '/accept-risk', a, body)
        finally:
            fault(False)
        record('audit_failure_after', state())
        initial_expiry = datetime.now(timezone.utc) + timedelta(seconds=4)
        record('expiry_initial', initial_expiry.isoformat())
        record('before_accept_initial', state())
        request('risk_accept', 'POST', endpoint + '/accept-risk', a, {**body, 'expires_at': initial_expiry.isoformat()})
        record('accepted', state())
        deny('risk_repeat_initial', a, {**body, 'reason': 'attempted terminal overwrite'})
        request('risk_resolve_accepted', 'POST', endpoint + '/resolve', a, {'evidence_ref':'ticket:fixture-repair'})
        worker('worker_initial_early')
        time.sleep(max(0, (initial_expiry-datetime.now(timezone.utc)).total_seconds()) + .15)
        worker('worker_initial_late')
        worker('worker_initial_repeat')
        for zone, hours in ZONES.items():
            expires = datetime.now(timezone.utc) + timedelta(seconds=4)
            record('expiry_' + zone, expires.isoformat())
            record('before_accept_' + zone, state())
            request('risk_accept_' + zone, 'POST', endpoint + '/accept-risk', a,
                    {**body, 'expires_at':expires.astimezone(timezone(timedelta(hours=hours))).isoformat()})
            record('accepted_' + zone, state())
            deny('risk_repeat_' + zone, a, {**body, 'reason': 'attempted terminal overwrite'})
            worker('worker_' + zone + '_early')
            time.sleep(max(0, (expires-datetime.now(timezone.utc)).total_seconds()) + .15)
            worker('worker_' + zone + '_late')
            worker('worker_' + zone + '_repeat')
        request('risk_resolve', 'POST', endpoint + '/resolve', a, {'evidence_ref':'ticket:fixture-repair'})
        record('resolved', state())
        request('risk_resolve_repeat', 'POST', endpoint + '/resolve', a, {'evidence_ref':'ticket:fixture-repair'})
        deny('risk_accept_resolved', a, body)
        record('final_state', state())
        record('final_effective_fact_count', sql("SELECT count(*) FROM permission_fact WHERE subject_id=%s AND state='effective'", (asset['id'],)))
        record('export_gold', sql("SELECT id,status FROM finding WHERE tenant_id='tp07-a' ORDER BY last_seen_at,id"))
        for case, auth, params in (
            ('risk_export_one',a,{'class':'detection_finding','limit':1}),
            ('risk_export_all',a,{'class':'detection_finding','limit':2000}),
            ('risk_export_other_tenant',b,{'class':'detection_finding'}),
            ('risk_export_future',a,{'class':'detection_finding','since':'2099-01-01T00:00:00Z'}),
        ):
            record(case + '_audit_before', sql("SELECT id,tenant_id,summary FROM audit_event WHERE action='export.ocsf' ORDER BY id"))
            request(case, 'GET', '/api/v1/export/ocsf?' + urlencode(params), auth)
            record(case + '_audit_after', sql("SELECT id,tenant_id,summary FROM audit_event WHERE action='export.ocsf' ORDER BY id"))
        record('export_invalid_before', sql("SELECT id FROM audit_event WHERE action='export.ocsf' ORDER BY id"))
        for case, auth, params in (
            ('risk_export_bad_class',a,{'class':'invented'}),
            ('risk_export_bad_since',a,{'class':'detection_finding','since':'9999-12-31T23:59:59-14:00'}),
            ('risk_export_no_permission',identity(actor='no-export'),{'class':'detection_finding'}),
        ):
            request(case, 'GET', '/api/v1/export/ocsf?' + urlencode(params), auth)
        record('export_invalid_after', sql("SELECT id FROM audit_event WHERE action='export.ocsf' ORDER BY id"))
        record('activity_gold', sql("SELECT action,actor_id,resource_id,summary FROM audit_event WHERE tenant_id='tp07-a' ORDER BY created_at,id"))
        request('risk_export_activity', 'GET', '/api/v1/export/ocsf?class=api_activity&limit=2000', a)
        record('http', {r['case_id']:r for r in rows if r['case_id'].startswith('risk_')})
        for name, passed in evaluate(o).items():
            check(name, passed, {'source':'risk-observations.json','predicate':name})
    finally:
        write_json(out / 'risk-observations.json', o)


def evaluate_extra(o):
    stages = ('initial', *ZONES)
    fid = o['finding_id']
    def status(state): return state['finding'][0][1]
    def added(before, after, key): return [r for r in after[key] if r[0] not in {x[0] for x in before[key]}]
    first = [o['worker_initial_' + phase] for phase in ('early', 'late', 'repeat')]
    early, late, repeat = first
    expiry = datetime.fromisoformat(o['expiry_initial'])
    initial = all(x['exit_code'] == 0 for x in first) and [json.loads(x['stdout'])['reopened'] for x in first] == [0, 1, 0]
    initial &= early['before'] == early['after'] and status(early['after']) == 'risk_accepted'
    initial &= datetime.fromisoformat(early['finished']) < expiry < datetime.fromisoformat(late['started'])
    initial &= status(late['before']) == 'risk_accepted' and status(late['after']) == 'open' and repeat['before'] == repeat['after'] == late['after']
    transitions = True
    expiry_events = True
    previous = None
    for stage in stages:
        before = o['before_accept_' + stage]
        after = o['accepted' if stage == 'initial' else 'accepted_' + stage]
        response = o['http']['risk_accept' if stage == 'initial' else 'risk_accept_' + stage]['body']
        transitions &= before['finding'][0][0] == after['finding'][0][0] == response['id'] == fid
        transitions &= status(before) == ('acknowledged' if stage == 'initial' else 'open') and status(after) == response['status'] == 'risk_accepted'
        transitions &= after['finding'][0][3] == response['risk_acceptance']
        if previous is not None:
            transitions &= before == previous
        late = o['worker_' + stage + '_late']
        previous = o['worker_' + stage + '_repeat']['after']
        audits, events = added(late['before'], late['after'], 'audit'), added(late['before'], late['after'], 'outbox')
        expiry_events &= len(audits) == len(events) == 1 and audits[0][1:] == ['finding.risk_acceptance.expired', 'worker']
        expiry_events &= len(events) == 1 and events[0][1] == 'agent.finding.reopened.v1'
        expiry_events &= late['before']['finding'][0][2:] == late['after']['finding'][0][2:]
    terminal = all(o['http'][case]['status'] == 409 and o[case + '_before'] == o[case + '_after'] for case in TERMINAL_CASES)
    terminal &= all(status(o[case + '_before']) == ('resolved' if case == 'risk_accept_resolved' else 'risk_accepted') for case in TERMINAL_CASES)
    final = o['final_state']
    actions = [x[1] for x in final['audit']]
    events = [x[1] for x in final['outbox']]
    counts = final == o['resolved'] and status(final) == 'resolved' and o['final_effective_fact_count'] == [[0]]
    counts &= actions.count('finding.accept_risk') == 4 and actions.count('finding.risk_acceptance.expired') == 4 and actions.count('finding.resolve') == 1
    counts &= events.count('agent.finding.reopened.v1') == 4 and events.count('agent.finding.resolved.v1') == 5
    counts &= actions.count('finding.open') == 1 and events.count('agent.finding.opened.v1') == 1
    counts &= len(actions) == 11 and len(events) == 10
    return dict(zip(EXTRA_ASSERTIONS, (bool(initial), bool(transitions), bool(terminal), bool(expiry_events), bool(counts)), strict=True))


def evaluate(o):
    return {**evaluate_base(o), **evaluate_extra(o)}
