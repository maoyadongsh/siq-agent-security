"""Native asset risk lifecycle and honest export using real API, PG and reaper."""
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from common import utc_now, write_json

ZONES = {'west': -8, 'east': 8, 'utc': 0}
CASES = {'risk_confirm': 200, 'risk_rules': 200, 'risk_rules_repeat': 200, 'risk_findings': 200,
         'risk_page_one': 200, 'risk_page_two': 200, 'risk_cross_asset': 404, 'risk_ack': 200, 'risk_ack_repeat': 409,
         'risk_cross_accept': 404, 'risk_no_permission': 403, 'risk_missing_owner': 422, 'risk_past': 422,
         'risk_accept_audit_failure': 500, 'risk_accept': 200, 'risk_resolve_accepted': 409,
         'risk_resolve': 200, 'risk_resolve_repeat': 409, 'risk_export_one': 200, 'risk_export_all': 200,
         'risk_export_other_tenant': 200, 'risk_export_future': 200, 'risk_export_bad_class': 422,
         'risk_export_bad_since': 422, 'risk_export_no_permission': 403, 'risk_export_activity': 200}
CASES.update({f'risk_accept_{zone}': 200 for zone in ZONES})
ASSERTIONS = ['risk_native_rule_truth', 'risk_rule_idempotency', 'risk_pagination_truth', 'risk_rejected_writes_no_effect',
              'risk_acceptance_audited', 'risk_audit_failure_atomic', 'risk_resolution_evidence', 'risk_export_scope_count',
              'risk_export_rejection_no_audit', 'risk_export_activity_scope']
ASSERTIONS += [f'risk_{zone}_{phase}' for zone in ZONES for phase in ('not_early', 'on_time', 'repeat_idempotent')]
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
        request('risk_accept', 'POST', endpoint + '/accept-risk', a, body)
        record('accepted', state())
        request('risk_resolve_accepted', 'POST', endpoint + '/resolve', a, {'evidence_ref':'ticket:fixture-repair'})
        for zone, hours in ZONES.items():
            expires = datetime.now(timezone.utc) + timedelta(seconds=4)
            record('expiry_' + zone, expires.isoformat())
            request('risk_accept_' + zone, 'POST', endpoint + '/accept-risk', a,
                    {**body, 'expires_at':expires.astimezone(timezone(timedelta(hours=hours))).isoformat()})
            worker('worker_' + zone + '_early')
            time.sleep(max(0, (expires-datetime.now(timezone.utc)).total_seconds()) + .15)
            worker('worker_' + zone + '_late')
            worker('worker_' + zone + '_repeat')
        request('risk_resolve', 'POST', endpoint + '/resolve', a, {'evidence_ref':'ticket:fixture-repair'})
        record('resolved', state())
        request('risk_resolve_repeat', 'POST', endpoint + '/resolve', a, {'evidence_ref':'ticket:fixture-repair'})
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


