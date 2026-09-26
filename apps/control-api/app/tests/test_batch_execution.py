from datetime import UTC, datetime, timedelta

import pytest

from app import batch_execution as execution
from app.db import session_scope
from app.models import Deployment
from app.routers import deployment_batch_draft as drafts
from app.routers import deployment_submission as submissions
from app.tests.test_batch_reservation import counts, setup


def execute(draft, identity, confirmation):
    with session_scope() as session:
        return execution.execute_batch(draft["id"], confirmation, session, identity).model_dump()


def test_batch_executes_each_fresh_item_once_and_replays_only_read(client, tenant_a, env_a, monkeypatch):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    original = submissions._execute_new_reservation
    calls = []

    def tracked(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(submissions, "_execute_new_reservation", tracked)
    before = counts()
    result = execute(draft, identity, confirmation)
    assert result["state"] == "recorded"
    assert [item["deployment_status"] for item in result["items"]] == ["sent", "sent"]
    assert counts()[3] - before[3] == 2  # Fake backend tasks, not OpenShell effects.
    before = counts()
    assert execute(draft, identity, confirmation) == result
    assert len(calls) == 2 and counts() == before


@pytest.mark.parametrize("fail_index", [0, 1])
def test_unknown_current_effect_stops_later_item_without_replaying(client, tenant_a, env_a, monkeypatch, fail_index):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    calls = []
    original = submissions.execute_deployment

    def fail(*args, **kwargs):
        calls.append(True)
        if len(calls) == fail_index + 1:
            raise RuntimeError("synthetic ambiguous backend failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(submissions, "execute_deployment", fail)
    result = execute(draft, identity, confirmation)
    expected = ["pending", "failed"] if fail_index == 0 else ["sent", "pending"]
    assert [item["deployment_status"] for item in result["items"]] == expected
    assert result["state"] == "unconfirmed"
    with session_scope() as session:
        if fail_index == 0:
            skipped = session.get(Deployment, result["items"][1]["deployment_id"])
            assert skipped.verification["backend_mutated"] is False
        current = session.get(Deployment, result["items"][fail_index]["deployment_id"])
        assert current.verification is None
    before = counts()
    assert execute(draft, identity, confirmation) == result and len(calls) == fail_index + 1
    assert counts() == before


@pytest.mark.parametrize("during_preflight", [False, True])
def test_deadline_stops_before_effect_and_marks_known_unstarted_items(
    client, tenant_a, env_a, monkeypatch, during_preflight
):
    _, draft, identity, confirmation = setup(client, tenant_a, env_a)
    original = execution.reserve_batch

    def reserved(*args, **kwargs):
        result = original(*args, **kwargs)
        if during_preflight:
            monkeypatch.setattr(submissions, "_execution_now", lambda: datetime.now(UTC) + timedelta(days=1))
        else:
            monkeypatch.setattr(drafts, "_now", lambda: datetime.now(UTC) + timedelta(days=1))
        return result

    def never(*args, **kwargs):
        pytest.fail("expired batch must not execute backend effects")

    monkeypatch.setattr(execution, "reserve_batch", reserved)
    monkeypatch.setattr(submissions, "execute_deployment", never)
    result = execute(draft, identity, confirmation)
    assert result["state"] == "needs_attention"
    assert [item["deployment_status"] for item in result["items"]] == ["failed", "failed"]
    with session_scope() as session:
        assert all(session.get(Deployment, item["deployment_id"]).verification["backend_mutated"] is False
                   for item in result["items"])


def test_stop_audit_failure_preserves_uncertainty_and_never_replays(client, tenant_a, env_a, monkeypatch):
    from fastapi import HTTPException, Response

    _, draft, identity, confirmation = setup(client, tenant_a, env_a)

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(submissions, "execute_deployment", fail)
    monkeypatch.setattr(execution, "audit", fail)
    with pytest.raises(HTTPException) as error:
        execute(draft, identity, confirmation)
    assert error.value.detail == "batch_stop_unconfirmed"
    with session_scope() as session:
        result = execution.read_batch_reservation(draft["id"], Response(), session, identity).model_dump()
    assert [item["deployment_status"] for item in result["items"]] == ["pending", "pending"]
    before = counts()
    assert execute(draft, identity, confirmation) == result
    assert counts() == before
