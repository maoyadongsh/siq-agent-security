"""Small, strict application contracts. These do not confer authority."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentError(RuntimeError):
    """A safe category suitable for task state; never include raw model data."""


class DataSensitivity(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    SECRET = "SECRET"

    @classmethod
    def parse(cls, value):
        try:
            return cls(value)
        except (TypeError, ValueError):
            raise AgentError("source_sensitivity_invalid") from None


def highest_sensitivity(*values):
    levels = list(DataSensitivity)
    return max((DataSensitivity.parse(v) for v in values), key=levels.index)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def strict_json(raw: str | bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AgentError("json_duplicate_key")
            result[key] = value
        return result

    def constant(_value):
        raise AgentError("json_nonfinite_number")

    if len(raw) > 1 << 20:
        raise AgentError("json_too_large")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise AgentError("json_invalid") from exc


def fields(value: Any, expected: set[str]) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise AgentError("contract_fields_invalid")
    return value


def string(value: Any, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise AgentError("contract_string_invalid")
    return value


@dataclass(frozen=True)
class UserTask:
    """Supplied by the operator, independently of the model's candidate plan."""

    prompt: str
    repository: str
    question: str
    scope: tuple[str, ...]
    report_path: str
    contact: str = "Alice"
    source_sensitivity: DataSensitivity = DataSensitivity.PUBLIC

    def __post_init__(self):
        object.__setattr__(self, "source_sensitivity", DataSensitivity.parse(self.source_sensitivity))
        for value in (self.prompt, self.repository, self.question, self.report_path, self.contact):
            string(value)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", self.repository):
            raise AgentError("repository_invalid")
        if not 1 <= len(self.scope) <= 16:
            raise AgentError("scope_invalid")
        for path in self.scope:
            string(path)
            if path.startswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
                raise AgentError("scope_path_invalid")


@dataclass(frozen=True)
class ResearchInput:
    repository: str
    question: str
    scope: tuple[str, ...]

    @classmethod
    def parse(cls, raw):
        fields(raw, {"repository", "question", "scope"})
        scope = raw["scope"]
        if not isinstance(scope, list) or not 1 <= len(scope) <= 16:
            raise AgentError("scope_invalid")
        return cls(string(raw["repository"]), string(raw["question"]), tuple(string(p) for p in scope))


@dataclass(frozen=True)
class ReportInput:
    path: str

    @classmethod
    def parse(cls, raw):
        fields(raw, {"path"})
        return cls(string(raw["path"]))


@dataclass(frozen=True)
class DeliveryInput:
    contact: str

    @classmethod
    def parse(cls, raw):
        fields(raw, {"contact"})
        return cls(string(raw["contact"], maximum=256))


SKILL_INPUTS = {"secure-research": ResearchInput, "secure-report": ReportInput,
                "secure-delivery": DeliveryInput}


@dataclass(frozen=True)
class SkillCall:
    name: str
    input: ResearchInput | ReportInput | DeliveryInput


@dataclass(frozen=True)
class TaskPlan:
    goal: str
    skills: tuple[SkillCall, ...]

    @classmethod
    def parse(cls, raw):
        fields(raw, {"goal", "skills"})
        if not isinstance(raw["skills"], list) or len(raw["skills"]) != 3:
            raise AgentError("plan_skills_invalid")
        calls = []
        # The frozen research/delivery workflow has typed data dependencies.
        # Plans cannot smuggle shell invocations or skip a required predecessor.
        for entry, expected in zip(raw["skills"], SKILL_INPUTS):
            fields(entry, {"name", "input"})
            if entry["name"] != expected:
                raise AgentError("plan_skill_order_invalid")
            calls.append(SkillCall(expected, SKILL_INPUTS[expected].parse(entry["input"])))
        return cls(string(raw["goal"]), tuple(calls))


@dataclass(frozen=True)
class Source:
    path: str
    revision: str
    digest: str
    content: str
    sensitivity: DataSensitivity = DataSensitivity.PUBLIC

    def __post_init__(self):
        object.__setattr__(self, "sensitivity", DataSensitivity.parse(self.sensitivity))


@dataclass(frozen=True)
class ResearchResult:
    findings: tuple[str, ...]
    sources: tuple[Source, ...]
    summary: str


@dataclass(frozen=True)
class ReportArtifact:
    path: str
    digest: str
    summary: str
    content: str


@dataclass(frozen=True)
class ContactCandidate:
    recipient: str
    provenance_id: str
    source: str


@dataclass(frozen=True)
class DeliveryResult:
    recipient: str
    action_id: str
    reported_success: bool


@dataclass
class TaskState:
    task_id: str
    goal: str
    model_provider: str
    status: str = "planning"
    current_skill: str | None = None
    current_step: str = "model planning"
    actions: list[dict] = field(default_factory=list)
    timings_ms: dict[str, list[float]] = field(default_factory=dict)
    completion: dict | None = None
    error_code: str | None = None
