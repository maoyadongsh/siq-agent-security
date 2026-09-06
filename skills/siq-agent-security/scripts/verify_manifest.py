#!/usr/bin/env python3
"""Verify skill-manifest.json (Ed25519 over canonical JSON), optional binary sha256,
and Skill directory content_hash (DEV04-C; must match Go HashSkillDir / admission.HashDir).

stdlib + openssl 3 only. Never executes the binary.
Exit 3 on mismatch (same as siq-agent-security admit quarantine).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urlparse

# Match apps/agentshield/internal/admission.DefaultLimits and skipNames.
SKIP_NAMES = frozenset({".git", "skill.oms.sig", "skill-manifest.json"})
MAX_FILES = 2000
MAX_DIRS = 2000
MAX_TOTAL = 64 << 20
MAX_DEPTH = 16


def die(msg: str, code: int = 3) -> None:
    sys.stderr.write(f"siq-agent-security-verify-manifest: {msg}\n")
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


MAX_ARTIFACT_BYTES = 256 << 20


def lookup_artifact(manifest: dict) -> dict | None:
    arts = (manifest.get("binary") or {}).get("artifacts") or []
    osname, arch = this_os_arch()
    for a in arts:
        if a.get("os") == osname and a.get("arch") == arch:
            return a
    return None


def select_artifact(manifest: dict) -> dict:
    """Return the signed-manifest artifact pin for this OS/arch (DEV04-E)."""
    osname, arch = this_os_arch()
    a = lookup_artifact(manifest)
    if not a:
        die(f"no artifact for {osname}/{arch}")
    want = (a.get("sha256") or "").lower()
    url = (a.get("url") or "").strip()
    if len(want) != 64 or any(c not in "0123456789abcdef" for c in want):
        die(f"artifact sha256 for {osname}/{arch} is not 64 hex")
    if not url:
        die(f"artifact URL missing for {osname}/{arch}")
    return a


def artifact_sha256(manifest: dict) -> str | None:
    a = lookup_artifact(manifest)
    if not a:
        return None
    want = (a.get("sha256") or "").lower()
    if len(want) == 64 and all(c in "0123456789abcdef" for c in want):
        return want
    return None


def _url_allowed(url: str, allow_insecure: bool) -> None:
    u = urlparse(url)
    scheme = (u.scheme or "").lower()
    if scheme == "https":
        return
    if scheme == "http":
        if not allow_insecure:
            die("refusing non-HTTPS download (set SIQ_AGENT_SECURITY_ALLOW_INSECURE_DOWNLOAD=1 for loopback tests)")
        host = (u.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1"):
            return
        die("insecure HTTP only allowed to loopback")
    die(f"unsupported URL scheme {scheme!r}")


def download_verified_artifact(art: dict, dest: str, allow_insecure: bool) -> str:
    """GET artifact URL; enforce bytes+sha256 pins; chmod 0700. Never executes."""
    url = (art.get("url") or "").strip()
    want = (art.get("sha256") or "").lower()
    pinned_bytes = art.get("bytes")
    try:
        pinned = int(pinned_bytes) if pinned_bytes is not None else 0
    except (TypeError, ValueError):
        die("artifact bytes is not an integer", 1)
    _url_allowed(url, allow_insecure)
    if len(want) != 64:
        die("artifact sha256 must be 64 hex")
    max_n = pinned if pinned > 0 else MAX_ARTIFACT_BYTES
    if max_n > MAX_ARTIFACT_BYTES:
        max_n = MAX_ARTIFACT_BYTES

    req = urllib.request.Request(url, headers={"User-Agent": "siq-agent-security-fetch/1"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            cl = resp.headers.get("Content-Length")
            if cl is not None:
                try:
                    cl_n = int(cl)
                except ValueError:
                    die("bad Content-Length", 1)
                if cl_n > max_n:
                    die(f"Content-Length {cl_n} exceeds max {max_n}")
                if pinned > 0 and cl_n != pinned:
                    die(f"Content-Length {cl_n} != pinned bytes {pinned}")
            os.makedirs(os.path.dirname(dest) or ".", mode=0o700, exist_ok=True)
            h = hashlib.sha256()
            n = 0
            with open(dest, "xb") as out:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    n += len(chunk)
                    if n > max_n:
                        die(f"downloaded size exceeds max {max_n}")
                    h.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
    except urllib.error.HTTPError as e:
        die(f"download HTTP {e.code}", 1)
    except urllib.error.URLError as e:
        die(f"download failed: {e}", 1)
    except FileExistsError:
        die(f"download dest already exists: {dest}", 1)

    if pinned > 0 and n != pinned:
        try:
            os.remove(dest)
        except OSError:
            pass
        die(f"downloaded {n} bytes != pinned {pinned}")
    got = h.hexdigest()
    if got != want:
        try:
            os.remove(dest)
        except OSError:
            pass
        die(f"downloaded sha256 {got} != required {want}")
    os.chmod(dest, 0o700)
    return got


def check_binary(manifest: dict, bin_path: str, allow_local: bool) -> str | None:
    """Verify bin against manifest pin when present. Returns pin sha256 if matched/required."""
    want = artifact_sha256(manifest)
    if not want:
        if allow_local:
            sys.stderr.write("siq-agent-security-verify-manifest: no artifact pin for this OS/arch; skipping binary hash\n")
            return None
        die("no artifact pin for this OS/arch")
    got = file_sha256(bin_path)
    if got == want:
        return want
    if allow_local:
        sys.stderr.write(
            "siq-agent-security-verify-manifest: warning: local binary sha256 does not match skill-manifest.json "
            "(set SIQ_AGENT_SECURITY_REQUIRE_PINNED=1 to refuse)\n"
        )
        return None
    die("binary sha256 does not match skill-manifest.json")
    return None


def stage_verified_binary(src: str, stage_root: str, want_sha256: str | None) -> str:
    """Copy src into a private 0700 staging dir, Sync, re-hash (DEV04-D).

    want_sha256: when set, source and staged digests must equal it.
    Always requires staged digest == source digest taken before copy.
    Returns the staged file path (caller should execute this path).
    """
    if not os.path.isfile(src):
        die(f"stage source not a file: {src}", 1)
    if not os.access(src, os.X_OK):
        die(f"stage source not executable: {src}", 1)
    src_sum = file_sha256(src)
    want = (want_sha256 or "").lower()
    if want and src_sum != want:
        die(f"source sha256 {src_sum} != required {want}")
    os.makedirs(stage_root, mode=0o700, exist_ok=True)
    try:
        os.chmod(stage_root, 0o700)
    except OSError:
        pass
    staged_dir = tempfile.mkdtemp(prefix="bin.", dir=stage_root)
    try:
        os.chmod(staged_dir, 0o700)
        leaf = os.path.basename(src)
        if not leaf or leaf in (".", ".."):
            die("invalid binary basename", 1)
        dest = os.path.join(staged_dir, leaf)
        # Exclusive create + copy + fsync (no follow of src symlink content via open flags beyond default).
        with open(src, "rb") as inf, open(dest, "xb") as outf:
            while True:
                chunk = inf.read(1024 * 1024)
                if not chunk:
                    break
                outf.write(chunk)
            outf.flush()
            os.fsync(outf.fileno())
        os.chmod(dest, 0o700)
        staged_sum = file_sha256(dest)
        if staged_sum != src_sum:
            die(f"staged sha256 {staged_sum} != source {src_sum} (refusing TOCTOU/corrupt copy)")
        if want and staged_sum != want:
            die(f"staged sha256 {staged_sum} != required {want}")
        return dest
    except Exception:
        # Best-effort cleanup of failed stage.
        try:
            for name in os.listdir(staged_dir):
                os.remove(os.path.join(staged_dir, name))
            os.rmdir(staged_dir)
        except OSError:
            pass
        raise


class IncompleteSkillTree(Exception):
    """Tree cannot produce a complete content_hash (budget / escape)."""


def _posix_rel(root: str, path: str) -> str:
    rel = os.path.relpath(path, root)
    if rel == ".":
        return ""
    return rel.replace(os.sep, "/")


def _depth(posix_rel: str) -> int:
    if not posix_rel:
        return 0
    return posix_rel.count("/")


def _read_regular_bounded(path: str, remaining: int) -> bytes:
    """Read a regular file under remaining total-byte budget (+1 probe), matching Go addFile."""
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        raise IncompleteSkillTree("non-regular file refused")
    if st.st_size < 0 or st.st_size > remaining:
        raise IncompleteSkillTree("over total byte budget")
    with open(path, "rb") as f:
        opened = os.fstat(f.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise IncompleteSkillTree("file changed while opening")
        if opened.st_ino != st.st_ino or opened.st_dev != st.st_dev:
            raise IncompleteSkillTree("file changed while opening")
        data = f.read(remaining)
        extra = f.read(1)
        if extra:
            raise IncompleteSkillTree("over total byte budget")
    return data


def hash_skill_dir(
    root: str,
    *,
    max_files: int = MAX_FILES,
    max_dirs: int = MAX_DIRS,
    max_total: int = MAX_TOTAL,
    max_depth: int = MAX_DEPTH,
) -> str:
    """content_hash ≡ Go skillmanifest.HashSkillDir / admission.HashDir (DefaultLimits)."""
    if max_files <= 0 or max_total <= 0 or max_depth <= 0:
        raise ValueError("invalid scan limits")
    real_root = os.path.realpath(root)
    if not os.path.isdir(real_root):
        raise NotADirectoryError(real_root)

    entries: list[tuple[str, str, int]] = []  # path, sha256, bytes
    dirs_seen = 0
    total_bytes = 0

    # topdown walk; never follow directory symlinks (followlinks=False).
    for dirpath, dirnames, filenames in os.walk(real_root, topdown=True, followlinks=False):
        rel_dir = _posix_rel(real_root, dirpath)
        if rel_dir:
            if _depth(rel_dir) >= max_depth:
                raise IncompleteSkillTree("max depth exceeded")
            dirs_seen += 1
            if max_dirs > 0 and dirs_seen > max_dirs:
                raise IncompleteSkillTree("max dirs exceeded")

        # Prune / classify directory children (symlink dirs are not descended and not counted).
        keep_dirs: list[str] = []
        for name in sorted(dirnames):
            if name in SKIP_NAMES:
                continue
            child = os.path.join(dirpath, name)
            child_rel = f"{rel_dir}/{name}" if rel_dir else name
            if _depth(child_rel) >= max_depth:
                raise IncompleteSkillTree("max depth exceeded")
            if os.path.islink(child):
                # Symlink-to-dir: Go records neither hash nor descent (fail-closed only for escapes).
                try:
                    target = os.path.realpath(child)
                except OSError as e:
                    raise IncompleteSkillTree(f"symlink escape: {e}") from e
                if target != real_root and not (target.startswith(real_root + os.sep)):
                    raise IncompleteSkillTree("symlink escape")
                continue
            keep_dirs.append(name)
        dirnames[:] = keep_dirs

        for name in sorted(filenames):
            if name in SKIP_NAMES:
                continue
            child = os.path.join(dirpath, name)
            child_rel = f"{rel_dir}/{name}" if rel_dir else name
            if _depth(child_rel) >= max_depth:
                raise IncompleteSkillTree("max depth exceeded")

            if os.path.islink(child):
                try:
                    target = os.path.realpath(child)
                except OSError as e:
                    raise IncompleteSkillTree(f"symlink escape: {e}") from e
                if target != real_root and not (target.startswith(real_root + os.sep)):
                    raise IncompleteSkillTree("symlink escape")
                try:
                    st = os.stat(target)
                except OSError:
                    raise IncompleteSkillTree("symlink escape") from None
                if stat.S_ISDIR(st.st_mode):
                    continue
                if not stat.S_ISREG(st.st_mode):
                    raise IncompleteSkillTree("non-regular file refused")
                remaining = max_total - total_bytes
                data = _read_regular_bounded(target, remaining)
            else:
                st = os.lstat(child)
                if not stat.S_ISREG(st.st_mode):
                    raise IncompleteSkillTree("non-regular file refused")
                remaining = max_total - total_bytes
                data = _read_regular_bounded(child, remaining)

            if len(entries) >= max_files:
                raise IncompleteSkillTree("max files exceeded")
            digest = hashlib.sha256(data).hexdigest()
            size = len(data)
            total_bytes += size
            entries.append((child_rel, digest, size))

    entries.sort(key=lambda e: e[0])
    h = hashlib.sha256()
    for path, digest, size in entries:
        h.update(f"{path}\n{digest}\n{size}\n".encode("utf-8"))
    return h.hexdigest()


def check_skill_content_hash(manifest: dict, skill_dir: str) -> None:
    want = ((manifest.get("skill") or {}).get("content_hash") or "").lower()
    if len(want) != 64 or any(c not in "0123456789abcdef" for c in want):
        die("manifest skill.content_hash missing or not 64 hex chars")
    try:
        got = hash_skill_dir(skill_dir)
    except IncompleteSkillTree as e:
        die(f"skill content_hash incomplete: {e}")
    except OSError as e:
        die(f"cannot hash skill dir: {e}", 1)
    if got != want:
        die(f"skill content_hash mismatch: manifest {want} dir {got}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", default="", help="path to skill-manifest.json (required unless --print-content-hash)")
    p.add_argument("--pubkey", default="", help="Ed25519 public key, standard base64")
    p.add_argument("--bin", dest="bin_path", default="")
    p.add_argument("--allow-local", action="store_true")
    p.add_argument(
        "--skill-dir",
        default="",
        help="Skill directory to hash; compare to skill.content_hash (required for install paths)",
    )
    p.add_argument(
        "--print-content-hash",
        metavar="DIR",
        default="",
        help="print HashSkillDir-equivalent digest for DIR to stdout and exit (no signature check)",
    )
    p.add_argument(
        "--stage-to",
        default="",
        help="after verify, copy --bin into a private dir under this root, re-hash, print staged path on stdout (DEV04-D)",
    )
    p.add_argument(
        "--fetch-artifact",
        action="store_true",
        help="after signature verify, download OS/arch artifact from signed manifest URL, pin-check, stage (DEV04-E); requires --stage-to",
    )
    args = p.parse_args()

    if args.print_content_hash:
        try:
            print(hash_skill_dir(args.print_content_hash))
        except IncompleteSkillTree as e:
            die(f"skill content_hash incomplete: {e}")
        except OSError as e:
            die(f"cannot hash skill dir: {e}", 1)
        return

    if not args.manifest or not args.pubkey:
        die("--manifest and --pubkey are required", 1)

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

    skill_dir = args.skill_dir
    if skill_dir:
        check_skill_content_hash(doc, skill_dir)

    if args.fetch_artifact:
        if args.bin_path:
            die("--fetch-artifact conflicts with --bin", 1)
        if not args.stage_to:
            die("--fetch-artifact requires --stage-to", 1)
        art = select_artifact(doc)
        allow_insecure = os.environ.get("SIQ_AGENT_SECURITY_ALLOW_INSECURE_DOWNLOAD", "") == "1"
        with tempfile.TemporaryDirectory(prefix="siq-fetch.") as td:
            os.chmod(td, 0o700)
            leaf = os.path.basename(urlparse(art["url"]).path) or "siq-agent-security"
            if leaf in (".", ".."):
                leaf = "siq-agent-security"
            dest = os.path.join(td, leaf)
            pin = download_verified_artifact(art, dest, allow_insecure)
            staged = stage_verified_binary(dest, args.stage_to, pin)
        sys.stderr.write("siq-agent-security-verify-manifest: ok (fetched+staged)\n")
        print(staged)
        return

    pin: str | None = None
    if args.bin_path:
        if not os.path.isfile(args.bin_path):
            die(f"binary not found: {args.bin_path}", 1)
        pin = check_binary(doc, args.bin_path, args.allow_local)

    if args.stage_to:
        if not args.bin_path:
            die("--stage-to requires --bin (or use --fetch-artifact)", 1)
        # When pinned mode matched, re-require pin on staged copy; otherwise self-consistency only.
        staged = stage_verified_binary(args.bin_path, args.stage_to, pin)
        sys.stderr.write("siq-agent-security-verify-manifest: ok (staged)\n")
        print(staged)
        return

    sys.stderr.write("siq-agent-security-verify-manifest: ok\n")


if __name__ == "__main__":
    main()
