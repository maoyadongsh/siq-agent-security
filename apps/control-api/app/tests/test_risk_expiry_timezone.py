"""Risk acceptance expiry is an instant, independent of its wire UTC offset."""
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import AuditEvent, Finding, OutboxEvent, Tenant
from app.worker import reap_expired_risk_acceptance


@pytest.mark.parametrize('minutes', [-480, -210, 0, 330, 480])
@pytest.mark.parametrize('delta_seconds', [-1, 0, 1])
def test_equivalent_expiry_instants_and_repeat_audit(client, monkeypatch, minutes, delta_seconds):
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    monkeypatch.setattr('app.worker.utcnow', lambda: now.replace(tzinfo=None))
    expires = now + timedelta(seconds=delta_seconds)
    encoded = expires.astimezone(timezone(timedelta(minutes=minutes))).isoformat()
    finding_id = 'tz-' + uuid4().hex
    tenant_id = 'risk-expiry-timezone-tests'
    with session_scope() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(Tenant(id=tenant_id, name='Timezone fixture'))
            session.flush()
        session.add(Finding(id=finding_id, tenant_id=tenant_id, rule_id='expiry-fixture',
                            severity='info', status='risk_accepted', owner_user_id='fixture-owner',
                            risk_acceptance={'reason': 'test', 'expires_at': encoded}))
    for _ in range(2):
        with session_scope() as session:
            reap_expired_risk_acceptance(session)
    expected = delta_seconds < 0
    with session_scope() as session:
        finding = session.get(Finding, finding_id)
        assert finding.status == ('open' if expected else 'risk_accepted')
        assert finding.risk_acceptance['expires_at'] == encoded
        audits = list(session.scalars(select(AuditEvent).where(
            AuditEvent.resource_id == finding_id, AuditEvent.action == 'finding.risk_acceptance.expired')))
        events = [x for x in session.scalars(select(OutboxEvent).where(OutboxEvent.tenant_id == tenant_id))
                  if x.payload.get('resource_ref') == finding_id]
        assert len(audits) == len(events) == int(expected)
        if expected:
            assert audits[0].actor_id == 'worker'
            assert events[0].event_type == 'agent.finding.reopened.v1'
