from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.discovery_schedule import DiscoverySchedule, due_slot

BASE = {
    "schema_version": "enterprise-discovery-schedule/v1",
    "schedule_id": "eds-" + "a" * 32,
    "installation_plan_sha256": "b" * 64,
    "device_identity": "edge-synthetic",
    "starts_at": "2026-09-26T00:00:00Z",
    "expires_at": "2026-09-27T00:00:00Z",
    "interval_seconds": 900,
    "max_runs": 4,
    "purpose": "discovery_only",
}
START = datetime(2026, 9, 26, tzinfo=UTC)


@pytest.mark.parametrize("field,value", [
    ("interval_seconds", True), ("interval_seconds", "900"),
    ("interval_seconds", 899), ("interval_seconds", 86401),
    ("max_runs", False), ("max_runs", 0), ("max_runs", 2881),
    ("starts_at", "2026-09-26T00:00:00"),
    ("starts_at", "2026-09-26T00:00:00+00:00"),
    ("expires_at", "2026-09-26T00:00:00Z"),
    ("expires_at", "2026-10-27T00:00:00Z"),
    ("expires_at", "2026-02-30T00:00:00Z"),
    ("purpose", "enforce"), ("tenant_id", "attacker"),
])
def test_invalid_intent_rejected(field, value):
    with pytest.raises(ValidationError):
        DiscoverySchedule.model_validate({**BASE, field: value})


@pytest.mark.parametrize("field", list(BASE))
def test_no_implicit_schedule_defaults(field):
    with pytest.raises(ValidationError):
        DiscoverySchedule.model_validate({key: value for key, value in BASE.items() if key != field})


def test_boundaries_and_recovery_do_not_catch_up():
    schedule = DiscoverySchedule.model_validate(BASE)
    def fresh(now):
        return due_slot(schedule, now=now, last_reserved_slot=None, reserved_runs=0, active=True)
    assert fresh(START - timedelta(microseconds=1)) is None
    assert fresh(START) == 0
    assert fresh(START + timedelta(seconds=899, microseconds=999999)) == 0
    assert fresh(START + timedelta(seconds=900)) == 1
    assert fresh(START + timedelta(hours=23)) == 92  # One current slot, not 93 jobs.
    assert fresh(START + timedelta(days=1)) is None
    assert due_slot(schedule, now=START + timedelta(hours=23),
                    last_reserved_slot=80, reserved_runs=1, active=True) == 92


def test_replay_clock_rollback_pause_and_budget():
    schedule = DiscoverySchedule.model_validate(BASE)
    for now in (START, START + timedelta(seconds=900)):
        assert due_slot(schedule, now=now, last_reserved_slot=1, reserved_runs=1, active=True) is None
    assert due_slot(schedule, now=START, last_reserved_slot=None, reserved_runs=0, active=False) is None
    assert due_slot(schedule, now=START + timedelta(hours=2),
                    last_reserved_slot=3, reserved_runs=4, active=True) is None


@pytest.mark.parametrize("last,runs,active", [
    (None, 1, True), (0, 0, True), (-1, 1, True), (100, 1, True),
    (0, 2, True), (None, True, True), (False, 1, True), (None, 0, "true"),
])
def test_inconsistent_state_fails_closed(last, runs, active):
    with pytest.raises(ValueError):
        due_slot(DiscoverySchedule.model_validate(BASE), now=START,
                 last_reserved_slot=last, reserved_runs=runs, active=active)


def test_naive_clock_rejected_and_binding_is_exact():
    schedule = DiscoverySchedule.model_validate(BASE)
    with pytest.raises(ValueError):
        due_slot(schedule, now=START.replace(tzinfo=None),
                 last_reserved_slot=None, reserved_runs=0, active=True)
    schedule.require_binding(BASE["device_identity"], BASE["installation_plan_sha256"])
    for device, digest in (("other", "b" * 64), ("edge-synthetic", "c" * 64)):
        with pytest.raises(ValueError):
            schedule.require_binding(device, digest)
