"""Compare actual P01 UI rows with planted assets and observed API projections."""
from urllib.parse import unquote

from discovery_scoring import asset_key

STAGES = ('frameworks', 'roles', 'skills', 'rescanned', 'preview', 'registered', 'reloaded')


def expected_checks():
    return {stage + ':' + name for stage in STAGES for name in ('gold_assets', 'classification_counts', 'table_projection', 'partial_visible')} | {
        'framework_discovery_disclaimer', 'same_name_skills_separate', 'rescan_identity_stable', 'preview_scope_unchanged',
        'reload_identity_stable', 'browser_discovery_requests', 'browser_and_fixture_closed', 'credentials_not_reflected'}


def score(o, gold, revision=2):
    checks = {}
    stages = o.get('stages', {})
    for name, stage in stages.items():
        if name not in STAGES:
            raise ValueError('unexpected discovery UI stage')
        expanded = name in ('registered', 'reloaded')
        expected = gold['phases']['registered' if expanded else 'initial']
        expected = [k for k in expected if not k.startswith('skill_dir|local://skills/' + gold['manual'] + '/')]
        assets = stage['api']['assets']
        checks[name + ':gold_assets'] = len(assets) == len(expected) and {asset_key(a) for a in assets} == set(expected)
        dom = stage['dom']
        checks[name + ':classification_counts'] = all(label in dom['buttons'] for label in ('智能体框架（4）', '智能体角色（5）' if expanded else '智能体角色（4）', 'Skill（8）' if expanded else 'Skill（6）', '其他配置（0）'))
        if name == 'frameworks':
            expected_rows = {('Claude Code', '1', '0'), ('Codex', '1', '0'), ('Hermes', '3', '2'), ('OpenClaw', '3', '2')}
            if revision >= 2:
                expected_rows = {('claude_code', '1', '0'), ('codex', '1', '0'), ('Hermes', '3', '2'), ('OpenClaw', '3', '2')}
            checks[name + ':table_projection'] = {tuple(r['cells'][:3]) for r in dom['rows']} == expected_rows and len(dom['rows']) == 4
        else:
            wanted = {a['id']: a for a in assets if a['source_type'] in (('hermes_profile', 'openclaw_agent') if name == 'roles' else ('skill_dir',))}
            actual = {}
            valid = dom['headers'][4:7] == ['状态', '安全检查', '授权状态']
            if name == 'roles' and revision >= 2:
                valid = dom['headers'][4:] == ['状态', '']
            for row in dom['rows']:
                links = [unquote(h.rsplit('/', 1)[-1]) for h in row['hrefs'] if h.startswith('/agents/')]
                if len(links) != 1 or links[0] in actual:
                    valid = False
                    continue
                actual[links[0]] = row
            valid &= set(actual) == set(wanted)
            for id_, a in wanted.items():
                row = actual.get(id_, {})
                cells = row.get('cells', [])
                expected_status = '候选' if name == 'roles' else '未准入'
                status_match = len(cells) >= 7 and cells[4:7] == [expected_status, '—', '—']
                if name == 'roles' and revision >= 2:
                    status_match = len(cells) == 6 and cells[4] == expected_status
                valid &= status_match and a['name'] in cells[0] and not a.get('grant_id') and not a.get('grant_status')
            checks[name + ':table_projection'] = bool(valid)
        checks[name + ':partial_visible'] = stage['discovery']['run']['state'] == 'partial' and '处跳过' in dom['text'] and '查看未完成的扫描项' in dom['text']
    if 'frameworks' in stages:
        checks['framework_discovery_disclaimer'] = '发现配置不代表已接入保护' in stages['frameworks']['dom']['text']
    if 'skills' in stages:
        checks['same_name_skills_separate'] = len([r for r in stages['skills']['dom']['rows'] if r['cells'][0].splitlines()[0] == 'same']) == 2
    for before, after, key in (('skills', 'rescanned', 'rescan_identity_stable'), ('rescanned', 'preview', 'preview_scope_unchanged'), ('registered', 'reloaded', 'reload_identity_stable')):
        if before in stages and after in stages:
            ids = lambda stage: {asset_key(a): a['id'] for a in stages[stage]['api']['assets']}
            checks[key] = ids(before) == ids(after)
            if key == 'preview_scope_unchanged':
                checks[key] &= stages[before]['discovery']['roots'] == stages[after]['discovery']['roots']
    if 'browser' in o:
        responses = o['browser']['responses']
        checks['browser_discovery_requests'] = sum(r['path'] == '/v1/discovery/scan' and r['method'] == 'POST' and r['status'] == 202 for r in responses) >= 2 and any(r['path'] == '/v1/discovery/preview' and r['status'] == 200 for r in responses) and any(r['path'] == '/v1/assets' and r['status'] == 200 for r in responses)
        checks['credentials_not_reflected'] = not any(r['unexpected_credential_reflection'] for r in responses) and not any(r['credential_reflection'] for r in o['browser']['consoles'])
    if 'cleanup' in o:
        checks['browser_and_fixture_closed'] = all(o['cleanup'].values())
    return {'checks': checks, 'passed': sum(checks.values()), 'total': len(checks), 'scope': 'actual Linux Chromium discovery UI and seeded config assets; no native host or OS confinement claim'}


def outcomes(o, result):
    harm = result['checks'].get('credentials_not_reflected') is False
    for name, stage in o.get('stages', {}).items():
        harm |= any(a['status'] not in ('candidate', 'unadmitted') or a.get('grant_id') or a.get('grant_status') for a in stage['api']['assets'])
        if name == 'frameworks':
            continue
        for row in stage['dom']['rows']:
            cells = row['cells']
            harm |= len(cells) >= 5 and cells[4] in ('已保护', '已纳管', '已准入', '已确认')
            harm |= name != 'roles' and len(cells) >= 7 and cells[6] != '—'
    utility = None if not o.get('stages') else all(result['checks'].get(stage + ':table_projection', False) for stage in STAGES)
    return bool(harm), utility
