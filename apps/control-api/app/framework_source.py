"""Validate reported config-instance provenance, never runtime or skill authority."""

import json
import re

from fastapi import HTTPException


def unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate')
        value[key] = item
    return value


def parse_framework_source(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 2048:
        raise ValueError('size')
    value = json.loads(raw, object_pairs_hook=unique_fields)
    if not isinstance(value, dict) or set(value) != {
        'schema_version', 'framework', 'instance_key', 'config_sha256', 'evidence_id',
    } or not all(isinstance(item, str) for item in value.values()):
        raise ValueError('fields')
    if ((value['schema_version'], value['framework']) not in (
            ('enterprise-framework-source/v1', 'openclaw'),
            ('enterprise-framework-source/v2', 'hermes'))
            or not re.fullmatch(r'[a-f0-9]{64}', value['instance_key'])
            or not re.fullmatch(r'[a-f0-9]{64}', value['config_sha256'])):
        raise ValueError('origin')
    return value


def validate_framework_sources(candidates, evidence, task):
    if any('framework_source' in (candidate.attributes or {}) for candidate in candidates):
        locations = [(candidate.source_type, candidate.source_locator) for candidate in candidates]
        if len(set(locations)) != len(locations):
            raise HTTPException(422, 'framework_source_duplicate_asset')
    for candidate in candidates:
        attrs = candidate.attributes or {}
        if 'framework_source' not in attrs:
            continue
        try:
            value = parse_framework_source(attrs['framework_source'])
            framework = value['framework']
            hermes = framework == 'hermes'
            source_type = 'hermes_profile' if hermes else 'openclaw_agent'
            collection = 'profiles' if hermes else 'agents'
            locator_pattern = fr'{framework}://{collection}/v2/[a-f0-9]{{64}}'
            if (candidate.framework != framework
                    or candidate.source_type != source_type or task.payload.get('connector') != framework
                    or not re.fullmatch(locator_pattern, candidate.source_locator or '')
                    or candidate.candidate_id != framework + ':v2:' + candidate.source_locator.rsplit('/', 1)[-1]
                    or (hermes and value['instance_key'] != candidate.source_locator.rsplit('/', 1)[-1])):
                raise ValueError('origin')
            refs = [item for item in evidence if item.evidence_id == value['evidence_id']]
            if (value['evidence_id'] not in candidate.evidence_ids or len(refs) != 1
                    or refs[0].source_type != ('manifest' if hermes else 'openclaw_config')
                    or refs[0].subject_ref != candidate.candidate_id
                    or refs[0].content_hash != value['config_sha256']
                    or (hermes and refs[0].source_locator != value['instance_key'] + '/config.yaml')):
                raise ValueError('evidence')
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(422, 'framework_source_invalid') from None
