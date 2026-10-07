"""Fixed ELF/echo transport for ADR-058; no authorization or policy verdict.

The caller must own a durable running claim and independently attest the target,
protected ELF paths and expected UID. Self-reported identity is only compared
with that trusted expectation. This transport alone cannot promote a deployment.
"""

from __future__ import annotations

import json
import math
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from app.adapters.openshell.behavior_protocol import (
    BehaviorChallenge,
    Digest,
    Endpoint,
    ProbeID,
    ProgramPath,
    Wire,
)
from app.adapters.openshell.bounded_command import run_bounded
from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.probe_channel import build_exec_args, classify_socket_error


class AgentObservation(Wire):
    schema_version: Literal["openshell-behavior-agent/v1"]
    verification_id: ProbeID
    nonce: Digest
    endpoint: Endpoint
    program_path: ProgramPath
    program_sha256: Digest
    uid: Annotated[int, Field(ge=1, le=4294967294)]
    outcome: Literal["connected", "timeout", "connection_refused", "connection_reset", "probe_error"]
    elapsed_ms: Annotated[int, Field(ge=0, le=11000)]


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate key")
        obj[key] = value
    return obj


def parse_agent_observation(
    stdout: str, challenge: BehaviorChallenge, *, kind: str, expected_uid: int,
) -> AgentObservation:
    """Strict transfer of raw observations, never inference from stderr/exit code."""
    if (kind not in ("allow", "deny") or type(expected_uid) is not int or not 1 <= expected_uid <= 4294967294
        or not isinstance(stdout, str) or len(stdout) > 4096):
        raise AdapterError("behavior_agent_report_invalid")
    try:
        if len(stdout.encode("utf-8")) > 4096:
            raise ValueError("oversized report")
        raw = json.loads(stdout, object_pairs_hook=_unique_object)
        report = AgentObservation.model_validate(raw)
    except (ValueError, TypeError, ValidationError, RecursionError):
        raise AdapterError("behavior_agent_report_invalid") from None
    expected_path = challenge.allow_path if kind == "allow" else challenge.deny_path
    if (report.verification_id != challenge.verification_id or report.nonce != challenge.nonce
        or report.endpoint != f"{challenge.receiver_ipv4}:{challenge.receiver_port}"
        or report.program_path != expected_path or report.program_sha256 != challenge.binding.probe_sha256
        or report.uid != expected_uid or report.elapsed_ms > challenge.timeout_ms + 1000):
        raise AdapterError("behavior_agent_identity_mismatch")
    return report


def _remaining(challenge: BehaviorChallenge, now: datetime) -> float:
    if not isinstance(now, datetime) or now.utcoffset() is None or now.utcoffset().total_seconds() != 0:
        raise AdapterError("behavior_clock_invalid")
    issued = datetime.fromisoformat(challenge.issued_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(challenge.expires_at.replace("Z", "+00:00"))
    if not issued <= now < expires:
        raise AdapterError("behavior_deadline_expired")
    return (expires - now).total_seconds()


def _observation(challenge, *, round_index, kind, outcome, elapsed_ms, observed_at):
    if type(round_index) is not int or not 0 <= round_index < challenge.attempts:
        raise AdapterError("behavior_round_invalid")
    _remaining(challenge, observed_at)
    inside = kind in ("allow", "deny")
    return {"round": round_index, "kind": kind, "nonce": challenge.nonce,
            "origin": "sandbox_exec" if inside else "control_plane_host",
            "endpoint": f"{challenge.receiver_ipv4}:{challenge.receiver_port}",
            "program_path": (challenge.allow_path if kind == "allow" else challenge.deny_path) if inside else "",
            "program_sha256": challenge.binding.probe_sha256 if inside else "",
            "outcome": outcome, "elapsed_ms": elapsed_ms,
            "observed_at": observed_at.isoformat(timespec="microseconds").replace("+00:00", "Z")}


class BehaviorProbeChannel:
    def __init__(self, command_builder: Callable[[list[str]], list[str]], *, runner=run_bounded,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.build_command, self.runner, self.clock = command_builder, runner, clock

    def run_arm(self, challenge: BehaviorChallenge, *, round_index: int, kind: str, expected_uid: int) -> dict:
        if kind not in ("allow", "deny") or type(round_index) is not int or not 0 <= round_index < challenge.attempts:
            raise AdapterError("behavior_round_invalid")
        if type(expected_uid) is not int or not 1 <= expected_uid <= 4294967294:
            raise AdapterError("behavior_agent_identity_mismatch")
        remaining = _remaining(challenge, self.clock())
        if remaining < challenge.timeout_ms / 1000:
            raise AdapterError("behavior_window_remaining_insufficient")
        path = challenge.allow_path if kind == "allow" else challenge.deny_path
        command = [path, challenge.verification_id, challenge.nonce, challenge.receiver_ipv4,
                   str(challenge.receiver_port), str(challenge.timeout_ms)]
        budget = min(remaining, challenge.timeout_ms / 1000 + 5)
        argv = self.build_command(build_exec_args(challenge.binding.target, command, timeout=math.ceil(budget)))
        code, stdout, _ = self.runner(argv, timeout=budget, limit=4096)
        if code != 0:
            raise AdapterError("behavior_agent_command_failed")
        report = parse_agent_observation(stdout, challenge, kind=kind, expected_uid=expected_uid)
        return _observation(challenge, round_index=round_index, kind=kind, outcome=report.outcome,
                            elapsed_ms=report.elapsed_ms, observed_at=self.clock())

    def control(self, challenge: BehaviorChallenge, *, round_index: int, kind: str) -> dict:
        if (kind not in ("control_before", "control_after") or type(round_index) is not int
            or not 0 <= round_index < challenge.attempts):
            raise AdapterError("behavior_round_invalid")
        remaining = _remaining(challenge, self.clock())
        if remaining < challenge.timeout_ms / 1000:
            raise AdapterError("behavior_window_remaining_insufficient")
        marker = f"SIQ-BEHAVIOR/1 {challenge.verification_id} {challenge.nonce}\n".encode("ascii")
        started = time.monotonic()
        deadline = started + challenge.timeout_ms / 1000
        outcome = "probe_error"
        try:
            # Numeric canonical IPv4 and AF_INET avoid DNS and address fallback.
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(max(0.001, deadline - time.monotonic()))
                sock.connect((challenge.receiver_ipv4, challenge.receiver_port))
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError
                sock.settimeout(left)
                sock.sendall(marker)
                received = bytearray()
                while len(received) < len(marker):
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError
                    sock.settimeout(left)
                    chunk = sock.recv(len(marker) - len(received))
                    if not chunk:
                        break
                    received.extend(chunk)
                if received == marker:
                    outcome = "connected"
        except OSError as error:
            outcome = classify_socket_error(error)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if elapsed_ms > challenge.timeout_ms + 1000:
            raise AdapterError("behavior_agent_deadline_exceeded")
        return _observation(challenge, round_index=round_index, kind=kind, outcome=outcome,
                            elapsed_ms=elapsed_ms, observed_at=self.clock())
