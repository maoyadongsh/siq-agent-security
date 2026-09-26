"""Atomic multi-policy proposals; every child still requires independent approval."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ChangeRequest, DesiredPolicy
from app.routers.deployment_preview import Wire
from app.routers.network_revoke_proposals import Selection, digest, existing_result, stage_proposal
from app.security import Identity, ensure_permission, get_identity

router = APIRouter(tags=['policies'])


class BatchManifest(Wire):
    schema_version: Literal['network-revoke-batch-manifest/v1']
    policy_ids: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(min_length=1, max_length=20)
    batch_digest: str = Field(pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def canonical_ids(self):
        if self.policy_ids != sorted(set(self.policy_ids)):
            raise ValueError('noncanonical_ids')
        return self


def batch_key(identity, request_key, index):
    return 'nrb-' + digest([identity.tenant_id, str(request_key), index])


class BatchItem(Wire):
    policy_id: str = Field(min_length=1, max_length=64)
    baseline_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    selections: list[Selection] = Field(min_length=1, max_length=256)


class Batch(Wire):
    schema_version: Literal['enterprise-network-revoke-batch/v1']
    request_key: UUID
    items: list[BatchItem] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def bounded_unique(self):
        if len({item.policy_id for item in self.items}) != len(self.items):
            raise ValueError('duplicate_policy')
        if sum(len(item.selections) for item in self.items) > 512:
            raise ValueError('selection_budget_exceeded')
        return self


def response_value(items):
    return {'schema_version': 'enterprise-network-revoke-batch-result/v1', 'items': items,
            'requires_independent_approval': True, 'executed': False}


def read_existing(session, identity, entries):
    items = [existing_result(session, identity, entry['key'], entry['digest'], entry['source'].id)
             for entry in entries]
    if all(item is None for item in items):
        return None
    if any(item is None for item in items):
        raise HTTPException(409, 'network_revoke_batch_incomplete')
    return response_value(items)


@router.post('/api/v1/network-revoke-batches', status_code=201)
def propose_batch(body: Batch, response: Response, session: Session = Depends(get_session),
                  identity: Identity = Depends(get_identity)):
    ordered = sorted(body.items, key=lambda item: item.policy_id)
    sources = list(session.scalars(select(DesiredPolicy).where(
        DesiredPolicy.tenant_id == identity.tenant_id,
        DesiredPolicy.id.in_([item.policy_id for item in ordered]),
    ).order_by(DesiredPolicy.id).with_for_update()))
    if len(sources) != len(ordered):
        raise HTTPException(404, 'not_found')
    for permission in ('policy:read', 'policy:manage', 'change:propose'):
        ensure_permission(identity, permission)
    if len({source.name for source in sources}) != len(sources):
        raise HTTPException(422, 'network_revoke_batch_duplicate_policy_family')
    response.headers['Cache-Control'] = 'no-store'
    canonical = [{**item.model_dump(), 'selections': sorted(
        (selection.model_dump() for selection in item.selections),
        key=lambda selection: (selection['endpoint'], selection['binary_path']))} for item in ordered]
    batch_digest = digest([identity.tenant_id, identity.actor_id, identity.identity_type, canonical])
    entries = [{'source': source, 'input': item,
                # Ordinal keys detect reuse even when every source policy in the request changes.
                'key': batch_key(identity, body.request_key, index),
                'digest': digest([batch_digest, index])}
               for index, (source, item) in enumerate(zip(sources, canonical, strict=True))]
    saved = read_existing(session, identity, entries)
    if saved:
        return saved
    try:
        values = [stage_proposal(session, identity, entry['source'], entry['input']['baseline_digest'],
                                 entry['input']['selections'], entry['key'], entry['digest'])
                  for entry in entries]
        manifest = BatchManifest(schema_version='network-revoke-batch-manifest/v1',
                                 policy_ids=[source.id for source in sources], batch_digest=batch_digest)
        for value in values:
            cr = session.get(ChangeRequest, value['change_request_id'])
            cr.impact = {**cr.impact, 'batch_manifest': manifest.model_dump()}
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except IntegrityError:
        session.rollback()
        saved = read_existing(session, identity, entries)
        if saved:
            return saved
        raise HTTPException(409, 'network_revoke_batch_concurrent_change') from None
    except Exception:
        session.rollback()
        raise HTTPException(503, 'network_revoke_batch_unavailable') from None
    return response_value(values)


@router.get('/api/v1/network-revoke-batches/{request_key}')
def recover_batch(request_key: UUID, response: Response, session: Session = Depends(get_session),
                  identity: Identity = Depends(get_identity)):
    first = session.scalar(select(ChangeRequest).where(
        ChangeRequest.tenant_id == identity.tenant_id,
        ChangeRequest.idempotency_key == batch_key(identity, request_key, 0),
        ChangeRequest.proposer_user_id == identity.actor_id))
    if (first is None or not isinstance(first.impact, dict)
        or first.impact.get('proposal_actor_type') != identity.identity_type):
        raise HTTPException(404, 'not_found')
    try:
        manifest = BatchManifest.model_validate(first.impact.get('batch_manifest'), strict=True)
    except ValidationError:
        raise HTTPException(404, 'not_found') from None
    items = []
    for index, source_id in enumerate(manifest.policy_ids):
        cr = session.scalar(select(ChangeRequest).where(
            ChangeRequest.tenant_id == identity.tenant_id,
            ChangeRequest.idempotency_key == batch_key(identity, request_key, index),
            ChangeRequest.proposer_user_id == identity.actor_id))
        if (cr is None or not isinstance(cr.impact, dict)
            or cr.impact.get('proposal_actor_type') != identity.identity_type
            or cr.impact.get('source_policy_id') != source_id
            or cr.impact.get('batch_manifest') != manifest.model_dump()
            or cr.impact.get('network_revoke_request_digest') != digest([manifest.batch_digest, index])):
            raise HTTPException(404, 'not_found')
        visible = set(session.scalars(select(DesiredPolicy.id).where(
            DesiredPolicy.tenant_id == identity.tenant_id, DesiredPolicy.id.in_([source_id, cr.policy_id]))))
        if source_id == cr.policy_id or visible != {source_id, cr.policy_id}:
            raise HTTPException(404, 'not_found')
        items.append({'source_policy_id': source_id, 'policy_id': cr.policy_id,
                      'change_request_id': cr.id, 'change_status': cr.status})
    for permission in ('policy:read', 'policy:manage', 'change:propose'):
        ensure_permission(identity, permission)
    response.headers['Cache-Control'] = 'no-store'
    return {'schema_version': 'enterprise-network-revoke-batch-recovery/v1',
            'items': items, 'lookup_executed': False}
