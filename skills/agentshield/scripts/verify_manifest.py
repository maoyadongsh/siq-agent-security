#!/usr/bin/env python3
"""Verify skill-manifest.json (Ed25519 over canonical JSON) and optional binary sha256.

stdlib + openssl 3 only. Never executes the binary.
Exit 3 on mismatch (same as agentshield admit quarantine).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile


def die(msg: str, code: int = 3) -> None:
    sys.stderr.write(f"agentshield-verify-manifest: {msg}\n")
    raise SystemExit(code)


def canonical_without_signature(doc: dict) -> bytes:
    body = dict(doc)
    body.pop("signature", None)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def spki_pem(pub_raw: bytes) -> str:
    if len(pub_raw) != 32:
        die("public key must be 32 bytes")
    der = bytes.fromhex("302a300506032b6570032100") + pub_raw
    b64 = base64.encodebytes(der).decode("ascii")
    return "-----BEGIN PUBLIC KEY-----\n" + b64 + "-----END PUBLIC KEY-----\n"


def openssl_verify(pub_raw: bytes, msg: bytes, sig: bytes) -> None:
    pem = spki_pem(pub_raw)
    with tempfile.TemporaryDirectory() as td:
        pub_path = os.path.join(td, "pub.pem")
        msg_path = os.path.join(td, "msg")
        sig_path = os.path.join(td, "sig")
        with open(pub_path, "w", encoding="ascii") as f:
            f.write(pem)
        with open(msg_path, "wb") as f:
            f.write(msg)
        with open(sig_path, "wb") as f:
            f.write(sig)
        try:
            r = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    pub_path,
                    "-rawin",
                    "-in",
                    msg_path,
                    "-sigfile",
                    sig_path,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            die("openssl not found; install OpenSSL 3 to verify skill-manifest.json", 1)
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            die(f"signature mismatch ({err})")


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def this_os_arch() -> tuple[str, str]:
    osname = {"linux": "linux", "darwin": "darwin", "win32": "windows"}.get(sys.platform, sys.platform)
    arch = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(arch, arch)
    return osname, arch


def check_binary(manifest: dict, bin_path: str, allow_local: bool) -> None:
    arts = (manifest.get("binary") or {}).get("artifacts") or []
    osname, arch = this_os_arch()
    want = None
    for a in arts:
        if a.get("os") == osname and a.get("arch") == arch:
            want = (a.get("sha256") or "").lower()
            break
    if not want:
        if allow_local:
            sys.stderr.write("agentshield-verify-manifest: no artifact pin for this OS/arch; skipping binary hash\n")
            return
        die("no artifact pin for this OS/arch")
    got = file_sha256(bin_path)
    if got == want:
        return
    if allow_local:
        sys.stderr.write(
            "agentshield-verify-manifest: warning: local binary sha256 does not match skill-manifest.json "
            "(set AGENTSHIELD_REQUIRE_PINNED=1 to refuse)\n"
        )
        return
    die("binary sha256 does not match skill-manifest.json")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", required=True)
    p.add_argument("--pubkey", required=True, help="Ed25519 public key, standard base64")
    p.add_argument("--bin", dest="bin_path", default="")
    p.add_argument("--allow-local", action="store_true")
    args = p.parse_args()

    try:
        pub_raw = base64.b64decode(args.pubkey, validate=True)
    except Exception:
        die("pubkey is not valid base64", 1)
    if len(pub_raw) != 32:
        die("pubkey must decode to 32 bytes", 1)

    try:
        with open(args.manifest, encoding="utf-8") as f:
            doc = json.load(f)
    except OSError as e:
        die(f"cannot read manifest: {e}", 1)
    except json.JSONDecodeError as e:
        die(f"manifest is not JSON: {e}", 1)

    signed_by = (doc.get("signed_by") or "").strip()
    if signed_by != args.pubkey.strip():
        die("signed_by does not match bootstrap public key")
    sig_hex = doc.get("signature") or ""
    try:
        sig = bytes.fromhex(sig_hex)
    except ValueError:
        die("signature is not hex")
    if len(sig) != 64:
        die("signature must be 64 bytes")

    openssl_verify(pub_raw, canonical_without_signature(doc), sig)

    if args.bin_path:
        if not os.path.isfile(args.bin_path):
            die(f"binary not found: {args.bin_path}", 1)
        check_binary(doc, args.bin_path, args.allow_local)

    sys.stderr.write("agentshield-verify-manifest: ok\n")


if __name__ == "__main__":
    main()
