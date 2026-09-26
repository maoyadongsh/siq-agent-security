#!/usr/bin/env python3
"""Build an isolated binary/Skill candidate; optionally verify publisher signing.

This command never publishes, starts a service, or changes the checkout.
Unsigned candidates deliberately have no installable Skill archive.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NAME = "siq-agent-security"
TARGETS = (("linux", "amd64"), ("linux", "arm64"), ("darwin", "arm64"), ("windows", "amd64"))
SEEDS = ("SIQ_AGENT_SECURITY_RELEASE_SEED", "AGENTSHIELD_RELEASE_SEED")
SOURCE_PATHS = ("apps/agentshield", "apps/web", "skills/siq-agent-security",
                "LICENSE", "NOTICE", "LICENSES", "THIRD_PARTY_NOTICES.md")
RELEASE_BASE = "https://github.com/maoyadongsh/siq-agent-security/releases/download/"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_name(system, arch):
    return f"{NAME}-{system}-{arch}" + (".exe" if system == "windows" else "")


def build_env(environ=None):
    return {k: v for k, v in (os.environ if environ is None else environ).items()
            if not k.upper().startswith(("SIQ_", "AGENTSHIELD_"))}


def run(args, *, cwd, env, phase):
    result = subprocess.run([str(a) for a in args], cwd=cwd, env=env, capture_output=True, check=False)
    if result.returncode:
        # Subprocess output can contain private build paths or signing diagnostics.
        raise ValueError(f"{phase} failed (exit {result.returncode}); no release produced")
    return result.stdout


def inventory(root):
    result = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("nonregular package entry")
        if stat.S_ISREG(mode):
            result[path.relative_to(root).as_posix()] = {
                "sha256": digest(path), "bytes": path.stat().st_size,
                "executable": bool(mode & 0o111),
            }
    return result


def validate_inputs(source_sha, version):
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("source-sha must be a full commit ID")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", version):
        raise ValueError("version must be an explicit semantic version")


def extract_source(archive, destination):
    with tarfile.open(archive) as bundle:
        members = bundle.getmembers()
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts or not (member.isfile() or member.isdir()):
                raise ValueError("unsafe source archive entry")
            if name.name == ".env" or name.suffix == ".seed":
                raise ValueError("private state in source archive")
        bundle.extractall(destination, members=members, filter="data")


def verify_source_inventory(source, expected):
    """Bind the exported commit to an independently reviewed source snapshot."""
    if expected.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("expected source inventory exceeds size limit")
    doc = json.loads(expected.read_text())
    if (not isinstance(doc, dict) or set(doc) != {"schema_version", "files"}
            or doc["schema_version"] != "siq-release-source-inventory/v1"
            or not isinstance(doc["files"], dict) or not doc["files"]):
        raise ValueError("invalid expected source inventory")
    if inventory(source) != doc["files"]:
        raise ValueError("exported commit differs from reviewed source inventory; no release produced")


def stage_skill(source, target, version):
    shutil.copytree(source, target)
    # A fixed source commit can contain a historical manifest. It cannot sign this build.
    (target / "skill-manifest.json").unlink(missing_ok=True)
    descriptor = target / "SKILL.md"
    text = descriptor.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("Skill frontmatter missing")
    end = text.index("\n---\n", 4)
    frontmatter, count = re.subn(r"(?m)^version: .+$", f"version: {version}", text[:end])
    if count != 1:
        raise ValueError("Skill frontmatter must have one version")
    descriptor.write_text(frontmatter + text[end:])


def verify_pins(manifest, binaries, version):
    doc = json.loads(manifest.read_text())
    if doc.get("manifest_version") != 3 or not doc.get("client_compatibility") or not doc.get("state_compatibility"):
        raise ValueError("client-compatible v3 manifest required")
    if any(doc.get(key, {}).get("name") != NAME or doc[key].get("version") != version
           for key in ("skill", "binary")):
        raise ValueError("manifest product/version mismatch")
    artifacts = doc["binary"].get("artifacts", [])
    targets = [(a.get("os"), a.get("arch")) for a in artifacts]
    if len(targets) != len(TARGETS) or set(targets) != set(TARGETS):
        raise ValueError("manifest must contain exactly four distinct targets")
    for artifact in artifacts:
        name = artifact_name(artifact["os"], artifact["arch"])
        path = binaries / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("binary missing or not regular")
        expected_url = f"{RELEASE_BASE}{NAME}-v{version}/{name}"
        if (artifact.get("sha256") != digest(path) or artifact.get("bytes") != path.stat().st_size
                or artifact.get("url") != expected_url):
            raise ValueError("binary pin or release URL mismatch")


def zip_verified(root, output, prefix):
    files = inventory(root)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, details in files.items():
            info = zipfile.ZipInfo(prefix + "/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if details["executable"] else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, (root / name).read_bytes())
    with zipfile.ZipFile(output) as bundle:
        if set(bundle.namelist()) != {prefix + "/" + name for name in files}:
            raise ValueError("archive inventory mismatch")
        for name, details in files.items():
            if hashlib.sha256(bundle.read(prefix + "/" + name)).hexdigest() != details["sha256"]:
                raise ValueError("archive content mismatch")


def build(args):
    validate_inputs(args.source_sha, args.version)
    source_root = args.source_root.resolve()
    output = args.out_dir.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("output already exists; choose a new directory")
    if output.resolve() == source_root or (output.resolve().is_relative_to(source_root)
            and output.resolve().relative_to(source_root).parts[0] != ".tmp"):
        raise ValueError("in-repository output must be under .tmp")
    if args.sign and not any(os.environ.get(key) for key in SEEDS):
        raise ValueError("publisher seed unavailable; use unsigned preparation or provide the existing release key securely")
    env = build_env()
    commit = run(["git", "rev-parse", args.source_sha + "^{commit}"], cwd=source_root,
                 env=env, phase="source identity").decode().strip()
    if commit != args.source_sha:
        raise ValueError("source commit mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Temporary output is on the destination filesystem. Failures never leave a release-looking directory.
    with tempfile.TemporaryDirectory(prefix=".siq-release-build-", dir=output.parent) as temp:
        workspace = Path(temp)
        archive, source, result = workspace / "source.tar", workspace / "source", workspace / "result"
        source.mkdir()
        result.mkdir()
        run(["git", "archive", "--format=tar", "--output", archive, commit, "--", *SOURCE_PATHS],
            cwd=source_root, env=env, phase="tracked source export")
        extract_source(archive, source)
        if getattr(args, "expected_source_inventory", None) is not None:
            verify_source_inventory(source, args.expected_source_inventory)
        embedded = source / "apps/agentshield/internal/ui/embedded"
        before = inventory(embedded)
        if "index.html" not in before:
            raise ValueError("embedded UI missing")
        print("Rebuilding the locked local UI in an isolated source snapshot", flush=True)
        run(["npm", "ci"], cwd=source / "apps/web", env=env, phase="locked Web dependencies")
        run(["npm", "run", "build:local"], cwd=source / "apps/web", env=env, phase="local UI build")
        if inventory(embedded) != before:
            raise ValueError("rebuilt UI differs from the committed embed; commit and review generated assets first")
        bundle = workspace / "bundle"
        bundle.mkdir()
        skill = bundle / "skills" / NAME
        stage_skill(source / "skills" / NAME, skill, args.version)
        binaries = bundle / "bin"
        binaries.mkdir()
        module = source / "apps/agentshield"
        flags = ["-buildvcs=false", "-trimpath", "-ldflags", f"-s -w -X main.Version={args.version}"]
        for system, arch in TARGETS:
            name = artifact_name(system, arch)
            print(f"Building {system}/{arch}", flush=True)
            run(["go", "build", *flags, "-o", binaries / name, "./cmd/agentshield"], cwd=module,
                env={**env, "GOOS": system, "GOARCH": arch, "CGO_ENABLED": "0"}, phase=f"build {system}/{arch}")
        verifier = workspace / ("verifier.exe" if os.name == "nt" else "verifier")
        native_env = {k: v for k, v in env.items() if k not in ("GOOS", "GOARCH")}
        run(["go", "build", *flags, "-o", verifier, "./cmd/agentshield"], cwd=module,
            env={**native_env, "CGO_ENABLED": "0"}, phase="native verifier build")
        scan_env = {**native_env, "SIQ_AGENT_SECURITY_STATE_DIR": str(workspace / "scan-state")}
        run([verifier, "init"], cwd=module, env=scan_env, phase="isolated admission state")
        admission = json.loads(run([verifier, "admit", skill], cwd=module, env=scan_env, phase="Skill self-admission"))
        if admission.get("verdict") not in ("admit", "admit_with_conditions"):
            raise ValueError("Skill self-admission did not allow the staged payload")
        if args.sign:
            manifest = skill / "skill-manifest.json"
            signing_env = {**native_env, **{key: os.environ[key] for key in SEEDS if os.environ.get(key)}}
            run([verifier, "release-manifest", "--skill-dir", skill, "--bin-dir", binaries,
                 "--version", args.version, "--url-base", f"{RELEASE_BASE}{NAME}-v{args.version}",
                 "--client-compatible", "--out", manifest], cwd=module, env=signing_env, phase="publisher signing")
            run([verifier, "manifest-verify", manifest], cwd=module, env=native_env, phase="official trust-root verification")
            verify_pins(manifest, binaries, args.version)
        for name in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"):
            shutil.copy2(source / name, bundle / name)
        shutil.copytree(source / "LICENSES", bundle / "LICENSES")
        identity = {
            "schema_version": "siq-binary-release-preparation/v1", "source_sha": commit,
            "version": args.version, "publisher_manifest_verified": args.sign, "published": False,
            "signature_scope": "Skill content and four binary pins" if args.sign else "none",
            "platform_installation_acceptance": "not_run", "ui_matches_committed_embed": True,
            "skill_self_admission": admission["verdict"],
            "go_version": run(["go", "version"], cwd=module, env=native_env, phase="Go version").decode().strip(),
            "node_version": run(["node", "--version"], cwd=source, env=env, phase="Node version").decode().strip(),
            "packaging_tool_sha256": digest(Path(__file__).resolve()),
            "staged_skill_changes": ["SKILL.md frontmatter version; historical manifest excluded before signing"],
            "files": inventory(bundle),
        }
        (bundle / "SOURCE-INFO.json").write_text(json.dumps(identity, indent=2) + "\n")
        (bundle / "INSTALL.md").write_text(installation_text(args.version, args.sign))
        kind = "bundle" if args.sign else "unsigned-candidate"
        zip_verified(bundle, result / f"{NAME}-{args.version}-{kind}.zip", f"{NAME}-{args.version}")
        if args.sign:
            zip_verified(skill, result / f"{NAME}-skill-{args.version}.zip", NAME)
        # Release assets have flat names matching the signed URLs and SHA256SUMS.
        for binary in binaries.iterdir():
            shutil.copy2(binary, result / binary.name)
        shutil.copy2(bundle / "SOURCE-INFO.json", result / "SOURCE-INFO.json")
        (result / "SHA256SUMS").write_text("".join(
            f"{details['sha256']}  {name}\n" for name, details in inventory(result).items()))
        if output.exists():
            raise ValueError("output appeared during build; refusing overwrite")
        result.rename(output)
    print(json.dumps({"directory": str(output), "source_sha": commit,
                      "publisher_manifest_verified": args.sign, "published": False}))


def installation_text(version, signed):
    if not signed:
        return (f"# Unsigned development candidate {version}\n\n"
                "No publisher manifest is included. Bootstrap intentionally refuses this candidate. "
                "It is for build review, not signed installation. Rebuild with the existing publisher key "
                "using --sign after approval; do not copy an old manifest here.\n")
    return f"""# Signed package {version}

