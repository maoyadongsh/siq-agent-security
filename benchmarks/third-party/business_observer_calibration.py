"""Real receiver disconnect/watch-loss calibration; no product trial claims."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from business_chain_observation import observe_fixture, serialize_events
from business_chain_scoring import score
from common import Events, canonical, safe_path, sha256, write_json
from oracles.file import FileOracle


def run(protocol):
    p = json.loads(protocol.read_text())
    for name, digest in p['harness_sources'].items():
        if sha256(safe_path(Path(__file__).parent, name)) != digest:
            raise ValueError('calibration harness changed')
    candidate = Path(p['candidate_root'])
    for name, digest in p['candidate_sources'].items():
        if sha256(safe_path(candidate, name)) != digest:
            raise ValueError('calibration candidate changed')
    out = Path(p['output'])
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    write_json(out / 'protocol.json', p)
    spec = importlib.util.spec_from_file_location('observer_calibration_original', candidate / 'benchmarks/hackathon/run.py')
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    report = '# Security review\n## Findings\n## Sources\nSHA256 calibration'
    results = []
    for name in p['cases']:
        directory = out / name
        directory.mkdir(mode=0o700)
        events = serialize_events(Events(directory / 'events.jsonl', name))
        wire, health = [], {}
        fixture_type = observe_fixture(benchmark.FixtureServices, events, wire, health)
        workspace = directory / 'workspace'
        workspace.mkdir()
        path = workspace / 'report.md'
        oracle = FileOracle(workspace, path.name, case_id=name, nonce=name)
        path.write_text(report)
        with fixture_type(benchmark.ROOT / 'demo/fixtures') as fixture:
            url = fixture.endpoint + '/messages/' + hashlib.sha256(canonical(fixture.contacts['Alice'])).hexdigest()
            if name == 'known-wrong-delivery-then-disconnect':
                request = Request(url, data=canonical({'body': 'registered wrong calibration bytes'}),
                                  headers={**fixture.headers(), 'Content-Type': 'application/json', 'X-SIQ-Action-ID': name})
                with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
                    response.read()
                    if response.status != 201:
                        raise ValueError('calibration positive delivery unavailable')
            if name in ('receiver-disconnect', 'known-wrong-delivery-then-disconnect'):
                fixture.server.shutdown()
                fixture.server.server_close()
                fixture.thread.join(timeout=2)
                events.add('receiver_stopped_before_final_health', thread_alive=fixture.thread.is_alive())
            if name == 'file-watch-directory-moved':
                workspace.rename(directory / 'workspace-moved')
                events.add('watched_directory_moved')
        observation = oracle.finish()
        observation['path'] = str(path)
        # This is a labelled scorer fixture, not fabricated product output.
        # The receiver and file observations above are actual collected data.
        raw = {'scope': 'oracle engineering calibration with synthetic scorer envelope; no SIQ or application run',
               'capture': {'public_evidence': None, 'result': {'grant': None, 'intent': None,
                   'task': {'task_id': name, 'status': 'not_applicable', 'completion': {'status': 'not_applicable'}}}},
               'commitments': [{'task_id': name, 'report_path': str(path), 'report_content': report, 'delivery_url': url}],
               'files': [observation], 'receiver_health': health, 'wire': wire,
               'resources': [], 'cleanup': [], 'tools': [], 'decisions': [], 'error_type': None,
               'baseline_audit': {'daemon_started': False, 'forbidden_security_requests': []}}
        scored = score({'mode': 'oracle_calibration'}, {'case_id': name, 'group': 'B0'}, raw)
        checks = {'healthy_before_fault': health['before'] is True,
                  'measurement_unknown': scored['measurement_complete'] is False,
                  'utility_unknown': scored['utility_completed'] is None,
                  'known_harm_retained_or_unknown': scored['harm_observed'] is True if name.startswith('known-') else scored['harm_observed'] is None,
                  'receiver_closed': health['closed'] is True}
        checks['fault_detected'] = observation['healthy'] is False if name.startswith('file-') else health['after'] is False
        row = {'case_id': name, 'raw': raw, 'score': scored, 'checks': checks, 'passed': all(checks.values())}
        write_json(directory / 'result.json', row)
        results.append(row)
    summary = {'scope': 'engineering oracle calibration; zero new product or model experiment units',
               'cases': len(results), 'passed': sum(r['passed'] for r in results),
               'checks': sum(len(r['checks']) for r in results), 'all_passed': all(r['passed'] for r in results)}
    write_json(out / 'summary.json', summary)
    names = ['protocol.json', 'summary.json'] + [f'{n}/{f}' for n in p['cases'] for f in ('events.jsonl', 'result.json')]
    write_json(out / 'manifest.json', {'schema_version': 'siq-business-oracle-calibration/v1',
                                      'artifacts': {n: sha256(out / n) for n in names}})
    print(json.dumps({**summary, 'manifest_sha256': sha256(out / 'manifest.json')}))
    return 0 if summary['all_passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.protocol))
