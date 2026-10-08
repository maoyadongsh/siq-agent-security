"""Real durable transactions/mutex/profile files; simulated external observations."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.adapters.openshell import behavior_journal as journal_module
from app.adapters.openshell.behavior_coordinator import BehaviorCoordinator
from app.adapters.openshell.behavior_profiles import MAX_BYTES, BehaviorProfile, load_behavior_profile
from app.adapters.openshell.cli_backend import OpenShellCliBackend
from app.adapters.openshell.contracts import AdapterError
from app.models import Deployment, OpenShellBehaviorOperation
from app.tests.test_openshell_behavior_journal import CLAIM_TIME, audit_count, journal
from app.tests.test_openshell_behavior_journal import ready as ready
from app.tests.test_openshell_behavior_protocol import NOW
from app.tests.test_openshell_behavior_protocol import documents as documents
from app.tests.test_operation_journal import database as database

ROOT = Path(__file__).resolve().parents[4]
ID = "opv-" + "f" * 32


@pytest.fixture
def configured(ready, tmp_path, monkeypatch):
    c = ready[0]
    p = {k: copy.deepcopy(v) for k, v in c.items() if k not in ("schema_version", "verification_id", "nonce")}
    p.update(profile_id="test", gateway_name_sha256=hashlib.sha256(b"test-gateway").hexdigest(),
             transport={"mode": "http_connect", "proxy_ipv4": "10.200.0.1", "proxy_port": 3128},
             protection={"container_id": "a" * 64, "image_digest": c["binding"]["image_digest"],
                         "namespace": "test", "sandbox_name": c["binding"]["target"], "sandbox_id": "test-id",
                         "uid": 998, "allow_path": c["allow_path"], "deny_path": c["deny_path"],
                         "probe_sha256": c["binding"]["probe_sha256"], "supervisor_profile": "openshell-rootful-v0"})
    profile = BehaviorProfile.model_validate(p)
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"schema_version": "openshell-behavior-profiles/v1", "profiles": [p]}))
    path.chmod(0o600)
    monkeypatch.setenv("SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE", str(path))
    return profile, path


@pytest.fixture
def rig(database, configured):
    profile, path = configured
    calls, auths, final = [], [], []
    adapter = OpenShellCliBackend(runner=lambda _: (0, "", ""), env_script="")
    caps = SimpleNamespace(backend="openshell", handshake_verified=True, handshake_gateway="test-gateway",
                           endpoint_fingerprint=profile.binding.gateway_fingerprint)
    snapshot = SimpleNamespace(target=profile.binding.target, revision=profile.binding.policy_revision,
                               policy_digest=profile.binding.policy_digest, enforcement_mode="unknown",
                               network=[{"endpoint": f"{profile.receiver_ipv4}:{profile.receiver_port}",
                                         "binary_paths": [profile.allow_path]}])
    adapter.probe = lambda: caps
    adapter.read_effective_policy = lambda _: snapshot

    class Guard:
        def __init__(self, target):
            assert target == profile.protection.target()

        def verify(self):
            return {"protected_execution_sha256": profile.binding.protected_execution_sha256}

    class Channel:
        def __init__(self, *args, **kwargs):
            pass

        def run_arm(self, challenge, *, round_index, kind, expected_uid):
            assert expected_uid == 998
            return self.control(challenge, round_index=round_index, kind=kind)

        def control(self, challenge, *, round_index, kind):
            with database() as session:
                row = session.get(OpenShellBehaviorOperation, ID)
                assert row.state == "running" and row.epoch == 1
            assert audit_count(database) == 2
            calls.append(kind)
            inside, denied = kind in ("allow", "deny"), kind == "deny"
            return {"round": round_index, "kind": kind, "nonce": challenge.nonce,
                    "origin": "sandbox_exec" if inside else "control_plane_host",
                    "endpoint": f"{profile.receiver_ipv4}:{profile.receiver_port}",
                    "program_path": (profile.allow_path if kind == "allow" else profile.deny_path) if inside else "",
                    "program_sha256": profile.binding.probe_sha256 if inside else "",
                    "transport": "http_connect" if inside else "direct_tcp",
                    "proxy_endpoint": "10.200.0.1:3128" if inside else "",
                    "proxy_status": 403 if denied else 200 if inside else 0,
                    "proxy_error": "policy_denied" if denied else "",
                    "outcome": "proxy_denied" if denied else "connected", "elapsed_ms": 1,
                    "observed_at": CLAIM_TIME.isoformat().replace("+00:00", "Z")}

    def before_accept(session, value):
        assert session.in_transaction() and value == profile
        row = session.get(OpenShellBehaviorOperation, ID)
        assert row.state == "running"
        final.append(True)

    coordinator = BehaviorCoordinator(journal(database), database.kw["bind"], adapter,
        authorize=lambda value: auths.append(value.profile_id), before_accept=before_accept,
        guard_factory=Guard, channel_factory=Channel, clock=lambda: CLAIM_TIME)
    return SimpleNamespace(coordinator=coordinator, profile=profile, path=path, calls=calls, auths=auths,
                           final=final, caps=caps, snapshot=snapshot, channel=Channel)


def test_profile_schema_and_file(configured):
    profile, path = configured
    approved = load_behavior_profile("test", now=NOW)
    assert approved.profile == profile
    assert approved.file_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    schema = json.loads((ROOT / "packages/contracts/openshell-behavior-profiles.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(json.loads(path.read_text()))


@pytest.mark.parametrize("fault", ["symlink", "hardlink", "writable", "parent_symlink", "parent_writable",
                                    "oversize", "duplicate", "expired", "missing", "ambiguous", "identity"])
def test_unsafe_operator_profile_rejected(configured, tmp_path, monkeypatch, fault):
    profile, path = configured
    now = NOW
    if fault == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(path)
        monkeypatch.setenv("SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE", str(link))
    elif fault == "hardlink":
        os.link(path, tmp_path / "link.json")
    elif fault == "writable":
        path.chmod(0o666)
    elif fault == "parent_symlink":
        link = tmp_path / "dirlink"
        link.symlink_to(path.parent, target_is_directory=True)
        monkeypatch.setenv("SIQ_AS_OPENSHELL_BEHAVIOR_PROFILES_FILE", str(link / path.name))
    elif fault == "parent_writable":
        tmp_path.chmod(0o777)
    elif fault == "oversize":
        path.write_bytes(b"x" * (MAX_BYTES + 1))
    elif fault == "duplicate":
        path.write_text('{"schema_version":"ignored",' + path.read_text()[1:])
    elif fault == "expired":
        now += timedelta(days=1)
    elif fault == "missing":
        path.unlink()
    else:
        value = json.loads(path.read_text())
        if fault == "ambiguous":
            value["profiles"].append(value["profiles"][0])
        else:
            value["profiles"][0]["protection"]["sandbox_name"] = "wrong"
        path.write_text(json.dumps(value))
    try:
        with pytest.raises(AdapterError, match="^behavior_profile_unavailable$"):
            load_behavior_profile("test", now=now)
    finally:
        tmp_path.chmod(0o700)


def test_whole_collection_commits_before_traffic_and_never_replays(database, rig):
    fact = rig.coordinator.run("test", ID)
    assert fact.state == "accepted" and len(rig.calls) == 12 and rig.final == [True]
    assert len(rig.auths) == 16
    again = rig.coordinator.run("test", ID)
    assert again == fact and len(rig.calls) == 12 and audit_count(database) == 3
    with database() as session:
        assert session.get(Deployment, rig.profile.binding.deployment_id).verification == {"level": "readback_verified"}


@pytest.mark.parametrize("fault", ["gateway", "policy", "protection", "authorization", "profile"])
def test_mid_collection_change_stops_before_next_arm(database, rig, fault):
    original = rig.channel.control

    def changed(self, *args, **kwargs):
        item = original(self, *args, **kwargs)
        if fault == "gateway":
            rig.caps.endpoint_fingerprint = "e" * 64
        elif fault == "policy":
            rig.snapshot.revision = "99"
        elif fault == "protection":
            rig.coordinator.guard_factory = lambda _: SimpleNamespace(
                verify=lambda: {"protected_execution_sha256": "e" * 64})
        elif fault == "authorization":
            def denied(_):
                raise AdapterError("revoked")
            rig.coordinator.authorize = denied
        else:
            rig.path.write_text(rig.path.read_text() + "\n")
        return item

    rig.channel.control = changed
    fact = rig.coordinator.run("test", ID)
    assert fact.state == "unknown" and len(rig.calls) == 1 and not rig.final
    assert audit_count(database) == 3


def test_final_authorization_denial_prevents_acceptance(database, rig):
    def denied(session, profile):
        raise AdapterError("revoked")
    rig.coordinator.before_accept = denied
    fact = rig.coordinator.run("test", ID)
    assert fact.state == "unknown" and len(rig.calls) == 12
    assert audit_count(database) == 3


def test_no_traffic_if_preparation_audit_fails(database, rig, monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(journal_module, "audit", failed)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        rig.coordinator.run("test", ID)
    assert not rig.calls
    with database() as session:
        assert session.get(OpenShellBehaviorOperation, ID) is None


def test_no_replay_when_final_audit_and_abandon_fail(database, rig, monkeypatch):
    original = journal_module.audit
    def fail_terminal(*args, **kwargs):
        if args[4] in ("openshell.behavior.accepted", "openshell.behavior.unknown"):
            raise RuntimeError("synthetic terminal audit failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(journal_module, "audit", fail_terminal)
    with pytest.raises(AdapterError, match="^behavior_collection_unconfirmed$"):
        rig.coordinator.run("test", ID)
    assert len(rig.calls) == 12
    monkeypatch.setattr(journal_module, "audit", original)
    fact = rig.coordinator.run("test", ID)
    assert fact.state == "running" and len(rig.calls) == 12 and audit_count(database) == 2


def test_prepared_crash_is_not_a_network_retry(database, rig):
    c = rig.coordinator._challenge(rig.profile, ID, nonce="e" * 64,
                                  issued_at=rig.profile.issued_at, expires_at=rig.profile.expires_at)
    before = rig.coordinator._readback(load_behavior_profile("test", now=NOW))
    approved = load_behavior_profile("test", now=NOW)
    rig.coordinator.journal.prepare(c.model_dump(), before, profile_id="test", profile_sha256=approved.file_sha256)
    fact = rig.coordinator.run("test", ID)
    assert fact.state == "prepared" and not rig.calls


def test_concurrent_coordinators_share_persistent_target_mutex(database, rig):
    entered, release = threading.Event(), threading.Event()
    original = rig.channel.control
    def waiting(self, *args, **kwargs):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(self, *args, **kwargs)
    rig.channel.control = waiting
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(rig.coordinator.run, "test", ID)
        assert entered.wait(3)
        second = pool.submit(rig.coordinator.run, "test", ID)
        release.set()
        a, b = first.result(5), second.result(5)
    assert a == b and a.state == "accepted" and len(rig.calls) == 12


def test_expiry_during_final_authorization_is_not_accepted(database, rig):
    def slow_authorization(session, profile):
        rig.coordinator.journal.clock = lambda: CLAIM_TIME + timedelta(minutes=6)
    rig.coordinator.before_accept = slow_authorization
    fact = rig.coordinator.run("test", ID)
    assert fact.state == "unknown" and fact.reason_code == "behavior_deadline_expired"
    assert len(rig.calls) == 12 and audit_count(database) == 3


def test_initial_denial_cannot_create_operation_or_send_probe(database, rig):
    def denied(_):
        raise AdapterError("permission_denied")
    rig.coordinator.authorize = denied
    with pytest.raises(AdapterError, match="permission_denied"):
        rig.coordinator.run("test", ID)
    assert not rig.calls and audit_count(database) == 0
    with database() as session:
        assert session.get(OpenShellBehaviorOperation, ID) is None
