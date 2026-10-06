"""Exercise account cleanup against an actual isolated local test database."""
import httpx
import pytest
from sqlmodel import Session, create_engine, select

from scripts.openshell.prove_research_daily_entry import disable_owned_account, response_summary
from services.auth_service import AuditLog, User


@pytest.fixture
def accounts(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'accounts.db'))
    User.__table__.create(engine)
    AuditLog.__table__.create(engine)
    with Session(engine) as session:
        for name, batch in [('owned', 'daily-001'), ('unrelated', 'different')]:
            session.add(User(username=name, email=name + '@example.org', hashed_password='fixture',
                full_name=name, approval_note=batch, is_active=True, token_version=3))
        session.commit()
        ids = {u.username: u.id for u in session.exec(select(User)).all()}
    yield engine, ids
    engine.dispose()


def test_cleanup_disables_only_bound_user_and_records_audit(accounts):
    engine, ids = accounts
    disable_owned_account(engine, ids['owned'], 'owned', 'daily-001')
    with Session(engine) as session:
        owned = session.get(User, ids['owned'])
        other = session.get(User, ids['unrelated'])
        assert not owned.is_active and owned.token_version == 4
        assert other.is_active and other.token_version == 3
        audit = session.exec(select(AuditLog)).one()
        assert audit.user_id == owned.id and audit.action == 'EVALUATION_ACCOUNT_DISABLED'


@pytest.mark.parametrize('username,batch', [('unrelated', 'daily-001'), ('owned', 'different')])
def test_cleanup_mismatched_identity_never_changes_user(accounts, username, batch):
    engine, ids = accounts
    with pytest.raises(RuntimeError, match='identity_changed'):
        disable_owned_account(engine, ids['owned'], username, batch)
    with Session(engine) as session:
        assert all(u.is_active and u.token_version == 3 for u in session.exec(select(User)))
        assert not session.exec(select(AuditLog)).all()


def test_public_response_projection_omits_response_text():
    response = httpx.Response(403, json={'detail': 'hermes_runtime_request_override_forbidden private-fixture'})
    summary = response_summary(response, 'MARKER')
    assert summary['categorical_errors'] == ['hermes_runtime_request_override_forbidden']
    assert 'private-fixture' not in str(summary)
