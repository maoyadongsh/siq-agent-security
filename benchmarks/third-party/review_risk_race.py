"""Join supplementary HTTP/worker evidence and strictly prove the overlap window."""
import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

from common import sha256
from enterprise_native_edge import CONFIG
from enterprise_risk_race import GROUPS, evaluate


def require(value, message):
    if not value:
        raise ValueError(message)


def strict_checks(o):
    joined = {r['label']: r for r in o['extra_http']}
    unique = len(joined) == len(o['extra_http'])
    ids = [o[g]['finding_id'] for g in GROUPS]
    checks = {'five_distinct_rule_findings': len(set(ids)) == 5, 'extra_http_unique': unique}
    for i, name in enumerate(GROUPS):
        g = o[name]; release = datetime.fromisoformat(g['barrier_released_at'])
        waiting = {r[0] for r in g['blocked']}
        strict = len(g['first_blocked']) == 1 and g['first_blocked'][0][0] in waiting
        strict &= g['before']['finding'][0][0] == g['after']['finding'][0][0] == g['finding_id']
        strict &= all(datetime.fromisoformat(r['started']) < release for r in g['responses'])
        if name == 'reaper_pair':
            if len(waiting) == 1:
                second = g['responses'][1]
                strict &= g['second_finished_before_release'] and datetime.fromisoformat(second['finished']) < release
                strict &= second['exit_code'] == 0 and json.loads(second['stdout'])['reopened'] == 0
            else:
                strict &= len(waiting) == 2 and all(datetime.fromisoformat(r['finished']) > release for r in g['responses'])
            strict &= g['before']['finding'][0][1] == 'risk_accepted'
        else:
            strict &= len(waiting) == 2 and all(datetime.fromisoformat(r['finished']) > release for r in g['responses'])
            strict &= all(joined.get(r['label']) == r for r in g['responses'])
            strict &= g['before']['finding'][0][1] == 'open'
        checks[name+'_strict_overlap'] = bool(strict)
        if i < len(GROUPS)-1:
            following = joined[name+'_next_findings']
            matches = [x for x in following['body'] if x['rule_id']=='no-effective-permissions' and x['status']=='open']
            checks[name+'_next_rule_identity'] = (following['status']==200 and len(matches)==1
                and matches[0]['id']==ids[i+1] and matches[0]['asset_id']==o['native_asset']['id'])
    return checks


def review(run):
    o = json.loads((run/'risk-observations.json').read_text())
    native = json.loads((run/'native-enterprise-observations.json').read_text())
    require(o['native_asset'] == native['asset'], 'native identity differs')
    require(sha256(run/'native-edge-private/home/.hermes/profiles/enterprise-native-fixture/config.yaml') == hashlib.sha256(CONFIG).hexdigest() == native['source_after'], 'native config differs')
    for command in ('register', 'tasks'):
        for stream in ('stdout', 'stderr'):
            require(sha256(run/'native-edge-private'/(command+'.'+stream)) == native[command][stream+'_sha256'], 'native raw output differs')
    events = [json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    finished = [{k:v for k,v in e.items() if k in row_keys()} for e in events if e['event']=='risk_race_http_finished']
    require(finished == o['extra_http'], 'supplementary HTTP projection differs')
    started = [e for e in events if e['event']=='risk_race_http_started']
    require(len(started)==len(finished) and {e['label'] for e in started}=={e['label'] for e in finished}, 'HTTP attempts differ')
    workers = [*o['serial_workers'], *o['reaper_pair']['responses']]
    for w in workers:
        require((run/(w['label']+'.stdout')).read_text()==w['stdout'], 'worker stdout differs')
        require(sha256(run/(w['label']+'.stderr'))==w['stderr_sha256'], 'worker stderr differs')
    strict = strict_checks(o)
    require(all(strict.values()), 'strict raw overlap or identity join failed')
    scores = evaluate(o); negative = {}
    if all(scores.values()):
        changes = {
            'unobserved_second_request':lambda x:x['accept_pair'].update(blocked=x['accept_pair']['blocked'][:1]),
            'no_first_waiter':lambda x:x['resolve_pair'].update(first_blocked=[]),
            'both_accept_success':lambda x:next(r for r in x['accept_pair']['responses'] if r['status']==409).update(status=200),
            'resolve_audit_lost':lambda x:x['resolve_pair']['after'].update(audit=x['resolve_pair']['before']['audit']),
            'accept_ack_overwrite':lambda x:x['accept_ack']['after']['finding'][0].__setitem__(1,'acknowledged'),
            'reaper_double_work':lambda x:x['reaper_pair']['responses'][1].update(stdout='{"reopened":1}'),
            'reaper_event_lost':lambda x:x['reaper_pair']['after'].update(outbox=x['reaper_pair']['before']['outbox']),
            'reaper_metadata_erased':lambda x:x['reaper_pair']['after']['finding'][0].__setitem__(3,{}),
            'effective_forged':lambda x:x.update(effective=[[1]]),
            'barrier_left':lambda x:x.update(barrier_remaining=[['tp_risk_race_lock']]),
            'supplementary_http_lost':lambda x:x.update(extra_http=[]),
            'false_skip_finished':lambda x:x['reaper_pair']['responses'][1].update(finished=x['reaper_pair']['responses'][0]['finished']),
        }
        for name,change in changes.items():
            altered=copy.deepcopy(o);change(altered)
            try: rejected=not (all(evaluate(altered).values()) and all(strict_checks(altered).values()))
            except (KeyError, IndexError, ValueError):rejected=True
            negative[name]=rejected
        require(all(negative.values()), 'false risk race evidence accepted')
    return {'run_id':run.name,'native_source_and_raw_cli_verified':True,'extra_HTTP_count':len(finished),'parallel_HTTP_count':8,
            'preparation_HTTP_count':len(finished)-8,'raw_worker_outputs_joined':len(workers),'strict_evidence_checks':strict,
            'frozen_checks':scores,'actual_evidence_negative_rejections':negative,
            'scope':'author controlled overlapping transactions; supplementary stronger skip timing; no natural workload or external witness claim'}


def row_keys():
    return {'label','path','action','actor','request_body','status','body','started','finished'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    print(json.dumps(review(args.run),ensure_ascii=False,indent=2))
