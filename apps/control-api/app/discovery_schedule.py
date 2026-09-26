"""Bounded discovery intent, not authorization or a durable scheduler."""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.install_plan import Digest, EnterpriseInstallPlan, Identifier, StrictWire


class DiscoverySchedule(StrictWire):
    schema_version: Literal["enterprise-discovery-schedule/v1"]
    schedule_id: Annotated[str, Field(pattern=r"^eds-[a-f0-9]{32}$")]
    installation_plan_sha256: Digest
    device_identity: Identifier
    starts_at: str
    expires_at: str
    interval_seconds: int = Field(ge=900, le=86400)
    max_runs: int = Field(ge=1, le=2880)
    purpose: Literal["discovery_only"]

    @field_validator("starts_at", "expires_at")
    @classmethod
    def utc_timestamp(cls, value: str) -> str:
        return EnterpriseInstallPlan.utc_timestamp(value)

    @model_validator(mode="after")
    def bounded_window(self):
        if not timedelta(0) < self.end - self.start <= timedelta(days=30):
            raise ValueError("invalid_discovery_schedule_window")
        return self

    @property
    def start(self) -> datetime:
        return datetime.fromisoformat(self.starts_at)

    @property
    def end(self) -> datetime:
        return datetime.fromisoformat(self.expires_at)

    def require_binding(self, device_identity: str, installation_plan_sha256: str) -> None:
        """Caller must independently verify the supplied device and plan digest."""
        if (device_identity != self.device_identity
                or installation_plan_sha256 != self.installation_plan_sha256):
            raise ValueError("discovery_schedule_binding_mismatch")


def due_slot(
    schedule: DiscoverySchedule, *, now: datetime, last_reserved_slot: int | None,
    reserved_runs: int, active: bool,
) -> int | None:
    """A scheduling hint only; caller must lock/recheck persisted state to claim."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("verification_time_requires_timezone")
    if (type(active) is not bool or type(reserved_runs) is not int
            or not 0 <= reserved_runs <= schedule.max_runs
            or (last_reserved_slot is not None and (
                type(last_reserved_slot) is not int or last_reserved_slot < 0
            ))):
        raise ValueError("invalid_discovery_schedule_state")
    if (last_reserved_slot is None) != (reserved_runs == 0):
        raise ValueError("inconsistent_discovery_schedule_state")
    if last_reserved_slot is not None:
        # Integer timedelta division preserves microsecond cutoff semantics.
        last_possible = (schedule.end - schedule.start - timedelta(microseconds=1)) // timedelta(
            seconds=schedule.interval_seconds
        )
        if last_reserved_slot > last_possible or reserved_runs > last_reserved_slot + 1:
            raise ValueError("inconsistent_discovery_schedule_state")
    if not active or reserved_runs == schedule.max_runs or not schedule.start <= now < schedule.end:
        return None
    slot = (now - schedule.start) // timedelta(seconds=schedule.interval_seconds)
    return slot if last_reserved_slot is None or slot > last_reserved_slot else None
