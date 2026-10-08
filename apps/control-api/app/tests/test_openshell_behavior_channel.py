"""Real Linux ELF/TCP observations; sandbox command wrapping is a local fixture."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.adapters.openshell.behavior_channel import BehaviorProbeChannel, parse_agent_observation
from app.adapters.openshell.behavior_protocol import BehaviorChallenge, challenge_digest, validate_behavior_result
from app.adapters.openshell.contracts import AdapterError
from app.tests.test_openshell_behavior_protocol import documents as documents

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def elf(tmp_path_factory):
    if sys.platform != "linux" or os.getuid() == 0 or not shutil.which("go"):
        pytest.skip("native Linux non-root user and Go compiler required for real ELF checks")
    root = tmp_path_factory.mktemp("behavior-elf")
    binary = root / "allow"
    env = {**os.environ, "CGO_ENABLED": "0", "GOWORK": "off", "GOPROXY": "off", "GOTOOLCHAIN": "local",
           "GOOS": "linux", "GOARCH": {"aarch64": "arm64", "x86_64": "amd64"}[platform.machine()], "GOFLAGS": ""}
    built = subprocess.run([shutil.which("go"), "build", "-trimpath", "-buildvcs=false", "-o", str(binary),
                            str(ROOT / "scripts/enterprise-experience/probe/behavior_probe.go")],
                           capture_output=True, env=env, timeout=90)
    assert built.returncode == 0, built.stderr.decode()
    shutil.copyfile(binary, root / "deny")
    (root / "deny").chmod(0o755)
    return binary


@contextmanager
def receiver(mode="echo"):
    received = []
    stop = threading.Event()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    server.settimeout(0.1)
    endpoint = server.getsockname()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with conn:
                conn.settimeout(1)
                payload = bytearray()
                try:
                    while len(payload) < 128 and not payload.endswith(b"\n"):
                        part = conn.recv(128 - len(payload))
                        if not part:
                            break
                        payload.extend(part)
                    received.append(bytes(payload))
                    if mode == "echo":
                        # Fragmentation must not turn a correct response into a failure.
                        conn.sendall(payload[:7])
                        conn.sendall(payload[7:])
                    elif mode == "wrong":
                        conn.sendall(b"x" * len(payload))
                    elif mode == "silent":
                        stop.wait(0.3)
                    elif mode == "reset":
                        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                except OSError:
                    pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield endpoint, received
    finally:
        stop.set()
        server.close()
        thread.join(timeout=2)
        assert not thread.is_alive()


def challenge_for(documents, endpoint, elf=None, *, timeout=1000):
    raw = copy.deepcopy(documents[0])
    now = datetime.now(UTC)
    raw.update(receiver_ipv4=endpoint[0], receiver_port=endpoint[1], timeout_ms=timeout,
               issued_at=(now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
               expires_at=(now + timedelta(minutes=4)).isoformat().replace("+00:00", "Z"))
    if elf:
        raw.update(allow_path=str(elf), deny_path=str(elf.with_name("deny")))
        raw["binding"]["probe_sha256"] = hashlib.sha256(elf.read_bytes()).hexdigest()
    return BehaviorChallenge.model_validate(raw)


def local_exec(args):
    # Only the transport is under test here. This never claims OpenShell enforcement.
    return args[args.index("--") + 1:]


def agent_document(challenge):
    return {"schema_version": "openshell-behavior-agent/v1", "verification_id": challenge.verification_id,
            "nonce": challenge.nonce, "endpoint": f"{challenge.receiver_ipv4}:{challenge.receiver_port}",
            "program_path": challenge.allow_path, "program_sha256": challenge.binding.probe_sha256,
            "uid": 1000, "outcome": "connected", "elapsed_ms": 1}


def test_actual_static_elf_and_two_paths_report_exact_identity_and_echo(elf, documents):
    raw = elf.read_bytes()
    assert raw[:6] == b"\x7fELF\x02\x01"
    offset = struct.unpack_from("<Q", raw, 32)[0]
    entry_size, count = struct.unpack_from("<HH", raw, 54)
    assert not any(struct.unpack_from("<I", raw, offset + i * entry_size)[0] == 3 for i in range(count))
    assert raw == elf.with_name("deny").read_bytes()
    with receiver() as (endpoint, received):
        challenge = challenge_for(documents, endpoint, elf)
        channel = BehaviorProbeChannel(local_exec)
        for kind in ("allow", "deny"):
            observed = channel.run_arm(challenge, round_index=0, kind=kind, expected_uid=os.getuid())
            assert observed["outcome"] == "connected"  # Local fixture has no sandbox policy.
            assert observed["program_path"] == getattr(challenge, kind + "_path")
        assert len(received) == 2
        marker = f"SIQ-BEHAVIOR/1 {challenge.verification_id} {challenge.nonce}\n".encode()
        assert all(data == marker for data in received)


def test_actual_program_output_matches_wire_schema(elf, documents):
    with receiver() as (endpoint, _):
        challenge = challenge_for(documents, endpoint, elf)
        command = [str(elf), challenge.verification_id, challenge.nonce, endpoint[0], str(endpoint[1]), "1000"]
        result = subprocess.run(command, capture_output=True, timeout=3)
    assert result.returncode == 0 and result.stderr == b""
    report = json.loads(result.stdout)
    schema = json.loads((ROOT / "packages/contracts/openshell-behavior-agent.v1.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)
    assert report["uid"] == os.getuid() and report["program_sha256"] == hashlib.sha256(elf.read_bytes()).hexdigest()


def test_real_local_three_arm_run_without_enforcement_cannot_pass_validator(elf, documents):
    with receiver() as (endpoint, received):
        challenge = challenge_for(documents, endpoint, elf)
        channel = BehaviorProbeChannel(local_exec)
        readback = {"binding": challenge.binding.model_dump(), "enforcement_mode": "unknown", "allow_rules": [
            {"endpoint": f"{endpoint[0]}:{endpoint[1]}", "program_path": str(elf)},
        ]}
        started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        observations = []
        for round_index in range(3):
            for kind in ("control_before", "allow", "deny", "control_after"):
                if kind in ("allow", "deny"):
                    observations.append(channel.run_arm(challenge, round_index=round_index, kind=kind,
                                                         expected_uid=os.getuid()))
                else:
                    observations.append(channel.control(challenge, round_index=round_index, kind=kind))
        result = {"schema_version": "openshell-behavior-result/v2", "verification_id": challenge.verification_id,
                  "nonce": challenge.nonce, "challenge_sha256": challenge_digest(challenge), "started_at": started,
                  "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                  "before": readback, "after": readback, "observations": observations}
        assert len(received) == 12 and all(item["outcome"] == "connected" for item in observations)
        assert validate_behavior_result(result, challenge.model_dump(), readback, now=datetime.now(UTC),
                                        run_state="running") == (False, "behavior_deny_not_observed")


@pytest.mark.parametrize("mode,expected", [("wrong", "probe_error"), ("eof", "probe_error"),
                                          ("silent", "timeout"), ("reset", "connection_reset")])
def test_connected_socket_without_valid_receiver_echo_is_not_success(elf, documents, mode, expected):
    with receiver(mode) as (endpoint, _):
        challenge = challenge_for(documents, endpoint, elf, timeout=100)
        observed = BehaviorProbeChannel(local_exec).run_arm(challenge, round_index=0, kind="allow",
                                                            expected_uid=os.getuid())
        assert observed["outcome"] == expected


def test_refused_tcp_is_raw_observation_not_enforcement_verdict(elf, documents):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))  # Bound but not listening; port cannot be stolen by another listener.
        challenge = challenge_for(documents, reserved.getsockname(), elf)
        observed = BehaviorProbeChannel(local_exec).run_arm(challenge, round_index=0, kind="deny",
                                                            expected_uid=os.getuid())
        assert observed["outcome"] == "connection_refused"


@pytest.mark.parametrize("mode,expected", [("echo", "connected"), ("wrong", "probe_error"),
                                          ("eof", "probe_error"), ("silent", "timeout")])
def test_host_control_requires_same_bounded_echo_protocol(documents, mode, expected):
    with receiver(mode) as (endpoint, received):
        challenge = challenge_for(documents, endpoint, timeout=100)
        result = BehaviorProbeChannel(local_exec).control(challenge, round_index=1, kind="control_before")
        assert result["outcome"] == expected and result["origin"] == "control_plane_host"
        assert result["program_path"] == result["program_sha256"] == ""
        assert len(received) == 1 and len(received[0]) <= 128


@pytest.mark.parametrize("field,value", [("nonce", "f" * 64), ("verification_id", "opv-" + "f" * 32),
    ("endpoint", "127.0.0.2:8443"), ("program_path", "/tmp/wrong"), ("program_sha256", "f" * 64),
    ("uid", 1001), ("uid", 0), ("uid", True), ("outcome", "success"), ("elapsed_ms", True), ("elapsed_ms", 2001)])
def test_wrong_or_coerced_identity_is_never_transferred(documents, field, value):
    challenge = BehaviorChallenge.model_validate(documents[0])
    report = agent_document(challenge)
    report[field] = value
    with pytest.raises(AdapterError):
        parse_agent_observation(json.dumps(report), challenge, kind="allow", expected_uid=1000)


@pytest.mark.parametrize("bad", ["duplicate", "extra", "oversized", "trailing", "nan", "surrogate"])
def test_noncanonical_json_output_never_becomes_observation(documents, bad):
    challenge = BehaviorChallenge.model_validate(documents[0])
    report = agent_document(challenge)
    raw = json.dumps(report)
    if bad == "duplicate":
        raw = raw[:-1] + ',"uid":1000}'
    elif bad == "extra":
        raw = raw[:-1] + ',"api_key":"synthetic-secret"}'
    elif bad == "oversized":
        raw += " " * 4096
    elif bad == "trailing":
        raw += "\n{}"
    elif bad == "nan":
        raw = raw.replace('"elapsed_ms": 1', '"elapsed_ms": NaN')
    else:
        raw += "\ud800"
    with pytest.raises(AdapterError, match="behavior_agent_report_invalid") as error:
        parse_agent_observation(raw, challenge, kind="allow", expected_uid=1000)
    assert "synthetic-secret" not in str(error.value)


def test_fixed_exec_template_and_failed_exit_cannot_forge_observation(documents):
    challenge = BehaviorChallenge.model_validate(documents[0])
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return 1, json.dumps(agent_document(challenge)), "synthetic-secret"

    channel = BehaviorProbeChannel(lambda args: ["/trusted/openshell", *args], runner=runner,
                                   clock=lambda: datetime(2026, 10, 8, tzinfo=UTC))
    with pytest.raises(AdapterError, match="behavior_agent_command_failed"):
        channel.run_arm(challenge, round_index=0, kind="allow", expected_uid=1000)
    assert calls[0][0] == ["/trusted/openshell", "sandbox", "exec", "--name", challenge.binding.target,
                           "--no-tty", "--timeout", "6", "--", challenge.allow_path,
                           challenge.verification_id, challenge.nonce, challenge.receiver_ipv4, "8443", "1000"]
    assert calls[0][1] == {"timeout": 6, "limit": 4096}


def test_expired_challenge_never_starts_program_or_control(documents):
    challenge = BehaviorChallenge.model_validate(documents[0])
    calls = []
    channel = BehaviorProbeChannel(lambda args: calls.append(args), clock=lambda: datetime(2026, 10, 9, tzinfo=UTC))
    for action in (lambda: channel.run_arm(challenge, round_index=0, kind="allow", expected_uid=1000),
                   lambda: channel.control(challenge, round_index=0, kind="control_after")):
        with pytest.raises(AdapterError, match="behavior_deadline_expired"):
            action()
    assert calls == []


@pytest.mark.parametrize("position,value", [(0, "opv-bad"), (1, "bad-nonce"), (2, "localhost"),
                                          (2, "::1"), (3, "+1234"), (3, "0"), (4, "99"), (4, "10001")])
def test_invalid_program_input_has_no_connection_and_redacted_error(elf, position, value):
    with receiver() as (endpoint, received):
        args = ["opv-" + "a" * 32, "b" * 64, endpoint[0], str(endpoint[1]), "1000"]
        args[position] = value
        result = subprocess.run([str(elf), *args], capture_output=True, timeout=3)
        assert result.returncode == 2 and result.stdout == b"" and result.stderr == b"behavior_probe_invalid\n"
        assert received == []
