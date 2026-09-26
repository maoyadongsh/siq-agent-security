"""Bounded shared provenance projection for detail and inventory consumers."""
import re

from sqlalchemy import select, tuple_

from app.framework_source import parse_framework_source
from app.models import EdgeAgent, Environment, Evidence


def project_framework_sources(session, tenant_id, assets):
    if len(assets) > 100 or any(asset.tenant_id != tenant_id for asset in assets):
        raise ValueError('framework_projection_scope_invalid')
    devices = {edge.id: (edge, environment) for edge, environment in session.execute(
        select(EdgeAgent, Environment).join(Environment, EdgeAgent.environment_id == Environment.id)
        .where(EdgeAgent.id.in_([asset.discovery_scope for asset in assets]), Environment.tenant_id == tenant_id)
    )} if assets else {}
    results, pending = {}, {}
    for asset in assets:
        hermes = asset.framework == 'hermes'
        version = 'v2' if hermes else 'v1'
        result = {'schema_version': f'enterprise-framework-source-view/{version}', 'asset_id': asset.id,
                  'status': 'no_recorded_source', 'source': None, 'runtime_status': 'unverified',
                  'skill_relationship_status': 'unresolved', 'effective_permissions': None}
        results[asset.id] = result
        attrs = asset.attributes if isinstance(asset.attributes, dict) else {}
        if 'framework_source' not in attrs:
            continue
        result['status'] = 'source_unavailable'
        try:
            source = parse_framework_source(attrs['framework_source'])
        except (ValueError, TypeError, RecursionError):
            continue
        framework = 'hermes' if hermes else 'openclaw'
        collection = 'profiles' if hermes else 'agents'
        if (asset.framework != framework or source['framework'] != framework
                or asset.source_type != ('hermes_profile' if hermes else 'openclaw_agent')
                or not re.fullmatch(fr'{framework}://{collection}/v2/[a-f0-9]{{64}}', asset.source_locator or '')
                or (hermes and source['instance_key'] != asset.source_locator.rsplit('/', 1)[-1])
                or source['evidence_id'] not in (asset.evidence_ids or [])
                or asset.discovery_scope not in devices):
            continue
        edge, environment = devices[asset.discovery_scope]
        key = (environment.id, edge.device_identity, source['evidence_id'], source['config_sha256'],
               framework + ':v2:' + asset.source_locator.rsplit('/', 1)[-1],
               'manifest' if hermes else 'openclaw_config')
        pending[asset.id] = (key, source, edge, environment)
    observations = {}
    if pending:
        keys = list({value[0] for value in pending.values()})
        rows = session.scalars(select(Evidence).where(
            Evidence.tenant_id == tenant_id,
            tuple_(Evidence.environment_id, Evidence.collector_id, Evidence.evidence_id,
                   Evidence.content_hash, Evidence.subject_ref, Evidence.source_type).in_(keys),
        ).limit(201))
        for row in rows:
            key = (row.environment_id, row.collector_id, row.evidence_id,
                   row.content_hash, row.subject_ref, row.source_type)
            observations.setdefault(key, []).append(row)
    for asset_id, (key, source, edge, environment) in pending.items():
        matching = observations.get(key, [])
        if len(matching) != 1:
            continue
        evidence = matching[0]
        if source['framework'] == 'hermes' and evidence.source_locator != source['instance_key'] + '/config.yaml':
            continue
        results[asset_id]['status'] = 'historical_reported_source'
        results[asset_id]['source'] = {
            'framework': source['framework'], 'instance_key': source['instance_key'],
            'environment_id': environment.id, 'device_id': edge.id, 'device_revoked': edge.revoked_at is not None,
            'config_sha256': source['config_sha256'], 'evidence_id': evidence.evidence_id,
            'observation_id': evidence.id, 'observed_at': evidence.observed_at.isoformat() + 'Z',
        }
    return results
