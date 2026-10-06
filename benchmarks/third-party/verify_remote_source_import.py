"""Offline verification of actual public HTTPS import evidence."""
import argparse
import json
from pathlib import Path

import verify_source_import as base
from remote_source_import import score


def verify(run, anchor):
    base.score = score
    return base.verify(run, anchor)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.run, args.expected_manifest_sha256)))