The Skill manifest authenticates Skill content and binary pins with the existing
publisher trust root. SOURCE-INFO and SHA256SUMS are descriptive metadata, not
independent publisher signatures. Cross compilation is not native OS acceptance.

Python 3 is required (3.12+ recommended). Extract the complete bundle into a new
directory owned by you. The commands below create independent state in state/.
The first run must initialize state: bootstrap calls serve and does not initialize
an empty state directory. Verify first, then use the verified program's start.

## Linux/macOS (Linux arm64 example)

Select linux-amd64 or darwin-arm64 instead when appropriate. Run in the extracted
bundle directory. Keep the terminal open while the foreground service is running.

```bash
chmod +x bin/siq-agent-security-linux-arm64
export SIQ_AGENT_SECURITY_BIN="$PWD/bin/siq-agent-security-linux-arm64"
export SIQ_AGENT_SECURITY_STATE_DIR="$PWD/state"
export SIQ_AGENT_SECURITY_STAGE_DIR="$PWD/.verified-bin"
export SIQ_AGENT_SECURITY_REQUIRE_PINNED=1
VERIFIED_BIN="$(sh skills/siq-agent-security/scripts/resolve_verified_bin.sh)" &&
  "$VERIFIED_BIN" start --port 47611
```

## Windows PowerShell (Python available as python)

