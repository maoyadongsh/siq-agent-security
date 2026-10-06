"""Actual risk HTTP/worker overlap, with explicit owned PostgreSQL barriers."""
import concurrent.futures
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import psycopg
from common import utc_now, write_json

CASES = {'risk_confirm': 200, 'risk_rules': 200, 'risk_findings': 200}
GROUPS = ('accept_pair', 'resolve_pair', 'accept_resolve', 'accept_ack', 'reaper_pair')
ASSERTIONS = ['risk_race_' + g for g in GROUPS] + ['risk_race_preparation', 'risk_race_no_effective', 'risk_race_barrier_removed']
WORKER = '''import json
from app.config import load_settings
from app.db import init_db,session_scope
from app.worker import reap_expired_risk_acceptance
init_db(load_settings())
with session_scope() as s: print(json.dumps({'reopened':reap_expired_risk_acceptance(s)}))
'''


def run(request, identity, sql, check, fault, events, out, a, b, command, python, api_dir, env, rows):
    o = {}; extra = []; serial = []; mutex = threading.Lock()
    conninfo = env['SIQ_AS_DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://')
    base_url = json.loads((out/'native-edge-private/state/state.json').read_text())['control_plane_url']
    def record(name, value):
        o[name] = value
        events.add('risk_observation', name=name, value=value)
        return value
    def fetch(label, action, fid=None, body=None, actor='operator-a', path=None, method='POST'):
        url = path or '/api/v1/findings/'+fid+'/'+action
        auth = identity(actor=actor, roles=['tenant_admin', 'security_admin', 'auditor'])
        started = utc_now()
        with mutex: events.add('risk_race_http_started', label=label, path=url, actor=actor)
        with httpx.Client(base_url=base_url, timeout=30, trust_env=False) as client:
            r = client.request(method, url, headers=auth, json=body)
        result = {'label':label, 'path':url, 'action':action, 'actor':actor, 'request_body':body,
                  'status':r.status_code, 'body':r.json(), 'started':started, 'finished':utc_now()}
        with mutex:
            extra.append(result)
            events.add('risk_race_http_finished', **result)
        return result
    def reap(label):
        started = utc_now()
        result = command([str(python), '-c', WORKER], cwd=api_dir, env=env)
        (out/(label+'.stdout')).write_text(result.stdout); (out/(label+'.stderr')).write_text(result.stderr)
        return {'label':label, 'exit_code':result.returncode, 'stdout':result.stdout, 'stderr_sha256':hashlib.sha256(result.stderr.encode()).hexdigest(), 'started':started, 'finished':utc_now()}
    def blocked():
        return sql("SELECT pid,wait_event_type,wait_event,left(query,600) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' ORDER BY pid")
    def wait_for(predicate):
        end = time.monotonic()+10
        last = []
        while time.monotonic()<end:
            last = blocked()
            if predicate(last): return last
            time.sleep(.025)
        return last
    try:
        native = json.loads((out/'native-enterprise-observations.json').read_text())
        asset = record('native_asset', native['asset'])
        request('risk_confirm', 'POST', '/api/v1/candidates/'+asset['id']+'/confirm', a, {})
        request('risk_rules', 'POST', '/api/v1/findings/run-rules', a)
        findings = request('risk_findings', 'GET', '/api/v1/findings?asset_id='+asset['id'], a)
        fid = next(x['id'] for x in findings if x['rule_id']=='no-effective-permissions')
        def state():
            return {'finding':sql('SELECT id,status,owner_user_id,risk_acceptance FROM finding WHERE id=%s',(fid,)),
                    'audit':sql('SELECT id,action,actor_id,summary FROM audit_event WHERE resource_id=%s ORDER BY id',(fid,)),
                    'outbox':sql("SELECT id,event_type,payload FROM outbox_event WHERE payload->>'resource_ref'=%s ORDER BY id",(fid,))}
        for group in GROUPS:
            expires = datetime.now(timezone.utc)+timedelta(seconds=3)
            body = {'owner_user_id':'race-owner','reason':group,'expires_at':expires.isoformat()}
            if group=='reaper_pair':
                fetch(group+'_setup', 'accept-risk', fid, body)
                time.sleep(max(0,(expires-datetime.now(timezone.utc)).total_seconds())+.15)
            g = {'finding_id':fid,'before':state(),'responses':[],'blocked':[]}
            guard = psycopg.connect(conninfo)
            try:
                if group=='reaper_pair':
                    sql("CREATE FUNCTION tp_risk_race_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='finding.risk_acceptance.expired' THEN PERFORM pg_advisory_xact_lock(8927164); END IF; RETURN NEW; END $$")
                    sql('CREATE TRIGGER tp_risk_race_lock BEFORE INSERT ON audit_event FOR EACH ROW EXECUTE FUNCTION tp_risk_race_barrier()')
                    guard.execute('SELECT pg_advisory_xact_lock(8927164)')
                else:
                    guard.execute('SELECT id FROM finding WHERE id=%s FOR UPDATE',(fid,))
                g['barrier_held_at'] = utc_now()
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures = []
                    try:
                        if group=='reaper_pair':
                            futures.append(pool.submit(reap,group+'_0'))
                            g['first_blocked'] = wait_for(lambda x:len(x)==1)
                            futures.append(pool.submit(reap,group+'_1'))
                            g['blocked'] = wait_for(lambda x, second=futures[1]:len(x)==2 or second.done())
                            g['second_finished_before_release'] = futures[1].done()
                        else:
                            actions = {'accept_pair':['accept-risk','accept-risk'], 'resolve_pair':['resolve','resolve'],
                                       'accept_resolve':['accept-risk','resolve'], 'accept_ack':['accept-risk','acknowledge']}[group]
                            for i, action in enumerate(actions):
                                payload = body if action=='accept-risk' else {'evidence_ref':'ticket:'+group+'-'+str(i)} if action=='resolve' else None
                                futures.append(pool.submit(fetch,group+'_'+str(i),action,fid,payload,'race-actor-'+str(i)))
                                if i==0: g['first_blocked'] = wait_for(lambda x:len(x)==1)
                            g['blocked'] = wait_for(lambda x:len(x)==2)
                    finally:
                        guard.rollback()
                        g['barrier_released_at'] = utc_now()
                    g['responses'] = [f.result() for f in futures]
            finally:
                guard.close()
                if group=='reaper_pair':
                    sql('DROP TRIGGER IF EXISTS tp_risk_race_lock ON audit_event')
                    sql('DROP FUNCTION IF EXISTS tp_risk_race_barrier()')
            g['after'] = state()
            record(group,g)
            if group!=GROUPS[-1]:
                current = state()['finding'][0]
                if current[1]=='risk_accepted':
                    deadline = datetime.fromisoformat(current[3]['expires_at'])
                    time.sleep(max(0,(deadline-datetime.now(timezone.utc)).total_seconds())+.15)
                    serial.append(reap(group+'_cleanup_reap'))
                if state()['finding'][0][1]!='resolved':
                    fetch(group+'_cleanup_resolve','resolve',fid,{'evidence_ref':'ticket:fixture-cleanup'})
                fetch(group+'_next_rules','run-rules',path='/api/v1/findings/run-rules')
                value = fetch(group+'_next_findings','list',path='/api/v1/findings?asset_id='+asset['id'],method='GET')['body']
                fid = next(x['id'] for x in value if x['rule_id']=='no-effective-permissions' and x['status']=='open')
        record('serial_workers',serial)
        record('extra_http',extra)
        record('http',{r['case_id']:r for r in rows if r['case_id'].startswith('risk_')})
        record('effective',sql("SELECT count(*) FROM permission_fact WHERE subject_id=%s AND state='effective'",(asset['id'],)))
        record('barrier_remaining',sql("SELECT tgname FROM pg_trigger WHERE tgname='tp_risk_race_lock'"))
        for name,passed in evaluate(o).items():check(name,passed,{'source':'risk-observations.json','predicate':name})
    finally:
        write_json(out/'risk-observations.json',o)


