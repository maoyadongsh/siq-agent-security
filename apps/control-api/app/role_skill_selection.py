"""Validated declared scope snapshots, never an installed-skill resolver."""

import json
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.rulepack import load_rulepack
from app.skill_upload import MachineName


class RoleSkillSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["enterprise-openclaw-skill-selection/v1"]
    source: Literal["agent", "defaults", "none"]
    status: Literal["declared_list", "unconfigured", "unsupported"]
    names: list[MachineName] = Field(max_length=64)

    @model_validator(mode="after")
    def consistent(self):
        if (self.source == "none") != (self.status == "unconfigured"):
            raise ValueError("inconsistent_source")
        if self.status != "declared_list" and self.names:
            raise ValueError("partial_selection")
        if self.names != sorted(set(self.names)):
            raise ValueError("noncanonical_names")
        _, _, redactions = load_rulepack()
        if any(rule.pattern.search(name) for rule in redactions for name in self.names):
            raise ValueError("sensitive_identifier")
        return self


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def selections_for_batch(candidates, task):
    """Validate before persistence, with fixed errors that do not disclose input."""
    result = {}
    locations = set()
    has_selection = any((c.attributes or {}).get("skill_selection") is not None for c in candidates)
    for candidate in candidates:
        raw = (candidate.attributes or {}).get("skill_selection")
        location = (candidate.source_type, candidate.source_locator)
        if location in locations and has_selection:
            raise HTTPException(422, "role_skill_duplicate_asset")
        locations.add(location)
        if raw is None:
            continue
        try:
            if (
                candidate.framework != "openclaw" or candidate.source_type != "openclaw_agent"
                or task.payload.get("connector") != "openclaw"
                or re.fullmatch(r"openclaw://agents/v2/[a-f0-9]{64}", candidate.source_locator or "") is None
                or candidate.candidate_id != "openclaw:v2:" + candidate.source_locator.rsplit("/", 1)[-1]
                or not 1 <= len(candidate.evidence_ids) <= 64
                or len(candidate.evidence_ids) != len(set(candidate.evidence_ids))
                or len(raw.encode("utf-8")) > 10000
            ):
                raise ValueError("invalid_origin")
            selection = RoleSkillSelection.model_validate(json.loads(raw, object_pairs_hook=_unique_object))
        except (ValueError, TypeError, RecursionError):
            raise HTTPException(422, "role_skill_selection_invalid") from None
        result[candidate.candidate_id] = selection.model_dump()
    return result
