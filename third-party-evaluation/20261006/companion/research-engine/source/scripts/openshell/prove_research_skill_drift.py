"""Repeat the original installed-content drift case with bounded diagnostics.

The original write/deny/utility criteria are unchanged. Diagnostic events do
not count as a signed tool denial or a completed business task.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

from scripts.openshell import prove_research_skill_withdrawal as withdrawal
from services import qwen38_request_startup as startup


def categorical_journal(raw):
    result = []
    for line in raw.splitlines():
        item = json.loads(line)
        message = item.get('MESSAGE', '')
        match = re.fullmatch(r'supervisor_failure stage=([a-z_]{1,40}) category=([a-z_]{1,40})', message)
        if match:
            result.append({'timestamp_microseconds': item.get('__REALTIME_TIMESTAMP'),
                'stage': match[1], 'category': match[2]})
    return result


class DriftScenario(withdrawal.WithdrawalScenario):
    def mutate(self, context):
        started = time.time()
        result = super().mutate(context)
        path = Path(self.factory.selected['installed_path']) / 'SKILL.md'
        raw = path.read_bytes()
        with (self.setup_state / 'changed-installed-SKILL.md').open('xb') as stream:
            stream.write(raw)
        return {**result, 'mutation_started_unix': started, 'mutation_finished_unix': time.time(),
                'changed_copy_sha256': hashlib.sha256(raw).hexdigest()}

    def cleanup(self, result):
        try:
            events = []
            for synced in self.sync_records:
                run_id = synced['business_run_id']
                directory = startup.location(run_id)
                raw = (directory / 'request-supervision.json').read_bytes()
                record = json.loads(raw)
                invocation = record['invocation_id']
                if not re.fullmatch('[a-f0-9]{32}', invocation):
                    raise ValueError('drift_invocation_invalid')
                journal = subprocess.run(['journalctl', '--user', '_SYSTEMD_INVOCATION_ID=' + invocation,
                    '-o', 'json', '--no-pager'], capture_output=True, timeout=15, check=True)
                events.append({'run_id': run_id, 'invocation_id': invocation,
                    'supervision_record_sha256': hashlib.sha256(raw).hexdigest(),
                    'failure_events': categorical_journal(journal.stdout),
                    'journal_record_count': len(journal.stdout.splitlines())})
            result['supervisor_diagnostics'] = events
        except Exception as exc:
            result['diagnostic_collection_failure_type'] = type(exc).__name__
        # Diagnostic failure never prevents original scope cleanup.
        return super().cleanup(result)


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recovery-file', type=Path, required=True)
    parser.add_argument('--relay-binary', type=Path, required=True)
    parser.add_argument('--relay-sha256', required=True)
    parser.add_argument('--helper-image-ref', required=True)
    parser.add_argument('--helper-image-id', required=True)
    parser.add_argument('--relay-port', type=int, default=47710)
    parser.add_argument('--evidence-suffix', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.set_defaults(control='drift-installation', task='paired-analysis')
    return parser.parse_args(argv)


def main():
    args = arguments()
    os.umask(0o077)
    scenario = DriftScenario(args)
    result = {'passed': False}
    try:
        scenario.prepare()
        result = withdrawal.skills.business.api.run(args.evidence_suffix, scenario=scenario)
    except Exception as exc:
        result['failure_type'] = type(exc).__name__
        if scenario.factory.admin:
            try:
                scenario.factory.close()
                result['setup_cleanup'] = True
            except Exception as cleanup:
                result['setup_cleanup'] = False
                result['cleanup_failure_type'] = type(cleanup).__name__
    finally:
        result['skill_installations'] = scenario.factory.installations
        result['evaluation_sync_only'] = True
        if hasattr(scenario, 'candidate_image_record'):
            result['candidate_image'] = json.loads(scenario.candidate_image_record.read_text())
        with args.output.open('x') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'passed': result.get('passed') is True}))
    return 0 if result.get('passed') else 1


if __name__ == '__main__':
    raise SystemExit(main())
