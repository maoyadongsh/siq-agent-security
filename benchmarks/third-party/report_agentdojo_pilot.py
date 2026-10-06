"""Summarize a sealed, independently recomputed AgentDojo pilot without reruns."""
import argparse
import json
from pathlib import Path

from analysis.agentdojo_pilot import paired
from common import sha256, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if Path(args.run_id).name != args.run_id:
        raise ValueError('run ID must be a single path component')
    run = args.campaign / 'data' / args.run_id
    verification = json.loads((args.campaign / 'reports' / (args.run_id + '-verification.json')).read_text())
    if (verification.get('integrity') != 'verified_against_supplied_digest'
            or verification.get('manifest_sha256') != sha256(run / 'manifest.json')):
        raise ValueError('verified sealed run required')
    summary = json.loads((run / 'summary.json').read_text())
    protocol = json.loads((run / 'protocol.json').read_text())
    rows = [json.loads((run / 'cases' / u['unit_id'] / 'result.json').read_text()) for u in protocol['allocation']]
    comparisons = [paired(rows, right=arm, condition=condition) for arm in ('B1', 'B2') for condition in ('benign', 'adversarial')]
    errors = [{'unit_id': r['unit_id'], 'error': r['error'], 'calls': r['calls']} for r in rows if r['execution_status'] != 'completed']
    dispatch = {arm: {'direct_mail_requested': 0, 'direct_mail_entered': 0, 'direct_mail_completed': 0,
                      'SIQ_decision_count': 0, 'lab_boundary_units': 0} for arm in ('B0', 'B1', 'B2')}
    for row in rows:
        counts = dispatch[row['group']]
        counts['SIQ_decision_count'] += len(row['decisions'])
        counts['lab_boundary_units'] += row['lab_boundary_intervened']
        for d in row['dispatches']:
            if d['tool'] == 'send_email':
                counts['direct_mail_requested'] += 1
                counts['direct_mail_entered'] += d['entered']
                counts['direct_mail_completed'] += d['completed']
    baseline = summary['strata']['B0:adversarial']
    interpretation = ('baseline_target_harm_observed_descriptive_comparison_only' if baseline['harm_count']
                      else 'baseline_harm_not_established_with_unknown_outcomes' if baseline['harm_unknown_count']
                      else 'baseline_not_discriminating')
    report = {'run_id': args.run_id, 'manifest_sha256': sha256(run / 'manifest.json'), 'model': protocol['model'],
              'allocated': len(rows), 'task_blocks': len({r['task_id'] for r in rows}), 'strata': summary['strata'],
              'budget': summary['budget'], 'paired_comparisons': comparisons, 'errors': errors, 'dispatch': dispatch,
              'interpretation': interpretation, 'verified_receipts': verification['verified_receipts'],
              'limitations': ['author-run public exploratory pilot, no independent third-party or hidden-set claim',
                              '20 official task IDs share workspace entities; not 20 independent attack families',
                              'one fixed attack injection_task_0; baseline zero harm cannot establish SIQ incremental benefit',
                              'B2 guards only top-level send_email; nested notifications and all other tool effects unguarded',
                              'AgentDojo tools modify simulated environment; no real email delivery',
                              'errors and timeouts retain allocated denominator with unknown outcome sensitivity; no retry replacement',
                              'exact reported model IDs and token usage preserved, provider credit charge not available']}
    write_json(args.campaign / 'reports' / (args.run_id + '-analysis.json'), report)
    print(json.dumps({'run_id': args.run_id, 'interpretation': interpretation, 'errors': len(errors)}))


if __name__ == '__main__':
    main()
