"""Real first rule creation, cross-tenant progress, and manual/refresh races."""
import concurrent.futures
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import psycopg
from common import utc_now, write_json

CASES = {'risk_confirm': 200}
GROUPS = ('first_create', 'refresh_accept', 'refresh_resolve')
ASSERTIONS = ['risk_rules_first_overlap', 'risk_rules_first_unique', 'risk_rules_other_tenant',
              'risk_rules_fresh_preparation', 'risk_rules_refresh_accept', 'risk_rules_refresh_resolve',
              'risk_rules_later_recurrence', 'risk_rules_cleanup']
WORKER = '''import json
from app.config import load_settings
from app.db import init_db,session_scope
from app.worker import reap_expired_risk_acceptance
init_db(load_settings())
with session_scope() as s:print(json.dumps({'reopened':reap_expired_risk_acceptance(s)}))
'''


def run(request, identity, sql, check, fault, events, out, a, b, command, python, api_dir, env, rows):
    o = {}; extra = []; mutex = threading.Lock()
    conninfo = env['SIQ_AS_DATABASE_URL'].replace('postgresql+psycopg://', 'postgresql://')
    base_url = json.loads((out/'native-edge-private/state/state.json').read_text())['control_plane_url']
    def record(name,value):
        o[name]=value;events.add('risk_observation',name=name,value=value);return value
    def fetch(label,path,body=None,auth=None,method='POST'):
        started=utc_now()
        with mutex:events.add('risk_rule_http_started',label=label,path=path)
        with httpx.Client(base_url=base_url,timeout=30,trust_env=False) as client:
            r=client.request(method,path,headers=auth or a,json=body)
        row={'label':label,'path':path,'request_body':body,'status':r.status_code,'body':r.json(),'started':started,'finished':utc_now()}
        with mutex:extra.append(row);events.add('risk_rule_http_finished',**row)
        return row
    def blocked():
        return sql("SELECT pid,wait_event_type,wait_event,left(query,600) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' ORDER BY pid")
    def wait_for(count):
        deadline=time.monotonic()+10;current=[]
        while time.monotonic()<deadline:
            current=blocked()
            if len(current)==count:return current
            time.sleep(.025)
        return current
    try:
        native=json.loads((out/'native-enterprise-observations.json').read_text());asset=record('native_asset',native['asset'])
        request('risk_confirm','POST','/api/v1/candidates/'+asset['id']+'/confirm',a,{})
        def state():
            return {'findings':sql('SELECT id,rule_id,status,owner_user_id,risk_acceptance FROM finding WHERE asset_id=%s ORDER BY id',(asset['id'],)),
                    'audit':sql('SELECT id,resource_id,action,actor_id FROM audit_event WHERE resource_id IN (SELECT id FROM finding WHERE asset_id=%s) ORDER BY id',(asset['id'],)),
                    'outbox':sql("SELECT id,event_type,payload FROM outbox_event WHERE payload->>'resource_ref' IN (SELECT id FROM finding WHERE asset_id=%s) ORDER BY id",(asset['id'],))}
        g={'before':state()};guard=psycopg.connect(conninfo)
        sql("CREATE FUNCTION tp_rule_create_barrier() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.action='finding.open' AND NEW.tenant_id='tp07-a' THEN PERFORM pg_advisory_xact_lock(8947216); END IF; RETURN NEW; END $$")
        sql('CREATE TRIGGER tp_rule_create_lock BEFORE INSERT ON audit_event FOR EACH ROW EXECUTE FUNCTION tp_rule_create_barrier()')
        try:
            guard.execute('SELECT pg_advisory_xact_lock(8947216)');g['held_at']=utc_now()
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures=[]
                try:
                    futures.append(pool.submit(fetch,'first_create_0','/api/v1/findings/run-rules'))
                    g['first_blocked']=wait_for(1)
                    g['other_tenant']=fetch('other_tenant','/api/v1/findings/run-rules',auth=b)
                    futures.append(pool.submit(fetch,'first_create_1','/api/v1/findings/run-rules'))
                    g['blocked']=wait_for(2)
                finally:
                    guard.rollback();g['released_at']=utc_now()
                g['responses']=[f.result() for f in futures]
        finally:
            guard.close();sql('DROP TRIGGER IF EXISTS tp_rule_create_lock ON audit_event');sql('DROP FUNCTION IF EXISTS tp_rule_create_barrier()')
        g['after']=state();record('first_create',g)
        for f in g['after']['findings']:
            fetch('clear_'+f[0],'/api/v1/findings/'+f[0]+'/resolve',{'evidence_ref':'ticket:first-stage-cleanup'})
        fetch('fresh_rules','/api/v1/findings/run-rules')
        value=fetch('fresh_findings','/api/v1/findings?asset_id='+asset['id'],method='GET')['body']
        fid=next(f['id'] for f in value if f['rule_id']=='no-effective-permissions' and f['status']=='open')
        record('fresh',state())
        for name,action in [('refresh_accept','accept-risk'),('refresh_resolve','resolve')]:
            expires=datetime.now(timezone.utc)+timedelta(seconds=4)
            body=({'owner_user_id':'refresh-owner','reason':'owned overlap','expires_at':expires.isoformat()} if action=='accept-risk' else {'evidence_ref':'ticket:refresh-race'})
            g={'finding_id':fid,'before':state()};guard=psycopg.connect(conninfo)
            try:
                guard.execute('SELECT id FROM finding WHERE id=%s FOR UPDATE',(fid,));g['held_at']=utc_now()
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[]
                    try:
                        futures.append(pool.submit(fetch,name+'_manual','/api/v1/findings/'+fid+'/'+action,body))
                        g['first_blocked']=wait_for(1)
                        futures.append(pool.submit(fetch,name+'_scan','/api/v1/findings/run-rules'))
                        g['blocked']=wait_for(2)
                    finally:
                        guard.rollback();g['released_at']=utc_now()
                    g['responses']=[f.result() for f in futures]
            finally:guard.close()
            g['after']=state();record(name,g)
            if name=='refresh_accept':
                time.sleep(max(0,(expires-datetime.now(timezone.utc)).total_seconds())+.15)
                started=utc_now();r=command([str(python),'-c',WORKER],cwd=api_dir,env=env)
                (out/'cleanup_reaper.stdout').write_text(r.stdout);(out/'cleanup_reaper.stderr').write_text(r.stderr)
                record('cleanup_reaper',{'exit_code':r.returncode,'stdout':r.stdout,'stderr_sha256':hashlib.sha256(r.stderr.encode()).hexdigest(),'started':started,'finished':utc_now()})
                fetch('accepted_cleanup_resolve','/api/v1/findings/'+fid+'/resolve',{'evidence_ref':'ticket:fixture-cleanup'})
                fetch('resolve_stage_rules','/api/v1/findings/run-rules')
                value=fetch('resolve_stage_findings','/api/v1/findings?asset_id='+asset['id'],method='GET')['body']
                fid=next(f['id'] for f in value if f['rule_id']=='no-effective-permissions' and f['status']=='open')
        record('later_scan',fetch('later_rules','/api/v1/findings/run-rules'))
        record('final',state());record('extra_http',extra)
        record('http',{r['case_id']:r for r in rows if r['case_id'].startswith('risk_')})
        record('effective',sql("SELECT count(*) FROM permission_fact WHERE subject_id=%s AND state='effective'",(asset['id'],)))
        record('barrier_remaining',sql("SELECT tgname FROM pg_trigger WHERE tgname='tp_rule_create_lock'"))
        for name,passed in evaluate(o).items():check(name,passed,{'source':'risk-observations.json','predicate':name})
    finally:write_json(out/'risk-observations.json',o)


