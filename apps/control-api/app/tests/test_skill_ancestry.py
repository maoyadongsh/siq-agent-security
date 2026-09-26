import json

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import EdgeTask, SkillInstallation, SkillManifestObservation, SkillUploadReceipt
from app.tests.test_skill_upload import upload_case as upload_case


@pytest.mark.parametrize('case', ['valid', 'v1', 'absent', 'null', 'empty', 'duplicate', 'first', 'digest', 'limit'])
def test_signed_skill_ancestry_schema_and_storage(upload_case, case):
    body, upload, task_id, edge_id, _, _ = upload_case
    body['schema_version'] = 'enterprise-skill-upload/v2'
    item = body['observations'][0]
    item['ancestor_sha256'] = [item['locator_sha256'], 'c' * 64]
    if case == 'v1':
        body['schema_version'] = 'enterprise-skill-upload/v1'
    if case == 'absent':
        item.pop('ancestor_sha256')
    if case == 'null':
        item['ancestor_sha256'] = None
    if case == 'empty':
        item['ancestor_sha256'] = []
    if case == 'duplicate':
        item['ancestor_sha256'][1] = item['locator_sha256']
    if case == 'first':
        item['ancestor_sha256'][0] = 'd' * 64
    if case == 'digest':
        item['ancestor_sha256'][1] = '/fixture/private'
    if case == 'limit':
        item['ancestor_sha256'] = ['a' * 64] * 34
    response = upload(body)
    assert response.status_code == (200 if case == 'valid' else 422), response.text
    with session_scope() as session:
        receipt = session.get(SkillUploadReceipt, task_id)
        installs = list(session.scalars(select(SkillInstallation).where(SkillInstallation.edge_agent_id == edge_id)))
        if case == 'valid':
            assert json.loads(receipt.signed_payload)['observations'][0]['ancestor_sha256'] == item['ancestor_sha256']
            assert len(installs) == 1
            observations = list(session.scalars(select(SkillManifestObservation).where(
                SkillManifestObservation.installation_id == installs[0].id)))
            assert len(observations) == 1
            assert observations[0].batch_digest == receipt.batch_digest
            assert observations[0].manifest_sha256 == item['manifest_sha256']
        else:
            assert receipt is None and not installs
            assert session.get(EdgeTask, task_id).status == 'pending'
    if case == 'valid':
        assert upload(body).json()['idempotent']
        item['ancestor_sha256'] = [item['locator_sha256']]
        assert upload(body).status_code == 409
