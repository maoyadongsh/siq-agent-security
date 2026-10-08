import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.tests.test_durable_openshell_operations import state
from app.tests.test_operation_journal import database as database


def run(mode, database, tmp_path):
    api = Path(__file__).resolve().parents[2]
    environment = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG"}}
    environment["PYTHONPATH"] = str(api)
    return subprocess.run([
        sys.executable, str(Path(__file__).parent / "fixtures/durable_operation_process.py"),
        mode, str(database.kw["bind"].url), str(tmp_path),
    ], cwd=api, env=environment, capture_output=True, text=True, timeout=15)


def test_independent_process_recovery_and_repeat_are_exact(database, tmp_path):
    result = run("apply", database, tmp_path)
    assert result.returncode == 0, result.stderr
    assert state(database) == "applied"
    result = run("rollback", database, tmp_path)
    assert result.returncode == 0, result.stderr
    assert state(database) == "rolled_back"
    assert run("rollback", database, tmp_path).returncode == 0
    assert json.loads((tmp_path / "gateway.json").read_text())["set_calls"] == 2


@pytest.mark.parametrize("stage", ["apply", "rollback"])
def test_hard_process_exit_does_not_replay_external_effect(database, tmp_path, stage):
    if stage == "rollback":
        assert run("apply", database, tmp_path).returncode == 0
    assert run("crash-" + stage, database, tmp_path).returncode == 73
    assert state(database) == ("applying" if stage == "apply" else "rollback_pending")
    before = json.loads((tmp_path / "gateway.json").read_text())
    assert run(stage, database, tmp_path).returncode == 74
    assert json.loads((tmp_path / "gateway.json").read_text()) == before
