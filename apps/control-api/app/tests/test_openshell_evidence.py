"""Shared protocol vectors and production compiler trust boundary."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from app.adapters.openshell.cli_backend import OpenShellCliBackend, _looks_like_openshell_status
from app.adapters.openshell.contracts import AdapterError
from app.adapters.openshell.policy_compiler import compile_policy
from app.tests.test_openshell_policy_operations import StatefulRunner


def test_shared_status_shape():
    path = Path(__file__).resolve().parents[4] / "testdata/openshell-status-shape.v1.json"
    for case in json.loads(path.read_text()):
        assert _looks_like_openshell_status(case["text"]) is case["valid"], case["name"]


def test_legacy_flags_cannot_authorize_compilation():
    caps = OpenShellCliBackend(runner=StatefulRunner()).probe()
    desired = {"network": [{"endpoint": "api.example.com:443", "effect": "allow",
                            "binary_paths": ["/usr/bin/curl"]}], "enforcement_mode": "block"}
    accepted = compile_policy(desired, caps)
    assert not accepted.unsupported_by_backend
    historical = replace(caps, configuration_capabilities={})
    refused = compile_policy(desired, historical)
    assert "network.dynamic_update" in refused.unsupported_by_backend
    assert any("enforcement_mode.block" in item for item in refused.unsupported_by_backend)
    assert caps.capability("network_l34").evidence_level == "documented"


def test_tls_and_failed_refresh_clear_evidence(monkeypatch):
    monkeypatch.setenv("SIQ_AS_OPENSHELL_CLI_BIN", "/fixture/openshell")
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT", "http://127.0.0.1:8080")
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "1")
    runner = StatefulRunner()
    backend = OpenShellCliBackend(runner=runner)
    backend.probe()
    before = backend._invocation_fingerprint()
    monkeypatch.setenv("SIQ_AS_OPENSHELL_GATEWAY_INSECURE", "0")
    assert backend._invocation_fingerprint() != before
    backend._runner = lambda args: (1, "", "failure")
    with pytest.raises(AdapterError):
        backend.probe()
    assert backend._detected_version is None
    assert backend._detected_fingerprint == ""
