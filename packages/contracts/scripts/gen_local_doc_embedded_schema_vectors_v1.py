#!/usr/bin/env python3
"""Independent producer for local_doc_embedded_schema_vectors_v1.json (DEV09-E).

Freezes dual-read: legacy bodies without signing_schema, and bodies that embed
signing_schema as a signed field. Does not import agentshield or control-api.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "local_doc_embedded_schema_vectors_v1.json"


def canon(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def main() -> None:
    seed = bytes(range(32))
    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_b64 = base64.b64encode(priv.public_key().public_bytes_raw()).decode("ascii")

    def sign(obj: dict) -> tuple[str, str]:
        b = canon(obj)
        return b.decode("ascii"), priv.sign(b).hex()

    base = {
        "doc_kind": "admission_fragment",
        "admission_id": "adm-embed-01",
        "verdict": "admit",
        "note": "<安全>",
        "n": 100.0,
    }
    legacy_canon, legacy_sig = sign(base)
    embedded = dict(base)
    embedded["signing_schema"] = "local_canonical/v1"
    emb_canon, emb_sig = sign(embedded)
    assert legacy_canon != emb_canon
    assert legacy_sig != emb_sig

    # Same field as task router id — still ASCII local canon bytes.
    task_embedded = dict(base)
    task_embedded["signing_schema"] = "task_envelope/v1"
    task_canon, task_sig = sign(task_embedded)

    out = {
        "schema": "local_doc_embedded_schema_vectors/v1",
        "producer": "CPython json.dumps(sort_keys=True, separators=(',',':'), ensure_ascii=True) + Ed25519 seed=bytes(range(32))",
        "contract": (
            "Dual-read VerifyDocument: omit signing_schema → local_canonical/v1; "
            "embed field in signed body; unsupported/unknown ids fail closed. "
            "Writers not switched in this fixture set."
        ),
        "cross_note": {
            "legacy_vs_embedded_must_differ": True,
            "legacy_canonical_utf8": legacy_canon,
            "embedded_canonical_utf8": emb_canon,
        },
        "vectors": [
            {
                "name": "legacy_no_schema_field",
                "expect": "verify_ok",
                "document": base,
                "canonical_utf8": legacy_canon,
                "signature_hex": legacy_sig,
                "public_key_b64": pub_b64,
            },
            {
                "name": "embedded_local_canonical_v1",
                "expect": "verify_ok",
                "document": embedded,
                "canonical_utf8": emb_canon,
                "signature_hex": emb_sig,
                "public_key_b64": pub_b64,
            },
            {
                "name": "embedded_task_envelope_v1",
                "expect": "verify_ok",
                "document": task_embedded,
                "canonical_utf8": task_canon,
                "signature_hex": task_sig,
                "public_key_b64": pub_b64,
            },
            {
                "name": "embedded_evidence_utf8_rejected",
                "expect": "schema_not_supported",
                "document": {**base, "signing_schema": "evidence_utf8/v1"},
                "signature_hex": "00",
                "public_key_b64": pub_b64,
            },
            {
                "name": "embedded_receipt_hash_chain_rejected",
                "expect": "schema_not_supported",
                "document": {**base, "signing_schema": "receipt_hash_chain/v1"},
                "signature_hex": "00",
                "public_key_b64": pub_b64,
            },
            {
                "name": "embedded_unknown_v2_rejected",
                "expect": "unknown_schema",
                "document": {**base, "signing_schema": "local_canonical/v2"},
                "signature_hex": "00",
                "public_key_b64": pub_b64,
            },
            {
                "name": "embedded_non_string_schema_rejected",
                "expect": "unknown_schema",
                "document": {**base, "signing_schema": 1},
                "signature_hex": "00",
                "public_key_b64": pub_b64,
            },
            {
                "name": "legacy_sig_must_not_verify_embedded_body",
                "expect": "verify_fail",
                "document": embedded,
                "signature_hex": legacy_sig,
                "public_key_b64": pub_b64,
            },
        ],
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
