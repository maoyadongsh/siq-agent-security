"""Real API review decisions, object isolation, stale content and audit evidence."""

import json
import uuid
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, ChangeRequest, DesiredPolicy, OutboxEvent
from app.tests.test_policy_flow import _create_policy


def approver(headers):
    return {**headers, "X-Dev-User-Id": "review-e146", "X-Dev-Roles": "reviewer,viewer"}


def change(client, headers, **policy_kwargs):
    policy = _create_policy(client, headers, **policy_kwargs)
    r = client.post(
        "/api/v1/change-requests",
        headers=headers,
        json={
            "policy_id": policy["id"],
            "idempotency_key": uuid.uuid4().hex,
            "impact": {"purpose": "研究分析仅访问批准的数据服务"},
        },
    )
    assert r.status_code == 201
    return r.json(), policy


def review(client, headers, cr):
    r = client.get(f"/api/v1/change-requests/{cr['id']}/review", headers=headers)
    assert r.status_code == 200, r.text
    assert r.headers["Cache-Control"] == "no-store"
    return r.json()


def decide(client, headers, cr, snapshot, decision="approve"):
    return client.post(
        f"/api/v1/change-requests/{cr['id']}/review-decision",
        headers=headers,
        json={
            "schema_version": "change-review-decision/v1",
            "decision": decision,
            "review_digest": snapshot["review_digest"],
        },
    )


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_review_contract_and_persisted_decision(client, tenant_a, decision):
    cr, _ = change(client, tenant_a)
    headers = approver(tenant_a)
    snap = review(client, headers, cr)
    schema = Path(__file__).resolve().parents[4] / "packages/contracts/change-review.v1.schema.json"
    jsonschema.Draft202012Validator(json.loads(schema.read_text())).validate(snap)
    decision_schema = schema.with_name("change-review-decision.v1.schema.json")
    jsonschema.Draft202012Validator(json.loads(decision_schema.read_text())).validate(
        {
            "schema_version": "change-review-decision/v1",
            "decision": decision,
            "review_digest": snap["review_digest"],
        }
    )
    assert snap["can_approve"] and snap["can_reject"]
    assert len(snap["sections"]) == 15
    assert {s["key"] for s in snap["sections"]} >= {"selector", "network", "tool_policies", "secrets", "impact"}
    assert decide(client, headers, cr, snap, decision).status_code == 200
    result = review(client, headers, cr)
    assert result["status"] == ("approved" if decision == "approve" else "rejected")
    assert result["approver_id"] == headers["X-Dev-User-Id"]
    assert not result["can_approve"] and not result["can_reject"]
    assert decide(client, headers, cr, snap, decision).status_code == 409
    with session_scope() as session:
        events = list(
            session.scalars(
                select(AuditEvent).where(AuditEvent.resource_id == cr["id"], AuditEvent.action == f"change.{decision}")
            )
        )
        assert len(events) == 1
        assert events[0].summary["review_digest"] == snap["review_digest"]
        assert "研究分析" not in json.dumps(events[0].summary, ensure_ascii=False)
        outbox = list(session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "policy.change.approved.v1")))
        assert sum(
            e.payload.get("resource_ref") == cr["id"] or e.payload.get("change_request_id") == cr["id"] for e in outbox
        ) == (1 if decision == "approve" else 0)


def test_review_object_permissions_and_sod(client, tenant_a, tenant_b):
    cr, _ = change(client, tenant_a)
    own = review(client, tenant_a, cr)
    assert "own_proposal" in own["approve_blockers"]
    assert decide(client, tenant_a, cr, own).status_code == 409
    assert own["can_reject"]  # Retain existing own-rejection semantics.
    viewer = {**tenant_a, "X-Dev-Roles": "viewer"}
    readonly = review(client, viewer, cr)
    assert not readonly["can_approve"] and not readonly["can_reject"]
    assert decide(client, viewer, cr, readonly).status_code == 403
    no_read = {**tenant_a, "X-Dev-Roles": "reviewer"}
    assert client.get(f"/api/v1/change-requests/{cr['id']}/review", headers=no_read).status_code == 403
    for headers in [tenant_b, {**tenant_b, "X-Dev-Roles": "platform_operator"}]:
        assert client.get(f"/api/v1/change-requests/{cr['id']}/review", headers=headers).status_code == 404
        assert decide(client, headers, cr, own).status_code == 404
    assert client.get(f"/api/v1/change-requests/{cr['id']}/review").status_code == 401


