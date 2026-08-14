"""任务签名测试（威胁 T5：中心任务重放或篡改）。

覆盖：注册响应携带公钥、任务签名可验证、篡改/换钥失败。
"""

from __future__ import annotations

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.evidence_signing import canonical_json
from app.signing import build_task_envelope, verify_task_signature
from app.tests.edge_helpers import edge_public_key_pem


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


def test_edge_python_canonical_signature_fixture():
    payload = {
        "task_id": "tsk_fixture",
        "note": "<安全>",
        "counts": [1, 2],
        "nested": {"z": False, "a": "值"},
    }
    expected_json = (
        '{"counts":[1,2],"nested":{"a":"值","z":false},'
        '"note":"<安全>","task_id":"tsk_fixture"}'
    ).encode()
    expected_signature = (
        "d9f7636415eca6419c6613673089f00cc254598d5211b710614c602d75de563e"
        "4f32da23213289be855a998d53380b21af99c810258b57e01ff15fafe41abe04"
    )
    encoded = canonical_json(payload)
    assert encoded == expected_json
    assert Ed25519PrivateKey.from_private_bytes(bytes(range(32))).sign(encoded).hex() == expected_signature


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
