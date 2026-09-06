#!/usr/bin/env python3
"""Independent producer for rulepack_signature_vectors_v1.json (DEV09-I).

Freezes local_canonical/v1 (ensure_ascii=True) bytes for rulepack .sig:
CPython json.dumps(sort_keys=True, separators=(',',':')) + Ed25519.

Does not import control-api or agentshield packages.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "rulepack_signature_vectors_v1.json"


def canon(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def main() -> None:
    seed = bytes(range(32))
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")

    def sign(doc: dict) -> tuple[str, str]:
        b = canon(doc)
        return b.decode("ascii"), base64.b64encode(priv.sign(b)).decode("ascii")

    chinese = {
        "version": 2,
        "rules": [
            {
                "rule_id": "fixture.chinese_html",
                "severity": "high",
                "confidence": 0.85,
                "description": "<安全> pattern",
                "impact": "impact",
                "remediation": "fix",
                "patterns": [r"\bSECRET_MARKER\b"],
            }
        ],
    }
    # Deliberately unsorted keys in source object; canon sorts.
    reordered = {
        "rules": [
            {
                "patterns": [r"\bSECRET_MARKER\b"],
                "remediation": "fix",
                "impact": "impact",
                "description": "<安全> pattern",
                "confidence": 0.85,
                "severity": "high",
                "rule_id": "fixture.chinese_html",
            }
        ],
        "version": 2,
    }
    c1, s1 = sign(chinese)
    c2, s2 = sign(reordered)
    assert c1 == c2 and s1 == s2

    float_doc = {
        "version": 3,
        "note": "n",
        "n": 100.0,
        "rules": [
            {
                "rule_id": "fixture.float",
                "severity": "medium",
                "confidence": 1.0,
                "description": "x",
                "impact": "i",
                "remediation": "r",
                "patterns": ["a"],
            }
        ],
    }
    c_float, s_float = sign(float_doc)

    evidence_utf8 = json.dumps(
        chinese, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )

    out = {
        "schema": "rulepack_signature_vectors/v1",
        "signing_schema": "local_canonical/v1",
        "producer": (
            "CPython json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=True) "
            "+ Ed25519 seed=bytes(range(32)); signature is base64 (rulepack .sig wire form)"
        ),
        "contract": (
            "apps/agentshield/internal/canon.Marshal + rulepack.VerifySignature; "
            "control-api app.signing._canonical_bytes + rulepack._verify_signature. "
            "Sidecar .sig over document body — no embedded signing_schema field."
        ),
        "cross_contract_note": {
            "evidence_utf8_canonical": evidence_utf8,
            "must_differ_from_local_canonical": True,
        },
        "public_key_b64": pub_b64,
        "seed_b64": base64.b64encode(seed).decode("ascii"),
        "vectors": [
            {
                "name": "chinese_html_confidence",
                "document": chinese,
                "canonical_utf8": c1,
                "signature_b64": s1,
            },
            {
                "name": "key_order_independent",
                "document": reordered,
                "canonical_utf8": c2,
                "signature_b64": s2,
                "note": "Same bytes/signature as chinese_html_confidence after sort_keys",
            },
            {
                "name": "float_100_0",
                "document": float_doc,
                "canonical_utf8": c_float,
                "signature_b64": s_float,
                "note": "CPython dumps 100.0 as 100.0; consumers must match producer",
            },
        ],
    }
    assert c1 != evidence_utf8
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
