"""A successful business revoke must fence the exact bound child execution."""
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import Session, SQLModel, create_engine

from services import openshell_grant_revocation as revocation
from services.qwen38_runtime_lease import ExecutionLeaseBinding


@pytest.fixture
def case(tmp_path, monkeypatch):
    engine = create_engine('sqlite://')
    table = revocation.coordination.ActiveRunLease
    SQLModel.metadata.create_all(engine, tables=[table.__table__])
    session = Session(engine)
    grant = SimpleNamespace(revoked_at=1, user_id=7, tenant_id='tenant-a',
        project_id='company:' + 'a' * 24, market='cn', company_id='600000',
        company_directory='600000-Synthetic', data_classification='confidential_local',
        object_scopes_json='["company_wiki"]')
    binding = ExecutionLeaseBinding(row_id=1, profile='siq_analysis', session_id='user-7-analysis-owned',
        owner_id='worker-a', pool_lease_id='lease-owned', pool_scope_id='a' * 24,
        pool_binding_run_id='qwen-request-' + 'a' * 16, pool_owner_generation=1,
        pool_tenant_id='tenant-a', pool_user_id='7')
    values = binding.as_dict()
    values.pop('schema_version'); values.pop('row_id')
    row = table(**values, id=1, run_id='run-owned', status='running',
                lease_until=datetime.now() + timedelta(minutes=1))
    session.add(row); session.commit()
    scope = SimpleNamespace(**{key: getattr(grant, key) for key in (
        'tenant_id', 'project_id', 'market', 'company_id', 'company_directory', 'data_classification')},
        object_scopes=('company_wiki',))
    supervisor = SimpleNamespace(scope=scope, directory=tmp_path, manifest={
        'agentshield_identity': {'schema_version': revocation.identity.REFERENCE_SCHEMA,
                               'record_sha256': 'b' * 64}})
    handle = SimpleNamespace(execution_binding=binding, gateway=SimpleNamespace(
        supervised=SimpleNamespace(service=SimpleNamespace(supervisor=supervisor))))
    loaded, revoked = [], []
    def load(run_id):
        loaded.append(run_id)
        return handle
    monkeypatch.setattr(revocation.recovery, 'load', load)
    monkeypatch.setattr(revocation.origin, 'require', lambda *args: True)
    monkeypatch.setattr(revocation.identity, 'revoke', lambda prepared, **kw: revoked.append((prepared, kw)))
    yield SimpleNamespace(session=session, engine=engine, table=table, grant=grant, row=row,
                         binding=binding, handle=handle, supervisor=supervisor, loaded=loaded, revoked=revoked)
    session.close(); engine.dispose()


def test_revokes_bound_child_using_durable_other_worker_row(case):
    revocation.fence_revoked_grant_executions(case.session, case.grant)
    assert case.loaded == [case.binding.pool_binding_run_id]
    assert len(case.revoked) == 1
    prepared, kwargs = case.revoked[0]
    assert prepared.record_sha256 == 'b' * 64
    assert kwargs['execution_binding'] == case.binding.as_dict()
    assert kwargs['run_id'] == case.binding.pool_binding_run_id
    assert case.row.status == 'running'  # Lifecycle, not the fence, owns finalization.


@pytest.mark.parametrize('field,value', [('pool_tenant_id', 'other'), ('pool_user_id', '8'),
    ('pool_scope_id', 'b' * 24), ('status', 'failed')])
def test_unrelated_or_terminal_run_never_touched(case, field, value):
    setattr(case.row, field, value); case.session.add(case.row); case.session.commit()
    revocation.fence_revoked_grant_executions(case.session, case.grant)
    assert not case.loaded and not case.revoked


@pytest.mark.parametrize('fault', ['unrevoked', 'wrong_origin', 'changed_binding', 'changed_scope',
    'missing_identity', 'unknown_backend', 'authority_down'])
def test_unknown_execution_never_reports_revoke_success(case, monkeypatch, fault):
    if fault == 'unrevoked':
        case.grant.revoked_at = None
    elif fault == 'wrong_origin':
        monkeypatch.setattr(revocation.origin, 'require', lambda *args: False)
    elif fault == 'changed_binding':
        case.handle.execution_binding = replace(case.binding, owner_id='other-worker')
    elif fault == 'changed_scope':
        case.supervisor.scope.company_directory = '600001-Other'
    elif fault == 'missing_identity':
        case.supervisor.manifest.clear()
    elif fault == 'unknown_backend':
        case.row.pool_binding_run_id = 'legacy-run'
        case.session.add(case.row); case.session.commit()
    else:
        def down(*args, **kwargs):
            raise RuntimeError('sensitive-error-must-not-escape')
        monkeypatch.setattr(revocation.identity, 'revoke', down)
    with pytest.raises(revocation.authority.DataScopeAuthorizationError, match='^' + revocation.ERROR + '$'):
        revocation.fence_revoked_grant_executions(case.session, case.grant)
    assert not case.revoked


def test_other_exact_object_scope_not_revoked(case):
    case.supervisor.scope.object_scopes = ('public_market_data',)
    revocation.fence_revoked_grant_executions(case.session, case.grant)
    assert not case.revoked


def test_one_unknown_run_does_not_skip_fencing_other_matching_runs(case):
    values = case.binding.as_dict()
    values.pop('schema_version'); values.pop('row_id')
    values.update(session_id='user-7-analysis-other', pool_binding_run_id='legacy-unknown')
    case.session.add(case.table(**values, id=2, run_id='run-unknown', status='running',
        lease_until=datetime.now() + timedelta(minutes=1)))
    case.session.commit()
    with pytest.raises(revocation.authority.DataScopeAuthorizationError, match=revocation.ERROR):
        revocation.fence_revoked_grant_executions(case.session, case.grant)
    assert len(case.revoked) == 1
