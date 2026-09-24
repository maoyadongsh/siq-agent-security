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


@pytest.mark.parametrize('key', [
    'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA',
    'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME',
    'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR',
])
def test_project_context_change_invalidates_cached_evidence(monkeypatch, key):
    from app.adapters.openshell.bounded_command import clean_env

    monkeypatch.setenv('SIQ_AS_OPENSHELL_CLI_BIN', '/fixture/openshell')
    monkeypatch.setenv('SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT', 'https://127.0.0.1:17671')
    monkeypatch.setenv(key, '/fixture/project-a')
    backend = OpenShellCliBackend(runner=StatefulRunner())
    first = backend.probe()
    assert backend._detected_version_at_least((0, 0, 104))
    monkeypatch.setenv(key, '/fixture/project-b')
    assert clean_env()[key] == '/fixture/project-b'
    assert backend._invocation_fingerprint() != first.endpoint_fingerprint
    assert not backend._detected_version_at_least((0, 0, 104))
    assert backend.probe().endpoint_fingerprint != first.endpoint_fingerprint


def test_unrelated_provider_secret_does_not_change_or_enter_connection_scope(monkeypatch):
    from app.adapters.openshell.bounded_command import clean_env

    monkeypatch.setenv('SIQ_AS_OPENSHELL_CLI_BIN', '/fixture/openshell')
    monkeypatch.setenv('SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT', 'https://127.0.0.1:17671')
    backend = OpenShellCliBackend(runner=StatefulRunner())
    before = backend._invocation_fingerprint()
    monkeypatch.setenv('OPENAI_API_KEY', 'fixture-only-never-forward')
    assert backend._invocation_fingerprint() == before
    assert 'OPENAI_API_KEY' not in clean_env()


def test_shared_live_status_version_vectors():
    from app.adapters.openshell.cli_backend import _parse_gateway_version

    path = Path(__file__).resolve().parents[4] / 'testdata/openshell-status-version.v1.json'
    for case in json.loads(path.read_text()):
        assert (_parse_gateway_version(case['text']) or '') == case['version'], case['name']


def test_live_endpoint_restrictions_survive_readback_but_cannot_enter_l34_writer():
    from app.adapters.openshell.contracts import UnsupportedCapability
    from app.adapters.openshell.policy_safety import gateway_network_to_rules, network_rules_to_gateway

    endpoint = {'host': 'api.example.com', 'port': 443, 'protocol': 'rest', 'enforcement': 'enforce',
                'allowed_ips': ['192.0.2.0/24'], 'request_body_credential_rewrite': True,
                'rules': [{'allow': {'method': 'GET', 'path': '/research/**'}},
                          {'allow': {'method': 'POST', 'path': '/reports'}}]}
    raw = {'research': {'name': 'research', 'binaries': [{'path': '/usr/bin/curl'}], 'endpoints': [endpoint]}}
    result = gateway_network_to_rules(raw)
    assert len(result) == 2
    for index, item in enumerate(result):
        assert item['protocol'] == 'rest' and item['enforcement'] == 'enforce'
        assert item['allowed_ips'] == ['192.0.2.0/24'] and item['request_body_credential_rewrite'] is True
        assert {k: item[k] for k in ['method', 'path']} == endpoint['rules'][index]['allow']
    with pytest.raises(UnsupportedCapability):
        network_rules_to_gateway(result)
    result[0]['allowed_ips'].append('198.51.100.0/24')
    assert result[1]['allowed_ips'] == endpoint['allowed_ips'] == ['192.0.2.0/24']


@pytest.mark.parametrize('extra', [
    {'protocol': 'unknown'}, {'enforcement': 'audit'}, {'request_body_credential_rewrite': 'true'},
    {'allowed_ips': []}, {'allowed_ips': ['192.0.2.1']}, {'allowed_ips': ['invalid/24']},
    {'rules': []}, {'rules': [{'deny': {'method': 'GET', 'path': '/'}}]},
    {'rules': [{'allow': {'method': 'GET'}}]},
    {'rules': [{'allow': {'method': 'GET', 'path': '/', 'headers': {}}}]},
    {'unknown': 'restriction'},
])
def test_unrepresentable_gateway_restrictions_still_fail_closed(extra):
    from app.adapters.openshell.policy_safety import gateway_network_to_rules

    with pytest.raises(AdapterError):
        gateway_network_to_rules({'rule': {'binaries': [{'path': '/usr/bin/curl'}],
            'endpoints': [{'host': 'api.example.com', 'port': 443, **extra}]}})
