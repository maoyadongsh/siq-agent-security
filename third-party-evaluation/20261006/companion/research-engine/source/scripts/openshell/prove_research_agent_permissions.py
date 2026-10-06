"""Owned DGX evaluation using the real analysis image and native Hermes tools.

This deterministic native-tool control is separate from the business HTTP/model
proof. It does not establish per-installed-Skill permissions.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.openshell import prove_qwen38_native_tool_security as native
from scripts.openshell import prove_qwen38_scoped_sandbox as scoped


class IsolatedController(native.security.CandidateToolSecurity):
    isolated_authority = True


class IsolatedAuthority(native.SyntheticAuthority):
    endpoint = 'http://127.0.0.1:47811'
    controller_class = IsolatedController


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-file', type=Path, required=True)
    parser.add_argument('--relay-binary', type=Path, required=True)
    parser.add_argument('--relay-sha256', required=True)
    parser.add_argument('--helper-image-ref', required=True)
    parser.add_argument('--helper-image-id', required=True)
    parser.add_argument('--relay-port', type=int, default=47710)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError('evaluation_output_preexists')
    authority = IsolatedAuthority(args)
    result = {'passed': False, 'scope': 'native_control_not_business_model_or_skill_permission'}
    try:
        authority.login()
        result = scoped.run(online_admission=True, expect_positive_model=True,
                            supervised_lifecycle=True, tool_security_factory=authority.create,
                            evidence_output=args.output.with_suffix('.sandbox.json'))
        if result.get('passed'):
            result['authority_receipts'] = authority.verify_receipts()
    except Exception as exc:
        result['passed'] = False
        result['evaluation_error_type'] = type(exc).__name__
        if isinstance(exc, (native.AuthorityProofError, scoped.ScopedProbeError)):
            result['evaluation_error_code'] = str(exc)
    finally:
        try:
            authority.close()
            result['evaluation_authority_cleanup'] = True
        except Exception as exc:
            result['evaluation_authority_cleanup'] = False
            result['cleanup_error_type'] = type(exc).__name__
            result['passed'] = False
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result['passed']}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
