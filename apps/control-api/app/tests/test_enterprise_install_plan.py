"""Installation contract parity and semantic denials, without issuing credentials."""

import copy
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from app.install_plan import EnterpriseInstallPlan

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = json.loads((ROOT / "packages/contracts/enterprise-install-plan.v1.schema.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def sample():
    return {
        "schema_version": "enterprise-install-plan/v1", "plan_id": "eip-" + "a" * 32,
        "tenant_id": "tenant-fixture", "environment_id": "env-fixture",
        "control_plane_origin": "https://security.example.test:8443",
        "issued_at": "2026-09-25T01:00:00Z", "expires_at": "2026-09-25T01:15:00Z",
        "target_os": "linux", "target_arch": "arm64", "service_mode": "user",
        "release_version": "0.4.0-test", "release_manifest_sha256": "a" * 64,
        "purpose": "discovery_only",
        "connectors": [{"id": "hermes", "version": "0.4.0-test", "artifact_sha256": "b" * 64,
                        "protocol_version": "connector-protocol.v1",
                        "scope": {"roots": ["~/.hermes/profiles/*"], "include": ["config.yaml", "SOUL.md"]}}],
    }


def test_plan_roundtrip_and_current_boundary():
    Draft202012Validator.check_schema(SCHEMA)
    value = sample()
    VALIDATOR.validate(value)
    plan = EnterpriseInstallPlan.model_validate(value)
    assert plan.model_dump(mode="json") == value
    VALIDATOR.validate(json.loads(plan.model_dump_json()))
    plan.require_current(datetime(2026, 9, 25, 1, 0, tzinfo=UTC))
    for time in [datetime(2026, 9, 25, 0, 59, tzinfo=UTC), datetime(2026, 9, 25, 1, 15, tzinfo=UTC),
                 datetime(2026, 9, 25, 1, 1)]:
        with pytest.raises(ValueError):
            plan.require_current(time)


@pytest.mark.parametrize("field", list(sample()))
def test_every_field_required(field):
    value = sample()
    value.pop(field)
    assert list(VALIDATOR.iter_errors(value))
    with pytest.raises(ValidationError):
        EnterpriseInstallPlan.model_validate(value)


@pytest.mark.parametrize("field,value", [
    ("purpose", "enforce"), ("tenant_id", " "), ("environment_id", "../other"),
    ("plan_id", "eip-abc"), ("target_os", "windows"), ("target_arch", "x86"),
    ("service_mode", "privileged"), ("release_manifest_sha256", "a" * 63),
    ("release_version", "../candidate"), ("connectors", []), ("connectors", sample()["connectors"] * 2),
    ("schema_version", "enterprise-install-plan/v0"), ("issued_at", "2026-09-25T01:00:00"),
    ("expires_at", "not-a-time"), ("expires_at", "2026-09-25T01:15:00+00:00"),
])
def test_schema_and_model_reject_invalid_wire(field, value):
    candidate = sample()
    candidate[field] = value
    assert list(VALIDATOR.iter_errors(candidate))
    with pytest.raises(ValidationError):
        EnterpriseInstallPlan.model_validate(candidate)


@pytest.mark.parametrize("level", ["plan", "connector", "scope"])
@pytest.mark.parametrize("extra", ["secret", "grant", "enrollment_code", "skip_tls_verify"])
def test_no_hidden_credentials_or_authority(level, extra):
    candidate = sample()
    target = candidate if level == "plan" else candidate["connectors"][0]
    if level == "scope":
        target = target["scope"]
    target[extra] = "synthetic"
    assert list(VALIDATOR.iter_errors(candidate))
    with pytest.raises(ValidationError):
        EnterpriseInstallPlan.model_validate(candidate)


@pytest.mark.parametrize("origin", [
    "http://192.168.2.121:10082", "https://user:pass@example.test", "https://example.test/path",
    "https://example.test?token=synthetic", "https://example.test#fragment", "https://example.test\\path",
    "https://example.test:65536", "https://example.test:0", "https://example.test:",
    "https://", "https://example.test\n", "https://example.test?", "https://example.test#",
    "file:///etc/passwd", "HTTPS://example.test", "https://example%2etest", "http://LOCALHOST",
])
def test_origin_semantics_fail_closed(origin):
    candidate = sample()
    candidate["control_plane_origin"] = origin
    with pytest.raises(ValidationError):
        EnterpriseInstallPlan.model_validate(candidate)


@pytest.mark.parametrize("origin", ["http://127.0.0.1:47620", "http://[::1]:47620", "https://gateway.test"])
def test_safe_origin_shape_is_not_authorization(origin):
    candidate = sample()
    candidate["control_plane_origin"] = origin
    VALIDATOR.validate(candidate)
    assert EnterpriseInstallPlan.model_validate(candidate).purpose == "discovery_only"


@pytest.mark.parametrize("root", ["/", "~/", "/home", "/root", "/etc", "/proc", "/sys", "/dev",
                                 "/home/../etc", "relative/path", "/home/*/secrets", "/home//fixture",
                                 "/home/fixture\x00", "/home/fixture/", "/home/[ab]"])
def test_unbounded_or_ambiguous_roots_rejected(root):
    candidate = sample()
    candidate["connectors"][0]["scope"]["roots"] = [root]
    with pytest.raises(ValidationError):
        EnterpriseInstallPlan.model_validate(candidate)


@pytest.mark.parametrize("name", [".env", "auth-profiles.json", "credentials.json", "id_rsa", "id_ed25519",
                                 "../config.yaml", "**", "subdir/config.yaml"])
def test_secret_or_recursive_includes_rejected(name):
    candidate = sample()
    candidate["connectors"][0]["scope"]["include"] = [name]
    with pytest.raises(ValidationError):
        EnterpriseInstallPlan.model_validate(candidate)


def test_same_connector_with_different_digest_cannot_duplicate_identity():
    candidate = sample()
    second = copy.deepcopy(candidate["connectors"][0])
    second["artifact_sha256"] = "c" * 64
    candidate["connectors"].append(second)
    with pytest.raises(ValidationError, match="duplicate_connector_id"):
        EnterpriseInstallPlan.model_validate(candidate)


@pytest.mark.parametrize("expiry", ["2026-09-25T01:00:00Z", "2026-09-25T00:59:00Z", "2026-09-25T01:15:01Z"])
def test_lifetime_limit(expiry):
    candidate = sample()
    candidate["expires_at"] = expiry
    with pytest.raises(ValidationError, match="invalid_plan_lifetime"):
        EnterpriseInstallPlan.model_validate(candidate)


def test_go_consumer_parity_and_actual_wire(tmp_path):
    fixtures = [sample()]
    for origin in ["http://127.0.0.1:47620", "http://[::1]:47620", "https://gateway.test",
                   "http://192.168.2.121", "http://LOCALHOST", "https://user:pass@example.test",
                   "https://example.test:65536", "https://example.test:0", "https://example.test?",
                   "https://example.test#", "HTTPS://example.test", "https://example%2etest"]:
        value = sample()
        value["control_plane_origin"] = origin
        fixtures.append(value)
    for field in sample():
        value = sample()
        value.pop(field)
        fixtures.append(value)
        value = sample()
        value[field] = None
        fixtures.append(value)
    for level in ["plan", "connector", "scope"]:
        value = sample()
        target = value if level == "plan" else value["connectors"][0]
        if level == "scope":
            target = target["scope"]
        target["secret"] = "fixture-only"
        fixtures.append(value)
    for root in ["/", "/home", "/home/../etc", "/home/fixture", "~/.hermes/profiles/*",
                 "/home/*/secrets", "/home//fixture", "/home/fixture\x00", "/home/fixture/", "/home/[ab]"]:
        value = sample()
        value["connectors"][0]["scope"]["roots"] = [root]
        fixtures.append(value)
    for include in [".env", "auth-profiles.json", "credentials.json", "id_rsa", "id_ed25519",
                    "../config.yaml", "**", "subdir/config.yaml", "config.yaml"]:
        value = sample()
        value["connectors"][0]["scope"]["include"] = [include]
        fixtures.append(value)
    cases = []
    for value in fixtures:
        try:
            EnterpriseInstallPlan.model_validate(value)
            valid = True
        except ValidationError:
            valid = False
        cases.append({"plan": value, "valid": valid})
    corpus = tmp_path / "corpus.json"
    output = tmp_path / "go-wire.json"
    corpus.write_text(json.dumps(cases))
    env = {**os.environ, "SIQ_INSTALL_PLAN_TEST_CORPUS": str(corpus), "SIQ_INSTALL_PLAN_TEST_OUTPUT": str(output)}
    run = subprocess.run(["go", "test", "./installplan", "-run", "^TestInstallPlanWireParity$", "-count=1"],
                         cwd=ROOT / "edge/agent", env=env, capture_output=True, text=True, timeout=60, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
    accepted = json.loads(output.read_text())
    assert len(accepted) == sum(case["valid"] for case in cases)
    for value in accepted:
        VALIDATOR.validate(value)
        EnterpriseInstallPlan.model_validate(value)
