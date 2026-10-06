"""Post-run joins for real archive, effect observer and network evidence."""
import argparse
import copy
import hashlib
import ipaddress
import json
import zipfile
from pathlib import Path

from common import sha256
from remote_source_import import score
from source_import_scoring import canonical


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(p, raw, logs, archive):
    result = score(p, raw)
    require(result['all_passed'], 'frozen conditions not met')
    source = p['public_source']
    require(sha256(archive) == source['archive_sha256'] and archive.stat().st_size == source['archive_bytes'], 'independent archive changed')
    prefix = source['archive_path'] + '/'
    with zipfile.ZipFile(archive) as z:
        files, directories = [], []
        for item in z.infolist():
            if not item.filename.startswith(prefix) or item.filename == prefix:
                continue
            name = item.filename[len(prefix):]
            if item.is_dir():
                directories.append(name.rstrip('/'))
            else:
                files.append({'path': name, 'sha256': hashlib.sha256(z.read(item)).hexdigest(), 'bytes': item.file_size, 'executable': bool((item.external_attr >> 16) & 0o111)})
    files.sort(key=lambda f: f['path'])
    directories.sort()
    require(files == source['selected_files'] and directories == source.get('selected_directories', []), 'independent file tree differs')
    tree_digest = hashlib.sha256(canonical({'files': files, 'directories': directories})).hexdigest()
    for row in raw['http']:
        if row['id'] in ('remote_pinned', 'remote_retry', 'remote_unpinned'):
            require(row['body']['import']['artifact_digest'] == tree_digest, 'tree digest differs')
    stamps = [r['monotonic_ns'] for r in raw['http']]
    require(stamps == sorted(set(stamps)), 'request order differs')
    mask = 2 | 64 | 128 | 256 | 512
    for guard in raw['guards']:
        require(guard['nonce'] == p['run_id'] and guard['case_id'] == 'source-management', 'borrowed guard')
        require(guard['window_start_ns'] < min(stamps) <= max(stamps) < guard['window_end_ns'], 'guard misses requests')
        require(guard['errors'] == [] and guard['barrier_acknowledged'], 'guard barrier failed')
        require(not any(e['mask'] & mask for e in guard['events']), 'transient mutation')
        require(not guard['before']['exists'] and not guard['after']['exists'], 'escape target exists')
    for item in raw['calibration']:
        require(any(e['mask'] & mask for e in item['observation']['events']) == item['expected'], 'raw calibration differs')
    network = raw['network_observation']
    require(network['started_ns'] < min(stamps) <= max(stamps) < network['finished_ns'], 'network window differs')
    require(all(network['started_ns'] <= row['monotonic_ns'] <= network['finished_ns'] for row in network['rows']), 'socket timestamp outside window')
    dns = [json.loads(line) for line in logs['dns']['stdout'].splitlines()]
    answers = {address for row in dns for address in row.get('addresses', [])}
    require(not any(row.get('error_type') for row in dns), 'resolver error')
    peers = {row['remote_ip'] for row in network['rows'] if row['remote_port'] == 443 and row['tcp_state'] == '01' and ipaddress.ip_address(row['remote_ip']).is_global}
    require(bool(peers) and peers <= answers, 'public TCP peers missing from DNS answers')
    return {'archive_tree_digest': tree_digest, 'public_peers': sorted(peers), 'dns_public_answers': sorted(a for a in answers if ipaddress.ip_address(a).is_global), 'raw_guard_joins': True}


def negatives(p, raw, logs, archive):
    mutations = {
        'hidden_transient_write': lambda r: r['guards'][0]['events'].append({'mask': 256}),
        'missing_window': lambda r: r['guards'][0].update(window_start_ns=r['http'][-1]['monotonic_ns']),
        'borrowed_guard': lambda r: r['guards'][0].update(nonce='another-run'),
        'false_calibration': lambda r: r['calibration'][1]['observation'].update(events=[]),
        'wrong_error_layer': lambda r: r['http'][3]['body'].update(error='authentication_required'),
        'missing_request': lambda r: r['http'].pop(),
        'unreported_publication': lambda r: r['http'][3]['after'].update({'records/fake.json': {'sha256': '0' * 64}}),
        'invalid_import_signature': lambda r: r['http'][1]['body']['import'].update(signature='0' * 128),
        'unexpected_grant': lambda r: r['authority_files'].append('grants/unapproved.json'),
        'different_pid': lambda r: r['network_observation'].update(pid=0),
        'outside_capture': lambda r: r['network_observation']['rows'][0].update(monotonic_ns=0),
        'network_window': lambda r: r['network_observation'].update(started_ns=r['http'][-1]['monotonic_ns']),
    }
    results = {}
    for name, mutate in mutations.items():
        altered = copy.deepcopy(raw)
        mutate(altered)
        try:
            validate(p, altered, logs, archive)
            results[name] = False
        except (ValueError, KeyError):
            results[name] = True
    require(all(results.values()), 'invalid evidence accepted')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--logs', type=Path, required=True)
    args = parser.parse_args()
    p = json.loads((args.run / 'protocol.json').read_text())
    raw = json.loads((args.run / 'result.json').read_text())
    logs = json.loads(args.logs.read_text())
    archive = Path(p['public_source']['private_archive_path'])
    print(json.dumps({'joins': validate(p, raw, logs, archive), 'negative_rejections': negatives(p, raw, logs, archive),
                      'scope': 'supplementary author review; frozen verifier must be run separately; not packet-level per-request attribution'}))