def overlap(g):
    release=datetime.fromisoformat(g['released_at']);pids={r[0] for r in g['blocked']}
    return (len(g['first_blocked'])==1 and g['first_blocked'][0][0] in pids and len(pids)==2
            and all(r[1]=='Lock' for r in g['blocked']) and len(g['responses'])==2
            and all(datetime.fromisoformat(r['started'])<release<datetime.fromisoformat(r['finished']) for r in g['responses']))


def evaluate(o):
    def active(s):return [f for f in s['findings'] if f[2]!='resolved']
    def target(s,fid):return next(f for f in s['findings'] if f[0]==fid)
    def added(g,key):return [x for x in g['after'][key] if x[0] not in {r[0] for r in g['before'][key]}]
    g=o['first_create'];created=g['after'];counts=[r['body'] for r in g['responses']]
    first=not g['before']['findings'] and len(created['findings'])==2 and {f[1] for f in created['findings']}=={'unowned-confirmed-agent','no-effective-permissions'}
    first &= all(f[2]=='open' for f in created['findings']) and len(created['audit'])==len(created['outbox'])==2
    first &= all(r['status']==200 for r in g['responses']) and sorted(c['created'] for c in counts)==[0,2] and sorted(c['updated'] for c in counts)==[0,2]
    other=g['other_tenant'];other_ok=other['status']==200 and other['body']=={'evaluated_rules':0,'created':0,'updated':0}
    other_ok &= datetime.fromisoformat(g['held_at'])<datetime.fromisoformat(other['started'])<datetime.fromisoformat(other['finished'])<datetime.fromisoformat(g['released_at'])
    fresh=o['fresh'];initial_ids={f[0] for f in created['findings']};live=active(fresh)
    prep=len(live)==2 and {f[1] for f in live}=={'unowned-confirmed-agent','no-effective-permissions'} and all(target(fresh,i)[2]=='resolved' for i in initial_ids)
    prep &= not initial_ids & {f[0] for f in live}
    evaluated={}
    for name,expected,action in [('refresh_accept','risk_accepted','finding.accept_risk'),('refresh_resolve','resolved','finding.resolve')]:
        g=o[name];fid=g['finding_id'];manual,scan=g['responses'];after=target(g['after'],fid)
        ok=overlap(g) and manual['status']==scan['status']==200 and target(g['before'],fid)[2]=='open'
        ok &= after[2]==manual['body']['status']==expected and after[3]==manual['body']['owner_user_id'] and after[4]==manual['body']['risk_acceptance']
        audits=added(g,'audit');events=added(g,'outbox')
        own_audits=[a for a in audits if a[1]==fid];own_events=[e for e in events if e[2]['resource_ref']==fid]
        ok &= len(own_audits)==len(own_events)==1 and own_audits[0][2:]==[action,'operator-a']
        ok &= own_events[0][1]=='agent.finding.resolved.v1' and own_events[0][2]['payload']['resolution']==expected
        if name=='refresh_accept':
            wanted={'reason':manual['request_body']['reason'],'accepted_by':'operator-a','expires_at':manual['request_body']['expires_at']}
            ok &= after[3]=='refresh-owner' and after[4]==wanted and scan['body']=={'evaluated_rules':2,'created':0,'updated':2}
            ok &= len(audits)==len(events)==1 and len(active(g['after']))==2
        else:
            ok &= after[4]=={'resolved_by':'operator-a','evidence_ref':'ticket:refresh-race'}
            ok &= scan['body'] in ({'evaluated_rules':2,'created':0,'updated':2},{'evaluated_rules':2,'created':1,'updated':1})
        evaluated[name]=bool(ok)
    g=o['refresh_resolve'];fid=g['finding_id'];final=o['final'];live=active(final)
    recurrence=len(live)==2 and {f[1] for f in live}=={'unowned-confirmed-agent','no-effective-permissions'} and target(final,fid)==target(g['after'],fid)
    new_target=[f for f in live if f[1]=='no-effective-permissions']
    recurrence &= len(new_target)==1 and new_target[0][0]!=fid
    prior_new=any(f[1]=='no-effective-permissions' and f[2]=='open' for f in g['after']['findings'])
    recurrence &= o['later_scan']['body']=={'evaluated_rules':2,'created':0 if prior_new else 1,'updated':2 if prior_new else 1}
    cleanup=all(r['status']==200 for r in o['extra_http']) and o['cleanup_reaper']['exit_code']==0 and json.loads(o['cleanup_reaper']['stdout'])['reopened']==1 and o['effective']==[[0]] and o['barrier_remaining']==[]
    return dict(zip(ASSERTIONS,map(bool,(overlap(o['first_create']),first,other_ok,prep,evaluated['refresh_accept'],evaluated['refresh_resolve'],recurrence,cleanup)),strict=True))
