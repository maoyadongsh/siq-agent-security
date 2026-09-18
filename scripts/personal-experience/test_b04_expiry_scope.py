"""Security regressions for the real-time raw-content purge evidence gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

RUNNER = Path(__file__).with_name("closure-b04-expiry-seed-runner.py")
SPEC = importlib.util.spec_from_file_location("b04_expiry_scope", RUNNER)
b04 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(b04)


def test_append_only_audit_preserves_every_existing_byte():
    path = "receipts/task/2026-09-17.jsonl"
    old = b'{"signed":"old"}\n'
    assert b04.out_of_scope_changes([], [], [path], {path: old}, {path: old + b'{"signed":"new"}\n'}) == []
    assert b04.out_of_scope_changes([], [], [path], {path: old}, {path: b'{"signed":"fake"}\n'}) == [path]
    assert b04.out_of_scope_changes([], [], [path], {path: old}, {path: old[:-1]}) == [path]


def test_purge_cannot_remove_receipt_or_rewrite_non_content_state():
    receipt = "receipts/task/2026-09-17.jsonl"
    grant = "raw-task-content-authority/rawgrant-a.grant.json"
    assert b04.out_of_scope_changes([receipt], [], [], {}, {}) == [receipt]
    assert b04.out_of_scope_changes([], [], [grant], {}, {}) == [grant]
    assert b04.out_of_scope_changes(["raw-task-content/expired.json"], [], [], {}, {}) == []


def test_private_evidence_is_created_0600_and_never_overwritten(tmp_path):
    out = tmp_path / "private" / "verify.json"
    runner = b04.B04Runner.__new__(b04.B04Runner)
    runner.args = SimpleNamespace(out=str(out))
    assert runner.write_json({"passed": False}) == out
    original = out.read_bytes()
    assert out.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        runner.write_json({"passed": True})
    assert out.read_bytes() == original