The public key below is the existing publisher trust root, not a key taken from
the manifest being verified. Keep the normal system execution policy.

```powershell
$ErrorActionPreference = 'Stop'
$env:SIQ_AGENT_SECURITY_BIN = (Resolve-Path './bin/siq-agent-security-windows-amd64.exe').Path
$env:SIQ_AGENT_SECURITY_STATE_DIR = Join-Path (Get-Location).Path 'state'
$env:SIQ_AGENT_SECURITY_STAGE_DIR = Join-Path (Get-Location).Path '.verified-bin'
$VerifiedBin = & python './skills/siq-agent-security/scripts/verify_manifest.py' `
  --manifest './skills/siq-agent-security/skill-manifest.json' `
  --pubkey 'LtEknKeTxzUQwErXI0MboUQQXKqrGp+R2x2RUv9/ZHY=' `
  --skill-dir './skills/siq-agent-security' `
  --bin $env:SIQ_AGENT_SECURITY_BIN --stage-to $env:SIQ_AGENT_SECURITY_STAGE_DIR
if ($LASTEXITCODE -ne 0 -or -not $VerifiedBin) {{ throw 'Package verification failed' }}
& "$VerifiedBin" start --port 47611
```

## Open the console on the correct computer

For normal personal use, install on the same computer as your browser. Open
http://127.0.0.1:47611/overview there. This address is local to the browser's
computer, not a public URL. Installing only the Skill does not start the runtime.

