from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.rulepack import load_rulepack

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
MachineName = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$")]


class SkillObservationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    locator_sha256: Digest
    manifest_sha256: Digest
    parser_version: Literal["enterprise-skill-manifest/v1"]
    parse_status: Literal["parsed", "missing_frontmatter", "unsupported", "invalid_utf8"]
    name: MachineName | None = None
    allowed_tools_present: bool = Field(strict=True)
    declared_tools: list[MachineName] = Field(max_length=64)
    observed_at: datetime
    ancestor_sha256: list[Digest] | None = Field(default=None, min_length=1, max_length=33)

    @model_validator(mode="after")
    def consistent_declaration(self):
        if self.parse_status == "parsed":
            if self.name is None or (self.declared_tools and not self.allowed_tools_present):
                raise ValueError("inconsistent_declaration")
        elif self.name is not None or self.allowed_tools_present or self.declared_tools:
            raise ValueError("partial_declaration")
        if len(set(self.declared_tools)) != len(self.declared_tools):
            raise ValueError("duplicate_tool")
        if self.observed_at.tzinfo is None:
            raise ValueError("timezone_required")
        _, _, redactions = load_rulepack()
        for value in [self.name or "", *self.declared_tools]:
            if any(rule.pattern.search(value) for rule in redactions):
                raise ValueError("sensitive_identifier")
        return self


class SkillBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["enterprise-skill-upload/v1", "enterprise-skill-upload/v2"]
    task_id: str = Field(min_length=1, max_length=64)
    scope_digest: Digest
    observations: list[SkillObservationIn] = Field(max_length=200)
    signature: str = Field(pattern=r"^[a-f0-9]{128}$")

    @model_validator(mode="after")
    def unique_locations(self):
        for item in self.observations:
            if self.schema_version == 'enterprise-skill-upload/v1':
                if 'ancestor_sha256' in item.model_fields_set:
                    raise ValueError('v1_ancestry_forbidden')
            elif (not item.ancestor_sha256 or item.ancestor_sha256[0] != item.locator_sha256
                  or len(set(item.ancestor_sha256)) != len(item.ancestor_sha256)):
                raise ValueError('invalid_ancestry')
        locations = [item.locator_sha256 for item in self.observations]
        if len(set(locations)) != len(locations):
            raise ValueError("duplicate_location")
        return self
