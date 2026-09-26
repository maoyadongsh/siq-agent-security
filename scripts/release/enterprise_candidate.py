"""Build offline enterprise candidates from a reviewed commit; never sign/install."""

import argparse
import json
import os
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import package

CONNECTORS = ("hermes", "openclaw", "directory")
PUBLISHER_PUBLIC_KEY = "LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY="
SOURCE_PATHS = ("edge/agent", *(f"connectors/{name}" for name in CONNECTORS),
                "LICENSE", "NOTICE", "LICENSES", "THIRD_PARTY_NOTICES.md")


def build_env(environ=None):
    source = os.environ if environ is None else environ
    allowed = ("PATH", "HOME", "USER", "TMPDIR", "GOCACHE", "GOMODCACHE", "GOPATH", "SystemRoot")
    return {**{key: source[key] for key in allowed if key in source},
            "GOENV": "off", "GOWORK": "off", "GOTOOLCHAIN": "local",
            "GOPROXY": "off", "GOSUMDB": "off", "CGO_ENABLED": "0"}


def build(args):
    package.validate_inputs(args.source_sha, args.version)
    if len(args.version) > 64:
        raise ValueError("version exceeds release limit")
    selected = tuple(args.connector or CONNECTORS)
    if not selected or len(set(selected)) != len(selected) or set(selected) - set(CONNECTORS):
        raise ValueError("unsupported or duplicate connector")
    source_root, output = args.source_root.resolve(), args.out_dir.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists")
    if output.resolve().is_relative_to(source_root):
        raise ValueError("enterprise candidate output must be outside checkout")
    env = build_env()
    commit = package.run(["git", "rev-parse", args.source_sha + "^{commit}"],
                         cwd=source_root, env=env, phase="source identity").decode().strip()
    if commit != args.source_sha:
        raise ValueError("source commit mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".siq-enterprise-candidate-", dir=output.parent) as tmp:
        work = Path(tmp)
        source, result = work / "source", work / "result"
        source.mkdir()
        result.mkdir()
        archive = work / "source.tar"
        package.run(["git", "archive", "--format=tar", "--output", archive, commit,
                     "--", *SOURCE_PATHS], cwd=source_root, env=env, phase="source export")
        package.extract_source(archive, source)
        package.verify_source_inventory(source, args.expected_source_inventory)
        # Old commits with const versions silently ignore Go -X. Reject before builds.
        modules = [("edge-agent", "edge/agent", "main.go", "agentVersion")]
        modules += [(name, f"connectors/{name}", f"{name}.go", "connectorVersion") for name in sorted(selected)]
        for _, directory, filename, symbol in modules:
            if f'var {symbol} = "' not in (source / directory / filename).read_text():
                raise ValueError("source lacks release version stamping support")
        artifacts = []
        for arch in ("amd64", "arm64"):
            for name, directory, _, symbol in modules:
                filename = "edge-agent" if name == "edge-agent" else f"{name}-connector"
                relative = f"bin/{arch}/{filename}"
                binary = result / relative
                binary.parent.mkdir(parents=True, exist_ok=True)
                package.run(["go", "build", "-mod=readonly", "-buildvcs=false", "-trimpath",
                             "-ldflags", f"-s -w -X main.{symbol}={args.version}",
                             "-o", binary, "."], cwd=source / directory,
                            env={**env, "GOOS": "linux", "GOARCH": arch}, phase=f"build {name}/{arch}")
                info = binary.lstat()
                size = info.st_size
                if not stat.S_ISREG(info.st_mode) or not 0 < size <= 268435456:
                    raise ValueError("invalid build artifact")
                with binary.open("rb") as stream:
                    header = stream.read(20)
                machine = 62 if arch == "amd64" else 183
                if (header[:6] != b"\x7fELF\x02\x01" or len(header) != 20
                        or int.from_bytes(header[18:20], "little") != machine):
                    raise ValueError("artifact architecture mismatch")
                binary.chmod(0o755)
                artifacts.append({"id": name, "os": "linux", "arch": arch,
                                  "path": relative, "sha256": package.digest(binary), "bytes": size})
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(source / name, result / name)
        shutil.copytree(source / "LICENSES", result / "LICENSES")
        candidate = {"schema_version": "enterprise-release-candidate/v1",
                     "product": "siq-agent-security-enterprise", "version": args.version,
                     "source_commit": commit, "artifacts": artifacts,
                     "signed": False, "installable": False, "published": False,
                     "native_installation_acceptance": "not_run",
                     "source_inventory": package.inventory(source),
                     "packaging_tool_sha256": package.digest(Path(__file__)),
                     "packaging_helper_sha256": package.digest(Path(package.__file__)),
                     "go_version": package.run(["go", "version"], cwd=source, env=env,
                                               phase="Go version").decode().strip()}
        # These exact bytes are the enterprise-release/v1 Ed25519 signing input.
        # A request is not a signature and is never named release.json.
        signing_input = {"schema_version": "enterprise-release/v1",
                         "product": candidate["product"], "version": candidate["version"],
                         "source_commit": commit, "artifacts": artifacts,
                         "signed_by": PUBLISHER_PUBLIC_KEY}
        signing_bytes = json.dumps(signing_input, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True).encode("ascii")
        (result / "publisher-signing-input.json").write_bytes(signing_bytes)
        (result / "CANDIDATE.json").write_text(json.dumps(candidate, sort_keys=True, indent=2) + "\n")
        (result / "REVIEW.md").write_text(
            "# Unsigned enterprise candidate\n\n"
            "Not installable. No release.json, signature, registration or service activation.\n"
            "Review source, binaries and licenses before separately authorized publisher signing.\n"
            "publisher-signing-input.json contains exact canonical Ed25519 input bytes, without a signature.\n"
            "Use only the existing publisher identity in the controlled signing environment.\n"
            "After signing, independently verify enterprise-release/v1 with the compiled trust root.\n"
            "Do not rename signing input to release.json or copy a historical signature.\n"
            "Cross compilation is not native installation or security acceptance.\n")
        # Archive outside its source tree to prevent accidental self-inclusion.
        prefix = f"siq-agent-security-enterprise-{args.version}-unsigned-candidate"
        portable = work / f"{prefix}.zip"
        package.zip_verified(result, portable, prefix)
        portable.rename(result / portable.name)
        (result / "SHA256SUMS").write_text("".join(
            f"{details['sha256']}  {name}\n" for name, details in package.inventory(result).items()))
        # mkdir is exclusive even if another builder finishes concurrently.
        output.mkdir()
        try:
            for entry in result.iterdir():
                entry.rename(output / entry.name)
        except OSError:
            # Do not delete a potentially externally modified directory.
            raise ValueError("candidate transfer incomplete; review output before reuse") from None
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=package.ROOT)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--expected-source-inventory", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--connector", action="append", choices=CONNECTORS)
    parser.add_argument("--out-dir", type=Path, required=True)
    try:
        build(parser.parse_args())
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile):
        print("enterprise candidate failed; no signed release produced", file=sys.stderr)
        return 1
    print("Unsigned enterprise candidate built; signing and installation acceptance pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
