"""Export only synthetic HTTP responses for the optional cross-language consumer check."""

import json
import os
from pathlib import Path

from app.tests.test_change_review import approver, decide, review
from app.tests.test_network_revoke_batches import request, submit
from app.tests.test_network_revoke_proposals import counts


def test_export_real_batch_responses(client, tenant_a, tmp_path):
    body = request(client, tenant_a)
    response = submit(client, tenant_a, body)
    assert response.status_code == 201, response.text
    cr = {'id': response.json()['items'][0]['change_request_id']}
    reviewer = approver(tenant_a)
    assert decide(client, reviewer, cr, review(client, reviewer, cr)).status_code == 200
    before = counts()
    recovered = client.get(f"/api/v1/network-revoke-batches/{body['request_key']}", headers=tenant_a)
    assert recovered.status_code == 200, recovered.text
    assert counts() == before
    value = {'scope': 'isolated-testclient-sqlite-development-identities',
             'request_key': body['request_key'], 'source_ids': [item['policy_id'] for item in body['items']],
             'proposal_response': response.json(), 'recovery_response': recovered.json()}
    # Explicit test-only output opt-in; never include identity headers or real configuration.
    output = Path(os.environ.get('SIQ_REVOKE_BATCH_WIRE_OUTPUT', str(tmp_path / 'revoke-wire.json')))
    with output.open('x') as stream:
        json.dump(value, stream)
    assert json.loads(output.read_text()) == value
