#!/usr/bin/env python3
"""Package an unsigned, license-checked research SOURCE archive from clean Git."""

import argparse
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hackathon"))
from package_rc import clean_source, sha

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = (
    "LICENSE", "NOTICE", "LICENSES/README.md", "LICENSES/scope.json",
    "LICENSES/CC-BY-4.0.txt", "LICENSES/Go-BSD-3-Clause.txt",
    "THIRD_PARTY_NOTICES.md", "CITATION.cff", "REPRODUCIBILITY.md",
    "patches/openclaw/LICENSE", "site/vendor/mermaid-LICENSE",
    "site/vendor/mermaid-bundled-notices.txt",
    "docs/research/third-party-source-inventory.json",
    "docs/research/third-party-dependency-inventory.json",
)


def safe_file(root, name):
    path = root / name
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise ValueError("invalid source path")
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("source member missing, nonregular or escaping root: " + name)
    return path


def license_inventory(root):
    paths = set(REQUIRED)
    for name in paths:
        safe_file(root, name)
    sources = json.loads((root / "docs/research/third-party-source-inventory.json").read_text())
    dependencies = json.loads((root / "docs/research/third-party-dependency-inventory.json").read_text())
    mermaid = sources["mermaid"]
    if sha(safe_file(root, mermaid["path"])) != mermaid["local_sha256"]:
        raise ValueError("vendored source differs from audited inventory")
    components = mermaid["bundled_components"]
    if not components:
        raise ValueError("missing vendored dependency inventory")
    for item in components:
        if item.get("license") in (None, "unknown") or not item.get("license_files"):
            raise ValueError("missing component license")
        paths.update(item["license_files"])
    for item in dependencies["web"]:
        if not item["dev"]:
            if not item.get("license_files"):
                raise ValueError("missing Web runtime license")
            paths.update(item["license_files"])
    for name, expected in dependencies["lockfiles"].items():
        if sha(safe_file(root, name)) != expected:
            raise ValueError("dependency inventory does not match lockfile")
    for item in sources["patches"]:
        if sha(safe_file(root, item["path"])) != item["sha256"]:
            raise ValueError("patch differs from audited inventory")
        paths.add(item["license_file"])
    return {name: sha(safe_file(root, name)) for name in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--scanner", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source_root.resolve(), args.out_dir.resolve()
    if not re.fullmatch(r"research-v[0-9]+\.[0-9]+\.[0-9]+-rc\.[1-9][0-9]*", args.version):
        parser.error("use a distinct research-vX.Y.Z-rc.N version")
    commit = clean_source(source)
    if commit != args.source_sha:
        raise ValueError("source SHA mismatch")
    licenses = license_inventory(source)
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=source).decode().split("\0")
    for name in filter(None, names):
        safe_file(source, name)
        if Path(name).suffix == ".seed" or Path(name).name == ".env":
            raise ValueError("private state in source selection")
    output.mkdir(parents=True, exist_ok=False)
    prefix = "siq-agent-security-" + args.version
    archive = output / (prefix + ".tar.gz")
    subprocess.run(["git", "archive", "--format=tar.gz", "--prefix=" + prefix + "/",
                    "--output=" + str(archive), commit], cwd=source, check=True)
    with tempfile.TemporaryDirectory(prefix="siq-research-source-") as directory:
        unpacked = Path(directory)
        with tarfile.open(archive) as bundle:
            bundle.extractall(unpacked, filter="data")
        tree = unpacked / prefix
        if license_inventory(tree) != licenses:
            raise ValueError("archive license inventory mismatch")
        subprocess.run([sys.executable, str(source / "scripts/check_gitleaks_config.py"),
                        "--binary", str(args.scanner.resolve())], check=True, capture_output=True)
        result = subprocess.run([str(args.scanner.resolve()), "dir", str(tree), "--config",
                                 str(source / ".gitleaks.toml"), "--redact"], capture_output=True, check=False)
        if result.returncode:
            raise ValueError("source archive secret scan failed; candidate is not publishable")
        file_map = {str(p.relative_to(tree)): sha(p) for p in sorted(tree.rglob("*")) if p.is_file()}
    if clean_source(source) != commit:
        raise ValueError("source changed during packaging")
    identity = {
        "schema_version": "siq-research-source-candidate/v1",
        "artifact_kind": "source-only; no newly compiled binaries or model weights",
        "version": args.version, "source_sha": commit,
        "build_tool_sha256": sha(Path(__file__).resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "archive": archive.name, "archive_sha256": sha(archive),
        "official_signature": False, "published": False,
        "license_files_sha256": licenses, "source_files_sha256": file_map,
        "scope": "Exact clean Git source with audited vendored assets and notices; "
                 "locked Python dependencies and external models are not distributed. "
                 "No native binary or clean binary launcher acceptance is claimed.",
        "secret_scan": "calibrated gitleaks passed on extracted source archive",
    }
    metadata = output / "SOURCE-INFO.json"
    metadata.write_text(json.dumps(identity, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(
        f"{sha(archive)}  {archive.name}\n{sha(metadata)}  {metadata.name}\n")
    print(json.dumps({"archive": str(archive), "sha256": sha(archive),
                      "source_sha": commit, "official_signature": False}))


if __name__ == "__main__":
    main()
