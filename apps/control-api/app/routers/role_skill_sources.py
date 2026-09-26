"""Historical, signed location comparison; no runtime or permission inference."""

import hashlib
import json
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.evidence_signing import canonical_json, verify_hex_signature
from app.framework_source import unique_fields
from app.framework_source_view import project_framework_sources
from app.models import (
    AgentAsset,
    EdgeAgent,
    EdgeTask,
    RoleConfigurationObservation,
    SkillInstallation,
    SkillUploadReceipt,
)
from app.role_skill_roots import parse_role_skill_roots
from app.routers.role_configuration_history import configuration_history_query, project_configuration_snapshot
from app.routers.skill_inventory import inventory_query, project_observation
from app.security import Identity, ensure_permission, get_identity
from app.skill_upload import SkillBatchIn

router = APIRouter(tags=['inventory'])


def verified_batch(receipt, task, edge, tenant_id):
    try:
        signed = receipt.signed_payload.encode('utf-8')
        if (len(signed) > 2 * 1024 * 1024 or receipt.tenant_id != tenant_id
                or receipt.edge_agent_id != edge.id or task.environment_id != edge.environment_id
                or task.task_type != 'skill_scan' or task.result_digest != receipt.batch_digest
                or hashlib.sha256(signed).hexdigest() != receipt.batch_digest
                or not verify_hex_signature(edge.public_key_pem, signed, receipt.signature)):
            return None
        raw = json.loads(signed, object_pairs_hook=unique_fields)
        if not isinstance(raw, dict) or 'signature' in raw:
            return None
        body = SkillBatchIn.model_validate({**raw, 'signature': receipt.signature})
        payload = task.payload
        if (body.task_id != receipt.task_id or task.id != receipt.task_id
                or payload.get('target_device_identity') != edge.device_identity
                or payload.get('connector') != 'directory' or payload.get('inventory_kind') != 'skills'
                or not isinstance(payload.get('scope'), dict)
                or hashlib.sha256(canonical_json(payload['scope'])).hexdigest() != body.scope_digest):
            return None
        return {item.locator_sha256: item for item in body.observations}
    except (ValueError, TypeError, AttributeError, RecursionError):
        return None


def matched_observation(item, observation):
    return (observation is not None and item.manifest_sha256 == observation.manifest_sha256
            and item.parser_version == observation.parser_version and item.parse_status == observation.parse_status
            and item.name == observation.name and item.allowed_tools_present == observation.allowed_tools_present
            and item.declared_tools == observation.declared_tools
            and item.observed_at.astimezone(UTC).replace(tzinfo=None) == observation.observed_at)


@router.get('/api/v1/agents/{asset_id}/skill-installation-sources')
def role_skill_sources(
    asset_id: str, response: Response,
    cursor: str | None = Query(default=None, pattern=r'^ski_[A-Za-z0-9_-]{1,60}$'),
    limit: int = Query(default=50, ge=1, le=100),
    identity: Identity = Depends(get_identity), session: Session = Depends(get_session),
):
    asset = session.scalar(select(AgentAsset).where(
        AgentAsset.id == asset_id, AgentAsset.tenant_id == identity.tenant_id))
    if asset is None:
        raise HTTPException(404, 'not_found')
    ensure_permission(identity, 'agent:read')
    ensure_permission(identity, 'env:read')
    response.headers['Cache-Control'] = 'no-store'
    source = project_framework_sources(session, identity.tenant_id, [asset])[asset.id]
    hermes = asset.framework == 'hermes'
    version = 'v2' if hermes else 'v1'
    result = {'schema_version': f'enterprise-role-skill-sources-view/{version}', 'asset_id': asset.id,
              'status': 'source_unavailable', 'framework_source': source, 'declared_roots': None,
              'coverage': 'page_of_device_installations', 'items': [], 'next_cursor': None,
              'runtime_status': 'unverified', 'effective_permissions': None}
    try:
        roots = parse_role_skill_roots((asset.attributes or {}).get('skill_source_roots'))
    except (ValueError, TypeError, AttributeError, RecursionError):
        return result
    if (source['status'] != 'historical_reported_source'
            or roots['status'] != ('layout_candidate' if hermes else 'declared')
            or roots['schema_version'] != f'enterprise-role-skill-roots/{version}'
            or source['schema_version'] != f'enterprise-framework-source-view/{version}'
            or source['source']['framework'] != ('hermes' if hermes else 'openclaw')):
        return result
    result.update(status='historical_comparison', declared_roots=roots)
    result.update(installation_source_page(session, identity, source['source']['device_id'], roots, cursor, limit))
    return result


