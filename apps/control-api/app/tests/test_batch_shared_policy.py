"""Shared desired policy, independent per-target approvals and drift refusal."""

from uuid import uuid4

import pytest

from app.db import session_scope
from app.models import ChangeRequest, DesiredPolicy
from app.routers import deployment_submission as submissions
from app.routers.deployment_batch_draft import DraftRevalidate
from app.security import ROLE_PERMISSIONS, Identity
from app.tests.binding_helpers import make_binding
from app.tests.test_batch_execution import execute
from app.tests.test_batch_reservation import counts
from app.tests.test_change_review import approver, change
from app.tests.test_deployment_batch_draft import URL


def shared_draft(client, headers):
    # Each case owns its queue. Fake publish tasks must not fill the session-wide
    # enrollment fixture's legitimate ten-task claim window.
    environment = client.post("/api/v1/environments", headers=headers, json={
        "name": "shared-policy-" + uuid4().hex, "mode": "enforce", "env_type": "host",
    })
    assert environment.status_code == 201, environment.text
    env = environment.json()
    bindings = [make_binding(client, headers, env["id"], target="shared-" + uuid4().hex) for _ in range(2)]
    first, policy = change(client, headers, agent_ids=[item[1] for item in bindings], enforcement_mode="block")
    second = client.post("/api/v1/change-requests", headers=headers, json={
        "policy_id": policy["id"], "idempotency_key": uuid4().hex, "impact": {"purpose": "isolated second target"},
    })
    assert second.status_code == 201, second.text
    items = []
    for (binding, _, _), cr in zip(bindings, [first, second.json()], strict=True):
        result = client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(headers), json={})
        assert result.status_code == 200, result.text
        items.append({"schema_version": "deployment-preview-request/v1", "change_request_id": cr["id"],
                      "environment_id": env["id"], "binding_id": binding["id"]})
    result = client.post(URL, headers=headers, json={
        "schema_version": "enterprise-batch-draft-create/v1", "request_key": str(uuid4()), "items": items,
    })
    assert result.status_code == 201, result.text
    roles = frozenset(headers["X-Dev-Roles"].split(","))
    identity = Identity("user", headers["X-Dev-User-Id"], headers["X-Dev-Tenant-Id"], roles,
                        frozenset().union(*(ROLE_PERMISSIONS[role] for role in roles)))
    draft = result.json()
    confirmation = DraftRevalidate(schema_version="enterprise-batch-draft-revalidate/v1",
                                   preview_digest=draft["preview"]["preview_digest"])
    return draft, identity, confirmation, policy["id"]


@pytest.mark.parametrize("mutation", [None, "content", "approval"])
def test_shared_policy_keeps_independent_approvals_and_real_drift_checks(
    client, tenant_a, monkeypatch, mutation
):
    draft, identity, confirmation, policy_id = shared_draft(client, tenant_a)
    original = submissions._execute_new_reservation
    entered = []

    def stage(*args, **kwargs):
        result = original(*args, **kwargs)
        entered.append(result.deployment_id)
        if len(entered) == 1 and mutation:
            with session_scope() as session:
                if mutation == "content":
                    session.get(DesiredPolicy, policy_id).network = [{
                        "endpoint": "changed.example:443", "effect": "allow", "binary_paths": ["/usr/bin/curl"],
                    }]
                else:
                    next_change = draft["preview"]["items"][1]["change_id"]
                    session.get(ChangeRequest, next_change).status = "rejected"
        return result

    monkeypatch.setattr(submissions, "_execute_new_reservation", stage)
    before = counts()
    result = execute(draft, identity, confirmation)
    assert [item["deployment_status"] for item in result["items"]] == ["sent", "failed" if mutation else "sent"]
    assert counts()[3] - before[3] == (1 if mutation else 2)
    assert result["state"] == ("needs_attention" if mutation else "recorded")
    before = counts()
    assert execute(draft, identity, confirmation) == result
    assert len(entered) == 2 and counts() == before
