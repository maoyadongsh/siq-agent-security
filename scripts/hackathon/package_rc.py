#!/usr/bin/env python3
"""Prepare an unsigned RC from a clean, frozen source commit."""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[2]
TARGETS = (("linux", "amd64"), ("linux", "arm64"), ("darwin", "arm64"), ("windows", "amd64"))
METADATA = {"candidate-manifest.json", "SHA256SUMS"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("x") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def entries(root):
    result = {}
    for path in sorted(root.rglob("*")):
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode) or not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("package contains a symlink or non-regular entry")
        name = path.relative_to(root).as_posix()
        if stat.S_ISREG(mode) and name not in METADATA:
            result[name] = {"sha256": sha(path), "bytes": path.stat().st_size,
                            "executable": bool(mode & 0o111)}
    return result


def verify_package(root):
    manifest_path = root / "candidate-manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("manifest must be a regular file")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != "hackathon-candidate/v1" or manifest.get("official_signature") is not False:
        raise ValueError("unsupported candidate manifest or false release-signature claim")
    if entries(root) != manifest["files"]:
        raise ValueError("candidate file inventory mismatch")
    required = {"source/apps/secure-agent/secure_agent/models.py", "source/demo/fixtures/github/repository.json",
                "source/scripts/hackathon/launch_rc.py", "source/apps/agentshield/internal/ui/embedded/index.html",
                "source/packages/contracts/model-task-plan-v2.schema.json", "sbom.cdx.json", "source-info.json",
                "skills-inventory.json", "EVIDENCE_SUMMARY.md"}
    required |= {f"source/skills/{name}/SKILL.md" for name in ("secure-research", "secure-report", "secure-delivery")}
    required |= {"bin/siq-agent-security-" + os_name + "-" + arch + (".exe" if os_name == "windows" else "")
                 for os_name, arch in TARGETS}
    if not required <= manifest["files"].keys():
        raise ValueError("candidate runtime or target artifacts missing")
    checksums = "".join(f"{item['sha256']}  {name}\n" for name, item in sorted(manifest["files"].items()))
    checksums += f"{sha(manifest_path)}  candidate-manifest.json\n"
    if (root / "SHA256SUMS").read_text() != checksums:
        raise ValueError("candidate checksum list mismatch")
    identity = json.loads((root / "source-info.json").read_text())
    validate_identity(identity)
    return manifest


def validate_identity(identity):
    required = {"schema_version", "git_sha", "git_ref", "build_time", "go_version", "python_version", "node_version", "target"}
    if (not isinstance(identity, dict) or not required <= identity.keys()
            or identity["schema_version"] != "hackathon-rc-source/v2"
            or not re.fullmatch(r"[0-9a-f]{40}", identity.get("git_sha", ""))
            or any(not isinstance(identity[key], str) or not identity[key] for key in required - {"target"})
            or not isinstance(identity["target"], list) or not identity["target"]
            or any(target not in [system + "/" + arch for system, arch in TARGETS] for target in identity["target"])
            or "dirty" in identity or "source_files" in identity):
        raise ValueError("candidate source identity invalid")


def clean_source(root):
    for args in (["diff", "--quiet"], ["diff", "--cached", "--quiet"]):
        if subprocess.run(["git", *args], cwd=root, check=False).returncode:
            raise ValueError("candidate requires clean committed source")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root):
        raise ValueError("candidate requires clean committed source")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def sbom(source, version, toolchain):
    components = [{"type": "application", "name": "Secure Agent", "version": version},
                  {"type": "framework", "name": "Go standard library", "version": toolchain}]
    lock = json.loads((source / "apps/web/package-lock.json").read_text())
    seen = set()
    for path, package in lock["packages"].items():
        if not path or package.get("dev") or "node_modules/" not in path:
            continue
        name = package.get("name") or path.rsplit("node_modules/", 1)[1]
        identity = (name, package["version"])
        if identity in seen:
            continue
        seen.add(identity)
        components.append({"type": "library", "name": name, "version": identity[1],
                           "purl": f"pkg:npm/{quote(name, safe='/')}@{identity[1]}"})
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"component": {"type": "application", "name": "SIQ Agent Security", "version": version},
                         "properties": [{"name": "siq:inventory-scope", "value":
                             "Go stdlib daemon, stdlib-only Python application, and production Web lockfile dependencies. "
                             "The lockfile is a dependency superset, not bundle-level reachability analysis. "
                             "External Python/model/OS runtimes and build dependencies are not bundled or inventoried here."}]},
            "components": components}