def installation_source_page(session, identity, device_id, roots, cursor, limit):
    result = {'items': [], 'next_cursor': None}
    query = inventory_query(identity.tenant_id).where(EdgeAgent.id == device_id)
    if cursor is not None:
        query = query.where(SkillInstallation.id > cursor)
    rows = session.execute(query.order_by(SkillInstallation.id).limit(limit + 1)).all()
    page = rows[:limit]
    if len(rows) > limit:
        result['next_cursor'] = page[-1][0].id
    digests = {row[3].batch_digest for row in page if row[3] is not None}
    receipts = {}
    receipt_rows = session.execute(select(SkillUploadReceipt, EdgeTask).join(
        EdgeTask, EdgeTask.id == SkillUploadReceipt.task_id).where(
            SkillUploadReceipt.tenant_id == identity.tenant_id,
            SkillUploadReceipt.edge_agent_id == device_id,
            SkillUploadReceipt.batch_digest.in_(digests),
    ).limit(101)).all()
    # More than one receipt per possible page digest is corrupt/ambiguous.
    # Never accept the first slice of an unbounded result as uniquely verified.
    for receipt, task in receipt_rows if len(receipt_rows) <= 100 else []:
        receipts.setdefault(receipt.batch_digest, []).append((receipt, task))
    checked = {}
    for installation, edge, _, observation in page:
        projected = {'installation_id': installation.id, 'locator_sha256': installation.locator_sha256,
                     'relationship_status': 'unresolved', 'matched_sources': [], 'observation': None}
        result['items'].append(projected)
        if observation is None:
            continue
        digest = observation.batch_digest
        entries = receipts.get(digest, [])
        if len(entries) != 1:
            continue
        receipt, task = entries[0]
        if digest not in checked:
            checked[digest] = verified_batch(receipt, task, edge, identity.tenant_id)
        batch = checked[digest]
        item = batch.get(installation.locator_sha256) if batch is not None else None
        if (item is None or not item.ancestor_sha256 or observation.batch_signature != receipt.signature
                or not matched_observation(item, observation)):
            continue
        matches = [root for root in roots['roots'] if root['locator_sha256'] in item.ancestor_sha256]
        projected.update(relationship_status='historical_source_match' if matches else 'outside_declared_sources',
                         matched_sources=matches, observation=project_observation(observation))
    return result


@router.get('/api/v1/agents/{asset_id}/configuration-observations/{observation_id}/skill-installation-sources')
def snapshot_skill_sources(
    asset_id: str, observation_id: str, response: Response,
    cursor: str | None = Query(default=None, pattern=r'^ski_[A-Za-z0-9_-]{1,60}$'),
    limit: int = Query(default=50, ge=1, le=100),
    identity: Identity = Depends(get_identity), session: Session = Depends(get_session),
):
    asset = session.scalar(select(AgentAsset).where(
        AgentAsset.id == asset_id, AgentAsset.tenant_id == identity.tenant_id))
    if asset is None:
        raise HTTPException(404, 'not_found')
    row = session.execute(configuration_history_query(identity.tenant_id, asset_id).where(
        RoleConfigurationObservation.id == observation_id)).first()
    if row is None:
        raise HTTPException(404, 'not_found')
    ensure_permission(identity, 'agent:read')
    ensure_permission(identity, 'env:read')
    response.headers['Cache-Control'] = 'no-store'
    snapshot = project_configuration_snapshot(row, asset.framework)
    hermes = asset.framework == 'hermes'
    version = 'v2' if hermes else 'v1'
    result = {'schema_version': f'enterprise-role-skill-snapshot-comparison/{version}', 'asset_id': asset_id,
              'configuration_observation': snapshot, 'status': 'snapshot_unavailable',
              'comparison_basis': 'latest_skill_observations_against_saved_configuration',
              'coverage': 'page_of_device_installations', 'items': [], 'next_cursor': None,
              'runtime_status': 'unverified', 'effective_permissions': None}
    if snapshot['status'] != 'recorded_snapshot':
        return result
    roots = snapshot['configuration']['skill_source_roots']
    if roots is None or roots['status'] != ('layout_candidate' if hermes else 'declared'):
        return result
    result['status'] = 'historical_comparison'
    result.update(installation_source_page(session, identity, snapshot['device_id'], roots, cursor, limit))
    return result