def evaluate(o):
    results = {}
    for group in GROUPS:
        g = o[group]; responses = g['responses']; after = g['after']; fid = g['finding_id']
        before_ids = {x[0] for x in g['before']['audit']}; before_events = {x[0] for x in g['before']['outbox']}
        audits = [x for x in after['audit'] if x[0] not in before_ids]
        emitted = [x for x in after['outbox'] if x[0] not in before_events]
        overlap = len(g['first_blocked'])==1 and len(responses)==2 and all(x[1]=='Lock' for x in g['blocked'])
        overlap &= len(g['blocked'])==2 and len({x[0] for x in g['blocked']})==2 if group!='reaper_pair' else len(g['blocked']) in (1,2)
        overlap &= all(datetime.fromisoformat(r['started']) < datetime.fromisoformat(g['barrier_released_at']) for r in responses)
        if group=='reaper_pair':
            ok = overlap and all(r['exit_code']==0 for r in responses) and sorted(json.loads(r['stdout'])['reopened'] for r in responses)==[0,1]
            ok &= g['before']['finding'][0][1]=='risk_accepted' and after['finding'][0][0:2]==[fid,'open']
            ok &= after['finding'][0][2:]==g['before']['finding'][0][2:]
            ok &= len(audits)==1 and audits[0][1:3]==['finding.risk_acceptance.expired','worker']
            ok &= len(emitted)==1 and emitted[0][1]=='agent.finding.reopened.v1'
            expiry=datetime.fromisoformat(g['before']['finding'][0][3]['expires_at'])
            ok &= all(datetime.fromisoformat(r['started'])>expiry for r in responses)
        else:
            winners=[r for r in responses if r['status']==200]
            ok=overlap and len(winners)==1 and sorted(r['status'] for r in responses)==[200,409]
            if len(winners)==1:
                winner=winners[0]; action=winner['action']; expected='risk_accepted' if action=='accept-risk' else 'resolved'
                ok &= after['finding'][0][0:2]==[fid,expected] and winner['body']['id']==fid and winner['body']['status']==expected
                wanted='finding.accept_risk' if action=='accept-risk' else 'finding.resolve'
                ok &= len(audits)==1 and audits[0][1:3]==[wanted,winner['actor']]
                ok &= len(emitted)==1 and emitted[0][1]=='agent.finding.resolved.v1' and emitted[0][2]['payload']['resolution']==expected
                ok &= all(r['body'].get('detail')=='invalid_state' for r in responses if r['status']==409)
                expected_meta=({'reason':winner['request_body']['reason'],'accepted_by':winner['actor'],'expires_at':winner['request_body']['expires_at']} if action=='accept-risk' else {'resolved_by':winner['actor'],'evidence_ref':winner['request_body']['evidence_ref']})
                ok &= after['finding'][0][3]==expected_meta and winner['body']['risk_acceptance']==expected_meta
                if group=='accept_ack':ok &= action=='accept-risk'
        results['risk_race_'+group]=bool(ok)
    parallel_labels={r['label'] for group in GROUPS if group!='reaper_pair' for r in o[group]['responses']}
    results['risk_race_preparation']=all(r['status']==200 for r in o['extra_http'] if r['label'] not in parallel_labels) and all(r['exit_code']==0 and json.loads(r['stdout'])['reopened']==1 for r in o['serial_workers'])
    results['risk_race_no_effective']=o['effective']==[[0]]
    results['risk_race_barrier_removed']=o['barrier_remaining']==[]
    return results
