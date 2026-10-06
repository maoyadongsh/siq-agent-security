"""Postrun review: failed before native attach has no invented binding."""
import argparse
import json
from pathlib import Path

import corrected_fault_joins as corrected
import review_native_runtime_faults as negative
import verify_native_runtime_faults as original

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    original.joins = corrected.joins
    negative.joins = corrected.joins
    result = negative.review(args.run, args.expected_manifest_sha256)
    result['supplementary_scope'] = 'allow absent binding only for signed pre-attach failure without running history, matching binding or any own receipt'
    print(json.dumps(result))
