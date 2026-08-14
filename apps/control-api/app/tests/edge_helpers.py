"""真实 Edge Ed25519 测试夹具；不使用生产或运行时密钥。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.evidence_signing import batch_signed_bytes, evidence_signed_bytes


def edge_private_key(identity: str) -> Ed25519PrivateKey:
    seed = hashlib.sha256(f"siq-test-edge:{identity}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def edge_public_key_pem(identity: str) -> str:
    return edge_private_key(identity).public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")


def register_edge(client, tenant_headers: dict, environment_id: str, identity: str) -> tuple[dict, Ed25519PrivateKey]:
    enrollment = client.post(
        f"/api/v1/environments/{environment_id}/edge-enrollment",
        json={},
        headers=tenant_headers,
    ).json()
    private_key = edge_private_key(identity)
    response = client.post(
        "/edge/v1/register",
        json={
            "enrollment_code": enrollment["code"],
            "device_identity": identity,
            "public_key_pem": edge_public_key_pem(identity),
            "version": "0.1.0",
            "capabilities": {"connectors": ["hermes", "openclaw", "docker", "directory"]},
        },
    )
    assert response.status_code == 200, response.text
    registration = response.json()
    headers = {
        "Authorization": f"Bearer {registration['device_secret']}",
        "X-Edge-Identity": identity,
    }
    return headers, private_key


def create_scan_task(client, tenant_headers: dict, environment_id: str, connector: str = "hermes") -> str:
    response = client.post(
        "/api/v1/scans",
        json={"environment_id": environment_id, "scope": {}, "connector": connector},
        headers=tenant_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["task_id"]


def signed_evidence(
    private_key: Ed25519PrivateKey,
    identity: str,
    evidence_id: str,
    *,
    content_hash: str | None = None,
    source_type: str = "manifest",
    source_locator: str = "profiles/test/config.yaml",
) -> dict:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    evidence = {
        "evidence_id": evidence_id,
        "source_type": source_type,
        "source_locator": source_locator,
        "observed_at": now,
        "collected_at": now,
        "collector_id": identity,
        "connector_version": "0.1.0",
        "content_hash": content_hash or hashlib.sha256(evidence_id.encode()).hexdigest(),
        "redaction_profile": "siq.redaction.v1",
        "classification": "internal",
        "signature": "",
    }
    evidence["signature"] = private_key.sign(evidence_signed_bytes(evidence)).hex()
    return evidence


def signed_batch(
    private_key: Ed25519PrivateKey,
    task_id: str,
    *,
    candidates: list[dict] | None = None,
    evidence: list[dict] | None = None,
    permission_facts: list[dict] | None = None,
) -> dict:
    batch = {
        "task_id": task_id,
        "candidates": candidates or [],
        "evidence": evidence or [],
        "permission_facts": permission_facts or [],
    }
    batch["signature"] = private_key.sign(batch_signed_bytes(batch)).hex()
    return batch


def candidate(name: str, evidence_ids: list[str], *, source_type: str = "hermes_profile") -> dict:
    return {
        "candidate_id": f"{source_type}:{name}",
        "source_type": source_type,
        "source_locator": f"{source_type}://{name}",
        "discovered_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "name": name,
        "framework": "hermes" if source_type == "hermes_profile" else "unknown",
        "evidence_ids": evidence_ids,
    }
