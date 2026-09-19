"""Regression tests for acceptance false positives and diagnostic disclosure."""
import importlib.util
import json
import stat
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "review_journey", Path(__file__).with_name("r07-linux-user-journey-smoke.py")
)
journey = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(journey)


@pytest.mark.parametrize("message", [
    "HTTP /fixture: expected 200, got 201; ",
    "HTTP /fixture: expected 200, got 500; internal_error",
    "timeout while waiting for response",
    "HTTP /fixture: expected 200, got 401; unauthorized",
    "HTTP /fixture: expected 200, got 404; not_found",
])
def test_refusal_never_accepts_success_server_error_or_timeout(message):
    harness = object.__new__(journey.Harness)

    def api(*_args):
        raise RuntimeError(message)

    harness.api = api
    with pytest.raises(RuntimeError, match="did not receive the expected refusal status"):
        harness.refuse("/fixture", {})


def test_refusal_requires_concrete_client_response():
    harness = object.__new__(journey.Harness)

    def api(*_args):
        raise RuntimeError("HTTP /fixture: expected 200, got 409; skill_install_changed")

    harness.api = api
    assert "got 409;" in harness.refuse("/fixture", {})


def test_diagnostic_does_not_persist_error_payload_or_read_page(tmp_path):
    harness = object.__new__(journey.Harness)
    harness.debug_directory = tmp_path
    harness.journey_results = []
    error = RuntimeError("Bearer secret-token pairing code 1234-5678-90ab-cdef")
    with pytest.raises(RuntimeError) as caught:
        harness.debug_dump(object(), "negative", error)
    assert caught.value is error
    path = tmp_path / "negative.json"
    assert json.loads(path.read_text()) == {
        "phase": "negative", "error_type": "RuntimeError", "checks_completed": 0,
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]


def test_diagnostic_retains_only_fixed_wait_stage(tmp_path):
    harness = object.__new__(journey.Harness)
    harness.debug_directory = tmp_path
    harness.journey_results = [{"id": "r07_step8", "status": "pass"}]
    harness.mark("step8_pairing_form_after_invalidation", "role:heading")
    error = TimeoutError("Bearer secret-token pairing code 1234-5678-90ab-cdef")
    with pytest.raises(TimeoutError) as caught:
        harness.debug_dump(object(), "phase-c", error)
    assert caught.value is error
    path = tmp_path / "phase-c.json"
    assert json.loads(path.read_text()) == {
        "phase": "phase-c", "error_type": "TimeoutError", "checks_completed": 1,
        "last_wait": {"journey_step": "step8_pairing_form_after_invalidation",
                      "wait_target": {"category": "role:heading", "state": "visible"}},
    }
    assert "secret-token" not in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
