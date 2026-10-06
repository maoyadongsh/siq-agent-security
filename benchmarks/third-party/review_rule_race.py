"""Join rule-race HTTP and source evidence; probe false uniqueness/refresh claims."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from common import sha256
from enterprise_native_edge import CONFIG
from enterprise_rule_race import GROUPS, evaluate, overlap


def require(value,message):
    if not value:raise ValueError(message)


def joins(o):
    rows={r['label']:r for r in o['extra_http']}
    checks={'HTTP_labels_unique':len(rows)==len(o['extra_http'])}
    for name in GROUPS:
        checks[name+'_response_join']=all(rows.get(r['label'])==r for r in o[name]['responses'])
        checks[name+'_strict_overlap']=overlap(o[name])
    checks['other_tenant_join']=rows.get('other_tenant')==o['first_create']['other_tenant']
    checks['later_scan_join']=rows.get('later_rules')==o['later_scan']
    for label,state in [('fresh_findings',o['fresh']),('resolve_stage_findings',o['refresh_resolve']['before'])]:
        http=rows[label]['body']
        projected=sorted([[r['id'],r['rule_id'],r['status'],r['owner_user_id'],r['risk_acceptance']] for r in http])
        checks[label+'_SQL_identity']=projected==state['findings'] and all(r['asset_id']==o['native_asset']['id'] for r in http)
    first=o['first_create']['after'];byid={f[0]:f for f in first['findings']}
    checks['initial_creation_audit_join']=sorted(a[1] for a in first['audit'])==sorted(byid) and all(a[2:]==['finding.open','rule-engine'] for a in first['audit'])
    checks['initial_creation_outbox_join']=len(first['outbox'])==len(byid) and all(
        e[1]=='agent.finding.opened.v1' and e[2]['resource_ref'] in byid
        and e[2]['payload']['finding_id']==e[2]['resource_ref'] and e[2]['payload']['asset_id']==o['native_asset']['id']
        and e[2]['payload']['rule_id']==byid[e[2]['resource_ref']][1] for e in first['outbox'])
    return checks


def review(run):
    o=json.loads((run/'risk-observations.json').read_text());native=json.loads((run/'native-enterprise-observations.json').read_text())
    require(o['native_asset']==native['asset'],'native identity differs')
    require(sha256(run/'native-edge-private/home/.hermes/profiles/enterprise-native-fixture/config.yaml')==hashlib.sha256(CONFIG).hexdigest()==native['source_after'],'native config differs')
    for command in ('register','tasks'):
        for stream in ('stdout','stderr'):
            require(sha256(run/'native-edge-private'/(command+'.'+stream))==native[command][stream+'_sha256'],'native raw output differs')
    events=[json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    keys={'label','path','request_body','status','body','started','finished'}
    finished=[{k:v for k,v in e.items() if k in keys} for e in events if e['event']=='risk_rule_http_finished']
    require(finished==o['extra_http'],'extra HTTP projection differs')
    started=[e for e in events if e['event']=='risk_rule_http_started']
    require(len(started)==len(finished) and {e['label'] for e in started}=={e['label'] for e in finished},'HTTP attempts differ')
    w=o['cleanup_reaper'];require((run/'cleanup_reaper.stdout').read_text()==w['stdout'],'reaper stdout differs')
    require(sha256(run/'cleanup_reaper.stderr')==w['stderr_sha256'],'reaper stderr differs')
    strict=joins(o);require(all(strict.values()),'identity/event/overlap joins failed')
    scores=evaluate(o);negative={}
    if all(scores.values()):
        def duplicate_first(x):
            duplicate=copy.deepcopy(x['first_create']['after']['findings'][0])
            duplicate[0]='extra'
            x['first_create']['after']['findings'].append(duplicate)
            resolved=copy.deepcopy(duplicate);resolved[2]='resolved'
            x['fresh']['findings'].append(resolved)
        mutations={
            'duplicate_first_finding':duplicate_first,
            'false_creation_count':lambda x:x['first_create']['responses'][1]['body'].update(created=2),
            'missing_waiter':lambda x:x['refresh_accept'].update(blocked=x['refresh_accept']['blocked'][:1]),
            'other_tenant_delayed':lambda x:x['first_create']['other_tenant'].update(finished=x['first_create']['responses'][0]['finished']),
            'accepted_state_overwritten':lambda x:next(f for f in x['refresh_accept']['after']['findings'] if f[0]==x['refresh_accept']['finding_id']).__setitem__(2,'open'),
            'resolution_erased':lambda x:next(f for f in x['refresh_resolve']['after']['findings'] if f[0]==x['refresh_resolve']['finding_id']).__setitem__(4,{}),
            'old_resolution_reopened':lambda x:next(f for f in x['final']['findings'] if f[0]==x['refresh_resolve']['finding_id']).__setitem__(2,'open'),
            'extra_HTTP_missing':lambda x:x.update(extra_http=[]),
            'creation_event_borrowed':lambda x:x['first_create']['after']['outbox'][0][2].update(resource_ref='foreign'),
            'effective_forged':lambda x:x.update(effective=[[1]]),
            'barrier_left':lambda x:x.update(barrier_remaining=[['left']]),
            'cleanup_reaper_missed':lambda x:x['cleanup_reaper'].update(stdout='{"reopened":0}'),
        }
        for name,mutate in mutations.items():
            altered=copy.deepcopy(o);mutate(altered)
            try:rejected=not (all(evaluate(altered).values()) and all(joins(altered).values()))
            except (KeyError,IndexError,ValueError):rejected=True
            negative[name]=rejected
        require(all(negative.values()),'false rule concurrency evidence accepted')
    return {'run_id':run.name,'native_source_and_raw_cli_verified':True,'extra_HTTP_count':len(finished),'race_HTTP_count':6,
            'other_tenant_HTTP_count':1,'preparation_HTTP_count':len(finished)-7,'raw_reaper_outputs_joined':1,
            'strict_evidence_checks':strict,'frozen_checks':scores,'actual_evidence_negative_rejections':negative,
            'scope':'author controlled overlap and real HTTP/SQL evidence; not external witness or performance claim'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    print(json.dumps(review(args.run),ensure_ascii=False,indent=2))
