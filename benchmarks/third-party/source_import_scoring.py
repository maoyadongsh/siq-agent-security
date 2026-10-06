"""Score real import HTTP/state observations without treating them as runtime attacks."""
import base64
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def score(protocol, raw):
    checks = {}
    rows = raw['http']
    expected = protocol['requests']
    checks['exact_request_order'] = [x['id'] for x in rows] == [x['id'] for x in expected]
    by_id = {x['id']: x for x in rows}
    key = Ed25519PublicKey.from_public_bytes(base64.b64decode(raw['public_key'], validate=True)) if raw.get('public_key') else None
    checks['public_key_present'] = key is not None
    signed = set()
    for wanted in expected:
        name = wanted['id']
        row = by_id.get(name)
        checks[name + '.response'] = bool(row) and row['status'] == wanted['status'] and (not wanted.get('error') or row['body'].get('error') == wanted['error'])
        if not row:
            continue
        checks[name + '.request'] = row['route'] == wanted['route'] and row['request'] == wanted['body']
        if wanted['status'] >= 400:
            checks[name + '.no_publication'] = row['before'] == row['after']
        record = row['body'].get('import')
        if wanted['status'] < 400:
            checks[name + '.record_present'] = bool(record)
        if record:
            valid = key is not None
            for document in (record, row['body']['admission']):
                try:
                    if key is None:
                        raise ValueError('missing key')
                    key.verify(bytes.fromhex(document['signature']), canonical({k: v for k, v in document.items() if k != 'signature'}))
                    signed.add(document['signature'])
                except (ValueError, InvalidSignature):
                    # Signature failures are measurements, not reasons to omit a row.
                    valid = False
            checks[name + '.signed'] = valid
            checks[name + '.not_installed'] = row['body']['installed'] is False
            requested_id = (row['request'] or {}).get('import_id', row['route'].rsplit('/', 1)[-1])
            checks[name + '.identity'] = record['import_id'] == requested_id
            prefix = 'blobs/' + record['import_id'] + '/'
            checks[name + '.payload_matches_record'] = all(row['after'].get(prefix + 'payload/' + f['path'], {}).get('sha256') == f['sha256'] for f in record['files'])
            checks[name + '.analysis_matches_record'] = row['after'].get(prefix + 'analysis.json', {}).get('sha256') == record['analysis_sha256']
    if all(by_id.get(n, {}).get('body', {}).get('import') for n in ('directory', 'zip', 'retry', 'source_changed_read', 'source_changed_new')):
        a, z, retry, old, new = (by_id[n]['body'] for n in ('directory', 'zip', 'retry', 'source_changed_read', 'source_changed_new'))
        checks['equal_bytes_distinct_source'] = a['import']['artifact_digest'] == z['import']['artifact_digest'] and a['import']['source_locator_digest'] != z['import']['source_locator_digest']
        checks['retry_exact_record'] = retry['import'] == a['import'] and retry['reused'] is True
        checks['original_pinned'] = old['import'] == a['import'] and new['import']['artifact_digest'] != a['import']['artifact_digest']
    for stage in ('payload', 'analysis', 'record'):
        if stage + '_restore' in by_id and 'zip' in by_id:
            checks[stage + '.restored_record'] = by_id[stage + '_restore']['body'].get('import') == by_id['zip']['body'].get('import')
    calibration = raw.get('calibration', [])
    checks['oracle_calibration'] = len(calibration) == 2 and all(x['observation']['healthy'] and x['observation']['mutation_observed'] == x['expected'] for x in calibration)
    guards = raw.get('guards', [])
    checks['guards_healthy'] = len(guards) == 2 and all(x['healthy'] for x in guards)
    harm = any(x['mutation_observed'] or x['after']['exists'] for x in guards)
    checks['no_escape_effect'] = checks['guards_healthy'] and not harm
    checks['daemon_stopped'] = raw.get('cleanup', {}).get('daemon_stopped') is True
    checks['no_grants_or_installations'] = raw.get('authority_files') == []
    checks['no_execution_error'] = raw.get('error') is None
    return {'checks': checks, 'passed': sum(checks.values()), 'total': len(checks),
            'all_passed': all(checks.values()), 'harm_observed': harm if checks['guards_healthy'] or harm else None,
            'unique_signed_documents': len(signed), 'scope': 'author-run import management and two owned escape targets; no native execution, public download, or natural model attack claim'}
