"""Independent skill identities on a migrated isolated database, never production."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.tests.test_discovery_scope_migration import insert


def test_skill_inventory_migration_identity_and_tenant_constraints(tmp_path):
    database = tmp_path / "skills.db"
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "TZ"}}
    env.update(
        SIQ_AS_DEV="1",
        SIQ_AS_ALLOW_SQLITE="1",
        SIQ_AS_DATABASE_URL=f"sqlite:///{database}",
        SIQ_AS_SIGNING_KEY_FILE=str(tmp_path / "fixture.seed"),
    )

    def migrate(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    result = migrate("upgrade", "0021")
    assert result.returncode == 0, result.stderr
    # Empty rollback is supported and leaves previous source identity migration intact.
    result = migrate("downgrade", "0020")
    assert result.returncode == 0, result.stderr
    assert migrate("upgrade", "0021").returncode == 0
    timestamp = "2026-09-25 00:00:00"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        for tenant in ("tenant-a", "tenant-b"):
            insert(
                connection,
                "tenant",
                dict(
                    id=tenant,
                    name=tenant,
                    status="active",
                    data_residency="default",
                    retention_days=180,
                    created_at=timestamp,
                ),
            )
        insert(
            connection,
            "environment",
            dict(
                id="env",
                tenant_id="tenant-a",
                name="fixture",
                env_type="host",
                mode="discovery",
                risk_level="medium",
                created_at=timestamp,
            ),
        )
        for edge in ("edge-a", "edge-b"):
            insert(
                connection,
                "edge_agent",
                dict(
                    id=edge,
                    environment_id="env",
                    device_identity=edge,
                    secret_hash="0" * 64,
                    public_key_pem="fixture-not-a-real-key",
                    version="fixture",
                    capabilities="{}",
                    registered_at=timestamp,
                ),
            )
        installation = dict(
            id="skill-a", tenant_id="tenant-a", edge_agent_id="edge-a", locator_sha256="a" * 64, created_at=timestamp
        )
        insert(connection, "skill_installation", installation)
        insert(connection, "skill_installation", {**installation, "id": "skill-b", "edge_agent_id": "edge-b"})
        insert(connection, "skill_installation", {**installation, "id": "skill-c", "locator_sha256": "b" * 64})
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection, "skill_installation", {**installation, "id": "duplicate-location"})
        observation = dict(
            id="obs-a",
            tenant_id="tenant-a",
            installation_id="skill-a",
            manifest_sha256="c" * 64,
            parser_version="enterprise-skill-manifest/v1",
            parse_status="parsed",
            name="same-name",
            allowed_tools_present=True,
            declared_tools='["read_file"]',
            observed_at=timestamp,
            batch_digest="d" * 64,
            batch_signature="e" * 128,
        )
        insert(connection, "skill_manifest_observation", observation)
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection, "skill_manifest_observation", {**observation, "id": "replay"})
        with pytest.raises(sqlite3.IntegrityError):
            insert(connection, "skill_manifest_observation", {**observation, "id": "foreign", "tenant_id": "tenant-b"})
        with pytest.raises(sqlite3.IntegrityError):
            insert(
                connection,
                "skill_manifest_observation",
                {**observation, "id": "partial", "batch_digest": "f" * 64, "parse_status": "too_large"},
            )
        insert(connection, "skill_manifest_observation", {**observation, "id": "obs-b", "batch_digest": "f" * 64})
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT count(*) FROM agent_asset").fetchone()[0] == 0
    result = migrate("downgrade", "0020")
    assert result.returncode != 0 and "skill discovery history must be preserved" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0021"
        assert connection.execute("SELECT count(*) FROM skill_installation").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM skill_manifest_observation").fetchone()[0] == 2
        assert (
            connection.execute("SELECT batch_signature FROM skill_manifest_observation WHERE id='obs-a'").fetchone()[0]
            == "e" * 128
        )
    assert migrate("upgrade", "0022").returncode == 0
    assert migrate("downgrade", "0021").returncode == 0
    assert migrate("upgrade", "0022").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        insert(
            connection,
            "edge_task",
            dict(
                id="task-fixture",
                environment_id="env",
                task_type="skill_scan",
                payload="{}",
                status="uploaded",
                attempt=1,
                expires_at=timestamp,
                created_at=timestamp,
            ),
        )
        insert(
            connection,
            "skill_upload_receipt",
            dict(
                task_id="task-fixture",
                tenant_id="tenant-a",
                edge_agent_id="edge-a",
                batch_digest="a" * 64,
                signed_payload='{"fixture":true}',
                signature="b" * 128,
                created_at=timestamp,
            ),
        )
    result = migrate("downgrade", "0021")
    assert result.returncode != 0 and "skill upload signature inputs must be preserved" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0022"
        assert connection.execute("SELECT signed_payload FROM skill_upload_receipt").fetchone()[0] == '{"fixture":true}'
        assert connection.execute("SELECT count(*) FROM skill_manifest_observation").fetchone()[0] == 2
    assert migrate("upgrade", "0023").returncode == 0
    assert migrate("downgrade", "0022").returncode == 0
    assert migrate("upgrade", "0023").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        insert(connection, "agent_asset", dict(
            id="role-a", tenant_id="tenant-a", name="role", framework="openclaw", status="candidate",
            discovery_scope="edge-a", attributes="{}", evidence_ids="[]", created_at=timestamp, updated_at=timestamp,
        ))
        observation = dict(
            id="role-obs", tenant_id="tenant-a", asset_id="role-a", edge_agent_id="edge-a",
            task_id="task-fixture", batch_digest="a" * 64, selection="{}", source_evidence="[]",
            observed_at=timestamp, received_at=timestamp,
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            insert(connection, "role_skill_selection_observation", {
                **observation, "id": "foreign", "tenant_id": "tenant-b", "asset_id": "role-a",
            })
        insert(connection, "role_skill_selection_observation", observation)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            insert(connection, "role_skill_selection_observation", {**observation, "id": "duplicate"})
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    result = migrate("downgrade", "0022")
    assert result.returncode != 0 and "role skill declaration history must be preserved" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0023"
        assert connection.execute("SELECT count(*) FROM role_skill_selection_observation").fetchone()[0] == 1
