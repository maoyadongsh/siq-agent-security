"""Single-use internal collection, with required live authorization callbacks.

No API route or deployment-grade promotion is provided here. The embedding
service owns authentication, target assignment and approved configuration.
"""
from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.adapters.openshell.behavior_channel import BehaviorProbeChannel
from app.adapters.openshell.behavior_journal import BehaviorFact, BehaviorJournal, BehaviorJournalError
from app.adapters.openshell.behavior_profiles import ApprovedBehaviorProfile, BehaviorProfile, load_behavior_profile
from app.adapters.openshell.behavior_protection import RootfulDockerProbeGuard
from app.adapters.openshell.behavior_protocol import (
    BehaviorChallengeV2,
    _time,
    challenge_digest,
    validate_behavior_challenge,
)
from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.target_mutex import target_mutex


def _wire_time(value: datetime) -> str:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise AdapterError("behavior_clock_invalid")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


class BehaviorCoordinator:
    def __init__(
        self, journal: BehaviorJournal, engine: Engine, adapter: OpenShellCliBackend, *,
        authorize: Callable[[BehaviorProfile], None],
        before_accept: Callable[[Session, BehaviorProfile], None],
        profile_loader=load_behavior_profile, guard_factory=RootfulDockerProbeGuard,
        channel_factory=BehaviorProbeChannel, clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        if (not callable(authorize) or not callable(before_accept)
            or not isinstance(adapter, OpenShellCliBackend)):
            raise AdapterError("behavior_authorizer_required")
        self.journal, self.engine, self.adapter = journal, engine, adapter
        self.authorize, self.before_accept = authorize, before_accept
        self.profile_loader, self.guard_factory, self.channel_factory = profile_loader, guard_factory, channel_factory
        self.clock = clock

    def _current_profile(self, original: ApprovedBehaviorProfile) -> None:
        current = self.profile_loader(original.profile.profile_id, now=self.clock())
        if current != original:
            raise AdapterError("behavior_profile_changed")

    def _readback(self, approved: ApprovedBehaviorProfile) -> dict:
        self._current_profile(approved)
        profile = approved.profile
        self.authorize(profile)
        caps = self.adapter.probe()
        if (caps.backend != "openshell" or not caps.handshake_verified
            or caps.endpoint_fingerprint != profile.binding.gateway_fingerprint
            or hashlib.sha256(caps.handshake_gateway.encode()).hexdigest() != profile.gateway_name_sha256):
            raise AdapterError("behavior_gateway_changed")
        snapshot = self.adapter.read_effective_policy(profile.binding.target)
        if snapshot.target != profile.binding.target:
            raise AdapterError("behavior_target_changed")
        protected = self.guard_factory(profile.protection.target()).verify()
        binding = profile.binding.model_dump()
        binding.update(policy_revision=snapshot.revision, policy_digest=snapshot.policy_digest,
                       protected_execution_sha256=protected["protected_execution_sha256"])
        # Empty, malformed or altered allow rules are rejected by the protocol.
        return {"binding": binding, "enforcement_mode": snapshot.enforcement_mode,
                "transport": profile.transport.model_dump(), "allow_rules": [
                    {"endpoint": rule["endpoint"], "program_path": path}
                    for rule in snapshot.network for path in rule["binary_paths"]]}

    def _existing(self, verification_id: str, approved: ApprovedBehaviorProfile) -> BehaviorFact | None:
        profile = approved.profile
        try:
            fact = self.journal.read(verification_id)
        except BehaviorJournalError as error:
            if str(error) != "behavior_operation_unknown":
                raise
            return None
        expected = self._challenge(profile, verification_id, nonce=fact.challenge["nonce"],
                                   issued_at=fact.challenge["issued_at"], expires_at=fact.challenge["expires_at"])
        if (fact.challenge != expected.model_dump()
            or (fact.profile_id, fact.profile_sha256) != (profile.profile_id, approved.file_sha256)):
            raise AdapterError("behavior_profile_operation_conflict")
        # A crash between prepare and claim is deliberately not resumed by POST.
        # A caller must create a new ID, preventing surprising probe replay.
        return self.journal.expire(verification_id)

    def _challenge(self, profile, verification_id, *, nonce, issued_at, expires_at):
        return BehaviorChallengeV2.model_validate({
            "schema_version": "openshell-behavior-challenge/v2", "verification_id": verification_id,
            "nonce": nonce, "binding": profile.binding.model_dump(), "transport": profile.transport.model_dump(),
            "receiver_ipv4": profile.receiver_ipv4, "receiver_port": profile.receiver_port,
            "allow_path": profile.allow_path, "deny_path": profile.deny_path,
            "attempts": profile.attempts, "timeout_ms": profile.timeout_ms,
            "issued_at": issued_at, "expires_at": expires_at,
        })

    def assess(self, verification_id: str) -> tuple[bool, str, datetime]:
        """Recheck current target facts without creating or replaying a probe."""
        fact = self.journal.read(verification_id)
        now = self.clock()
        if fact.state != "accepted":
            return False, "behavior_operation_not_accepted", now
        if now >= _time(fact.challenge["expires_at"]):
            return False, "behavior_evidence_expired", now
        if fact.profile_id is None:
            return False, "behavior_profile_reference_missing", now
        approved = self.profile_loader(fact.profile_id, now=now)
        profile = approved.profile
        expected = self._challenge(profile, verification_id, nonce=fact.challenge["nonce"],
            issued_at=fact.challenge["issued_at"], expires_at=fact.challenge["expires_at"])
        if fact.challenge != expected.model_dump() or fact.profile_sha256 != approved.file_sha256:
            return False, "behavior_profile_changed", now
        self.authorize(profile)
        with target_mutex(self.engine, profile.binding.gateway_fingerprint, profile.binding.target):
            current = self._readback(approved)
            return self.journal.assess(verification_id, current,
                before_accept=lambda session: self.before_accept(session, profile))

    def run(self, profile_id: str, verification_id: str, *, expected_profile_sha256: str | None = None) -> BehaviorFact:
        if not isinstance(verification_id, str) or not re.fullmatch(r"opv-[a-f0-9]{32}", verification_id):
            raise AdapterError("behavior_verification_id_invalid")
        approved = self.profile_loader(profile_id, now=self.clock())
        if expected_profile_sha256 is not None and approved.file_sha256 != expected_profile_sha256:
            raise AdapterError("behavior_profile_changed")
        profile = approved.profile
        if (profile.binding.tenant_id != self.journal.tenant_id
            or profile.binding.deployment_id != self.journal.deployment_id):
            raise AdapterError("behavior_profile_scope_mismatch")
        self.authorize(profile)
        with target_mutex(self.engine, profile.binding.gateway_fingerprint, profile.binding.target):
            existing = self._existing(verification_id, approved)
            if existing is not None:
                return existing
            before = self._readback(approved)
            now = self.clock()
            challenge = self._challenge(profile, verification_id, nonce=secrets.token_hex(32),
                                        issued_at=_wire_time(now),
                                        expires_at=_wire_time(min(now + timedelta(minutes=5),
                                                                  _time(profile.expires_at))))
            raw = challenge.model_dump()
            valid, reason = validate_behavior_challenge(raw, before, now=now)
            if not valid:
                raise AdapterError(reason)
            self.journal.prepare(raw, before, profile_id=profile.profile_id, profile_sha256=approved.file_sha256)
            self._current_profile(approved)
            self.authorize(profile)
            claim = self.journal.claim(verification_id, before)
            if claim is None:
                return self.journal.read(verification_id)
            try:
                # Claim and its audit are committed before either TCP transport.
                started = _wire_time(self.clock())
                channel = self.channel_factory(self.adapter._build_command, clock=self.clock)
                observations = []
                for round_index in range(profile.attempts):
                    for kind in ("control_before", "allow", "deny", "control_after"):
                        if self._readback(approved) != before:
                            raise AdapterError("behavior_readback_changed")
                        if kind in ("allow", "deny"):
                            item = channel.run_arm(challenge, round_index=round_index, kind=kind,
                                                   expected_uid=profile.protection.uid)
                        else:
                            item = channel.control(challenge, round_index=round_index, kind=kind)
                        observations.append(item)
                after = self._readback(approved)
                result = {"schema_version": "openshell-behavior-result/v3",
                          "verification_id": verification_id, "nonce": challenge.nonce,
                          "challenge_sha256": challenge_digest(challenge), "started_at": started,
                          "finished_at": _wire_time(self.clock()), "before": before, "after": after,
                          "observations": observations}
                return self.journal.finish(claim, result, after,
                    before_accept=lambda session: self.before_accept(session, profile))
            except Exception:  # noqa: BLE001 - no backend paths, credentials or parser details escape.
                try:
                    return self.journal.abandon(claim)
                except Exception:
                    # Audit/database failure preserves running; no invented terminal state.
                    raise AdapterError("behavior_collection_unconfirmed") from None
