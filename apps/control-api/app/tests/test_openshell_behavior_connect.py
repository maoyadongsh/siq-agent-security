"""Real local ELF/CONNECT transport; synthetic proxy is not OpenShell evidence."""
from __future__ import annotations

import copy
import json
import os
import socket
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.adapters.openshell.behavior_channel import BehaviorProbeChannel, parse_agent_observation
from app.adapters.openshell.behavior_protocol import (
    BehaviorChallengeV2,
    challenge_digest,
    parse_behavior_challenge,
    validate_behavior_challenge,
    validate_behavior_result,
)
from app.adapters.openshell.contracts import AdapterError
from app.tests.test_openshell_behavior_channel import challenge_for, local_exec
from app.tests.test_openshell_behavior_channel import elf as elf
from app.tests.test_openshell_behavior_journal import audit_count, finish, journal
from app.tests.test_openshell_behavior_journal import ready as ready
from app.tests.test_openshell_behavior_protocol import NOW
from app.tests.test_openshell_behavior_protocol import documents as documents
from app.tests.test_operation_journal import database as database

ROOT = Path(__file__).resolve().parents[4]


def connect_documents(documents):
    challenge, result, current = copy.deepcopy(documents)
    transport = {"mode": "http_connect", "proxy_ipv4": "10.200.0.1", "proxy_port": 3128}
    challenge.update(schema_version="openshell-behavior-challenge/v2", transport=transport)
    current["transport"] = copy.deepcopy(transport)
    result.update(schema_version="openshell-behavior-result/v3", before=copy.deepcopy(current),
                  after=copy.deepcopy(current), challenge_sha256=challenge_digest(parse_behavior_challenge(challenge)))
    for item in result["observations"]:
        inside, denied = item["kind"] in ("allow", "deny"), item["kind"] == "deny"
        item.update(transport="http_connect" if inside else "direct_tcp",
                    proxy_endpoint="10.200.0.1:3128" if inside else "",
                    proxy_status=403 if denied else 200 if inside else 0,
                    proxy_error="policy_denied" if denied else "", outcome="proxy_denied" if denied else "connected")
    return challenge, result, current