def build(args):
    if not re.fullmatch(r"0\.3\.0-rc\.[1-9][0-9]*", args.version):
        raise ValueError("candidate version must be 0.3.0-rc.N")
    commit = clean_source(ROOT)
    if not args.source_sha or args.source_sha != commit:
        raise ValueError("--source-sha must match the frozen CI-verified checkout")
    # Build the UI from the locked clean checkout. A generated difference means
    # the commit did not contain its actual embedded UI and must go through CI again.
    subprocess.run(["npm", "ci"], cwd=ROOT / "apps/web", check=True, capture_output=True)
    subprocess.run(["npm", "run", "build:local"], cwd=ROOT / "apps/web", check=True, capture_output=True)
    if clean_source(ROOT) != commit:
        raise ValueError("source commit changed during build")
    out = args.out.resolve()
    if out.is_relative_to(ROOT) and out.relative_to(ROOT).parts[0] != ".tmp":
        raise ValueError("in-repository candidates must use the ignored .tmp directory")
    archive = out.with_name(out.name + ".tar.gz")
    if out.exists() or archive.exists():
        raise ValueError("candidate output already exists; choose a fresh directory")
    out.mkdir(parents=True)
    source = out / "source"
    source.mkdir()
    files = {}
    names = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=ROOT)
    for name in sorted(set(names.decode().split("\0")) - {""}):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] in (".git", ".tmp"):
            raise ValueError("unsafe source path")
        original = ROOT / relative
        if original.is_symlink() or original.name.endswith(".seed") or original.name == ".env":
            raise ValueError("symlink or private state in source selection")
        if not original.is_file():
            raise ValueError("source selection is not a regular file")
        copied = source / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copied)
        files[name] = sha(copied)
    env = dict(os.environ, GOTOOLCHAIN="go1.26.6", CGO_ENABLED="0")
    toolchain = subprocess.check_output(["go", "env", "GOVERSION"], env=env, text=True).strip()
    identity = {"schema_version": "hackathon-rc-source/v2", "build_time": datetime.now(timezone.utc).isoformat(),
                "git_sha": commit, "git_ref": subprocess.check_output(
                    ["git", "rev-parse", "--symbolic-full-name", "HEAD"], cwd=ROOT, text=True).strip(),
                "go_version": toolchain, "python_version": subprocess.check_output(["python3", "--version"], text=True).strip(),
                "node_version": subprocess.check_output(["node", "--version"], text=True).strip(),
                "target": [system + "/" + arch for system, arch in TARGETS]}
    validate_identity(identity)
    write_json(out / "source-info.json", identity)
    binary_dir = out / "bin"
    binary_dir.mkdir()
    for os_name, arch in TARGETS:
        name = f"siq-agent-security-{os_name}-{arch}" + (".exe" if os_name == "windows" else "")
        subprocess.run(["go", "build", "-buildvcs=false", "-trimpath", "-ldflags",
                        f"-s -w -X main.Version={args.version}", "-o", str(binary_dir / name), "./cmd/agentshield"],
                       cwd=source / "apps/agentshield", env={**env, "GOOS": os_name, "GOARCH": arch}, check=True)
        print(json.dumps({"built": name}), flush=True)
    write_json(out / "sbom.cdx.json", sbom(source, args.version, toolchain))
    (out / "EVIDENCE_SUMMARY.md").write_text(
        "# Candidate evidence summary\n\n"
        f"Frozen source: `{commit}`. This candidate is unsigned. Source identity, binary/Skill inventories "
        "and checksums are in this package.\n\n"
        "Implementation and measured checks are recorded in source/docs/hackathon/final-hardening-progress-v4.md. "
        "Canonical raw records are under source/docs/hackathon/evidence/final-hardening-v4/. "
        "Final extracted-candidate launch and video records are published separately after packaging; "
        "a package cannot contain proof of its own final archive hash.\n\n"
        "Model cohorts are small samples; earlier failures remain in the evidence set. Checksums establish "
        "byte integrity, not publisher identity. See the source limitations for same-UID, external-model "
        "and controlled-effect boundaries.\n")
    (out / "QUICK_START.md").write_text(
        "# Local unpublished candidate\n\n"
        "This is an unsigned release candidate built from a clean frozen commit, not an official release. Verify the archive hash from its "
        "separate preparation record and inspect source-info.json before use. Checksums detect changed bytes; "
        "they do not establish publisher identity. The historical v0.2.0 signed manifest does not sign this package.\n\n"
        "Requires Linux amd64/arm64 and Python >=3.12. Configure Step Plan outside this package as described in "
        "source/docs/hackathon/step-plan.md. No key or model weights are bundled. From the unpacked candidate:\n\n"
        "```bash\npython3 source/scripts/hackathon/package_rc.py --out . --verify-only\n"
        "python3 source/scripts/hackathon/launch_rc.py --state-dir /tmp/siq-candidate-new-state --port 47631\n```\n\n"
        "The state path must be new and outside this package. Open the printed loopback /demo URL and pair "
        "with the one-use code. Ctrl-C stops this foreground service after the current task exits. "
        "Use --provider ornith for the explicit local backup. Sources and delivery are controlled fixtures. "
        "See source/HACKATHON.md, source/docs/hackathon/submission-checklist.md and limitations.md for evidence "
        "and remaining gates. Other OS binaries are cross-compiled daemon artifacts, not native service certification.\n")
    write_json(out / "skills-inventory.json", {"schema_version": "hackathon-skill-inventory/v1",
        "official_signature": False, "version": args.version, "skills": {
            name: {path: value for path, value in files.items() if path.startswith("skills/" + name + "/")}
            for name in ("secure-research", "secure-report", "secure-delivery")},
        "historical_manifest": "source/skills/siq-agent-security/skill-manifest.json",
        "limitation": "Historical signed manifest belongs to v0.2.0; it does not authorize these new binaries."})
    subprocess.run(["python3", str(source / "scripts/check_gitleaks_config.py"), "--binary", str(args.scanner.resolve())],
                   check=True)
    with tempfile.TemporaryDirectory(prefix="siq-rc-scan-") as temp:
        report = Path(temp) / "findings.json"
        result = subprocess.run([str(args.scanner.resolve()), "dir", str(out), "--config", str(source / ".gitleaks.toml"),
            "--redact", "--report-format", "json", "--report-path", str(report)], capture_output=True, check=False)
        if result.returncode != 0:
            raise ValueError("candidate secret scan failed; no archive produced (inspect source separately with --redact)")
    write_json(out / "candidate-manifest.json", {"schema_version": "hackathon-candidate/v1", "version": args.version,
        "official_signature": False, "published": False, "toolchain": toolchain, "secret_scan": "calibrated gitleaks passed",
        "scope": "local unsigned candidate; checksum integrity is not official publisher authenticity",
        "files": entries(out)})
    manifest = json.loads((out / "candidate-manifest.json").read_text())
    with (out / "SHA256SUMS").open("x") as stream:
        for name, item in sorted(manifest["files"].items()):
            stream.write(f"{item['sha256']}  {name}\n")
        stream.write(f"{sha(out / 'candidate-manifest.json')}  candidate-manifest.json\n")
    verify_package(out)
    if clean_source(ROOT) != commit:
        raise ValueError("source changed during candidate build")
    with (archive.open("xb") as target,
          gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as compressed,
          tarfile.open(fileobj=compressed, mode="w") as bundle):
        for path in sorted(out.rglob("*")):
            info = bundle.gettarinfo(str(path), arcname=str(Path(out.name) / path.relative_to(out)))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if path.is_file():
                with path.open("rb") as stream:
                    bundle.addfile(info, stream)
            else:
                bundle.addfile(info)
    print(json.dumps({"candidate": str(out), "archive": str(archive), "archive_sha256": sha(archive),
                      "official_signature": False, "published": False}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--version", default="0.3.0-rc.1")
    parser.add_argument("--source-sha", help="exact frozen commit with successful remote PR CI")
    parser.add_argument("--scanner", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        result = verify_package(args.out.resolve())
        print(json.dumps({"verified_files": len(result["files"]), "official_signature": False}))
    elif args.scanner is None:
        parser.error("--scanner is required for calibrated candidate scanning")
    else:
        build(args)


if __name__ == "__main__":
    main()
