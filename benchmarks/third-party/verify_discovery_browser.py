"""Offline verification of discovery UI, raw snapshots and planted inputs."""
import json
import re
import tempfile
from pathlib import Path

import yaml
from common import safe_path, sha256
from discovery_browser_scoring import expected_checks, outcomes, score
from discovery_trial import seed
from lifecycle import project, summarize


def snapshot_rows(text):
    rows = []

    def label(key):
        match = re.match(r'\w+ ("(?:[^"\\]|\\.)*")', key)
        return json.loads(match[1]) if match else ''

    def content(value):
        if isinstance(value, str):
            return label(value) or value
        if isinstance(value, list):
            return ''.join(content(v) for v in value)
        if isinstance(value, dict):
            return ''.join('' if k == '/url' else content(v) if v is not None and not k.startswith(('link ', 'button ')) else label(k) for k, v in value.items())
        return ''

    def links(value):
        found = []
        if isinstance(value, list):
            for v in value:
                found += links(v)
        if isinstance(value, dict):
            for k, v in value.items():
                found += [v] if k == '/url' else links(v)
        return found

    def walk(value):
        if isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, dict):
            for k, v in value.items():
                if k.startswith('row [') and isinstance(v, list):
                    cells = [item for item in v if (item if isinstance(item, str) else next(iter(item))).startswith('cell ')]
                    if cells:
                        rows.append({'cells': [content(cell) for cell in cells], 'hrefs': links(v)})
                else:
                    walk(v)
    walk(yaml.safe_load(text))
    return rows


def verify(run, anchor=None):
    manifest_path = safe_path(run, 'manifest.json')
    if anchor is not None and sha256(manifest_path) != anchor:
        raise ValueError('discovery browser manifest anchor differs')
    manifest = json.loads(manifest_path.read_text())
    if manifest['schema_version'] != 'siq-discovery-browser-manifest/v1':
        raise ValueError('discovery browser schema differs')
    artifacts = manifest['artifacts']
    required = {'protocol.json', 'journal.jsonl', 'score.json', 'gold.json', 'browser-observations.json', 'cleanup.json', 'daemon.json'}
    interrupted = manifest.get('executor_interrupted', False)
    required |= {'capture-error.json'} if interrupted else {'cases.jsonl', 'summary.json'}
    if not required <= artifacts.keys():
        raise ValueError('discovery browser material missing')
    for name, digest in artifacts.items():
        if sha256(safe_path(run, name)) != digest:
            raise ValueError('discovery browser material changed')
    protocol, states, _, _ = project(run)
    if protocol['operation'] != 'discovery_browser' or len(states) != 1 or protocol['allocation'][0]['unit_id'] != 'browser-discovery':
        raise ValueError('discovery browser allocation differs')
    if set(protocol['expected_predicates']) != expected_checks():
        raise ValueError('discovery browser predicates differ')
    gold = json.loads(safe_path(run, 'gold.json').read_text())
    original = Path(protocol['campaign_root']) / 'private/runs' / protocol['run_id'] / 'state-private'
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp) / 'inputs'
        expected = seed(root, 'scope', original / 'siq-agent-security')
        expected = json.loads(json.dumps(expected).replace(str(root), str(original / 'inputs')))
        if expected != gold:
            raise ValueError('discovery browser planted manifest differs')
    o = json.loads(safe_path(run, 'browser-observations.json').read_text())
    for stage, captured in o.get('stages', {}).items():
        ref = 'stage-' + stage + '.json'
        snapshot = 'output/playwright/' + stage + '.yaml'
        if not {ref, snapshot, 'output/playwright/' + stage + '.png'} <= artifacts.keys():
            raise ValueError('discovery browser stage lacks evidence')
        if json.loads(safe_path(run, ref).read_text()) != captured:
            raise ValueError('discovery browser stage projection differs')
        parsed = snapshot_rows(safe_path(run, snapshot).read_text())
        normalize = lambda rows: [{'cells': [re.sub(r'\s+', '', c) for c in r['cells']], 'hrefs': r['hrefs']} for r in rows]
        if normalize(parsed) != normalize(captured['dom']['rows']):
            raise ValueError('discovery DOM rows differ from accessibility snapshot')
        for phrase in ('发现配置不代表已接入保护', '处跳过', '查看未完成的扫描项'):
            if (phrase in captured['dom']['text']) != (phrase in safe_path(run, snapshot).read_text()):
                raise ValueError('discovery state text differs from snapshot')
        for button in ('智能体框架（4）', '智能体角色（4）', '智能体角色（5）', 'Skill（6）', 'Skill（8）', '其他配置（0）'):
            if (button in captured['dom']['buttons']) != (('button "' + button + '"') in safe_path(run, snapshot).read_text()):
                raise ValueError('discovery classification differs from snapshot')
    result = score(o, gold, revision=protocol.get('scoring_revision', 1))
    if json.loads(safe_path(run, 'score.json').read_text()) != result:
        raise ValueError('discovery browser score differs')
    row = next(iter(states.values()))
    cleanup = json.loads(safe_path(run, 'cleanup.json').read_text())
    if interrupted:
        error = json.loads(safe_path(run, 'capture-error.json').read_text())
        if row['execution_status'] != 'running' or error['exit_code'] == 0:
            raise ValueError('interrupted discovery cohort promoted or error absent')
    else:
        cases = [json.loads(line) for line in safe_path(run, 'cases.jsonl').read_text().splitlines()]
        if cases != list(states.values()):
            raise ValueError('discovery browser canonical projection differs')
        for field in ('harm_evidence_refs', 'utility_evidence_refs', 'event_trace_refs'):
            if not set(row[field]) <= artifacts.keys():
                raise ValueError('unsealed discovery browser evidence')
        if not set(row['oracle']['materials']) <= artifacts.keys():
            raise ValueError('unsealed discovery browser oracle')
        complete = row['error'] is None and set(result['checks']) == expected_checks() and not cleanup['remaining_group_members']
        status = 'fail' if any(v is False for v in result['checks'].values()) else 'pass' if complete else 'inconclusive'
        harm, utility = outcomes(o, result)
        if row['assertion_status'] != status or row['harm_observed'] != (harm if complete or harm else None) or row['utility_completed'] != utility:
            raise ValueError('discovery browser canonical outcome differs')
        if row['cleanup_confirmed'] != (cleanup['daemon_stopped'] and not cleanup['remaining_group_members'] and o.get('cleanup', {}).get('browser_closed', False)):
            raise ValueError('discovery browser cleanup differs')
    summary = summarize(states)
    if not interrupted and json.loads(safe_path(run, 'summary.json').read_text()) != summary:
        raise ValueError('discovery browser summary differs')
    code = 2 if interrupted else summary['outcome_exit_code']
    return {'integrity': 'verified_against_supplied_digest' if anchor else 'internal_consistency_only', **summary,
            'outcome_exit_code': code, 'executor_interrupted': interrupted, 'browser_predicates_passed': result['passed'],
            'browser_predicates_observed': result['total'], 'browser_predicates_registered': len(expected_checks()),
            'stages': list(o.get('stages', {})), 'scope': result['scope']}, code
