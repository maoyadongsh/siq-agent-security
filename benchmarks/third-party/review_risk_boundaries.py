"""Review captured native identity, risk subjects and negative evidence variants."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from common import sha256
from enterprise_native_edge import CONFIG
from enterprise_risk_boundaries import CASES, evaluate


def require(value,message):
    if not value:raise ValueError(message)


def review(run):
    o=json.loads((run/'risk-observations.json').read_text());native=json.loads((run/'native-enterprise-observations.json').read_text())
    require(o['native_asset']==native['asset'],'native source identity differs')
    require(o['synthetic_asset'] in native['assets'] and o['synthetic_asset']['id']!=native['asset']['id'],'control identity differs')
    require(sha256(run/'native-edge-private/home/.hermes/profiles/enterprise-native-fixture/config.yaml')==hashlib.sha256(CONFIG).hexdigest()==native['source_after'],'native config differs')
    for command in ('register','tasks'):
        for stream in ('stdout','stderr'):
            require(sha256(run/'native-edge-private'/(command+'.'+stream))==native[command][stream+'_sha256'],'native output differs')
    byid={x['id']:x for x in o['http']['rb_findings']['body']}
    require(all(byid[o['subjects'][name]]['asset_id']==native['asset']['id'] for name in ('primary','open_control')),'native risk subject differs')
    require(byid[o['subjects']['resolved_control']]['asset_id']==o['synthetic_asset']['id'],'resolved fixture subject differs')
    def passes(x):return all(evaluate(x).values()) and all(x['http'][name]['status']==status for name,status in CASES.items())
    negative={}
    if passes(o):
        mutations={
            'foreign_permission_first':lambda x:x['http']['rb_cross_unprivileged'].update(status=403),
            'blank_owner_accepted':lambda x:x['http']['rb_blank_owner'].update(status=200),
            'expiry_internal_error':lambda x:x['http']['rb_extreme_expiry'].update(status=500),
            'terminal_accepted':lambda x:x['http']['rb_repeat_accept'].update(status=200),
            'terminal_state_changed':lambda x:x['rb_repeat_accept_after']['finding'][0].__setitem__(1,'open'),
            'resolution_reference_erased':lambda x:x['rb_resolved_accept_after']['finding'][0].__setitem__(3,{}),
            'denied_write_audited_as_success':lambda x:x['rb_empty_owner_after']['audit'].append(['fake','finding.accept_risk','actor']),
            'denied_write_emits_event':lambda x:x['rb_blank_reason_after']['outbox'].append(['fake','agent.finding.resolved.v1',{}]),
            'ack_control_failed':lambda x:x['ack_after']['finding'][0].__setitem__(1,'open'),
            'open_control_audit_lost':lambda x:x['rb_accept_open_after'].update(audit=[]),
            'open_control_event_lost':lambda x:x['rb_accept_open_after'].update(outbox=[]),
            'native_and_synthetic_conflated':lambda x:x['synthetic_asset'].update(id=x['native_asset']['id']),
        }
        for name,mutate in mutations.items():
            altered=copy.deepcopy(o);mutate(altered);negative[name]=not passes(altered)
        require(all(negative.values()),'false boundary evidence accepted')
    return {'run_id':run.name,'native_source_and_raw_cli_verified':True,'native_and_synthetic_subjects_distinct':True,
            'original_risk_checks':evaluate(o),'original_HTTP_statuses':{k:v['status'] for k,v in o['http'].items()},
            'actual_evidence_negative_rejections':negative,'scope':'author supplemental raw evidence review; negative probes only on passing cohort; no independent witness or concurrency claim'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run',type=Path);a=p.parse_args();print(json.dumps(review(a.run),ensure_ascii=False,indent=2))