def evaluate(o):
    http = o['http']
    findings = http['risk_findings']['body']
    subject = o['native_asset']['id']
    def state_status(x): return x['finding'][0][1]
    def count(x, event): return sum(row[1] == event for row in x['audit'])
    accepted, resolved = o['accepted'], o['resolved']
    page1, page2 = (http['risk_page_' + name] for name in ('one','two'))
    results = {
        'risk_native_rule_truth': len(findings)==2 and {x['rule_id'] for x in findings}=={'no-effective-permissions','unowned-confirmed-agent'}
         and all(x['asset_id']==subject and x['status']=='open' for x in findings) and o['effective_fact_count']==[[0]],
        'risk_rule_idempotency': o['rule_ids_before']==o['rule_ids_after'] and http['risk_rules_repeat']['body']['created']==0,
        'risk_pagination_truth': len(page1['body'])==len(page2['body'])==1 and {x['id'] for p in [page1,page2] for x in p['body']}=={x['id'] for x in findings}
         and page1['response_headers']['x-siq-list-truncated']=='1' and page2['response_headers']['x-siq-list-truncated']=='0'
         and all(p['response_headers']['x-siq-list-returned']=='1' for p in [page1,page2]),
        'risk_rejected_writes_no_effect': all(o[c+'_before']==o[c+'_after'] for c in ('risk_cross_accept','risk_no_permission','risk_missing_owner','risk_past')),
        'risk_acceptance_audited': state_status(accepted)=='risk_accepted' and accepted['finding'][0][2]=='risk-owner'
         and accepted['finding'][0][3]['reason']=='owned fixture temporary acceptance' and count(accepted,'finding.accept_risk')==1
         and any(x[1]=='agent.finding.resolved.v1' for x in accepted['outbox']),
        'risk_audit_failure_atomic': o['audit_failure_before']==o['audit_failure_after'],
        'risk_resolution_evidence': state_status(resolved)=='resolved' and resolved['finding'][0][3]['evidence_ref']=='ticket:fixture-repair' and count(resolved,'finding.resolve')==1,
        'risk_export_rejection_no_audit': o['export_invalid_before']==o['export_invalid_after'],
    }
    export_ok = True
    for case, gold, tenant, truncated in [('risk_export_one',o['export_gold'][:1],'tp07-a','1'),('risk_export_all',o['export_gold'],'tp07-a','0'),
                                         ('risk_export_other_tenant',[],'tp07-b','0'),('risk_export_future',[],'tp07-a','0')]:
        row=http[case]; data=[json.loads(s) for s in row['body']['ndjson'].splitlines()];headers=row['response_headers']
        export_ok &= [x['finding_info']['uid'] for x in data]==[x[0] for x in gold] and all(x['class_uid']==2004 for x in data)
        export_ok &= [x['status_id'] for x in data]==[{'open':1,'acknowledged':2,'risk_accepted':3,'resolved':4}[x[1]] for x in gold]
        export_ok &= headers['x-siq-export-truncated']==truncated and headers['cache-control']=='no-store' and headers['content-type'].startswith('application/x-ndjson')
        before,after=o[case+'_audit_before'],o[case+'_audit_after'];new=[x for x in after if x[0] not in {r[0] for r in before}]
        export_ok &= len(new)==1 and new[0][1]==tenant and new[0][2]['count']==len(data) and set(new[0][2])=={'class','count','since'}
    results['risk_export_scope_count']=bool(export_ok)
    activity=[json.loads(s) for s in http['risk_export_activity']['body']['ndjson'].splitlines()]
    results['risk_export_activity_scope'] = len(activity)==len(o['activity_gold']) and all(x['class_uid']==6003 for x in activity)
    results['risk_export_activity_scope'] &= [[x['activity_name'],x['actor']['user']['uid'],x['resources'][0].get('uid'),x['unmapped']['summary']] for x in activity]==o['activity_gold']
    for zone in ZONES:
        early,late,repeat=(o[f'worker_{zone}_{moment}'] for moment in ('early','late','repeat'))
        expiry=datetime.fromisoformat(o['expiry_'+zone])
        results[f'risk_{zone}_not_early'] = early['exit_code']==0 and json.loads(early['stdout'])['reopened']==0 and early['before']==early['after']
        results[f'risk_{zone}_not_early'] &= state_status(early['after'])=='risk_accepted' and datetime.fromisoformat(early['finished'])<expiry
        results[f'risk_{zone}_on_time'] = late['exit_code']==0 and json.loads(late['stdout'])['reopened']==1 and state_status(late['before'])=='risk_accepted' and state_status(late['after'])=='open'
        results[f'risk_{zone}_on_time'] &= datetime.fromisoformat(late['started'])>expiry and count(late['after'],'finding.risk_acceptance.expired')==count(late['before'],'finding.risk_acceptance.expired')+1
        results[f'risk_{zone}_repeat_idempotent'] = repeat['exit_code']==0 and json.loads(repeat['stdout'])['reopened']==0 and repeat['before']==repeat['after'] and state_status(repeat['after'])=='open'
    if set(results)!=set(ASSERTIONS): raise ValueError('risk assertion allocation differs')
    return {k:bool(v) for k,v in results.items()}
