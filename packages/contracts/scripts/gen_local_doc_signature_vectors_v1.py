#!/usr/bin/env python3
"""Independent producer for local_doc_signature_vectors_v1.json (DEV09-C).

Does not import apps/control-api or agentshield. Re-run only when intentionally
refreshing frozen vectors; consumers must not regenerate expected signatures.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "local_doc_signature_vectors_v1.json"


def canon(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def main() -> None:
    seed = bytes(range(32))
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")

    def sign(obj: dict) -> tuple[str, str]:
        b = canon(obj)
        return b.decode("ascii"), priv.sign(b).hex()

    vectors: list[dict] = []
    adm = {
        "admission_id": "adm-fixture01",
        "skill_id": "local_dir:demo@aaaaaaaaaaaa",
        "skill_name": "demo",
        "skill_version": "1.0.0",
        "source": {
            "type": "local_dir",
            "locator": "fixtures/demo",
            "trust_level": "unknown",
            "ref": None,
        },
        "content_hash": "a" * 64,
        "verdict": "admit",
        "decided_at": "2026-09-06T00:00:00Z",
        "engine": {
            "name": "agentshield-go",
            "version": "test",
            "rulepack_version": 1,
            "rulepack_sha256": "b" * 64,
        },
        "declared_facts": [],
        "findings": [],
        "integrity": {
            "over_limit": False,
            "symlink_escape": False,
            "file_count": 1,
            "total_bytes": 10,
        },
        "evidence_ids": [],
    }
    c, s = sign(adm)
    vectors.append(
        {
            "name": "admission_minimal",
            "signing_schema": "local_canonical/v1",
            "document": adm,
            "canonical_utf8": c,
            "signature_hex": s,
            "public_key_b64": pub_b64,
        }
    )

    grant = {
        "grant_id": "grn-fixture01",
        "admission_id": "adm-fixture01",
        "subject": {"type": "agent_instance", "id": "agent-1"},
        "platform": "hermes",
        "facts": [],
        "default_effect": "deny",
        "enforcement_mode": "block",
        "status": "pending",
        "overlap_conflicts": [],
        "created_at": "2026-09-06T00:00:00Z",
    }
    c, s = sign(grant)
    vectors.append(
        {
            "name": "grant_minimal",
            "signing_schema": "local_canonical/v1",
            "document": grant,
            "canonical_utf8": c,
            "signature_hex": s,
            "public_key_b64": pub_b64,
        }
    )

    uni = {
        "note": "<安全>",
        "n": 100.0,
        "nested": {"z": True, "y": "值", "a": None},
        "items": [1, 0.85, None],
    }
    c, s = sign(uni)
    vectors.append(
        {
            "name": "chinese_html_float_null",
            "signing_schema": "local_canonical/v1",
            "document": uni,
            "canonical_utf8": c,
            "signature_hex": s,
            "public_key_b64": pub_b64,
        }
    )

    evidence_canon = json.dumps(uni, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert evidence_canon.encode("utf-8") != canon(uni)

    out = {
        "schema": "local_doc_signature_vectors/v1",
        "producer": "CPython json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=True) + Ed25519 seed=bytes(range(32))",
        "contract": "apps/agentshield/internal/canon.Marshal / signing.VerifyCanonical; signing_schema=local_canonical/v1",
        "cross_contract_note": {
            "document_name": "chinese_html_float_null",
            "evidence_utf8_canonical": evidence_canon,
            "must_differ_from_local_canonical": True,
        },
        "vectors": vectors,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
