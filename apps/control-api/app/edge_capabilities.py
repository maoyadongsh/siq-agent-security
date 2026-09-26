"""Bounded device-reported inventory, never an authorization or attestation."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.install_plan import ConnectorID, StrictWire, Version

Label = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:/-]+$")]


class InstalledCapabilities(StrictWire):
    inventory_schema: Literal["enterprise-installed-capabilities/v1", "enterprise-installed-capabilities/v2"]
    protocol_version: Literal["connector-protocol.v1"]
    connectors: list[ConnectorID] = Field(max_length=12)
    connector_versions: dict[ConnectorID, Version] = Field(max_length=12)
    data_categories: list[Label] = Field(max_length=64)
    connector_task_types: dict[ConnectorID, list[Literal["scan", "skill_scan"]]] | None = Field(
        default=None, max_length=12
    )

    @model_validator(mode="after")
    def matching_versions(self):
        if len(set(self.connectors)) != len(self.connectors) or set(self.connectors) != set(self.connector_versions):
            raise ValueError("capability_version_set_mismatch")
        if len(set(self.data_categories)) != len(self.data_categories):
            raise ValueError("duplicate_data_category")
        if self.inventory_schema.endswith("/v2"):
            if self.connector_task_types is None or set(self.connector_task_types) != set(self.connectors):
                raise ValueError("capability_task_set_mismatch")
            for connector, kinds in self.connector_task_types.items():
                if not kinds or len(kinds) > 2 or len(set(kinds)) != len(kinds):
                    raise ValueError("invalid_connector_task_types")
                if "skill_scan" in kinds and connector != "directory":
                    raise ValueError("unsupported_skill_connector")
        elif self.connector_task_types is not None:
            raise ValueError("task_types_require_v2")
        return self


def can_claim_skills(capabilities: dict, last_seen: datetime | None, now: datetime, cutoff: datetime) -> bool:
    if not isinstance(capabilities, dict):
        return False
    try:
        inventory = InstalledCapabilities.model_validate(capabilities)
    except ValueError:
        return False
    return (
        last_seen is not None
        and cutoff <= last_seen <= now
        and inventory.inventory_schema.endswith("/v2")
        and "skill_scan" in (inventory.connector_task_types or {}).get("directory", [])
    )


def claimable_connectors(capabilities: dict, last_seen: datetime | None, now: datetime, cutoff: datetime):
    """None means legacy; [] means measured/unknown inventory cannot scan."""
    if not isinstance(capabilities, dict) or "inventory_schema" not in capabilities:
        return None
    try:
        inventory = InstalledCapabilities.model_validate(capabilities)
    except ValueError:
        return []
    if last_seen is None or last_seen < cutoff or last_seen > now:
        return []
    if inventory.connector_task_types is not None:
        return [key for key, kinds in inventory.connector_task_types.items() if "scan" in kinds]
    return inventory.connectors
