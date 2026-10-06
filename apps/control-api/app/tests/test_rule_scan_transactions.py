"""Partial multi-finding failure must roll back and permit a complete retry."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app import outbox
from app.db import session_scope
from app.models import AuditEvent, Finding, OutboxEvent, Tenant
from app.rules import RuleResult, upsert_findings


@pytest.mark.parametrize("fault", ["audit", "emit_event"])
def test_rule_scan_failure_rolls_back_all_scopes(client, monkeypatch, fault):
    tenant = "rule-atomic-" + uuid4().hex[:12]
    with session_scope() as session:
        session.add(Tenant(id=tenant, name=tenant))
    results = [
        RuleResult("atomic-fixture", "low", "governance", None, scope, [], "test", "test")
        for scope in ("scope-a", "scope-b")
    ]
    original = getattr(outbox, fault)
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("owned second-scope failure")
        return original(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(outbox, fault, fail_second)
        with pytest.raises(RuntimeError, match="owned second-scope failure"):
            with session_scope() as session:
                upsert_findings(session, tenant, results)
    with session_scope() as session:
        assert list(session.scalars(select(Finding).where(Finding.tenant_id == tenant))) == []
        assert list(session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant))) == []
        assert list(session.scalars(select(OutboxEvent).where(OutboxEvent.tenant_id == tenant))) == []
        assert upsert_findings(session, tenant, results) == {"created": 2, "updated": 0}
    with session_scope() as session:
        assert len(list(session.scalars(select(Finding).where(Finding.tenant_id == tenant)))) == 2
        assert len(list(session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant)))) == 2
        assert len(list(session.scalars(select(OutboxEvent).where(OutboxEvent.tenant_id == tenant)))) == 2
