"""Real Alembic upgrade on populated isolated SQLite, never the running database."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[2]


def insert(connection, table, row):
    columns = list(row)
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [row[column] for column in columns],
    )


def test_populated_device_scope_upgrade_preserves_history_and_constraints(tmp_path):
    database = tmp_path / "migration.db"
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "TZ"}}
    env.update(
        {
            "SIQ_AS_DEV": "1",
            "SIQ_AS_ALLOW_SQLITE": "1",
            "SIQ_AS_DATABASE_URL": f"sqlite:///{database}",
            "SIQ_AS_SIGNING_KEY_FILE": str(tmp_path / "fixture.seed"),
        }
    )

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    result = migrate("upgrade", "0019")
    assert result.returncode == 0, result.stderr
    timestamp = "2026-09-25 00:00:00"
    asset = {
        "id": "asset-fixture",
        "tenant_id": "tenant-fixture",
        "name": "legacy profile",
        "framework": "hermes",
        "attributes": '{"note":"preserve"}',
        "status": "managed",
        "source_type": "hermes_profile",
        "source_locator": "hermes://profile/same",
        "evidence_ids": '["evidence-fixture"]',
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    evidence = {
        "id": "observation-fixture",
        "evidence_id": "evidence-fixture",
        "tenant_id": "tenant-fixture",
        "environment_id": "env-fixture",
        "source_type": "manifest",
        "source_locator": "same/config.yaml",
        "observed_at": timestamp,
        "collected_at": timestamp,
        "collector_id": "device-a",
        "connector_version": "0.1.0",
        "content_hash": "a" * 64,
        "redaction_profile": "siq.redaction.v1",
        "classification": "internal",
        "signature": "fixture-signature-preserve",
    }
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert "discovery_scope" not in {row[1] for row in connection.execute("PRAGMA table_info(agent_asset)")}
        insert(
            connection,
            "tenant",
            {
                "id": "tenant-fixture",
                "name": "fixture",
                "status": "active",
                "data_residency": "default",
                "retention_days": 180,
                "created_at": timestamp,
            },
        )
        insert(
            connection,
            "environment",
            {
                "id": "env-fixture",
                "tenant_id": "tenant-fixture",
                "name": "fixture",
                "env_type": "host",
                "mode": "discovery",
                "risk_level": "medium",
                "created_at": timestamp,
            },
        )
        insert(connection, "agent_asset", asset)
        insert(
            connection,
            "agent_instance",
            {
                "id": "instance-fixture",
                "tenant_id": "tenant-fixture",
                "asset_id": asset["id"],
                "environment_id": "env-fixture",
                "runtime": "hermes",
                "location": "{}",
                "status": "observed",
                "observed_at": timestamp,
            },
        )
        insert(connection, "evidence", evidence)
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ["agent_asset", "agent_instance", "evidence"]
        }
    result = migrate("upgrade", "0020")
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        rows = connection.execute("SELECT * FROM agent_asset").fetchall()
        assert rows == [before["agent_asset"][0] + ("legacy",)]
        for table in ["agent_instance", "evidence"]:
            assert connection.execute(f"SELECT * FROM {table}").fetchall() == before[table]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        for scope in ["device-scope-a", "device-scope-b"]:
            insert(connection, "agent_asset", {**asset, "id": scope, "discovery_scope": scope})
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection, "agent_asset", {**asset, "id": "duplicate", "discovery_scope": "device-scope-a"})
        insert(connection, "evidence", {**evidence, "id": "observation-b", "collector_id": "device-b"})
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection, "evidence", {**evidence, "id": "observation-duplicate"})
    result = migrate("downgrade", "0019")
    assert result.returncode != 0
    assert "cannot be merged by automatic downgrade" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0020"
        assert connection.execute("SELECT count(*) FROM agent_asset").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM evidence").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM agent_instance").fetchone()[0] == 1
