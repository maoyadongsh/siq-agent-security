import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def test_batch_draft_migration_and_history_preservation(tmp_path):
    database = tmp_path / "drafts.db"
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TZ"}}
    env.update(SIQ_AS_DEV="1", SIQ_AS_ALLOW_SQLITE="1", SIQ_AS_DATABASE_URL=f"sqlite:///{database}",
               SIQ_AS_SIGNING_KEY_FILE=str(tmp_path / "fixture.seed"))

    def migrate(*args):
        return subprocess.run([sys.executable, "-m", "alembic", *args],
                              cwd=Path(__file__).resolve().parents[2], env=env,
                              capture_output=True, text=True, timeout=30, check=False)

    result = migrate("upgrade", "0024")
    assert result.returncode == 0, result.stderr
    assert migrate("downgrade", "0023").returncode == 0
    assert migrate("upgrade", "0024").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO tenant(id,name,status,data_residency,retention_days,created_at) "
            "VALUES('fixture','fixture','active','default',180,'2026-09-25')"
        )
        values = ("draft", "fixture", "actor", "user", "key", "a" * 64, "{}", "2026-09-25", "2026-09-26")
        connection.execute("INSERT INTO deployment_batch_draft VALUES(?,?,?,?,?,?,?,?,?)", values)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute("INSERT INTO deployment_batch_draft VALUES(?,?,?,?,?,?,?,?,?)", ("other", *values[1:]))
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute("INSERT INTO deployment_batch_draft VALUES(?,?,?,?,?,?,?,?,?)",
                               ("foreign", "missing", *values[2:]))
    result = migrate("downgrade", "0023")
    assert result.returncode != 0 and "batch preview history must be preserved" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0024"
        assert connection.execute("SELECT count(*) FROM deployment_batch_draft").fetchone()[0] == 1
    result = migrate("upgrade", "0025")
    assert result.returncode == 0, result.stderr
    assert migrate("downgrade", "0024").returncode == 0
    assert migrate("upgrade", "0025").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO tenant(id,name,status,data_residency,retention_days,created_at) "
            "VALUES('tenant-b','fixture','active','default',180,'2026-09-25')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            connection.execute("INSERT INTO deployment_batch_reservation VALUES(?,?,?,?,?)",
                               ("foreign", "tenant-b", "draft", "[]", "2026-09-25"))
        connection.execute("INSERT INTO deployment_batch_reservation VALUES(?,?,?,?,?)",
                           ("batch", "fixture", "draft", "[]", "2026-09-25"))
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            connection.execute("INSERT INTO deployment_batch_reservation VALUES(?,?,?,?,?)",
                               ("duplicate", "fixture", "draft", "[]", "2026-09-25"))
    result = migrate("downgrade", "0024")
    assert result.returncode != 0 and "batch execution claims must be preserved" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0025"
        assert connection.execute("SELECT count(*) FROM deployment_batch_reservation").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM deployment_batch_draft").fetchone()[0] == 1
