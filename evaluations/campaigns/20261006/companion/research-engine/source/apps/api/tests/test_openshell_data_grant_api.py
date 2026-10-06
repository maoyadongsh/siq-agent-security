from __future__ import annotations

import json

import anyio
import pytest
from database import get_session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routers import openshell_data_grants
from services.auth_dependencies import get_current_user
from services.auth_service import AuditLog, User, UserRole
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.ext.asyncio.session import AsyncSession

from services import openshell_data_scope, openshell_grant_revocation, runtime_coordination


def test_local_grant_api_requires_authenticated_user(monkeypatch):
    monkeypatch.setenv("SIQ_OPENSHELL_LOCAL_GRANT_ADMIN_ENABLED", "1")
    monkeypatch.setenv("SIQ_ENV", "development")
    app = FastAPI()
    app.include_router(openshell_data_grants.router, prefix="/api")
    response = TestClient(app).post(
        "/api/auth/openshell-data-grants/users/42",
        headers={"Idempotency-Key": "A" * 32},
        json={
            "project_id": "company:scope-600104",
            "market": "cn",
            "company_directory": "600104-上汽集团",
            "object_scopes": ["company_wiki"],
        },
    )
    assert response.status_code == 401


@pytest.mark.parametrize('fence_failure', [False, True])
def test_local_grant_api_is_opt_in_super_admin_only_audited_and_revocable(tmp_path, monkeypatch, fence_failure):
    db_path = tmp_path / "grant-api.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(
        engine,
        tables=[User.__table__, AuditLog.__table__, openshell_data_scope.OpenShellDataGrant.__table__,
                runtime_coordination.ActiveRunLease.__table__],
    )
    with Session(engine, expire_on_commit=False) as session:
        super_admin = User(
            username="superadmin", email="superadmin@example.test", hashed_password="unused",
            full_name="Super Admin", role=UserRole.SUPER_ADMIN,
        )
        admin = User(
            username="admin", email="admin@example.test", hashed_password="unused",
            full_name="Admin", role=UserRole.ADMIN,
        )
        analyst = User(
            username="analyst", email="analyst@example.test", hashed_password="unused",
            full_name="Analyst", role=UserRole.ANALYST,
        )
        session.add_all([super_admin, admin, analyst])
        session.commit()

    def override_session():
        with Session(engine) as session:
            yield session

    app = FastAPI()
    app.include_router(openshell_data_grants.router, prefix="/api")
    app.dependency_overrides[get_session] = override_session
    actor = super_admin
    app.dependency_overrides[get_current_user] = lambda: actor
    client = TestClient(app)
    payload = {
        "project_id": "company:scope-600104",
        "market": "cn",
        "company_directory": "600104-上汽集团",
        "object_scopes": ["company_wiki", "public_market_data"],
        "ttl_seconds": 900,
    }
    create_url = f"/api/auth/openshell-data-grants/users/{analyst.id}"
    headers = {"Idempotency-Key": "A" * 32}

    monkeypatch.delenv("SIQ_OPENSHELL_LOCAL_GRANT_ADMIN_ENABLED", raising=False)
    assert client.post(create_url, json=payload, headers=headers).status_code == 503
    monkeypatch.setenv("SIQ_OPENSHELL_LOCAL_GRANT_ADMIN_ENABLED", "1")
    monkeypatch.setenv("SIQ_ENV", "production")
    assert client.post(create_url, json=payload, headers=headers).status_code == 503
    monkeypatch.setenv("SIQ_ENV", "development")

    actor = admin
    assert client.post(create_url, json=payload, headers=headers).status_code == 403
    actor = super_admin
    assert client.post(
        f"/api/auth/openshell-data-grants/users/{super_admin.id}", json=payload,
        headers=headers,
    ).status_code == 403
    assert client.post(create_url, json={**payload, "tenant_id": "other"}, headers=headers).status_code == 422
    assert client.post(
        create_url, json={**payload, "company_directory": "../other"}, headers=headers
    ).status_code == 400

    created = client.post(create_url, json=payload, headers=headers)
    assert created.status_code == 200
    assert created.headers["Cache-Control"] == "no-store"
    grant_id = created.json()["grant_id"]
    assert isinstance(grant_id, int)
    retried = client.post(create_url, json=payload, headers=headers)
    assert retried.status_code == 200
    assert retried.json()["grant_id"] == grant_id
    assert client.post(
        create_url, json={**payload, "project_id": "company:other"}, headers=headers
    ).status_code == 409
    with Session(engine) as session:
        grant = session.get(openshell_data_scope.OpenShellDataGrant, grant_id)
        assert grant is not None
        assert grant.user_id == analyst.id
        assert grant.tenant_id == openshell_data_grants.DEFAULT_TENANT_ID
        assert grant.object_scopes_json == '["company_wiki","public_market_data"]'
        logs = session.exec(select(AuditLog)).all()
        assert len(logs) == 1
        assert logs[0].action == "GRANT_OPENSHELL_DATA"
        assert "上汽" not in (logs[0].details or "")
        assert set(json.loads(logs[0].details)) == {"scope_sha256", "expires_at"}
        session.add(
            openshell_data_scope.OpenShellDataGrant(
                user_id=grant.user_id,
                tenant_id=grant.tenant_id,
                project_id=grant.project_id,
                market=grant.market,
                company_id=grant.company_id,
                company_directory=grant.company_directory,
                data_classification=grant.data_classification,
                object_scopes_json=grant.object_scopes_json,
                user_token_version=grant.user_token_version,
                granted_by=grant.granted_by,
                request_key_sha256=grant.request_key_sha256,
                granted_at=grant.granted_at,
                expires_at=grant.expires_at,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    scope_ref = openshell_data_scope.issue_authorized_scope(
        tenant_id=openshell_data_grants.DEFAULT_TENANT_ID, user_id=str(analyst.id),
        project_id=payload["project_id"], market=payload["market"],
        company_directory=payload["company_directory"],
        data_classification="confidential_local",
        object_scopes=payload["object_scopes"],
    ).scope_ref

    async def check_live():
        async_engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        try:
            async with AsyncSession(async_engine) as session:
                await openshell_data_scope.require_live_confidential_scope(
                    session, scope_ref, user_id=str(analyst.id)
                )
        finally:
            await async_engine.dispose()

    anyio.run(check_live)
    if fence_failure:
        def unconfirmed(*args):
            raise openshell_data_scope.DataScopeAuthorizationError(openshell_grant_revocation.ERROR)
        with monkeypatch.context() as patch:
            patch.setattr(openshell_grant_revocation, 'fence_revoked_grant_executions', unconfirmed)
            failed = client.post(f"/api/auth/openshell-data-grants/{grant_id}/revoke")
            assert failed.status_code == 503
            assert failed.json()['detail'] == openshell_grant_revocation.ERROR
        with Session(engine) as session:
            assert session.get(openshell_data_scope.OpenShellDataGrant, grant_id).revoked_at is not None
    revoked = client.post(f"/api/auth/openshell-data-grants/{grant_id}/revoke")
    assert revoked.status_code == 200
    assert revoked.json() == {"grant_id": grant_id, "revoked": True}
    assert client.post(f"/api/auth/openshell-data-grants/{grant_id}/revoke").status_code == 200
    assert client.post(create_url, json=payload, headers=headers).json() == {
        "grant_id": grant_id, "expires_at": created.json()["expires_at"], "revoked": True
    }
    with Session(engine) as session:
        logs = session.exec(select(AuditLog)).all()
        assert [item.action for item in logs] == [
            "GRANT_OPENSHELL_DATA", "REVOKE_OPENSHELL_DATA"
        ]
    try:
        anyio.run(check_live)
    except openshell_data_scope.DataScopeAuthorizationError as exc:
        assert str(exc) == "data_scope_live_grant_denied"
    else:
        raise AssertionError("revoked grant must fail closed")
    engine.dispose()
