"""Explain anchored semantic report failures without changing primary scores."""
import argparse
import json
from pathlib import Path

from common import write_json
from native_semantic import lines, normalize, unique_object
from verify_native_business import verify


def explain(run, anchor):
    verified = verify(run, anchor)
    protocol = json.loads((run / 'protocol.json').read_text())
    if protocol['profile'] not in ('semantic-briefing', 'semantic-support-v2'):
        raise ValueError('semantic cohort required')
    units = {}
    for unit in protocol['allocation']:
        raw = json.loads((run / 'cases' / unit['unit_id'] / 'result.json').read_text())
        scored = verified['units'][unit['unit_id']]
        quality = scored['semantic_quality']
        row = {'group': unit['group'], 'task_block_id': unit['task_block_id'],
               'primary_utility_completed': scored['utility_completed'],
               'report_schema_valid': quality['report_schema_valid'], 'claims': {}}
        if not quality['report_schema_valid']:
            row['parse_error'] = quality.get('parse_error', 'invalid_claim_schema')
            row['claims_not_explained'] = quality['claims_total']
            units[unit['unit_id']] = row
            continue
        parsed = json.loads(raw['brief'], object_pairs_hook=unique_object)
        task = raw['gold']['semantic_task']
        evidence = lines(task)
        for name, claim in task['claims'].items():
            answer = parsed['answers'][name]
            refs = [c['document'] + ':' + c['line_id'] for c in answer['citations']]
            false_quotes = [ref for ref, citation in zip(refs, answer['citations'], strict=True)
                            if ref not in evidence or normalize(citation['quote']) != normalize(evidence[ref])]
            mismatches = []
            for ref, citation in zip(refs, answer['citations'], strict=True):
                if ref not in false_quotes:
                    continue
                kind = 'unknown_reference' if ref not in evidence else (
                    'retained_line_id_prefix' if normalize(citation['quote']) == normalize(
                        '[' + citation['line_id'] + '] ' + evidence[ref]) else 'other_text_difference')
                mismatches.append({'reference': ref, 'kind': kind})
            row['claims'][name] = {
                **quality['claims'][name], 'expected_value': claim['value'], 'observed_value': answer['value'],
                'missing_required_refs': sorted(set(claim['support']) - set(refs)),
                'additional_refs': sorted(set(refs) - set(claim['support'])),
                'false_or_unknown_quote_refs': false_quotes,
                'quote_mismatches': mismatches,
                'duplicate_ref_count': len(refs) - len(set(refs)),
            }
        units[unit['unit_id']] = row
    return {'run_id': protocol['run_id'], 'profile': protocol['profile'], 'manifest_sha256': anchor,
            'original_outcome_exit_code': verified['outcome_exit_code'], 'units': units,
            'scope': 'post-run explanations of registered typed-value and citation-dependency rules; no rescoring or new independent samples'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    write_json(args.out, explain(args.run, args.expected_manifest_sha256))
