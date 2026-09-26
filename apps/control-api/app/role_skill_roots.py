"""Validate config-declared roots; never infer installation or runtime authority."""

import json
import re

from fastapi import HTTPException

from app.framework_source import parse_framework_source, unique_fields


def parse_role_skill_roots(raw):
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 2048:
        raise ValueError('size')
    value = json.loads(raw, object_pairs_hook=unique_fields)
    if not isinstance(value, dict) or set(value) != {'schema_version', 'basis', 'status', 'roots'}:
        raise ValueError('fields')
    if value['schema_version'] == 'enterprise-role-skill-roots/v2':
        roots = value['roots']
        if (value['basis'] != 'hermes_profile_layout' or value['status'] != 'layout_candidate'
                or not isinstance(roots, list) or len(roots) != 1):
            raise ValueError('layout')
        root = roots[0]
        if (not isinstance(root, dict) or set(root) != {'kind', 'locator_sha256'}
                or root['kind'] != 'profile_skills' or not isinstance(root['locator_sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', root['locator_sha256'])):
            raise ValueError('root')
        return value
    if (value['schema_version'] != 'enterprise-role-skill-roots/v1'
            or value['basis'] not in ('none', 'agent_workspace', 'default_workspace')
            or value['status'] not in ('declared', 'unresolved')
            or not isinstance(value['roots'], list)):
        raise ValueError('values')
    roots = value['roots']
    if value['status'] == 'unresolved':
        if roots:
            raise ValueError('unresolved')
        return value
    if value['basis'] == 'none' or len(roots) != 2:
        raise ValueError('roots')
    for root, kind in zip(roots, ('workspace_skills', 'project_agent_skills'), strict=True):
        if (not isinstance(root, dict) or set(root) != {'kind', 'locator_sha256'}
                or root['kind'] != kind or not isinstance(root['locator_sha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', root['locator_sha256'])):
            raise ValueError('root')
    if roots[0]['locator_sha256'] == roots[1]['locator_sha256']:
        raise ValueError('duplicate')
    return value


def validate_role_skill_roots(candidates):
    # Caller must validate framework_source and its evidence before this function.
    for candidate in candidates:
        attrs = candidate.attributes or {}
        if 'skill_source_roots' not in attrs:
            continue
        try:
            if 'framework_source' not in attrs:
                raise ValueError('source')
            source = parse_framework_source(attrs['framework_source'])
            roots = parse_role_skill_roots(attrs['skill_source_roots'])
            hermes = roots['schema_version'] == 'enterprise-role-skill-roots/v2'
            framework = 'hermes' if hermes else 'openclaw'
            if (candidate.framework != framework
                    or candidate.source_type != ('hermes_profile' if hermes else 'openclaw_agent')
                    or source['schema_version'] != f'enterprise-framework-source/{"v2" if hermes else "v1"}'
                    or source['framework'] != framework):
                raise ValueError('origin')
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(422, 'role_skill_roots_invalid') from None