def test_connect_protocol_and_contracts(documents):
    challenge, result, current = connect_documents(documents)
    assert validate_behavior_challenge(challenge, current, now=NOW)[0]
    assert validate_behavior_result(result, challenge, current, now=NOW, run_state="running")[0]
    for name, value in (("challenge.v2", challenge), ("result.v3", result)):
        schema = json.loads((ROOT / f"packages/contracts/openshell-behavior-{name}.schema.json").read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


@pytest.mark.parametrize("kind,outcome,status,error", [
    ("deny", "timeout", 0, ""), ("deny", "connection_refused", 0, ""),
    ("deny", "connection_reset", 0, ""), ("deny", "proxy_denied", 403, "other"),
    ("deny", "probe_error", 403, "other"), ("deny", "proxy_denied", 503, "policy_denied"),
    ("deny", "connected", 200, ""), ("allow", "connected", 0, ""),
    ("allow", "probe_error", 200, ""), ("control_before", "connected", 200, ""),
])
def test_failures_and_unproven_denials_cannot_pass(documents, kind, outcome, status, error):
    challenge, result, current = connect_documents(documents)
    item = next(i for i in result["observations"] if i["kind"] == kind)
    item.update(outcome=outcome, proxy_status=status, proxy_error=error)
    assert not validate_behavior_result(result, challenge, current, now=NOW, run_state="running")[0]


@pytest.mark.parametrize("where", ["current", "before", "after", "challenge", "observation", "direct"])
def test_proxy_identity_drift_rejects(documents, where):
    challenge, result, current = connect_documents(documents)
    if where in ("before", "after"):
        result[where]["transport"]["proxy_port"] = 3129
    elif where == "current":
        current["transport"]["proxy_port"] = 3129
    elif where == "challenge":
        challenge["transport"]["proxy_port"] = 3129
    elif where == "observation":
        result["observations"][1]["proxy_endpoint"] = "10.200.0.2:3128"
    else:
        result["observations"][1]["transport"] = "direct_tcp"
    assert not validate_behavior_result(result, challenge, current, now=NOW, run_state="running")[0]


def test_connect_journal_persists_single_use_and_audit(database, ready):
    challenge, result, current = connect_documents(ready)
    j = journal(database)
    prepared = j.prepare(challenge, current)
    claim = j.claim(prepared.verification_id, current)
    accepted = finish(database, claim, result, current)
    assert accepted.state == "accepted" and accepted.result == result
    assert j.read(prepared.verification_id) == accepted
    assert j.claim(prepared.verification_id, current) is None
    assert audit_count(database) == 3


@contextmanager
def proxy(mode):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(2)
    captured, failures = [], []
    stop = threading.Event()

    def serve():
        try:
            conn, _ = server.accept()
            with conn:
                conn.settimeout(2)
                header = bytearray()
                while not header.endswith(b"\r\n\r\n") and len(header) < 4096:
                    part = conn.recv(1)
                    if not part:
                        return
                    header.extend(part)
                captured.append(bytes(header))
                endpoint = bytes(header).split(b" ")[1].decode()
                if mode == "silent":
                    stop.wait(0.4)
                    return
                if mode == "oversize":
                    conn.sendall(b"HTTP/1.1 200 OK\r\nX: " + b"x" * 4096)
                    return
                if mode == "eof":
                    return
                if mode in ("echo", "wrong"):
                    conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    marker = bytearray()
                    while not marker.endswith(b"\n") and len(marker) < 128:
                        marker.extend(conn.recv(1))
                    captured.append(bytes(marker))
                    conn.sendall(marker if mode == "echo" else b"x" * len(marker))
                    return
                body = json.dumps({"error": "policy_denied", "detail": f"CONNECT {endpoint} not permitted by policy"})
                status, length = 403, None
                if mode == "ssrf":
                    body = body.replace("policy_denied", "ssrf_blocked")
                elif mode == "wrong_target":
                    body = body.replace(endpoint, "192.0.2.1:1")
                elif mode == "duplicate":
                    body = '{"error":"ssrf_blocked",' + body[1:]
                elif mode == "oversize_body":
                    length = 5000
                elif mode == "malformed":
                    body = "invalid"
                elif mode == "extra":
                    body = body[:-1] + ',"token":"synthetic"}'
                elif mode in ("502", "503", "302", "100"):
                    status = int(mode)
                raw = body.encode()
                conn.sendall(f"HTTP/1.1 {status} Response\r\nContent-Type: application/json\r\nContent-Length: "
                             f"{length or len(raw)}\r\n\r\n".encode() + raw)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            failures.append(type(error).__name__)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield server.getsockname(), captured
    finally:
        stop.set()
        server.close()
        thread.join(3)
        assert not thread.is_alive() and not failures


@pytest.mark.parametrize("mode,expected", [
    ("echo", "connected"), ("denied", "proxy_denied"), ("ssrf", "probe_error"),
    ("wrong_target", "probe_error"), ("duplicate", "probe_error"), ("extra", "probe_error"),
    ("malformed", "probe_error"), ("wrong", "probe_error"), ("eof", "probe_error"),
    ("502", "probe_error"), ("503", "probe_error"), ("302", "probe_error"), ("100", "probe_error"),
    ("oversize", "probe_error"), ("oversize_body", "probe_error"), ("silent", "timeout"),
])
def test_real_elf_connect_response_classification(elf, documents, mode, expected, monkeypatch):
    # An unreachable destination is never dialled directly; only the declared proxy receives traffic.
    base = challenge_for(documents, ("192.0.2.10", 8443), elf, timeout=200).model_dump()
    with proxy(mode) as (endpoint, requests):
        base.update(schema_version="openshell-behavior-challenge/v2",
                    transport={"mode": "http_connect", "proxy_ipv4": endpoint[0], "proxy_port": endpoint[1]})
        challenge = BehaviorChallengeV2.model_validate(base)
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
        reports = []

        def runner(argv, **kwargs):
            from app.adapters.openshell.bounded_command import run_bounded
            result = run_bounded(argv, **kwargs)
            assert result[0] == 0
            reports.append(json.loads(result[1]))
            return result

        item = BehaviorProbeChannel(local_exec, runner=runner).run_arm(
            challenge, round_index=0, kind="allow", expected_uid=os.getuid())
        assert item["outcome"] == expected
        assert requests[0] == b"CONNECT 192.0.2.10:8443 HTTP/1.1\r\nHost: 192.0.2.10:8443\r\n\r\n"
        assert item["transport"] == "http_connect" and item["proxy_endpoint"] == f"{endpoint[0]}:{endpoint[1]}"
        schema = json.loads((ROOT / "packages/contracts/openshell-behavior-agent.v2.schema.json").read_text())
        Draft202012Validator(schema).validate(reports[0])
        forged = copy.deepcopy(reports[0])
        forged["proxy_endpoint"] = "127.0.0.1:1"
        with pytest.raises(AdapterError, match="behavior_agent_identity_mismatch"):
            parse_agent_observation(json.dumps(forged), challenge, kind="allow", expected_uid=os.getuid())


@pytest.mark.parametrize("side", ["challenge", "result"])
def test_mixed_versions_cannot_be_accepted(documents, side):
    challenge, result, current = connect_documents(documents)
    if side == "challenge":
        challenge, current = documents[0], documents[2]
    else:
        result = documents[1]
    assert validate_behavior_result(result, challenge, current, now=NOW, run_state="running") == (
        False, "behavior_version_mismatch")


@pytest.mark.parametrize("transport", [
    {"mode": "http_connect", "proxy_ipv4": "localhost", "proxy_port": 3128},
    {"mode": "http_connect", "proxy_ipv4": "http://10.200.0.1", "proxy_port": 3128},
    {"mode": "http_connect", "proxy_ipv4": "10.200.0.01", "proxy_port": 3128},
    {"mode": "http_connect", "proxy_ipv4": "10.200.0.1", "proxy_port": True},
    {"mode": "http_connect", "proxy_ipv4": "10.200.0.1", "proxy_port": 0},
    {"mode": "direct_tcp", "proxy_ipv4": "10.200.0.1", "proxy_port": 3128},
])
def test_invalid_proxy_never_becomes_eligible(documents, transport):
    challenge, _, current = connect_documents(documents)
    challenge["transport"] = transport
    assert validate_behavior_challenge(challenge, current, now=NOW) == (False, "behavior_schema_invalid")


def test_connect_journal_drift_rejects_without_reclaim(database, ready):
    challenge, result, current = connect_documents(ready)
    j = journal(database)
    prepared = j.prepare(challenge, current)
    claim = j.claim(prepared.verification_id, current)
    current["transport"]["proxy_port"] = 3129
    rejected = finish(database, claim, result, current)
    assert rejected.state == "rejected" and rejected.reason_code == "behavior_transport_changed"
    assert j.read(prepared.verification_id) == rejected
    assert j.claim(prepared.verification_id, current) is None
    assert audit_count(database) == 3
