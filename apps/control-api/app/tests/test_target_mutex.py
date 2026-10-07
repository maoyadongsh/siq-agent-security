import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from app.adapters.openshell.target_mutex import TargetLockError, target_mutex

CHILD = """
import sys
from sqlalchemy import create_engine
from app.adapters.openshell.target_mutex import target_mutex, TargetLockError
engine = create_engine(sys.argv[1])
try:
    with target_mutex(engine, 'synthetic-gateway', 'synthetic-target', timeout=0):
        pass
except TargetLockError as exc:
    assert str(exc) == 'operation_target_busy'
    sys.exit(3)
finally:
    engine.dispose()
"""


def child(url):
    return subprocess.run([sys.executable, "-c", CHILD, url], capture_output=True, text=True, timeout=10)


def test_sqlite_separate_process_exclusion_and_release(tmp_path):
    url = f"sqlite:///{tmp_path / 'mutex.db'}"
    engine = create_engine(url)
    try:
        with target_mutex(engine, "synthetic-gateway", "synthetic-target"):
            result = child(url)
            assert result.returncode == 3, result.stderr
            with target_mutex(engine, "synthetic-gateway", "another-target", timeout=0):
                pass
        assert child(url).returncode == 0
        with pytest.raises(RuntimeError, match="synthetic failure"):
            with target_mutex(engine, "synthetic-gateway", "synthetic-target"):
                raise RuntimeError("synthetic failure")
        assert child(url).returncode == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode"])
def test_sqlite_unsafe_lock_file_refused(tmp_path, kind):
    engine = create_engine(f"sqlite:///{tmp_path / 'mutex.db'}")
    try:
        with target_mutex(engine, "synthetic-gateway", "synthetic-target"):
            pass
        path = next((tmp_path / ".mutex.db.siq-operation-locks").glob("*.lock"))
        if kind == "symlink":
            path.unlink()
            external = tmp_path / "external"
            external.write_text("synthetic untouched data")
            path.symlink_to(external)
        elif kind == "hardlink":
            (tmp_path / "hardlink").hardlink_to(path)
        else:
            path.chmod(0o644)
        with pytest.raises(TargetLockError, match="operation_lock_storage_invalid"):
            with target_mutex(engine, "synthetic-gateway", "synthetic-target"):
                pytest.fail("unsafe storage accepted")
        if kind == "symlink":
            assert external.read_text() == "synthetic untouched data"
    finally:
        engine.dispose()


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "sqlite:///file:synthetic.db?uri=true"])
def test_sqlite_memory_or_uri_database_cannot_claim_process_exclusion(url):
    engine = create_engine(url)
    try:
        with pytest.raises(TargetLockError, match="operation_lock_database_unsupported"):
            with target_mutex(engine, "synthetic-gateway", "synthetic-target"):
                pytest.fail("in-memory database accepted")
    finally:
        engine.dispose()


@pytest.mark.parametrize("failure", ["acquire_reply", "commit", "release_reply", "release_false"])
def test_postgres_uncertain_lock_connection_never_returns_to_pool(failure):
    class Connection:
        invalidated = False
        closed = False
        calls = 0
        commits = 0

        def scalar(self, *args, **kwargs):
            self.calls += 1
            if (self.calls == 1 and failure == "acquire_reply") or (
                self.calls == 2 and failure == "release_reply"
            ):
                raise RuntimeError("synthetic transport fault")
            return not (self.calls == 2 and failure == "release_false")

        def commit(self):
            self.commits += 1
            if self.commits == 1 and failure == "commit":
                raise RuntimeError("synthetic transport fault")

        def invalidate(self):
            self.invalidated = True

        def close(self):
            self.closed = True

    connection = Connection()
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: connection)
    with pytest.raises((RuntimeError, TargetLockError)):
        with target_mutex(engine, "synthetic-gateway", "synthetic-target"):
            pass
    assert connection.invalidated and connection.closed
