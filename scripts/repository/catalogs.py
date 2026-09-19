"""Validate public indexes; unknown historical metadata never becomes a passing claim."""
import hashlib
import json
import re
from pathlib import Path

from check import require, safe_path


def evidence(root, item):
    require(re.fullmatch(r'[0-9a-f]{64}', item.get('sha256', '')), 'missing evidence SHA-256')
    path = safe_path(root, item['path'])
    require(path.is_file(), 'evidence must be a file')
    require(hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'],
            f'index evidence digest mismatch: {item["path"]}')
    return path


def unique(records):
    ids = [r['id'] for r in records]
    require(all(ids) and len(ids) == len(set(ids)), 'duplicate/empty catalog ID')


def literature(root, data):
    require(data['schema_version'] == 'siq-literature-catalog/v1', 'unknown literature schema')
    records = data['records']
    unique(records)
    paths = [r['path'] for r in records]
    require(len(paths) == len(set(paths)), 'duplicate literature file')
    for record in records:
        path = evidence(root, record)
        require(path.stat().st_size == record['bytes'], 'literature size mismatch')
        require(record['rights_status'] in ('not_reviewed', 'confirmed', 'restricted'), 'invalid rights status')
        if record['rights_status'] == 'confirmed':
            require(record.get('redistribution_basis'), 'rights confirmed without basis')
        require(record['reading_status'] in ('not_recorded', 'read', 'reviewed', 'reproduced'), 'invalid reading status')
        if record['reading_status'] != 'not_recorded':
            require(record.get('reading_record'), 'reading claim without record')
        if record['title_verified']:
            require(record['authors'] and record['year'] and record['source_url']
                    and record['source_checked_at'], 'verified metadata lacks source')
    return len(records)


def evaluations(root, data):
    require(data['schema_version'] == 'siq-evaluation-catalog/v1', 'unknown evaluation schema')
    unique(data['records'])
    for record in data['records']:
        require(record['kind'] in ('release-package', 'publication-readback', 'source-ci', 'engineering',
                                   'research', 'external-reproduction'), 'unknown evaluation kind')
        for key in ('relationship', 'implementation_candidate', 'environment', 'results', 'limits',
                    'failure_and_rerun_record', 'review_status', 'evidence'):
            require(record.get(key), f'missing {key}: {record["id"]}')
        candidate = record['implementation_candidate']
        require(candidate.get('identity') and candidate.get('dirty'), 'missing candidate identity')
        if candidate['source_sha'] is not None:
            require(re.fullmatch(r'[0-9a-f]{40}', candidate['source_sha']), 'source SHA must be full or null')
        for key in ('os', 'arch', 'host_mode', 'model_mode'):
            require(record['environment'].get(key), f'missing environment {key}')
        if record['kind'] == 'external-reproduction':
            require(record.get('independence_statement') and record.get('method_record'),
                    'external reproduction without independence/method record')
        metrics = set()
        for result in record['results']:
            require(result['metric'] not in metrics, 'duplicate result metric')
            metrics.add(result['metric'])
            require(type(result['value']) is int and type(result['total']) is int
                    and 0 <= result['value'] <= result['total'] and result['total'] > 0,
                    'invalid result denominator')
        paths = [evidence(root, item) for item in record['evidence']]
        # Counts with a machine-readable source are derived, not manually upgraded.
        for result in record['results']:
            metric = result['metric']
            if metric not in ('package_checks_passed', 'matching_remote_assets', 'successful_workflows'):
                continue
            docs = [json.loads(path.read_text()) for path in paths if path.suffix == '.json']
            if metric == 'package_checks_passed':
                doc = next(d for d in docs if 'checks' in d)
                expected = sum(c['passed'] is True for c in doc['checks']), len(doc['checks'])
            elif metric == 'matching_remote_assets':
                doc = next(d for d in docs if 'all_assets_equal_local_verified_candidate' in d)
                require(doc['all_assets_equal_local_verified_candidate'] is True, 'remote assets did not match')
                expected = len(doc['assets']), len(doc['assets'])
            else:
                doc = next(d for d in docs if 'runs' in d)
                expected = sum(r['conclusion'] == 'success' for r in doc['runs']), len(doc['runs'])
            require((result['value'], result['total']) == expected, 'result count disagrees with original evidence')
    return len(data['records'])


def validate(root):
    result = {}
    for name, validator in (('research/literature/catalog.json', literature), ('evaluations/catalog.json', evaluations)):
        path = Path(root) / name
        if path.exists():
            result[name] = validator(root, json.loads(path.read_text()))
    return result
