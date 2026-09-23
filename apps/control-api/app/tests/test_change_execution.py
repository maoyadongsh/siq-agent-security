"""Exact history, permission boundaries, truthful evidence and audit correlation."""

import json
import uuid
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AuditEvent, Deployment, utcnow
from app.tests.binding_helpers import make_binding
from app.tests.test_change_review import approver, change


def get_execution(client, headers, cr, suffix=""):
    response = client.get(f"/api/v1/change-requests/{cr['id']}/execution{suffix}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


def seed_deployment(cr, env_id, **kwargs):
    with session_scope() as session:
        row = Deployment(
            id="dep_" + uuid.uuid4().hex,
            tenant_id="tnt-A",
            environment_id=env_id,
            change_request_id=cr["id"],
            target="fixture-sandbox",
            to_revision="policy-1",
            **kwargs,
        )
        session.add(row)
        session.commit()
        return row.id


def test_real_fake_deployment_and_audit_are_exact_and_read_only(client, tenant_a, env_a):
    binding, asset_id, _ = make_binding(client, tenant_a, env_a["id"])
    cr, _ = change(client, tenant_a, agent_ids=[asset_id])
    assert (
        client.post(f"/api/v1/change-requests/{cr['id']}/approve", headers=approver(tenant_a), json={}).status_code
        == 200
    )
    dep = client.post(
        "/api/v1/deployments",
        headers=tenant_a,
        json={"change_request_id": cr["id"], "environment_id": env_a["id"], "binding_id": binding["id"]},
    )
    assert dep.status_code == 201
    headers = {**tenant_a, "X-Dev-Roles": tenant_a["X-Dev-Roles"] + ",auditor"}
    with session_scope() as session:
        count_before = session.scalar(select(func.count()).select_from(AuditEvent))
    result = get_execution(client, headers, cr)
    schema = Path(__file__).resolve().parents[4] / "packages/contracts/change-execution.v1.schema.json"
    jsonschema.Draft202012Validator(json.loads(schema.read_text()), format_checker=jsonschema.FormatChecker()).validate(
        result
    )
    assert result["change_status"] == "deploying"
    assert len(result["deployments"]) == 1
    record = result["deployments"][0]
    assert record["id"] == dep.json()["id"]
    assert record["status"] == "sent" and record["verification_level"] == "none"
    assert record["environment_name"] == env_a["name"]
    assert record["created_at"].endswith("Z")
    event = next(e for e in result["audit_events"] if e["action"] == "deployment.create")
    assert event["resource_id"] == record["id"]
    assert result["evaluated_at"].endswith("Z")
    with session_scope() as session:
        assert session.scalar(select(func.count()).select_from(AuditEvent)) == count_before


def test_permissions_and_cross_tenant_history(client, tenant_a, tenant_b, env_a):
    cr, _ = change(client, tenant_a)
    seed_deployment(cr, env_a["id"])
    viewer = {**tenant_a, "X-Dev-Roles": "viewer"}
    result = get_execution(client, viewer, cr)
    assert result["audit_access"] == "denied" and result["audit_events"] == [] and not result["audit_truncated"]
    assert result["deployments"][0]["environment_name"] is None
    path = f"/api/v1/change-requests/{cr['id']}/execution"
    assert client.get(path, headers={**tenant_a, "X-Dev-Roles": "platform_operator"}).status_code == 403
    assert client.get(path, headers=tenant_b).status_code == 404
    assert client.get(path).status_code == 401


def test_older_exact_record_not_lost_behind_global_first_page(client, tenant_a, env_a):
    cr, _ = change(client, tenant_a)
    other, _ = change(client, tenant_a)
    target = seed_deployment(cr, env_a["id"], created_at=utcnow() - timedelta(days=7))
    for _ in range(55):
        seed_deployment(other, env_a["id"])
    assert [d["id"] for d in get_execution(client, tenant_a, cr)["deployments"]] == [target]


def test_bounds_and_foreign_or_unbound_audit_not_guessed(client, tenant_a, env_a):
    cr, _ = change(client, tenant_a)
    ids = [seed_deployment(cr, env_a["id"]) for _ in range(22)]
    with session_scope() as s:
        for _ in range(52):
            s.add(
                AuditEvent(
                    tenant_id="tnt-A",
                    actor_type="user",
                    actor_id="fixture-reviewer",
                    action="deployment.verify",
                    resource_type="deployment",
                    resource_id=ids[0],
                    decision="allow",
                    summary={"raw": "fixture-never-export"},
                )
            )
        for tenant, resource_type, rid in [
            ("tnt-B", "deployment", ids[0]),
            ("tnt-A", "deployment", None),
            ("tnt-A", "agent_asset", cr["id"]),
        ]:
            s.add(
                AuditEvent(
                    tenant_id=tenant,
                    actor_type="user",
                    actor_id="fixture-excluded",
                    action="deployment.create",
                    resource_type=resource_type,
                    resource_id=rid,
                    decision="allow",
                )
            )
        s.commit()
    headers = {**tenant_a, "X-Dev-Roles": "auditor"}
    result = get_execution(client, headers, cr)
    assert len(result["deployments"]) == 20 and result["deployments_truncated"]
    assert len(result["audit_events"]) == 50 and result["audit_truncated"]
    expanded = get_execution(client, headers, cr, "?expanded=true")
    assert len(expanded["deployments"]) == 22 and not expanded["deployments_truncated"]
    assert len(expanded["audit_events"]) == 53 and not expanded["audit_truncated"]  # proposal + 52 exact events
    assert "fixture-excluded" not in json.dumps(expanded)
    assert "fixture-never-export" not in json.dumps(expanded)


@pytest.mark.parametrize(
    "verification,level,independent",
    [
        (
            {"level": "readback_verified", "independent_attestation": {"result": "mismatch"}},
            "config_readback",
            "mismatch",
        ),
        ({"level": "readback_verified", "expired": True}, "stale", "not_checked"),
        ({"level": {"unexpected": "fixture-secret"}}, "none", "not_checked"),
        ({"level": "fixture-secret"}, "unknown", "not_checked"),
    ],
)
def test_only_bounded_evidence_projection(client, tenant_a, env_a, verification, level, independent):
    cr, _ = change(client, tenant_a)
    seed_deployment(
        cr,
        env_a["id"],
        status="failed",
        verification={
            **verification,
            "raw_error": "fixture-secret",
            "backend_mutated": True,
            "apply_failed": {"error_digest": "a" * 64},
        },
        receipt={"raw_secret": "fixture-secret"},
    )
    result = get_execution(client, tenant_a, cr)
    row = result["deployments"][0]
    assert row["verification_level"] == level and row["independent_result"] == independent
    assert row["status"] == "failed" and row["backend_mutated"] and row["error_digest"] == "a" * 64
    assert "fixture-secret" not in json.dumps(result)
