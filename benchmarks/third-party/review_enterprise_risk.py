"""Supplementary raw worker/native evidence checks; original scoring unchanged."""
import argparse
import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

from common import sha256
from enterprise_native_edge import CONFIG
from enterprise_risk import ZONES, evaluate


def require(condition, message):
    if not condition:
        raise ValueError(message)


def review(run):
    o=json.loads((run/'risk-observations.json').read_text());native=json.loads((run/'native-enterprise-observations.json').read_text())
    require(o['native_asset']==native['asset'],'native discovery asset differs')
    require(sha256(run/'native-edge-private/home/.hermes/profiles/enterprise-native-fixture/config.yaml')==hashlib.sha256(CONFIG).hexdigest()==native['source_after'],'native source differs')
    for name in ('register','tasks'):
        for stream in ('stdout','stderr'):
            require(sha256(run/'native-edge-private'/(name+'.'+stream))==native[name][stream+'_sha256'],'native capture differs')
    require(not Path(native['ephemeral_root']).exists() and native['ephemeral_root_removed'],'native temporary path remains')
    timings={}
    for zone,hours in ZONES.items():
        request=o['http']['risk_accept_'+zone]['request_body'];encoded=datetime.fromisoformat(request['expires_at']);expiry=datetime.fromisoformat(o['expiry_'+zone])
        require(encoded==expiry and encoded.utcoffset().total_seconds()==hours*3600,'wire timezone/instant differs')
        stages={}
        for phase in ('early','late','repeat'):
            name=f'worker_{zone}_{phase}';x=o[name]
            require((run/(name+'.stdout')).read_text()==x['stdout'] and sha256(run/(name+'.stderr'))==x['stderr_sha256'],'worker capture differs')
            stages[phase]={'started_relative_to_expiry_seconds':(datetime.fromisoformat(x['started'])-expiry).total_seconds(),
                           'finished_relative_to_expiry_seconds':(datetime.fromisoformat(x['finished'])-expiry).total_seconds(),
                           'reopened':json.loads(x['stdout'])['reopened'],'status_after':x['after']['finding'][0][1]}
        timings[zone]=stages
    scored=evaluate(o);negative={}
    if all(scored.values()):
        mutations={
            'unknown_falsely_effective':lambda x:x.update(effective_fact_count=[[1]]),
            'duplicate_rules':lambda x:x['rule_ids_after'].append(['extra','invented','other']),
            'pagination_duplicate':lambda x:x['http']['risk_page_two'].update(body=x['http']['risk_page_one']['body']),
            'pagination_truncation_hidden':lambda x:x['http']['risk_page_one']['response_headers'].update({'x-siq-list-truncated':'0'}),
            'acceptance_audit_lost':lambda x:x['accepted'].update(audit=[]),
            'audit_failure_state_changed':lambda x:x['audit_failure_after'].update(finding=[]),
            'resolution_reference_lost':lambda x:x['resolved']['finding'][0][3].update(evidence_ref='invented'),
            'export_truncation_hidden':lambda x:x['http']['risk_export_one']['response_headers'].update({'x-siq-export-truncated':'0'}),
            'foreign_export_record':lambda x:x['http']['risk_export_other_tenant'].update(body=x['http']['risk_export_all']['body']),
            'premature_reopen':lambda x:x['worker_utc_early']['after']['finding'][0].__setitem__(1,'open'),
            'missed_reopen':lambda x:x['worker_west_late']['after']['finding'][0].__setitem__(1,'risk_accepted'),
            'missing_expiry_audit':lambda x:x['worker_east_late']['after'].update(audit=x['worker_east_late']['before']['audit']),
        }
        for name,mutate in mutations.items():
            altered=copy.deepcopy(o);mutate(altered);negative[name]=not all(evaluate(altered).values())
        require(all(negative.values()),'false risk lifecycle accepted')
    return {'run_id':run.name,'native_asset_source_and_output_joins':True,'worker_raw_outputs_joined':9,'timezones_and_instants_verified':True,
            'time_windows':timings,'original_checks':scored,'actual_evidence_negative_rejections':negative,
            'negative_scope':'only evaluated on passing cohort; failing original is not reused as a false positive control',
            'limits':['author supplemental review, not external witness','controlled reaper invocation; no continuous scheduler or webhook claim']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    print(json.dumps(review(args.run),ensure_ascii=False,indent=2))
