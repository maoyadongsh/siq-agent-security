#!/usr/bin/env python3
"""Print public-key fingerprints for known trust materials. Never prints seeds."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "ed25519_pub.go"
RELEASE_PUB_B64 = "LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY="
HISTORICAL_TASK_SEED = "364dade:apps/control-api/signing-key.seed"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_public_b64(b64: str) -> dict[str, str]:
    raw = base64.b64decode(b64, validate=True)
    if len(raw) != 32:
        raise ValueError("public key must be 32 bytes")
    return {
        "public_key_b64": b64,
        "sha256": sha256_hex(raw),
    }


def fingerprint_seed_bytes(seed_text: bytes) -> dict[str, str]:
    proc = subprocess.run(
        ["go", "run", str(HELPER)],
        input=seed_text,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "ed25519_pub failed")
    out: dict[str, str] = {}
    for line in proc.stdout.decode("ascii").splitlines():
        key, _, value = line.partition("=")
        if value:
            out[key] = value
    if "public_key_b64" not in out or "sha256" not in out:
        raise RuntimeError("ed25519_pub produced no public fields")
    return out


def git_blob(spec: str) -> bytes | None:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-p", spec],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def git_show_exists(spec: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", spec],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


def main() -> int:
    rows: list[dict[str, str]] = []

    rel = fingerprint_public_b64(RELEASE_PUB_B64)
    rows.append(
        {
            "purpose": "local_release_manifest_v1",
            "material": "apps/agentshield/internal/skillmanifest.ReleasePublicKeyB64",
            "status_in_tree": "public_constant",
            **rel,
        }
    )

    if git_show_exists(HISTORICAL_TASK_SEED):
        blob = git_blob(HISTORICAL_TASK_SEED)
        if blob is None:
            rows.append(
                {
                    "purpose": "control_plane_task_signing_historical",
                    "material": HISTORICAL_TASK_SEED,
                    "status_in_tree": "history_reachable_unreadable",
                }
            )
        else:
            derived = fingerprint_seed_bytes(blob)
            rows.append(
                {
                    "purpose": "control_plane_task_signing_historical",
                    "material": HISTORICAL_TASK_SEED,
                    "introduced": "364dade",
                    "removed_from_tree": "145e53f",
                    "status_in_tree": "deleted_blob_still_in_git_history",
                    **derived,
                }
            )
    else:
        rows.append(
            {
                "purpose": "control_plane_task_signing_historical",
                "material": HISTORICAL_TASK_SEED,
                "status_in_tree": "blob_not_in_this_clone",
            }
        )

    rows.append(
        {
            "purpose": "control_plane_task_signing_current",
            "material": "SIQ_AS_TASK_SIGNING_KEY_SEED / production Secret Manager",
            "status_in_tree": "not_in_repository",
            "in_service": "unverified",
        }
    )
    rows.append(
        {
            "purpose": "local_receipt_identity",
            "material": "<state>/keys/signing.seed",
            "status_in_tree": "generated_per_machine_not_committed",
            "in_service": "local_only",
        }
    )
    rows.append(
        {
            "purpose": "external_rulepack",
            "material": "SIQ_AGENT_SECURITY_RULEPACK_PUBKEY / SIQ_AS_THREAT_RULEPACK_PATH.sig",
            "status_in_tree": "env_configured_optional",
            "note": "unsigned external packs fall back to the builtin pack; builtin has no separate committed private key",
        }
    )

    json.dump({"records": rows}, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 — operator tool; keep stderr free of seed bytes
        print(f"trust-fingerprint: {exc}", file=sys.stderr)
        raise SystemExit(1)
