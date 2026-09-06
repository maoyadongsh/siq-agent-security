"""IAM JWT claims → 控制面 Identity（管理员 * / role_codes）。"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.security import Identity, _identity_from_claims


def test_refresh_token_type_rejected_on_resource_identity():
    with pytest.raises(HTTPException) as exc_info:
        _identity_from_claims(
            {
                "sub": "user-1",
                "tenant_id": "default",
                "type": "refresh",
                "permissions": ["*"],
            }
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "token_type_rejected"


def test_id_token_and_unknown_types_rejected():
    for typ in ("id_token", "offline", "foobar"):
        with pytest.raises(HTTPException) as exc_info:
            _identity_from_claims(
                {
                    "sub": "user-1",
                    "tenant_id": "default",
                    "type": typ,
                    "permissions": ["agent:read"],
                }
            )
        assert exc_info.value.detail == "token_type_rejected", typ


def test_missing_type_defaults_to_user():
    identity = _identity_from_claims(
        {"sub": "user-1", "tenant_id": "default", "permissions": ["agent:read"]}
    )
    assert identity.identity_type == "user"


def test_access_token_type_maps_to_user():
    identity = _identity_from_claims(
        {
            "sub": "user-1",
            "tenant_id": "default",
            "type": "access",
            "role_codes": ["viewer"],
            "permissions": [],
        }
    )
    assert identity.identity_type == "user"


def test_service_token_type_maps_to_service_without_role_inflation():
    identity = _identity_from_claims(
        {
            "sub": "svc-batch",
            "tenant_id": "default",
            "type": "service",
            "permissions": ["agent:read"],
            "role_codes": [],
        }
    )
    assert identity.identity_type == "service"
    assert identity.has_permission("agent:read")
    assert not identity.has_permission("env:manage")


def test_iam_admin_star_permission_is_wildcard():
    identity = _identity_from_claims(
        {
            "sub": "user-admin",
            "tenant_id": "default",
            "type": "access",
            "roles": ["rol_not_a_product_code"],
            "role_codes": ["admin"],
            "permissions": ["*"],
        }
    )
    assert identity.actor_id == "user-admin"
    assert identity.tenant_id == "default"
    assert identity.identity_type == "user"
    assert "admin" in identity.roles
    assert identity.has_permission("agent:read")
    assert identity.has_permission("env:manage")
    assert identity.has_permission("audit:read")
    assert "*" in identity.permissions


def test_role_codes_map_to_product_permissions_not_role_ids():
    identity = _identity_from_claims(
        {
            "sub": "user-viewer",
            "tenant_id": "default",
            "role_codes": ["viewer"],
            "roles": ["tenant_admin"],  # IAM 角色 id，不得当成产品角色码
            "permissions": [],
        }
    )
    assert identity.has_permission("agent:read")
    assert not identity.has_permission("env:manage")


def test_missing_tenant_is_unauthorized():
    with pytest.raises(HTTPException) as exc_info:
        _identity_from_claims({"sub": "user-1", "permissions": ["*"]})
    assert exc_info.value.status_code == 401


def test_identity_star_is_wildcard_without_claim_mapping():
    identity = Identity("user", "u1", "default", frozenset(), frozenset({"*"}))
    assert identity.has_permission("finding:manage")