@pytest.mark.parametrize("field", ["network", "impact", "approval_policy", "actor", "previous"])
def test_stale_review_cannot_apply(client, tenant_a, field):
    cr, policy = change(client, tenant_a)
    headers = approver(tenant_a)
    if field == "previous":
        with session_scope() as s:
            s.get(DesiredPolicy, policy["id"]).version = 2
            s.add(
                DesiredPolicy(
                    id="pol_" + uuid.uuid4().hex,
                    tenant_id="tnt-A",
                    name=policy["name"],
                    version=1,
                    selector={"agent_ids": ["agt_1"]},
                    enforcement_mode="audit_only",
                    status="validated",
                )
            )
            s.commit()
    snap = review(client, headers, cr)
    with session_scope() as s:
        if field == "network":
            s.get(DesiredPolicy, policy["id"]).network = [{"endpoint": "changed.example:443"}]
        elif field == "impact":
            s.get(ChangeRequest, cr["id"]).impact = {"purpose": "different task"}
        elif field == "approval_policy":
            s.get(ChangeRequest, cr["id"]).approval_policy = "high_risk"
        elif field == "previous":
            previous = s.scalar(
                select(DesiredPolicy).where(DesiredPolicy.name == policy["name"], DesiredPolicy.version == 1)
            )
            previous.enforcement_mode = "block"
        else:
            headers = {**headers, "X-Dev-User-Id": "another-reviewer"}
        s.commit()
    r = decide(client, headers, cr, snap)
    assert r.status_code == 409 and r.json()["detail"] == "review_changed"
    current = review(client, headers, cr)
    assert current["status"] == "proposed"
    if field == "previous":
        assert "downgrade_requires_high_risk" in current["approve_blockers"]
        assert decide(client, headers, cr, current).status_code == 409


@pytest.mark.parametrize(
    "value,flag",
    [
        ({"api_key": "fixture-secret-never-echo"}, "redacted"),
        ({"long": "x" * 6001}, "truncated"),
        ({"note": "sk-fixtureKnownSecret12345678"}, "redacted"),
        ({"entries": list(range(1002))}, "truncated"),
    ],
)
def test_incomplete_content_cannot_approve_but_can_reject(client, tenant_a, value, flag):
    cr, policy = change(client, tenant_a)
    with session_scope() as s:
        s.get(DesiredPolicy, policy["id"]).process = value
        s.commit()
    headers = approver(tenant_a)
    snap = review(client, headers, cr)
    section = next(s for s in snap["sections"] if s["key"] == "process")
    assert section[flag]
    assert "fixture-secret-never-echo" not in json.dumps(snap)
    assert "fixtureKnownSecret12345678" not in json.dumps(snap)
    assert "incomplete_content" in snap["approve_blockers"]
    assert decide(client, headers, cr, snap).status_code == 409
    assert decide(client, headers, cr, snap, "reject").status_code == 200


def test_token_budget_is_not_a_secret_and_deep_content_is_incomplete(client, tenant_a):
    cr, policy = change(client, tenant_a)
    headers = approver(tenant_a)
    with session_scope() as s:
        s.get(DesiredPolicy, policy["id"]).resources = {"max_tokens": 4096, "token_budget": 8000}
        s.commit()
    assert review(client, headers, cr)["can_approve"]
    nested = {}
    for _ in range(18):
        nested = {"item": nested}
    with session_scope() as s:
        s.get(DesiredPolicy, policy["id"]).process = nested
        s.commit()
    snap = review(client, headers, cr)
    assert "incomplete_content" in snap["approve_blockers"]
    assert decide(client, headers, cr, snap).status_code == 409


def test_review_rejects_invalid_policy(client, tenant_a):
    cr, policy = change(client, tenant_a)
    with session_scope() as s:
        s.get(DesiredPolicy, policy["id"]).selector = {}
        s.commit()
    headers = approver(tenant_a)
    snap = review(client, headers, cr)
    assert "policy_invalid" in snap["approve_blockers"]
    assert decide(client, headers, cr, snap).status_code == 409


def test_strict_decision_body_and_transaction_rollback(client, tenant_a, monkeypatch):
    cr, _ = change(client, tenant_a)
    headers = approver(tenant_a)
    snap = review(client, headers, cr)
    r = client.post(
        f"/api/v1/change-requests/{cr['id']}/review-decision",
        headers=headers,
        json={
            "schema_version": "change-review-decision/v1",
            "decision": "approve",
            "review_digest": snap["review_digest"],
            "tenant_id": "tnt-B",
        },
    )
    assert r.status_code == 422

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture audit unavailable")

    monkeypatch.setattr("app.routers.policies.audit", unavailable)
    with pytest.raises(RuntimeError, match="fixture audit unavailable"):
        decide(client, headers, cr, snap)
    assert review(client, headers, cr)["status"] == "proposed"
