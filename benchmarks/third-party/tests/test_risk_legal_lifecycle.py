"""Reject a claimed legal lifecycle with missing expiry or unauthorized state changes."""
import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from enterprise_risk_v2 import evaluate_extra


def observation():
    fid = 'risk-fixture'
    current = {'finding': [[fid, 'acknowledged', 'risk-owner', {}]],
               'audit': [['created', 'finding.open', 'rule-engine'], ['ack', 'finding.acknowledge', 'actor']],
               'outbox': [['created', 'agent.finding.opened.v1', {}]]}
    o = {'finding_id': fid, 'http': {}, 'final_effective_fact_count': [[0]], 'expiry_initial': '2026-10-06T12:00:04+00:00'}
    for stage in ('initial', 'west', 'east', 'utc'):
        o['before_accept_' + stage] = copy.deepcopy(current)
        accepted = copy.deepcopy(current)
        accepted['finding'][0][1] = 'risk_accepted'
        accepted['finding'][0][3] = {'reason': stage}
        accepted['audit'].append(['accept-' + stage, 'finding.accept_risk', 'actor'])
        accepted['outbox'].append(['accepted-' + stage, 'agent.finding.resolved.v1', {}])
        o['accepted' if stage == 'initial' else 'accepted_' + stage] = copy.deepcopy(accepted)
        o['http']['risk_accept' if stage == 'initial' else 'risk_accept_' + stage] = {
            'body': {'id': fid, 'status': 'risk_accepted', 'risk_acceptance': {'reason': stage}}}
        terminal = 'risk_repeat_' + stage
        o['http'][terminal] = {'status': 409}
        o[terminal + '_before'] = copy.deepcopy(accepted)
        o[terminal + '_after'] = copy.deepcopy(accepted)
        reopened = copy.deepcopy(accepted)
        reopened['finding'][0][1] = 'open'
        reopened['audit'].append(['expiry-' + stage, 'finding.risk_acceptance.expired', 'worker'])
        reopened['outbox'].append(['reopened-' + stage, 'agent.finding.reopened.v1', {}])
        for phase, before, after, number in [('early', accepted, accepted, 0), ('late', accepted, reopened, 1), ('repeat', reopened, reopened, 0)]:
            o['worker_' + stage + '_' + phase] = {'before': copy.deepcopy(before), 'after': copy.deepcopy(after),
                'exit_code': 0, 'stdout': json.dumps({'reopened': number}), 'started': '2026-10-06T12:00:05+00:00', 'finished': '2026-10-06T12:00:01+00:00'}
        current = reopened
    current['finding'][0][1] = 'resolved'
    current['finding'][0][3] = {'evidence_ref': 'ticket:fixed'}
    current['audit'].append(['resolve', 'finding.resolve', 'actor'])
    current['outbox'].append(['resolved', 'agent.finding.resolved.v1', {}])
    o['resolved'] = copy.deepcopy(current)
    o['final_state'] = copy.deepcopy(current)
    o['risk_accept_resolved_before'] = copy.deepcopy(current)
    o['risk_accept_resolved_after'] = copy.deepcopy(current)
    o['http']['risk_accept_resolved'] = {'status': 409}
    return o


def test_legal_lifecycle_control():
    assert all(evaluate_extra(observation()).values())


@pytest.mark.parametrize('mutation', ['premature', 'not_expired', 'repeat_reopens', 'wrong_clock', 'renew_without_reopen',
                                   'borrowed_finding', 'missing_event', 'duplicate_event', 'wrong_actor',
                                   'terminal_allowed', 'terminal_mutated', 'resolved_mutated', 'extra_acceptance', 'effective_forged'])
def test_false_legal_lifecycle_rejected(mutation):
    o = observation()
    if mutation == 'premature': o['worker_initial_early']['after']['finding'][0][1] = 'open'
    if mutation == 'not_expired': o['worker_initial_late']['after']['finding'][0][1] = 'risk_accepted'
    if mutation == 'repeat_reopens': o['worker_initial_repeat']['stdout'] = '{"reopened":1}'
    if mutation == 'wrong_clock': o['worker_initial_late']['started'] = '2026-10-06T12:00:03+00:00'
    if mutation == 'renew_without_reopen': o['before_accept_west']['finding'][0][1] = 'risk_accepted'
    if mutation == 'borrowed_finding': o['http']['risk_accept_east']['body']['id'] = 'other'
    if mutation == 'missing_event': o['worker_west_late']['after']['outbox'] = copy.deepcopy(o['worker_west_late']['before']['outbox'])
    if mutation == 'duplicate_event': o['worker_east_late']['after']['outbox'].append(['duplicate', 'agent.finding.reopened.v1', {}])
    if mutation == 'wrong_actor': o['worker_utc_late']['after']['audit'][-1][2] = 'user'
    if mutation == 'terminal_allowed': o['http']['risk_repeat_west']['status'] = 200
    if mutation == 'terminal_mutated': o['risk_repeat_east_after']['finding'][0][2] = 'other-owner'
    if mutation == 'resolved_mutated': o['risk_accept_resolved_after']['finding'][0][3] = {}
    if mutation == 'extra_acceptance': o['final_state']['audit'].append(['extra', 'finding.accept_risk', 'actor'])
    if mutation == 'effective_forged': o['final_effective_fact_count'] = [[1]]
    assert not all(evaluate_extra(o).values())
