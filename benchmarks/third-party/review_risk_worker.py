"""Join native files and full worker output; reject altered lifecycle evidence."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

from common import sha256
from enterprise_native_edge import CONFIG
from enterprise_risk_worker import CASES, STAGES, evaluate


def require(value, message):
    if not value:
        raise ValueError(message)


def review(run):
    o = json.loads((run/'risk-observations.json').read_text())
    native = json.loads((run/'native-enterprise-observations.json').read_text())
    require(o['native_asset'] == native['asset'], 'native asset differs')
    require(sha256(run/'native-edge-private/home/.hermes/profiles/enterprise-native-fixture/config.yaml') == hashlib.sha256(CONFIG).hexdigest() == native['source_after'], 'native config differs')
    for command in ('register', 'tasks'):
        for stream in ('stdout', 'stderr'):
            require(sha256(run/'native-edge-private'/(command+'.'+stream)) == native[command][stream+'_sha256'], 'native output differs')
    for stage in STAGES:
        name = 'worker_'+stage
        require((run/(name+'.stdout')).read_text() == o[name]['stdout'], 'worker stdout differs')
        require(sha256(run/(name+'.stderr')) == o[name]['stderr_sha256'], 'worker stderr differs')
    for received in o['received']:
        body = json.dumps(received['payload'], ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
        require(hashlib.sha256(body).hexdigest() == received['body_sha256'], 'webhook body differs')
        require(received['path'] == '/events', 'webhook path differs')
    def passes(value):
        return all(evaluate(value).values()) and all(value['http'][k]['status'] == v for k, v in CASES.items())
    negative = {}
    if passes(o):
        changes = {
            'duplicate_acknowledged': lambda x: x['worker_acknowledged']['after']['findings'].append(["extra", 'no-effective-permissions', 'open', None, None]),
            'acceptance_overwritten': lambda x: next(f for f in x['worker_accepted']['after']['findings'] if f[0] == x['finding_id']).__setitem__(4, {}),
            'late_acceptance_window': lambda x: x['worker_accepted_repeat'].update(finished=x['worker_expired']['finished']),
            'missing_expiry': lambda x: next(f for f in x['worker_expired']['after']['findings'] if f[0] == x['finding_id']).__setitem__(2, 'risk_accepted'),
            'old_audit_lost': lambda x: x['final'].update(audit=[]),
            'notification_lost': lambda x: x.update(received=[]),
            'notification_duplicated': lambda x: x['received'].extend(copy.deepcopy(x['received'])),
            'unpublished_outbox': lambda x: x['final']['outbox'][0].__setitem__(3, False),
            'effective_forged': lambda x: x['final'].update(effective=[[1]]),
            'receiver_left_running': lambda x: x.update(receiver_closed=False),
            'partial_worker': lambda x: x['worker_open'].update(stdout='{"reaped":0}'),
            'resolved_evidence_erased': lambda x: next(f for f in x['final']['findings'] if f[0] == x['finding_id']).__setitem__(4, {}),
        }
        for name, change in changes.items():
            altered = copy.deepcopy(o)
            change(altered)
            try:
                rejected = not passes(altered)
            except (KeyError, IndexError, ValueError):
                rejected = True
            negative[name] = rejected
        require(all(negative.values()), 'false worker evidence accepted')
    return {'run_id': run.name, 'native_source_and_raw_cli_verified': True, 'raw_worker_outputs_joined': len(STAGES),
            'observed_webhook_bodies_joined': len(o['received']), 'frozen_checks': evaluate(o),
            'actual_evidence_negative_rejections': negative,
            'scope': 'author supplemental review; actual loopback notifications; no independent witness, concurrency or long-running scheduler assurance'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.run), ensure_ascii=False, indent=2))
