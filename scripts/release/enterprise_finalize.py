"""Assemble an enterprise bundle after external signing; never sign or publish."""

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import enterprise_candidate
import package


def read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError("unsafe input file")
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError("input exceeds limit")
        return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def verify(verifier, manifest, root, expected):
    result = subprocess.run([str(verifier), "verify-enterprise-release", "--release", str(manifest),
                             "--bundle", str(root)], env=enterprise_candidate.build_env(),
                            capture_output=True, timeout=60, check=False)
    if result.returncode != 0 or len(result.stdout) > 8192:
        raise ValueError("independent release verification failed")
    report = json.loads(result.stdout, object_pairs_hook=unique_object)
    if (not isinstance(report, dict) or report != expected
            or any(type(report[key]) is not type(value) for key, value in expected.items())):
        raise ValueError("independent verification report mismatch")


def finalize(args):
    if sys.platform != "linux":
        raise ValueError("enterprise finalization requires Linux")
    package.validate_inputs(args.source_sha, args.version)
    if not re.fullmatch(r"[0-9a-f]{64}", args.verifier_sha256):
        raise ValueError("reviewed verifier digest required")
    candidate, output = args.candidate_dir.resolve(), args.out_dir.absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(candidate):
        raise ValueError("output must be new and outside candidate")
    if output.resolve().is_relative_to(package.ROOT):
        raise ValueError("output must be outside product checkout")
    if args.verifier.resolve().is_relative_to(candidate):
        raise ValueError("verifier must be independent of candidate")
    raw = read_regular(args.release, 2 << 20)
    envelope = json.loads(raw, object_pairs_hook=unique_object)
    if (not isinstance(envelope, dict) or envelope.get("version") != args.version
            or envelope.get("source_commit") != args.source_sha):
        raise ValueError("expected release identity mismatch")
    unsigned = {key: value for key, value in envelope.items() if key != "signature"}
    signing_input = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    if signing_input != read_regular(candidate / "publisher-signing-input.json", 2 << 20):
        raise ValueError("signed release differs from candidate signing request")
    trusted = read_regular(args.verifier, 256 << 20)
    if hashlib.sha256(trusted).hexdigest() != args.verifier_sha256:
        raise ValueError("reviewed verifier digest mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".siq-enterprise-finalize-", dir=output.parent) as tmp:
        work = Path(tmp)
        verifier, manifest = work / "trusted-verifier", work / "signed-release.json"
        verifier.write_bytes(trusted)
        verifier.chmod(0o500)
        manifest.write_bytes(raw)
        expected = {"schema_version": "enterprise-release-verification/v1", "version": args.version,
                    "source_commit": args.source_sha, "manifest_sha256": hashlib.sha256(raw).hexdigest(),
                    "publisher_signature_verified": True, "artifact_bytes_verified": True, "installed": False}
        verify(verifier, manifest, candidate, expected)
        bundle, result = work / "bundle", work / "result"
        bundle.mkdir()
        result.mkdir()
        for artifact in envelope["artifacts"]:
            relative = artifact["path"]
            if not re.fullmatch(r"bin/(?:amd64|arm64)/(?:edge-agent|[a-z]+-connector)", relative):
                raise ValueError("invalid artifact layout")
            data = read_regular(candidate / relative, 256 << 20)
            if len(data) != artifact["bytes"] or hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                raise ValueError("artifact changed during assembly")
            destination = bundle / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            destination.chmod(0o755)
        licenses = [Path(name) for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md")]
        license_root = candidate / "LICENSES"
        if not license_root.is_dir() or license_root.is_symlink():
            raise ValueError("license directory missing or unsafe")
        for path in license_root.rglob("*"):
            if path.is_symlink():
                raise ValueError("linked license entry")
            if path.is_file():
                licenses.append(path.relative_to(candidate))
            if len(licenses) > 256:
                raise ValueError("too many license files")
        for relative in licenses:
            data = read_regular(candidate / relative, 1 << 20)
            destination = bundle / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        (bundle / "release.json").write_bytes(raw)
        verify(verifier, bundle / "release.json", bundle, expected)
        info = {**expected, "published": False, "installation_acceptance": "not_run",
                "verifier_sha256": args.verifier_sha256,
                "finalizer_sha256": package.digest(Path(__file__)),
                "unsigned_supporting_files": [str(path) for path in licenses]}
        (bundle / "SOURCE-INFO.json").write_text(json.dumps(info, sort_keys=True, indent=2) + "\n")
        (bundle / "INSTALL.md").write_text(
            "# Enterprise signed binary bundle\n\n"
            "Publisher signature covers release identity and binary pins, not these instructions or licenses.\n"
            "No device enrollment, runtime protection or installation acceptance is implied.\n"
            "Use the trusted Skill installer with a current organization/environment plan and explicit scope confirmation.\n"
            "Never execute an unverified binary. Installation must reverify the publisher, plan and private staging.\n")
        prefix = f"siq-agent-security-enterprise-{args.version}"
        package.zip_verified(bundle, result / f"{prefix}-bundle.zip", prefix)
        (result / "SOURCE-INFO.json").write_bytes((bundle / "SOURCE-INFO.json").read_bytes())
        (result / "release.json").write_bytes(raw)
        (result / "SHA256SUMS").write_text("".join(
            f"{entry['sha256']}  {name}\n" for name, entry in package.inventory(result).items()))
        output.mkdir()
        for entry in result.iterdir():
            entry.rename(output / entry.name)
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("candidate-dir", "release", "verifier", "out-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("source-sha", "version", "verifier-sha256"):
        parser.add_argument("--" + name, required=True)
    try:
        finalize(parser.parse_args())
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile):
        print("enterprise finalization failed; no publication performed", file=sys.stderr)
        return 1
    print("Verified bundle assembled; unpublished, installation acceptance pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
