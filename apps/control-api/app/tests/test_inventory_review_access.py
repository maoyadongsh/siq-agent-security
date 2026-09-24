"""Verified candidate access and stale-review refusal; no UI-derived authority."""

import json
from pathlib import Path

import jsonschema
import pytest
from sqlalchemy import func, select

from app.db import session_scope
from app.models import AgentAsset, AuditEvent, OutboxEvent
from app.tests.test_inventory_hardening import _upload_candidate


def test_inventory_access_schema_and_readonly(client, tenant_a):
    result = client.get("/api/v1/inventory/access", headers=tenant_a)
    assert result.status_code == 200 and result.json()["can_confirm"]
    contract = Path(__file__).resolve().parents[4] / "packages/contracts/inventory-access.v1.schema.json"
    jsonschema.validate(result.json(), json.loads(contract.read_text()))
    viewer = {**tenant_a, "X-Dev-Roles": "viewer"}
    assert client.get("/api/v1/inventory/access", headers=viewer).json() == {
        "schema_version": "inventory-access/v1",
        "can_confirm": False,
        "can_discover": False,
        "can_manage_policy": False,
    }
    assert client.get("/api/v1/inventory/access", headers={**tenant_a, "X-Dev-Roles": "reviewer"}).status_code == 403


@pytest.mark.parametrize("action,body", [("confirm", {"role": "研究分析"}), ("dismiss", {"reason": "重复配置"})])
def test_candidate_action_tenant_before_permission(client, tenant_a, tenant_b, action, body):
    asset = _upload_candidate(client, tenant_a, f"review-boundary-{action}")
    viewer = {**tenant_a, "X-Dev-Roles": "viewer"}
    foreign = {**tenant_b, "X-Dev-Roles": "viewer"}
    path = f"/api/v1/candidates/{asset['id']}/{action}"
    assert client.post(path, headers=viewer, json=body).status_code == 403
    assert client.post(path, headers=foreign, json=body).status_code == 404
    assert client.get(f"/api/v1/agents/{asset['id']}", headers=tenant_a).json()["status"] == "candidate"


@pytest.mark.parametrize("state", ["confirmed", "managed", "stale", "retired", "dismissed"])
def test_dismiss_stale_candidate_rejected_without_audit(client, tenant_a, state):
    asset = _upload_candidate(client, tenant_a, f"review-stale-{state}")
    with session_scope() as session:
        session.get(AgentAsset, asset["id"]).status = state
    with session_scope() as session:
        before = (session.scalar(select(func.count(AuditEvent.id))), session.scalar(select(func.count(OutboxEvent.id))))
    response = client.post(f"/api/v1/candidates/{asset['id']}/dismiss", headers=tenant_a, json={"reason": "过时界面"})
    assert response.status_code == 409
    with session_scope() as session:
        assert session.get(AgentAsset, asset["id"]).status == state
        assert before == (
            session.scalar(select(func.count(AuditEvent.id))),
            session.scalar(select(func.count(OutboxEvent.id))),
        )


def test_review_actions_persist_and_second_action_refused(client, tenant_a):
    asset = _upload_candidate(client, tenant_a, "review-confirm")
    route = f"/api/v1/candidates/{asset['id']}"
    assert client.post(route + "/confirm", headers=tenant_a, json={"role": "研究分析"}).status_code == 200
    got = client.get(f"/api/v1/agents/{asset['id']}", headers=tenant_a).json()
    assert (got["status"], got["role"]) == ("confirmed", "研究分析")
    assert client.post(route + "/confirm", headers=tenant_a, json={}).status_code == 409
    other = _upload_candidate(client, tenant_a, "review-dismiss")
    path = f"/api/v1/candidates/{other['id']}/dismiss"
    assert client.post(path, headers=tenant_a, json={"reason": "不属于本次管理范围"}).status_code == 200
    assert client.post(path, headers=tenant_a, json={"reason": "重复"}).status_code == 409
    with session_scope() as session:
        for item, action in [(asset, "agent.confirm"), (other, "agent.dismiss")]:
            assert (
                session.scalar(
                    select(func.count(AuditEvent.id)).where(
                        AuditEvent.resource_id == item["id"], AuditEvent.action == action
                    )
                )
                == 1
            )