If you installed on a remote/SSH machine, run the following on your **browser
computer**, replacing SSH_USER@SSH_HOST with your established SSH login target:

```text
ssh -N -o ExitOnForwardFailure=yes -L 127.0.0.1:47611:127.0.0.1:47611 SSH_USER@SSH_HOST
```

Keep that SSH terminal open, then open http://127.0.0.1:47611/overview on the
browser computer. SSH access and a local SSH client are required. Use the same
port at both ends to preserve Host/Origin checks; replace all three port values
if your instance uses another port. If the local port is occupied, resolve its
ownership first; do not kill an unknown process. Do not expose the personal
service on 0.0.0.0, replace the URL with a LAN IP, or disable host-key checks.

If the page offers “通过智能体连接”, send its connection request to the SIQ Skill
on the **service machine**. After your explicit confirmation, that browser enters
the console without copying a pairing code. New v2 management sessions last a
fixed 24 hours; refreshing does not extend them. Logout or service restart
requires reconnection. The connection request itself lasts 5 minutes.
Older releases retain manual pairing and their original session duration.

Manual fallback: enter the one-time pairing code printed by the service locally;
do not paste it or any token into chat. Ctrl+C stops this foreground instance. Reuse the same state path
to retain identity and history. A matching running instance is reused; use pair
--port 47611 with the same verified program and state directory for a fresh code.

If you use bootstrap.sh/bootstrap.ps1 instead, first run init --port 47611 with
the verified program and the same state directory, and check initialization
succeeded. Check readiness with status --port 47611; a bootstrap log line alone
is not health verification. Starting the service does not install an adapter or
grant permissions.

For subsequent visits, use the same verified program and state directory with
ui. It verifies the instance before opening a browser; SSH/headless environments
receive access instructions instead. ui --print returns only the local URL for
tools, not a guarantee that another computer can reach it. Session connection
does not approve agent business permissions.

For the Skill-only ZIP, same-version binary assets must exist at the signed URLs.
On Linux/macOS explicitly set SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=1 and use the
Skill's scripts/resolve_verified_bin.sh to obtain a verified program, then start
it as above with independent state/staging directories. On Windows explicitly
replace --bin with --fetch-artifact in the verifier command, retaining the fixed
public key and --stage-to. GitHub's automatic source ZIP is not this signed
installation package.
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--expected-source-inventory", type=Path,
                        help="require exported commit bytes/modes to match a reviewed source inventory before builds")
    parser.add_argument("--version", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sign", action="store_true", help="sign using the existing publisher key; verify the built-in trust root")
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"release preparation: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
