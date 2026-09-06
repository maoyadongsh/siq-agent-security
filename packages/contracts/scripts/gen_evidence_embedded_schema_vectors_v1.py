#!/usr/bin/env python3
"""Independent producer for evidence_embedded_schema_vectors_v1.json (DEV09-H).

Freezes dual-read for Evidence UTF-8 canon:
  - legacy bodies without signing_schema
  - writers embedding signing_schema=evidence_utf8/v1
  - wrong schema ids fail closed

Does not import control-api or edge packages.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "evidence_embedded_schema_vectors_v1.json"


def canon(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def main() -> None:
    seed = bytes(range(32))
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub = priv.public_key()
    pub_pem = pub.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    seed_b64 = base64.b64encode(seed).decode("ascii")

    def sign(obj: dict) -> tuple[str, str]:
        body = dict(obj)
        body["signature"] = ""
        b = canon(body)
        return b.decode("utf-8"), priv.sign(b).hex()

    base = {
        "evidence_id": "ev-embed-001",
        "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_type": "manifest",
        "classification": "internal",
        "collector_id": "edge-fixture",
        "collected_at": "2026-09-06T00:00:00Z",
        "observed_at": "2026-09-06T00:00:00Z",
        "redaction_profile": "siq.redaction.v1",
        "note": "<安全>",
        "signature": "",
    }

    legacy_canon, legacy_sig = sign(base)
    embedded = dict(base)
    embedded["signing_schema"] = "evidence_utf8/v1"
    emb_canon, emb_sig = sign(embedded)
    assert legacy_canon != emb_canon
    assert legacy_sig != emb_sig

    wrong = dict(base)
    wrong["signing_schema"] = "local_canonical/v1"
    wrong_canon, wrong_sig = sign(wrong)

    out = {
        "schema": "evidence_embedded_schema_vectors/v1",
        "producer": (
            "CPython json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=False) "
            "+ Ed25519 seed=bytes(range(32))"
        ),
        "contract": (
            "DEV09-H dual-read: omit signing_schema → evidence_utf8/v1; "
            "embed field in signed body; wrong schema ids fail closed before accept."
        ),
        "cross_contract_note": {
            "legacy_canonical_utf8": legacy_canon,
            "embedded_canonical_utf8": emb_canon,
        },
        "public_key_pem": pub_pem,
        "seed_b64": seed_b64,
        "vectors": [
            {
                "name": "legacy_omit_signing_schema",
                "expect": "accept",
                "document": base,
                "canonical_utf8": legacy_canon,
                "signature_hex": legacy_sig,
            },
            {
                "name": "embedded_evidence_utf8_v1",
                "expect": "accept",
                "document": embedded,
                "canonical_utf8": emb_canon,
                "signature_hex": emb_sig,
            },
            {
                "name": "embedded_local_canonical_rejected",
                "expect": "reject_schema",
                "document": wrong,
                "canonical_utf8": wrong_canon,
                "signature_hex": wrong_sig,
                "note": "Bytes may verify under UTF-8 canon, but schema dual-read must reject.",
            },
            {
                "name": "embedded_non_string_schema_rejected",
                "expect": "reject_schema",
                "document": {**base, "signing_schema": 1},
                "canonical_utf8": canon({**base, "signing_schema": 1, "signature": ""}).decode("utf-8"),
                "signature_hex": priv.sign(canon({**base, "signing_schema": 1, "signature": ""})).hex(),
            },
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
