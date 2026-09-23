"""Read-only enterprise onboarding projections; no credential material."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class OnboardingWire(BaseModel):
    @field_serializer("*", check_fields=False, when_used="json")
    def timestamps(self, value):
        if isinstance(value, datetime):
            utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            return utc.isoformat().replace("+00:00", "Z")
        return value


class OnboardingAccess(OnboardingWire):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["environment-onboarding-access/v1"] = "environment-onboarding-access/v1"
    can_create: bool
    can_enroll: bool
    can_scan: bool
    can_view_assets: bool


class OnboardingDevice(OnboardingWire):
    model_config = ConfigDict(extra="forbid")
    id: str
    device_identity: str
    version: str
    registered_at: datetime
    last_seen_at: datetime | None
    status: Literal["waiting", "online", "stale", "revoked"]
    connectors: list[str] = Field(max_length=4)


class OnboardingScan(OnboardingWire):
    model_config = ConfigDict(extra="forbid")
    id: str
    connector: str
    status: Literal["pending", "uploaded", "delivered", "failed", "expired"]
    created_at: datetime
    expires_at: datetime
    device_identity: str | None
    candidate_count: int | None = Field(ge=0)
    evidence_count: int | None = Field(ge=0)


class OnboardingStatus(OnboardingWire):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["environment-onboarding/v1"] = "environment-onboarding/v1"
    environment_id: str
    evaluated_at: datetime
    heartbeat_stale_seconds: int = Field(ge=1)
    device_count: int = Field(ge=0)
    devices: list[OnboardingDevice] = Field(max_length=100)
    devices_truncated: bool
    evidence_count: int = Field(ge=0)
    last_evidence_at: datetime | None
    scans: list[OnboardingScan] = Field(max_length=20)
    scans_truncated: bool
