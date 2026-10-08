"""Recovery confidentiality/integrity tests; no live provider material."""

import base64
import json
from dataclasses import fields, replace

import pytest

from app.adapters.openshell.policy_safety import policy_digest
from app.adapters.openshell.sealed_snapshot import SnapshotCipher, SnapshotError, SnapshotOrigin

POLICY = {"version": 1, "network_policies": {}, "extension": {"synthetic_secret": "only-a-test-secret"}}
ORIGIN = SnapshotOrigin(
    operation_id="opo-test", tenant_id="tenant-test", environment_id="environment-test",
    binding_id="binding-test", deployment_id="deployment-test", backend="openshell-cli",
    target="target-test", gateway_fingerprint="sha256:" + "a" * 64,
    gateway_name_sha256="b" * 64, base_revision="1", base_digest=policy_digest(POLICY),
    expected_digest="c" * 64,
)


def cipher():
    return SnapshotCipher({"test-key-1": bytes(range(32))}, "test-key-1")


def test_exact_roundtrip_fresh_instance_and_randomized_ciphertext():
    first, second = cipher().seal(ORIGIN, POLICY), cipher().seal(ORIGIN, POLICY)
    assert first != second
    assert cipher().open(ORIGIN, json.loads(json.dumps(first))) == POLICY
    assert "only-a-test-secret" not in json.dumps(first)
    assert "synthetic_secret" not in json.dumps(first)
    assert bytes(range(32)).hex() not in repr(cipher())


@pytest.mark.parametrize("name", [f.name for f in fields(SnapshotOrigin)])
def test_every_origin_field_is_authenticated(name):
    current = getattr(ORIGIN, name)
    value = "d" * 64 if name.endswith("digest") or name.endswith("sha256") else current + "x"
    if name == "base_revision":
        value = "2"
    changed = replace(ORIGIN, **{name: value})
    with pytest.raises(SnapshotError, match="snapshot_(authentication_failed|origin_invalid)"):
        cipher().open(changed, cipher().seal(ORIGIN, POLICY))


@pytest.mark.parametrize("field", ["nonce", "ciphertext"])
def test_tamper_fails_without_plaintext_in_error(field):
    envelope = cipher().seal(ORIGIN, POLICY)
    raw = bytearray(base64.b64decode(envelope[field]))
    raw[0] ^= 1
    envelope[field] = base64.b64encode(raw).decode()
    with pytest.raises(SnapshotError) as exc:
        cipher().open(ORIGIN, envelope)
    assert str(exc.value) == "snapshot_authentication_failed"
    assert exc.value.__cause__ is None


def test_rotation_retains_old_key_and_missing_key_fails():
    envelope = cipher().seal(ORIGIN, POLICY)
    rotated = SnapshotCipher({"test-key-1": bytes(range(32)), "test-key-2": b"x" * 32}, "test-key-2")
    assert rotated.open(ORIGIN, envelope) == POLICY
    assert rotated.seal(ORIGIN, POLICY)["key_id"] == "test-key-2"
    with pytest.raises(SnapshotError, match="snapshot_key_unavailable"):
        SnapshotCipher({"test-key-2": b"x" * 32}, "test-key-2").open(ORIGIN, envelope)
    envelope["key_id"] = "test-key-2"
    with pytest.raises(SnapshotError, match="snapshot_authentication_failed"):
        rotated.open(ORIGIN, envelope)


@pytest.mark.parametrize("patch", [
    {"version": "future"}, {"nonce": "!" * 16}, {"ciphertext": "?"},
    {"ciphertext": "a" * 1_400_000}, {"nonce": None}, {"extra": "unexpected"},
])
def test_malformed_envelopes_rejected(patch):
    envelope = cipher().seal(ORIGIN, POLICY) | patch
    with pytest.raises(SnapshotError, match="snapshot_envelope_invalid"):
        cipher().open(ORIGIN, envelope)


@pytest.mark.parametrize("keys,active", [({}, "test"), ({"test": b"short"}, "test"),
    ({"bad\nkey": b"x" * 32}, "bad\nkey"), ({"test": b"x" * 32}, "absent")])
def test_invalid_keyrings_rejected(keys, active):
    with pytest.raises(SnapshotError, match="snapshot_key"):
        SnapshotCipher(keys, active)


@pytest.mark.parametrize("policy", [{"x": 1.5}, {1: "lossy"}, {"x": 2**64}, {"x": float("nan")}])
def test_non_parser_value_domain_rejected(policy):
    with pytest.raises(SnapshotError, match="snapshot_policy_invalid"):
        cipher().seal(ORIGIN, policy)


def test_digest_and_size_bounds():
    with pytest.raises(SnapshotError, match="snapshot_digest_mismatch"):
        cipher().seal(ORIGIN, {"different": "policy"})
    with pytest.raises(SnapshotError, match="snapshot_too_large"):
        cipher().seal(ORIGIN, {"large": "x" * 1024**2})
    nested = {}
    for _ in range(66):
        nested = {"next": nested}
    with pytest.raises(SnapshotError, match="snapshot_policy_invalid"):
        cipher().seal(ORIGIN, nested)
