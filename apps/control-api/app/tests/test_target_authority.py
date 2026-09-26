import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models import RuntimeBinding
from app.target_authority import MAX_BYTES, TargetAuthorityError, authorize_runtime_target

NOW = datetime(2026, 9, 25, 12, tzinfo=UTC)


@pytest.fixture
def authority(tmp_path, monkeypatch):
    path = tmp_path / "authority.json"
    item = dict(id="assignment-a", tenant_id="tenant-a", environment_id="env-a", asset_id="asset-a",
                agent_instance_id="instance-a", endpoint_fingerprint="a" * 64, gateway_name_sha256="b" * 64,
                backend_target_id="sandbox-a")
    catalog = {"schema_version": "enterprise-runtime-target-authority/v1",
               "issued_at": "2026-09-25T00:00:00Z", "expires_at": "2026-09-26T00:00:00Z", "assignments": [item]}
    binding = RuntimeBinding(tenant_id="tenant-a", environment_id="env-a", asset_id="asset-a",
                             agent_instance_id="instance-a", backend="openshell-cli", backend_target_id="sandbox-a")
    monkeypatch.setenv("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE", str(path))

    def save():
        path.write_text(json.dumps(catalog))
        path.chmod(0o600)

    save()
    return path, catalog, binding, save


def authorize(binding, **kwargs):
    return authorize_runtime_target(binding, "tenant-a", "a" * 64, "b" * 64, now=NOW, **kwargs)


def test_exact_assignment_digest_no_other_tenant_projection(authority):
    _, catalog, binding, save = authority
    catalog["assignments"].append({**catalog["assignments"][0], "id": "private-other-assignment",
                                   "tenant_id": "tenant-b", "backend_target_id": "sandbox-b"})
    save()
    result = authorize(binding)
    assert result["assignment_id"] == "assignment-a" and len(result["authority_sha256"]) == 64
    assert "private-other" not in str(result) and "tenant-b" not in str(result)
    assert result["expires_at"] == "2026-09-26T00:00:00Z"


@pytest.mark.parametrize("field", ["tenant_id", "environment_id", "asset_id", "agent_instance_id", "backend_target_id"])
def test_partial_match_never_authorizes(authority, field):
    _, _, binding, _ = authority
    setattr(binding, field, "different")
    with pytest.raises(TargetAuthorityError, match="^target_authority_unassigned$"):
        authorize(binding)


@pytest.mark.parametrize("endpoint,gateway", [("c" * 64, "b" * 64), ("a" * 64, "c" * 64)])
def test_gateway_context_drift_denied(authority, endpoint, gateway):
    _, _, binding, _ = authority
    with pytest.raises(TargetAuthorityError, match="unassigned"):
        authorize_runtime_target(binding, "tenant-a", endpoint, gateway, now=NOW)


def test_removal_and_replacement_do_not_reuse_cached_authority(authority):
    _, catalog, binding, save = authority
    initial = authorize(binding)
    catalog["expires_at"] = "2026-09-26T01:00:00Z"
    save()
    assert authorize(binding)["authority_sha256"] != initial["authority_sha256"]
    catalog["assignments"] = []
    save()
    with pytest.raises(TargetAuthorityError, match="unassigned"):
        authorize(binding)


@pytest.mark.parametrize("fault", [
    "expired", "future", "naive", "timezone", "duplicate_id", "shared", "wildcard", "extra", "version",
])
def test_invalid_or_ambiguous_catalog_rejected(authority, fault):
    _, catalog, binding, save = authority
    if fault == "expired":
        catalog["expires_at"] = "2026-09-25T12:00:00Z"
    elif fault == "future":
        catalog["issued_at"] = "2026-09-25T13:00:00Z"
    elif fault == "naive":
        catalog["issued_at"] = "2026-09-25T00:00:00"
    elif fault == "timezone":
        catalog["issued_at"] = "2026-09-25T01:00:00+01:00"
    elif fault in ("duplicate_id", "shared"):
        other = {**catalog["assignments"][0], "tenant_id": "tenant-b"}
        if fault == "shared":
            other["id"] = "other"
        else:
            other["backend_target_id"] = "other-target"
        catalog["assignments"].append(other)
    elif fault == "wildcard":
        catalog["assignments"][0]["backend_target_id"] = "*"
    elif fault == "extra":
        catalog["private-diagnostic-marker"] = "must-not-echo"
    else:
        catalog["schema_version"] = "unknown"
    save()
    with pytest.raises(TargetAuthorityError) as failure:
        authorize(binding)
    assert str(failure.value) in {"target_authority_expired", "target_authority_invalid"}


@pytest.mark.parametrize("fault", [
    "symlink", "ancestor_symlink", "hardlink", "writable", "oversize", "fifo", "duplicate_key", "bad_utf8",
])
def test_file_boundary_fails_closed(authority, tmp_path, monkeypatch, fault):
    path, _, binding, _ = authority
    if fault == "symlink":
        link = tmp_path / "linked"
        link.symlink_to(path)
        monkeypatch.setenv("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE", str(link))
    elif fault == "ancestor_symlink":
        link = tmp_path / "directory-link"
        link.symlink_to(tmp_path, target_is_directory=True)
        monkeypatch.setenv("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE", str(link / path.name))
    elif fault == "hardlink":
        os.link(path, tmp_path / "other")
    elif fault == "writable":
        path.chmod(0o666)
    elif fault == "oversize":
        path.write_bytes(b" " * (MAX_BYTES + 1))
    elif fault == "fifo":
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo)
        monkeypatch.setenv("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE", str(fifo))
    elif fault == "duplicate_key":
        path.write_text('{"assignments":[],"assignments":[]}')
    else:
        path.write_bytes(b"\xff")
    with pytest.raises(TargetAuthorityError) as failure:
        authorize(binding)
    assert str(tmp_path) not in str(failure.value)


def test_missing_configuration_has_no_fallback(authority, monkeypatch):
    _, _, binding, _ = authority
    monkeypatch.delenv("SIQ_AS_OPENSHELL_TARGET_AUTHORITY_FILE")
    with pytest.raises(TargetAuthorityError, match="unconfigured"):
        authorize(binding)


@pytest.mark.parametrize("fault", ["foreign_owner", "changed_during_read"])
def test_owner_and_stability_checked_on_descriptor(authority, monkeypatch, fault):
    _, _, binding, _ = authority
    original = os.fstat
    count = 0

    def fstat(fd):
        nonlocal count
        count += 1
        info = original(fd)
        fields = {name: getattr(info, name) for name in (
            "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode", "st_uid", "st_nlink",
        )}
        if fault == "foreign_owner":
            fields["st_uid"] = max(os.geteuid(), 0) + 100000
        elif count == 2:
            fields["st_mtime_ns"] += 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(TargetAuthorityError, match="^target_authority_unsafe$"):
        authorize(binding)
