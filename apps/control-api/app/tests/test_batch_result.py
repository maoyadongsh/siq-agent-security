from datetime import UTC, datetime, timedelta

import pytest

from app.db import session_scope
from app.models import Deployment, DeploymentBatchReservation, DeploymentSubmission
from app.routers import deployment_batch_draft as drafts
from app.tests.test_batch_reservation import counts, reserve, setup
from app.tests.test_deployment_batch_draft import URL


def read(client, headers, draft):
    return client.get(URL + "/" + draft["id"] + "/reservation", headers=headers)


@pytest.mark.parametrize("statuses,expected", [
    (["pending", "pending"], "unconfirmed"), (["failed", "pending"], "unconfirmed"),
    (["sent", "effective"], "recorded"), (["failed", "effective"], "needs_attention"),
    (["rolled_back", "failed"], "needs_attention"),
])
def test_read_only_aggregate_preserves_unknowns_and_per_item_status(
    client, tenant_a, env_a, monkeypatch, statuses, expected
):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    batch_id, fresh = reserve(draft, identity, confirmation)
    # Synthetic recorded outcomes, not backend execution or an enforcement test.
    with session_scope() as session:
        for (_, _, deployment_id), status in zip(fresh, statuses, strict=True):
            session.get(Deployment, deployment_id).status = status

    def never(*args, **kwargs):
        pytest.fail("result query must not run preflight or execute")

    monkeypatch.setattr(drafts, "prepare_batch", never)
    monkeypatch.setattr(drafts, "_now", lambda: datetime.now(UTC) + timedelta(days=1))
    before = counts()
    response = read(client, tenant_a, draft)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["id"] == batch_id and value["state"] == expected
    assert value["execution_supported"] is False
    assert [item["deployment_status"] for item in value["items"]] == statuses
    assert response.headers["cache-control"] == "no-store"
    assert read(client, tenant_a, draft).json() == value and counts() == before


def test_batch_result_authority_and_missing_reservation(client, tenant_a, tenant_b, env_a):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    response = read(client, tenant_a, draft)
    assert response.status_code == 404 and response.json()["detail"] == "batch_reservation_not_found"
    reserve(draft, identity, confirmation)
    before = counts()
    assert read(client, tenant_b, draft).status_code == 404
    assert read(client, {**tenant_a, "X-Dev-User-Id": "other"}, draft).status_code == 403
    assert read(client, {**tenant_a, "X-Dev-Roles": "viewer"}, draft).status_code == 403
    assert counts() == before


@pytest.mark.parametrize("mutation", ["duplicate", "reverse", "missing", "foreign", "target", "digest", "actor_digest"])
def test_inconsistent_references_refuse_entire_response(client, tenant_a, tenant_b, env_a, mutation):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    batch_id, fresh = reserve(draft, identity, confirmation)
    with session_scope() as session:
        batch = session.get(DeploymentBatchReservation, batch_id)
        submission = session.get(DeploymentSubmission, fresh[0][1])
        if mutation == "duplicate":
            batch.submission_ids = [fresh[0][1], fresh[0][1]]
        elif mutation == "reverse":
            batch.submission_ids = batch.submission_ids[::-1]
        elif mutation == "missing":
            batch.submission_ids = ["missing", fresh[1][1]]
        elif mutation == "foreign":
            submission.tenant_id = tenant_b["X-Dev-Tenant-Id"]
        elif mutation == "target":
            session.get(Deployment, fresh[0][2]).target = "unrelated"
        elif mutation == "digest":
            submission.preview_digest = "0" * 64
        else:
            submission.request_digest = "0" * 64
    before = counts()
    response = read(client, tenant_a, draft)
    assert response.status_code == 409 and response.json() == {"detail": "batch_reservation_inconsistent"}
    assert counts() == before
