"""Actual public HTTPS import with a fixed independently retrieved archive."""
import argparse
import hashlib
import ipaddress
import json
import zipfile
from pathlib import Path

import source_import_trial as base
from common import sha256, utc_now, write_json
from source_import_scoring import canonical
from source_import_scoring import score as original_score
from source_network_observer import NetworkObserver


def score(p, raw):
    result = original_score(p, raw)
    checks = result['checks']
    by_id = {x['id']: x for x in raw['http']}
    fixture = p['public_source']
    for name in ('remote_pinned', 'remote_retry', 'remote_unpinned'):
        row = by_id.get(name, {})
        record = row.get('body', {}).get('import', {})
        remote = record.get('remote', {})
        request = row.get('request', {})
        checks[name + '.actual_public_archive'] = (record.get('source_kind') == 'https_zip' and remote.get('archive_sha256') == fixture['archive_sha256'] and remote.get('archive_bytes') == fixture['archive_bytes'])
        checks[name + '.selected_content'] = record.get('files') == fixture['selected_files'] and record.get('directories') == fixture.get('selected_directories', [])
        checks[name + '.locator_binding'] = bool(request) and record.get('source_locator_digest') == hashlib.sha256(canonical({k: request[k] for k in ('url', 'archive_path', 'expected_sha256')})).hexdigest()
        checks[name + '.final_locator_binding'] = remote.get('final_locator_digest') == hashlib.sha256(fixture['url'].encode()).hexdigest()
        checks[name + '.expected_digest_recorded'] = bool(request) and remote.get('expected_sha256') == request['expected_sha256']
    pinned = by_id.get('remote_pinned', {}).get('body', {})
    retry = by_id.get('remote_retry', {}).get('body', {})
    unpinned = by_id.get('remote_unpinned', {}).get('body', {})
    checks['remote_retry_exact_record'] = bool(pinned.get('import')) and retry.get('import') == pinned['import'] and retry.get('reused') is True
    checks['optional_digest_distinct_identity'] = bool(pinned.get('import')) and bool(unpinned.get('import')) and pinned['import']['artifact_digest'] == unpinned['import']['artifact_digest'] and pinned['import']['source_locator_digest'] != unpinned['import']['source_locator_digest']
    network = raw.get('network_observation', {})
    checks['network_capture_healthy'] = network.get('stopped') is True and network.get('errors') == [] and network.get('pid') == raw.get('daemon_identity', {}).get('pid')
    checks['daemon_public_tls_port_connected'] = any(r['remote_port'] == 443 and r['tcp_state'] == '01' and ipaddress.ip_address(r['remote_ip']).is_global for r in network.get('rows', []))
    result.update(passed=sum(checks.values()), total=len(checks), all_passed=all(checks.values()),
                  scope='author-run actual public HTTPS import and digest/path controls; sampled TCP peers plus signed archive metadata; no publisher certification or native installation')
    return result


def freeze(campaign, run_id, source, container=False, registration=None, skill_path='skills/web-design-guidelines'):
    meta = json.loads((source / 'archive-result.json').read_text())
    archive = source / 'archive.zip'
    if sha256(archive) != meta['sha256']:
        raise ValueError('evaluator archive identity changed')
    selected = 'agent-skills-' + meta['commit'] + '/' + skill_path
    with zipfile.ZipFile(archive) as z:
        entries = [i for i in z.infolist() if i.filename.startswith(selected + '/') and i.filename != selected + '/']
        if selected + '/SKILL.md' not in [i.filename for i in entries]:
            raise ValueError('selected source lacks SKILL.md')
        files = sorted([{'path': i.filename[len(selected) + 1:], 'sha256': hashlib.sha256(z.read(i)).hexdigest(), 'bytes': i.file_size,
                         'executable': bool((i.external_attr >> 16) & 0o111)} for i in entries if not i.is_dir()], key=lambda x: x['path'])
        directories = sorted(i.filename[len(selected) + 1:].rstrip('/') for i in entries if i.is_dir())
    path = base.freeze(campaign, run_id)
    p = json.loads(path.read_text())
    requests = [r for r in p['requests'] if r['id'] == 'zip']
    body = {'schema_version': 'local-skill-import-remote-create/v1', 'import_id': 'si-' + 'c' * 32, 'url': meta['url'],
            'archive_path': selected, 'expected_sha256': meta['sha256'], 'actor_id': 'source-evaluation-operator'}

    def add(name, value, status, error=None):
        requests.append({'id': name, 'route': '/v1/skill-imports/remote', 'body': value, 'status': status, 'error': error})

    add('remote_pinned', body, 201)
    add('remote_retry', body, 200)
    add('remote_digest_error', {**body, 'import_id': 'si-' + 'd' * 32, 'expected_sha256': '0' * 64}, 409, 'skill_import_archive_mismatch')
    add('remote_path_missing', {**body, 'import_id': 'si-' + 'e' * 32, 'archive_path': selected + '/not-present'}, 400, 'skill_import_invalid')
    add('remote_root_missing', {**body, 'import_id': 'si-' + 'f' * 32, 'archive_path': ''}, 400, 'skill_import_invalid')
    add('remote_expected_conflict', {**body, 'expected_sha256': ''}, 409, 'skill_import_conflict')
    add('remote_unpinned', {**body, 'import_id': 'si-' + 'a' * 32, 'expected_sha256': ''}, 201)
    p.update(requests=requests, timeout_seconds=420, frozen_at=utc_now(), profile='remote-source-import',
             scope='actual public HTTPS production import, fixed archive hash and selected Skill; no Git transport or native execution')
    p['public_source'] = {'url': meta['url'], 'repository': 'https://github.com/vercel-labs/agent-skills', 'commit': meta['commit'], 'archive_path': selected,
                          'archive_sha256': meta['sha256'], 'archive_bytes': meta['bytes'], 'private_archive_path': str(archive.resolve()),
                          'selected_files': files, 'selected_directories': directories,
                          'retrieval_metadata_sha256': sha256(source / 'archive-result.json'), 'publisher_identity_verified': False}
    if container:
        from remote_source_container import IMAGE
        p.update(network_environment='container_doh_dns', container_image=IMAGE)
    registration = registration or campaign / ('plan/remote-source-import-002.md' if container else 'plan/remote-source-import-001.md')
    p['registration'] = {'path': str(registration), 'sha256': sha256(registration)}
    for name in ('remote_source_import.py', 'verify_remote_source_import.py', 'source_network_observer.py', 'remote_source_container.py', 'source_doh_relay.py'):
        (path.parent / 'harness-source' / name).write_bytes(Path(__file__).with_name(name).read_bytes())
    p['harness_sources'] = {str(f.relative_to(path.parent / 'harness-source')): sha256(f) for f in (path.parent / 'harness-source').rglob('*') if f.is_file()}
    write_json(path, p, exclusive=False)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('freeze', 'run'))
    parser.add_argument('--campaign', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--run-id')
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--container', action='store_true')
    parser.add_argument('--registration', type=Path)
    parser.add_argument('--skill-path', default='skills/web-design-guidelines')
    args = parser.parse_args()
    if args.action == 'freeze':
        print(freeze(args.campaign.resolve(), args.run_id, args.source.resolve(), args.container, args.registration, args.skill_path))
    else:
        base.score = score
        raise SystemExit(base.execute(args.protocol, observer_factory=NetworkObserver))
