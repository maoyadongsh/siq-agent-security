"""Verify a sealed source-management run against an externally supplied anchor."""
import argparse
import json
from pathlib import Path

from common import safe_path, sha256
from lifecycle import project, summarize
from source_import_scoring import score


def verify(run, anchor):
    if sha256(run / 'manifest.json') != anchor:
        raise ValueError('manifest anchor mismatch')
    manifest = json.loads((run / 'manifest.json').read_text())
    required = {'protocol.json', 'journal.jsonl', 'result.json', 'score.json', 'summary.json', 'http.jsonl'}
    if set(manifest['artifacts']) != required:
        raise ValueError('artifact set differs')
    for name, digest in manifest['artifacts'].items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError('artifact changed')
    p, states, _, _ = project(run)
    for name, digest in p['harness_sources'].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError('frozen verifier source changed')
    raw = json.loads((run / 'result.json').read_text())
    if raw['http'] != [json.loads(line) for line in (run / 'http.jsonl').read_text().splitlines()]:
        raise ValueError('HTTP capture differs')
    result = score(p, raw)
    if result != json.loads((run / 'score.json').read_text()) or summarize(states) != json.loads((run / 'summary.json').read_text()):
        raise ValueError('recomputed result differs')
    row = states['source-management#1']
    if (row['assertion_status'] == 'pass') != result['all_passed'] or row['harm_observed'] != result['harm_observed']:
        raise ValueError('journal result differs')
    return {'verified': True, 'all_passed': result['all_passed'], 'passed': result['passed'], 'total': result['total'],
            'unique_signed_documents': result['unique_signed_documents'], 'http_requests': len(raw['http']), 'scope': result['scope']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.run, args.expected_manifest_sha256)))
