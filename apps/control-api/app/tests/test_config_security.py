"""生产配置与任务签名密钥 fail-closed 测试。"""

from __future__ import annotations

import base64
import stat
from pathlib import Path

import pytest

from app.config import load_settings
from app.signing import get_signing_key, public_key_base64


def _production_env(monkeypatch) -> None:
    monkeypatch.setenv("SIQ_AS_DEV", "0")
    monkeypatch.setenv("SIQ_AS_DATABASE_URL", "postgresql+psycopg://localhost/siq")
    monkeypatch.setenv("SIQ_AS_OIDC_JWKS_URL", "https://iam.invalid/.well-known/jwks.json")
    monkeypatch.delenv("SIQ_AS_TASK_SIGNING_KEY_SEED", raising=False)


def test_production_requires_secret_managed_task_signing_key(monkeypatch):
    _production_env(monkeypatch)
    with pytest.raises(RuntimeError, match="TASK_SIGNING_KEY_SEED"):
        load_settings()

    monkeypatch.setenv("SIQ_AS_TASK_SIGNING_KEY_SEED", base64.b64encode(bytes(range(32))).decode())
    settings = load_settings()
    assert settings.task_signing_key_seed
    assert settings.task_signing_key_file is None


def test_production_rejects_sqlite_even_when_allow_flag_is_set(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("SIQ_AS_DATABASE_URL", "sqlite:///prod.db")
    monkeypatch.setenv("SIQ_AS_ALLOW_SQLITE", "1")
    monkeypatch.setenv("SIQ_AS_TASK_SIGNING_KEY_SEED", base64.b64encode(bytes(range(32))).decode())
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        load_settings()


def test_production_cors_is_same_origin_by_default_and_rejects_wildcard(monkeypatch):
    _production_env(monkeypatch)
    monkeypatch.setenv("SIQ_AS_TASK_SIGNING_KEY_SEED", base64.b64encode(bytes(range(32))).decode())
    monkeypatch.delenv("SIQ_AS_CORS_ORIGINS", raising=False)
    assert load_settings().cors_origins == ()

    monkeypatch.setenv("SIQ_AS_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
        load_settings()

    monkeypatch.setenv("SIQ_AS_CORS_ORIGINS", "https://security.example.com")
    assert load_settings().cors_origins == ("https://security.example.com",)

    for origin in (
        "https://user:secret@security.example.com",
        "https://security.example.com/admin",
        "https://security.example.com?tenant=other",
        "https://security.example.com:invalid",
    ):
        monkeypatch.setenv("SIQ_AS_CORS_ORIGINS", origin)
        with pytest.raises(RuntimeError, match="CORS_ORIGINS"):
            load_settings()


def test_dev_signing_key_is_persistent_and_owner_only(monkeypatch, tmp_path):
    key_file = tmp_path / "state" / "signing-key.seed"
    monkeypatch.setenv("SIQ_AS_DEV", "1")
    monkeypatch.setenv("SIQ_AS_DATABASE_URL", f"sqlite:///{tmp_path / 'dev.db'}")
    monkeypatch.setenv("SIQ_AS_ALLOW_SQLITE", "1")
    monkeypatch.setenv("SIQ_AS_SIGNING_KEY_FILE", str(key_file))
    monkeypatch.delenv("SIQ_AS_TASK_SIGNING_KEY_SEED", raising=False)

    get_signing_key.cache_clear()
    first = public_key_base64()
    get_signing_key.cache_clear()
    second = public_key_base64()
    get_signing_key.cache_clear()

    assert first == second
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_baseline_migration_is_frozen_and_does_not_import_runtime_models():
    migration = Path(__file__).parents[2] / "migrations" / "versions" / "0001_baseline.py"
    source = migration.read_text(encoding="utf-8")
    assert "from app import models" not in source
    assert "Base.metadata.create_all" not in source
