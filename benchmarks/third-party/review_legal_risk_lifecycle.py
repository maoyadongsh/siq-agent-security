"""Raw initial expiry proof and error-evidence probes for the legal lifecycle."""
import argparse
import copy
import json
from datetime import datetime
from pathlib import Path

from common import sha256
from enterprise_risk_v2 import evaluate, evaluate_extra
from review_enterprise_risk import require
from review_enterprise_risk import review as review_base


def review(run):
    base = review_base(run)
    o = json.loads((run / 'risk-observations.json').read_text())
    expiry = datetime.fromisoformat(o['expiry_initial'])
    request_expiry = datetime.fromisoformat(o['http']['risk_accept']['request_body']['expires_at'])
    response_expiry = datetime.fromisoformat(o['http']['risk_accept']['body']['risk_acceptance']['expires_at'])
    require(expiry == request_expiry == response_expiry, 'initial deadline differs between request, response and oracle')
    initial = {}
    for phase in ('early', 'late', 'repeat'):
        name = 'worker_initial_' + phase
        x = o[name]
        require((run / (name + '.stdout')).read_text() == x['stdout'], 'initial worker stdout differs')
        require(sha256(run / (name + '.stderr')) == x['stderr_sha256'], 'initial worker stderr differs')
        initial[phase] = {'started_relative_to_expiry_seconds': (datetime.fromisoformat(x['started']) - expiry).total_seconds(),
                          'finished_relative_to_expiry_seconds': (datetime.fromisoformat(x['finished']) - expiry).total_seconds(),
                          'reopened': json.loads(x['stdout'])['reopened'], 'status_after': x['after']['finding'][0][1]}
    scores = evaluate(o)
    negative = {}
    if all(scores.values()):
        mutations = {
            'initial_premature': lambda x: x['worker_initial_early'].update(stdout='{"reopened":1}'),
            'initial_delayed': lambda x: x['worker_initial_late']['after']['finding'][0].__setitem__(1, 'risk_accepted'),
            'repeat_before_reopening': lambda x: x['before_accept_west']['finding'][0].__setitem__(1, 'risk_accepted'),
            'borrowed_identity': lambda x: x['http']['risk_accept_east']['body'].update(id='other'),
            'terminal_allowed': lambda x: x['http']['risk_repeat_initial'].update(status=200),
            'terminal_mutated': lambda x: x['risk_repeat_west_after']['finding'][0].__setitem__(3, {}),
            'expired_event_absent': lambda x: x['worker_east_late']['after'].update(outbox=x['worker_east_late']['before']['outbox']),
            'expiry_audit_duplicated': lambda x: x['worker_utc_late']['after']['audit'].append(['extra', 'finding.risk_acceptance.expired', 'worker']),
            'expiry_wrong_actor': lambda x: next(row for row in x['worker_initial_late']['after']['audit'] if row[1] == 'finding.risk_acceptance.expired').__setitem__(2, 'operator'),
            'final_state_mutated': lambda x: x['final_state']['finding'][0].__setitem__(1, 'risk_accepted'),
            'effective_forged': lambda x: x.update(final_effective_fact_count=[[1]]),
            'resolved_reference_erased': lambda x: x['risk_accept_resolved_after']['finding'][0].__setitem__(3, {}),
        }
        for name, mutate in mutations.items():
            altered = copy.deepcopy(o)
            mutate(altered)
            negative[name] = not all(evaluate_extra(altered).values())
        require(all(negative.values()), 'false legal lifecycle accepted')
    return {'run_id': run.name, 'base_raw_review': base, 'initial_worker_raw_joins': initial,
            'all_worker_raw_outputs_joined': 12, 'initial_request_response_deadline_join': True,
            'frozen_lifecycle_checks': scores, 'extra_actual_evidence_negative_rejections': negative,
            'scope': 'author post-run raw evidence review; no external witness, continuous scheduling or concurrency claim'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    print(json.dumps(review(args.run), ensure_ascii=False, indent=2))
