"""ADR-058 challenge/observation validation; no IO, authorization or durable CAS.

The caller must obtain challenge/state/current readback from trusted sources and
atomically consume the operation after validation. Client-submitted evidence is
not a trusted producer. Passing this module alone cannot promote a deployment.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

Token = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", max_length=128)]
Digest = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$", max_length=64)]
ProbeID = Annotated[str, StringConstraints(pattern=r"^opv-[a-f0-9]{32}$", max_length=36)]
ImageDigest = Annotated[str, StringConstraints(pattern=r"^sha256:[a-f0-9]{64}$", max_length=71)]
ProgramPath = Annotated[str, StringConstraints(pattern=r"^/[A-Za-z0-9_./-]+$", max_length=512)]
Endpoint = Annotated[str, StringConstraints(pattern=r"^(?:[0-9]{1,3}\.){3}[0-9]{1,3}:[0-9]{1,5}$", max_length=21)]
Timestamp = Annotated[str, StringConstraints(
    pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$", max_length=32,
)]


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")


def _path(value: str) -> str:
    parsed = PurePosixPath(value)
    if value == "/" or str(parsed) != value or ".." in parsed.parts:
        raise ValueError("probe_program_path_invalid")
    return value


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @field_validator("issued_at", "expires_at", "started_at", "finished_at", "observed_at", check_fields=False)
    @classmethod
    def valid_timestamp(cls, value: str) -> str:
        _time(value)
        return value


class BehaviorBinding(Wire):
    tenant_id: Token
    environment_id: Token
    binding_id: Token
    deployment_id: Token
    operation_id: Token
    target: Token
    gateway_fingerprint: Token
    policy_revision: Token
    policy_digest: Digest
    image_digest: ImageDigest
    probe_sha256: Digest
    protected_execution_sha256: Digest


class BehaviorChallenge(Wire):
    schema_version: Literal["openshell-behavior-challenge/v1"]
    verification_id: ProbeID
    nonce: Digest
    binding: BehaviorBinding
    receiver_ipv4: Annotated[str, Field(max_length=15)]
    receiver_port: Annotated[int, Field(ge=1, le=65535)]
    allow_path: ProgramPath
    deny_path: ProgramPath
    attempts: Annotated[int, Field(ge=3, le=10)]
    timeout_ms: Annotated[int, Field(ge=100, le=10000)]
    issued_at: Timestamp
    expires_at: Timestamp

    @field_validator("receiver_ipv4")
    @classmethod
    def numeric_receiver(cls, value: str) -> str:
        if str(ipaddress.IPv4Address(value)) != value:
            raise ValueError("probe_receiver_invalid")
        return value

    @field_validator("allow_path", "deny_path")
    @classmethod
    def canonical_path(cls, value: str) -> str:
        return _path(value)


class BehaviorRule(Wire):
    endpoint: Endpoint
    program_path: ProgramPath

    @field_validator("program_path")
    @classmethod
    def canonical_path(cls, value: str) -> str:
        return _path(value)


class BehaviorReadback(Wire):
    binding: BehaviorBinding
    enforcement_mode: Literal["block", "unknown", "warn", "audit_only"]
    allow_rules: Annotated[list[BehaviorRule], Field(max_length=512)]


class BehaviorObservation(Wire):
    round: Annotated[int, Field(ge=0, le=9)]
    kind: Literal["control_before", "allow", "deny", "control_after"]
    nonce: Digest
    origin: Literal["sandbox_exec", "control_plane_host"]
    endpoint: Endpoint
    program_path: Annotated[str, Field(max_length=512)]
    program_sha256: Annotated[str, Field(max_length=64)]
    outcome: Literal["connected", "timeout", "connection_refused", "connection_reset", "dns_failure", "probe_error"]
    elapsed_ms: Annotated[int, Field(ge=0, le=11000)]
    observed_at: Timestamp


class BehaviorResult(Wire):
    schema_version: Literal["openshell-behavior-result/v2"]
    verification_id: ProbeID
    nonce: Digest
    challenge_sha256: Digest
    started_at: Timestamp
    finished_at: Timestamp
    before: BehaviorReadback
    after: BehaviorReadback
    observations: Annotated[list[BehaviorObservation], Field(min_length=12, max_length=40)]


def challenge_digest(challenge: BehaviorChallenge) -> str:
    return hashlib.sha256(json.dumps(
        challenge.model_dump(mode="json"), sort_keys=True, ensure_ascii=True, separators=(",", ":"),
    ).encode()).hexdigest()


def _challenge_check(expected: BehaviorChallenge, current: BehaviorReadback, now: datetime) -> str | None:
    if current.binding != expected.binding:
        return "behavior_current_binding_changed"
    if current.enforcement_mode not in ("block", "unknown"):
        return "behavior_mode_not_block"
    issued, expires = _time(expected.issued_at), _time(expected.expires_at)
    window_ms = (expires - issued).total_seconds() * 1000
    if not 0 < window_ms <= 300000 or window_ms < expected.attempts * 4 * expected.timeout_ms:
        return "behavior_window_invalid"
    if not issued <= now < expires:
        return "behavior_time_invalid"
    endpoint = f"{expected.receiver_ipv4}:{expected.receiver_port}"
    pairs = {(rule.endpoint, rule.program_path) for rule in current.allow_rules}
    if (expected.allow_path == expected.deny_path or len(pairs) != len(current.allow_rules)
        or (endpoint, expected.allow_path) not in pairs or (endpoint, expected.deny_path) in pairs):
        return "behavior_differential_invalid"
    return None


def validate_behavior_challenge(challenge: dict, current_readback: dict, *, now: datetime) -> tuple[bool, str]:
    """Pre-execution eligibility; caller still owns authorization and one-time claim."""
    if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
        return False, "behavior_clock_invalid"
    if type(challenge) is not dict or type(current_readback) is not dict:
        return False, "behavior_schema_invalid"
    try:
        expected = BehaviorChallenge.model_validate(challenge)
        current = BehaviorReadback.model_validate(current_readback)
    except (ValidationError, ValueError, TypeError):
        return False, "behavior_schema_invalid"
    reason = _challenge_check(expected, current, now)
    remaining_ms = (_time(expected.expires_at) - now).total_seconds() * 1000
    if not reason and remaining_ms < expected.attempts * 4 * expected.timeout_ms:
        reason = "behavior_window_remaining_insufficient"
    return (False, reason) if reason else (True, "behavior_challenge_eligible")


def validate_behavior_result(
    result: dict, challenge: dict, current_readback: dict, *, now: datetime, run_state: str,
) -> tuple[bool, str]:
    """Accept only bounded, fresh, correctly bound raw observations.

    `run_state` must be a locked durable state, not request data. A second call
    with the same invented `running` value cannot substitute for atomic consume.
    All failures return a fixed code, without echoing endpoints or inputs.
    """
    if run_state != "running":
        return False, "behavior_operation_not_running"
    if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
        return False, "behavior_clock_invalid"
    if any(type(value) is not dict for value in (result, challenge, current_readback)):
        return False, "behavior_schema_invalid"
    try:
        expected = BehaviorChallenge.model_validate(challenge)
        observed = BehaviorResult.model_validate(result)
        current = BehaviorReadback.model_validate(current_readback)
    except (ValidationError, ValueError, TypeError):
        return False, "behavior_schema_invalid"
    if observed.verification_id != expected.verification_id or observed.nonce != expected.nonce:
        return False, "behavior_challenge_mismatch"
    if observed.challenge_sha256 != challenge_digest(expected):
        return False, "behavior_challenge_digest_mismatch"
    if reason := _challenge_check(expected, current, now):
        return False, reason
    if observed.before != current or observed.after != current:
        return False, "behavior_readback_changed"
    issued, expires = _time(expected.issued_at), _time(expected.expires_at)
    started, finished = _time(observed.started_at), _time(observed.finished_at)
    if not issued <= started <= finished <= now < expires:
        return False, "behavior_time_invalid"
    endpoint = f"{expected.receiver_ipv4}:{expected.receiver_port}"
    if len(observed.observations) != expected.attempts * 4:
        return False, "behavior_observations_incomplete"
    previous = started
    kinds = ("control_before", "allow", "deny", "control_after")
    for index, item in enumerate(observed.observations):
        if item.round != index // 4 or item.kind != kinds[index % 4]:
            return False, "behavior_observation_order_invalid"
        if item.nonce != expected.nonce or item.endpoint != endpoint:
            return False, "behavior_observation_binding_mismatch"
        instant = _time(item.observed_at)
        if not previous <= instant <= finished or item.elapsed_ms > expected.timeout_ms + 1000:
            return False, "behavior_observation_time_invalid"
        previous = instant
        inside = item.kind in ("allow", "deny")
        program_path = expected.allow_path if item.kind == "allow" else expected.deny_path
        if (item.origin != ("sandbox_exec" if inside else "control_plane_host")
            or item.program_path != (program_path if inside else "")
            or item.program_sha256 != (expected.binding.probe_sha256 if inside else "")):
            return False, "behavior_program_identity_mismatch"
        if item.kind == "deny":
            if item.outcome not in ("connection_refused", "connection_reset", "timeout"):
                return False, "behavior_deny_not_observed"
        elif item.outcome != "connected":
            return False, "behavior_control_or_allow_failed"
    return True, "behavior_candidate_observations_accepted"
