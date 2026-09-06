"""任务签名测试（威胁 T5：中心任务重放或篡改）。

覆盖：注册响应携带公钥、任务签名可验证、篡改/换钥失败；
DEV09 固定向量（独立 CPython 生产者）与 Edge 共用。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.evidence_signing import (
    canonical_json,
    normalize_evidence_signing_schema,
    verify_evidence_signature,
)
from app.signing import _canonical_bytes, build_task_envelope, verify_task_signature
from app.tests.edge_helpers import edge_public_key_pem

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TASK_SIG_FIXTURES = _REPO_ROOT / "packages" / "contracts" / "fixtures" / "task_signature_vectors_v1.json"
_EVIDENCE_SIG_FIXTURES = _REPO_ROOT / "packages" / "contracts" / "fixtures" / "evidence_signature_vectors_v1.json"
_EVIDENCE_EMBED_FIXTURES = (
    _REPO_ROOT / "packages" / "contracts" / "fixtures" / "evidence_embedded_schema_vectors_v1.json"
)
_RULEPACK_SIG_FIXTURES = (
    _REPO_ROOT / "packages" / "contracts" / "fixtures" / "rulepack_signature_vectors_v1.json"
)
_LOCAL_DOC_SIG_FIXTURES = _REPO_ROOT / "packages" / "contracts" / "fixtures" / "local_doc_signature_vectors_v1.json"


def _register_and_fetch(client, tenant_a, env_a, identity):
    enr = client.post(
        f"/api/v1/environments/{env_a['id']}/edge-enrollment", json={}, headers=tenant_a
    ).json()
    reg = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enr["code"],
            "device_identity": identity,
            "public_key_pem": edge_public_key_pem(identity),
            "version": "0.1.0",
        },
    ).json()
    return reg


def test_evidence_canonical_differs_from_task_signing_on_unicode():
    """Evidence 用 ensure_ascii=False；任务签名用 CPython 默认 ensure_ascii=True。"""
    payload = {
        "task_id": "tsk_fixture",
        "note": "<安全>",
        "counts": [1, 2],
        "nested": {"z": False, "a": "值"},
    }
    evidence = canonical_json(payload)
    task = _canonical_bytes(payload)
    assert evidence != task
    assert "安全".encode() in evidence
    assert "安全".encode() not in task
    assert r"<\u5b89\u5168>" in task.decode("ascii")


def test_local_doc_signature_vectors_v1_match_ascii_contract():
    """admission/grant 本地文档：ensure_ascii=True 向量（DEV09-C）。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    doc = json.loads(_LOCAL_DOC_SIG_FIXTURES.read_text(encoding="utf-8"))
    assert doc["schema"] == "local_doc_signature_vectors/v1"
    cross = doc["cross_contract_note"]
    for vec in doc["vectors"]:
        assert vec["signing_schema"] == "local_canonical/v1"
        encoded = _canonical_bytes(vec["document"])
        assert encoded.decode("utf-8") == vec["canonical_utf8"], vec["name"]
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(vec["public_key_b64"]))
        pub.verify(bytes.fromhex(vec["signature_hex"]), encoded)
        bad = bytearray(encoded)
        bad[len(bad) // 2] ^= 1
        try:
            pub.verify(bytes.fromhex(vec["signature_hex"]), bytes(bad))
            raise AssertionError(f"tampered accepted: {vec['name']}")
        except InvalidSignature:
            pass
        if vec["name"] == "chinese_html_float_null":
            assert vec["canonical_utf8"] != cross["evidence_utf8_canonical"]
            assert "安全".encode() not in encoded


def test_evidence_signature_vectors_v1_match_contract():
    """独立生产者夹具：evidence_signing.canonical_json + 验签必须通过（DEV09-B）。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    doc = json.loads(_EVIDENCE_SIG_FIXTURES.read_text(encoding="utf-8"))
    assert doc["schema"] == "evidence_signature_vectors/v1"
    for vec in doc["vectors"]:
        encoded = canonical_json(vec["document"])
        assert encoded.decode("utf-8") == vec["canonical_utf8"], vec["name"]
        pub = serialization.load_pem_public_key(vec["public_key_pem"].encode("ascii"))
        assert isinstance(pub, Ed25519PublicKey)
        pub.verify(bytes.fromhex(vec["signature_hex"]), encoded)
        bad = bytearray(encoded)
        bad[len(bad) // 2] ^= 1
        try:
            pub.verify(bytes.fromhex(vec["signature_hex"]), bytes(bad))
            raise AssertionError(f"tampered accepted: {vec['name']}")
        except InvalidSignature:
            pass


def test_evidence_embedded_schema_vectors_v1_dual_read():
    """DEV09-H：嵌入 evidence_utf8/v1；缺省双读；错误 schema 拒绝。"""
    doc = json.loads(_EVIDENCE_EMBED_FIXTURES.read_text(encoding="utf-8"))
    assert doc["schema"] == "evidence_embedded_schema_vectors/v1"
    cross = doc["cross_contract_note"]
    assert cross["legacy_canonical_utf8"] != cross["embedded_canonical_utf8"]
    pem = doc["public_key_pem"]
    for vec in doc["vectors"]:
        body = dict(vec["document"])
        body["signature"] = vec["signature_hex"]
        encoded = canonical_json({**vec["document"], "signature": ""})
        assert encoded.decode("utf-8") == vec["canonical_utf8"], vec["name"]
        if vec["expect"] == "accept":
            assert normalize_evidence_signing_schema(body) == "evidence_utf8/v1"
            assert verify_evidence_signature(pem, body), vec["name"]
        elif vec["expect"] == "reject_schema":
            try:
                normalize_evidence_signing_schema(body)
                raise AssertionError(f"schema should reject: {vec['name']}")
            except ValueError:
                pass
            assert not verify_evidence_signature(pem, body), vec["name"]
        else:
            raise AssertionError(vec["expect"])


def test_rulepack_signature_vectors_v1_match_local_canonical():
    """DEV09-I：rulepack .sig 与 _canonical_bytes / Go canon 对等（独立生产者）。"""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    doc = json.loads(_RULEPACK_SIG_FIXTURES.read_text(encoding="utf-8"))
    assert doc["schema"] == "rulepack_signature_vectors/v1"
    assert doc["signing_schema"] == "local_canonical/v1"
    cross = doc["cross_contract_note"]
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(doc["public_key_b64"]))
    for vec in doc["vectors"]:
        encoded = _canonical_bytes(vec["document"])
        assert encoded.decode("utf-8") == vec["canonical_utf8"], vec["name"]
        pub.verify(base64.b64decode(vec["signature_b64"]), encoded)
        bad = bytearray(encoded)
        bad[len(bad) // 2] ^= 1
        try:
            pub.verify(base64.b64decode(vec["signature_b64"]), bytes(bad))
            raise AssertionError(f"tampered accepted: {vec['name']}")
        except InvalidSignature:
            pass
        if vec["name"] == "chinese_html_confidence":
            assert vec["canonical_utf8"] != cross["evidence_utf8_canonical"]
            assert "安全".encode() not in encoded
            assert r"<\u5b89\u5168>" in vec["canonical_utf8"]


def test_task_signature_vectors_v1_match_signing_contract():
    """独立生产者夹具：控制面 _canonical_bytes + 验签必须通过（DEV09）。"""
    doc = json.loads(_TASK_SIG_FIXTURES.read_text(encoding="utf-8"))
    assert doc["schema"] == "task_signature_vectors/v1"
    for vec in doc["vectors"]:
        envelope = vec["envelope"]
        # Rebuild payload from wire JSON so 100 vs 100.0 is preserved.
        envelope = {
            **envelope,
            "payload": json.loads(vec["payload_json"]),
        }
        encoded = _canonical_bytes(envelope)
        assert encoded.decode("utf-8") == vec["canonical_utf8"], vec["name"]
        assert verify_task_signature(vec["public_key_b64"], envelope, vec["signature_b64"]), vec["name"]
        # Wrong key / tamper fail closed.
        foreign = Ed25519PrivateKey.generate()
        foreign_pub = base64.b64encode(
            foreign.public_key().public_bytes_raw()
        ).decode("ascii")
        assert not verify_task_signature(foreign_pub, envelope, vec["signature_b64"])
        bad = {**envelope, "payload": {"tampered": True}}
        assert not verify_task_signature(vec["public_key_b64"], bad, vec["signature_b64"])


def test_register_returns_control_plane_public_key(client, tenant_a, env_a):
    reg = _register_and_fetch(client, tenant_a, env_a, "edge-sign-1")
    assert "control_plane_public_key" in reg
    assert len(reg["control_plane_public_key"]) == 44  # base64 of 32 raw bytes


def test_scan_task_signature_verifies(client, tenant_a, env_a):
    client.post(
        "/api/v1/scans", json={"environment_id": env_a["id"], "scope": {"connector": "hermes"}}, headers=tenant_a
    )
    reg = _register_and_fetch(client, tenant_a, env_a, "edge-sign-2")
    headers = {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": "edge-sign-2"}
    tasks = client.get("/edge/v1/tasks", headers=headers).json()
    assert len(tasks) >= 1
    task = tasks[0]
    assert task["signature"]
    envelope = build_task_envelope(
        task["id"], task["task_type"], env_a["id"], task["payload"], task["expires_at"]
    )
    assert verify_task_signature(reg["control_plane_public_key"], envelope, task["signature"])


def test_tampered_task_fails_verification(client, tenant_a, env_a):
    client.post(
        "/api/v1/scans", json={"environment_id": env_a["id"], "scope": {"connector": "docker"}}, headers=tenant_a
    )
    reg = _register_and_fetch(client, tenant_a, env_a, "edge-sign-3")
    headers = {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": "edge-sign-3"}
    task = client.get("/edge/v1/tasks", headers=headers).json()[0]
    envelope = build_task_envelope(
        task["id"], task["task_type"], env_a["id"], {"scope": {"connector": "EVIL"}}, task["expires_at"]
    )
    assert not verify_task_signature(reg["control_plane_public_key"], envelope, task["signature"])


def test_foreign_key_fails_verification(client, tenant_a, env_a):

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    client.post("/api/v1/scans", json={"environment_id": env_a["id"], "scope": {}}, headers=tenant_a)
    reg = _register_and_fetch(client, tenant_a, env_a, "edge-sign-4")
    headers = {"Authorization": f"Bearer {reg['device_secret']}", "X-Edge-Identity": "edge-sign-4"}
    task = client.get("/edge/v1/tasks", headers=headers).json()[0]
    envelope = build_task_envelope(task["id"], task["task_type"], env_a["id"], task["payload"], task["expires_at"])
    foreign = Ed25519PrivateKey.generate()
    raw = foreign.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    import base64

    assert not verify_task_signature(base64.b64encode(raw).decode(), envelope, task["signature"])
    assert verify_task_signature(reg["control_plane_public_key"], envelope, task["signature"])
