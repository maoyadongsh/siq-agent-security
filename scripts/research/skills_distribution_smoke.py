#!/usr/bin/env python3
"""Verify a pinned skills CLI in temporary projects; never execute Skill scripts."""

import argparse
import base64
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from verify_skill_distribution import snapshot_tree, verify_distribution

ROOT = Path(__file__).resolve().parents[2]
PIN_PATH = Path(__file__).with_name("skills-upstream.json")
SKILL_PATH = "skills/siq-agent-security"
AGENTS = {
    "openclaw": "skills",
    "hermes-agent": ".hermes/skills",
    "codebuddy": ".codebuddy/skills",
    "trae": ".trae/skills",
}
AGENT_LABELS = {"openclaw": "OpenClaw", "hermes-agent": "Hermes Agent",
                "codebuddy": "CodeBuddy", "trae": "Trae"}
MAX_DOWNLOAD = 32 * 1024 * 1024
PRELOAD = """const os = require('node:os');
const { syncBuiltinESMExports } = require('node:module');
os.homedir = () => process.env.SIQ_SKILLS_TEST_HOME;
syncBuiltinESMExports();
"""


def load_pin(path):
    pin = json.loads(Path(path).read_text())
    if not isinstance(pin, dict) or pin.get("schema_version") != 1:
        raise ValueError("unsupported pin schema")
    upstream, packages = pin.get("upstream"), pin.get("packages")
    if (not isinstance(upstream, dict) or not isinstance(packages, list) or not packages
            or not all(isinstance(upstream.get(key), str) for key in ("commit", "version", "repository"))):
        raise ValueError("invalid pin structure")
    if not re.fullmatch(r"[0-9a-f]{40}", upstream["commit"]):
        raise ValueError("invalid upstream commit")
    seen = set()
    for item in packages:
        if (not isinstance(item, dict)
                or not all(isinstance(item.get(key), str) for key in ("name", "version", "url", "sha256", "integrity"))):
            raise ValueError("invalid package pin structure")
        name, version = item["name"], item["version"]
        if not re.fullmatch(r"(?:@[a-z0-9-]+/)?[a-z0-9-]+", name) or name in seen:
            raise ValueError("invalid or duplicate package name")
        seen.add(name)
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise ValueError("package version must be exact")
        expected = f"https://registry.npmjs.org/{name}/-/{name.split('/')[-1]}-{version}.tgz"
        if item["url"] != expected:
            raise ValueError("package must use the exact official registry URL")
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("invalid package digest")
        try:
            integrity = base64.b64decode(item["integrity"].removeprefix("sha512-"), validate=True)
        except (ValueError, TypeError) as error:
            raise ValueError("invalid package integrity") from error
        if not item["integrity"].startswith("sha512-") or len(integrity) != 64:
            raise ValueError("invalid package integrity")
    main = [item for item in pin["packages"] if item["name"] == "skills"]
    if len(main) != 1 or main[0]["version"] != pin["upstream"]["version"]:
        raise ValueError("CLI version and pin differ")
    return pin


def verify_download(data, pin):
    if hashlib.sha256(data).hexdigest() != pin["sha256"]:
        raise ValueError("package digest mismatch")
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    if integrity != pin["integrity"]:
        raise ValueError("package integrity mismatch")


def extract_archive(data, target, prefix, *, max_bytes=64 * 1024 * 1024):
    """Materialize only bounded ordinary archive entries, without extraction hooks."""
    target = Path(target)
    if target.exists() or target.is_symlink():
        raise FileExistsError("archive target already exists")
    entries, names, total = [], set(), 0
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as bundle:
        for member in bundle:
            name = member.name.rstrip("/")
            parts = PurePosixPath(name).parts
            if (not name or name.startswith("/") or ".." in parts or "\\" in name
                    or ":" in name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
                raise ValueError("invalid archive path")
            if name == prefix or prefix.startswith(name + "/"):
                if not member.isdir():
                    raise ValueError("invalid archive prefix")
                continue
            if not name.startswith(prefix + "/") or not (member.isfile() or member.isdir()):
                raise ValueError("archive member outside scope or nonregular")
            relative = name[len(prefix) + 1:]
            normalized = PurePosixPath(relative).as_posix()
            if normalized in names:
                raise ValueError("duplicate archive member")
            names.add(normalized)
            total += member.size
            if len(names) > 4096 or member.size < 0 or total > max_bytes or len(parts) > 24:
                raise ValueError("archive limit exceeded")
            entries.append((member, normalized))
        target.mkdir(parents=True)
        for member, name in entries:
            destination = target / name
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output)
            destination.chmod(0o755 if member.mode & 0o111 else 0o644)


def child_environment(runtime):
    runtime = Path(runtime)
    return {
        "PATH": os.defpath,
        "TMPDIR": str(runtime / "tmp"),
        "TMP": str(runtime / "tmp"),
        "TEMP": str(runtime / "tmp"),
        "XDG_STATE_HOME": str(runtime / "state"),
        "XDG_CONFIG_HOME": str(runtime / "config"),
        "SIQ_SKILLS_TEST_HOME": str(runtime / "home"),
        "DO_NOT_TRACK": "1", "DISABLE_TELEMETRY": "1", "NO_COLOR": "1", "CI": "1",
    }


def prepare_output(path):
    path = Path(path)
    if path.resolve().is_relative_to((ROOT / SKILL_PATH).resolve()):
        raise ValueError("output cannot modify the source Skill payload")
    path.mkdir(parents=True, exist_ok=False)
    return path


def node_version(node):
    return subprocess.check_output([node, "--version"], text=True, timeout=15,
                                   env={"PATH": os.defpath, "NO_COLOR": "1"}).strip()


def node_command(node, runtime):
    # Node fs.cp stats ancestor directories. The read grant must include /tmp
    # (Linux) or /private (macOS); writes remain limited to this one runtime.
    # homedir() is instrumented by the reviewed preload, not HOME/CODEX_HOME.
    read_root = Path("/tmp").resolve()
    while read_root.parent != Path("/"):
        read_root = read_root.parent
    return [str(node), "--permission", f"--allow-fs-read={read_root}",
            f"--allow-fs-write={runtime}", "--require", str(runtime / "preload.cjs")]


def run_cli(node, runtime, args, cwd):
    command = [*node_command(node, runtime),
               str(runtime / "node_modules/skills/bin/cli.mjs"), *args]
    return subprocess.run(command, cwd=cwd, env=child_environment(runtime),
                          capture_output=True, text=True, timeout=90, check=False)


def verify_node_permissions(node, runtime):
    probe = """const fs = require('node:fs'), cp = require('node:child_process');
const result = {};
function check(name, fn) {
  try { fn(); result[name] = 'unexpected_success'; }
  catch (e) { result[name] = e.code + '/' + e.permission; }
}
check('home_read', () => fs.readdirSync(process.argv[1]));
check('outside_write', () => fs.writeFileSync(process.argv[2], 'probe', {flag: 'wx'}));
check('child_process', () => cp.execFileSync(process.execPath, ['--version']));
console.log(JSON.stringify(result));
"""
    outside = runtime.parent / (runtime.name + "-write-probe")
    if outside.exists() or outside.is_symlink():
        raise ValueError("permission probe target already exists")
    try:
        result = subprocess.run([*node_command(node, runtime), "-e", probe, str(Path.home()), str(outside)],
                                cwd=runtime, env=child_environment(runtime), capture_output=True,
                                text=True, timeout=30, check=False)
        actual = json.loads(result.stdout)
        expected = {"home_read": "ERR_ACCESS_DENIED/FileSystemRead",
                    "outside_write": "ERR_ACCESS_DENIED/FileSystemWrite",
                    "child_process": "ERR_ACCESS_DENIED/ChildProcess"}
        if result.returncode or actual != expected:
            raise ValueError("Node permission negative probes failed")
        return actual
    finally:
        if outside.is_file() and not outside.is_symlink():
            outside.unlink()


def fetch_packages(pin, runtime):
    for item in pin["packages"]:
        request = urllib.request.Request(item["url"], headers={"User-Agent": "SIQ-skills-compat/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.geturl() != item["url"]:
                raise ValueError("unexpected package download redirect")
            data = response.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD:
            raise ValueError("package download limit exceeded")
        verify_download(data, item)
        destination = runtime / "node_modules" / item["name"]
        extract_archive(data, destination, "package")
        actual = json.loads((destination / "package.json").read_text())
        if actual.get("name") != item["name"] or actual.get("version") != item["version"]:
            raise ValueError("package identity mismatch")


def source_snapshot(runtime):
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid source commit")
    payload = subprocess.check_output(["git", "archive", "--format=tar", commit, SKILL_PATH],
                                      cwd=ROOT, timeout=60)
    source = runtime / "siq-agent-security"
    extract_archive(payload, source, SKILL_PATH)
    return source, commit


def verify_removed(installed, lock_path):
    if installed.exists() or installed.is_symlink():
        raise ValueError("uninstall left the installation directory")
    lock = json.loads(lock_path.read_text())
    if (not isinstance(lock, dict) or not isinstance(lock.get("skills"), dict)
            or "siq-agent-security" in lock["skills"]):
        raise ValueError("uninstall left or corrupted the project lock")


def validate_install_rows(rows, agent, installed):
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or rows[0].get("status") != "installed" or rows[0].get("name") != "siq-agent-security"
            or rows[0].get("agents") != [AGENT_LABELS[agent]] or rows[0].get("mode") != "copy"
            or rows[0].get("scope") != "project" or rows[0].get("path") != str(installed)):
        raise ValueError("installer did not confirm the requested placement")


def exercise_agents(node, runtime, source, report):
    initial_source = snapshot_tree(source)
    listing_project = runtime / "discovery"
    listing_project.mkdir()
    listing = run_cli(node, runtime, ["add", str(source), "--list"], listing_project)
    if listing.returncode or "siq-agent-security" not in listing.stdout + listing.stderr:
        raise ValueError("skill discovery failed")
    report["discovery"] = "passed"
    for agent, directory in AGENTS.items():
        project = runtime / ("project-" + agent)
        project.mkdir()
        neighbor = project / directory / "unrelated-skill"
        neighbor.mkdir(parents=True)
        neighbor_bytes = b"---\nname: unrelated-skill\ndescription: Preserve this test fixture.\n---\n"
        (neighbor / "SKILL.md").write_bytes(neighbor_bytes)
        neighbor_lock = {"source": f"./{directory}/unrelated-skill", "sourceType": "local",
                         "computedHash": hashlib.sha256(b"SKILL.md" + neighbor_bytes).hexdigest()}
        (project / "skills-lock.json").write_text(json.dumps({"version": 1, "skills": {"unrelated-skill": neighbor_lock}}))
        attempt = {"agent": agent, "mode": "copy", "result": "failed"}
        report["cases"].append(attempt)
        installed = project / directory / "siq-agent-security"
        result = run_cli(node, runtime, ["add", str(source), "--skill", "siq-agent-security",
                                        "--agent", agent, "--copy", "--yes", "--json"], project)
        attempt["install_exit_code"] = result.returncode
        try:
            rows = json.loads(result.stdout)
        except ValueError as error:
            raise ValueError("installer did not return valid JSON") from error
        if result.returncode:
            raise ValueError("installer returned nonzero status")
        validate_install_rows(rows, agent, installed)
        verification = verify_distribution(source, installed)
        attempt["distribution"] = verification
        if verification["result"] != "passed":
            raise ValueError("installed content differs from source")
        removed = run_cli(node, runtime, ["remove", "--skill", "siq-agent-security",
                                         "--agent", agent, "--yes"], project)
        attempt["remove_exit_code"] = removed.returncode
        attempt["removed"] = not installed.exists() and not installed.is_symlink()
        if removed.returncode or not attempt["removed"]:
            raise ValueError("uninstall did not remove the requested installation")
        verify_removed(installed, project / "skills-lock.json")
        attempt["lock_entry_removed"] = True
        final_lock = json.loads((project / "skills-lock.json").read_text())
        attempt["unrelated_skill_preserved"] = (
            (neighbor / "SKILL.md").read_bytes() == neighbor_bytes
            and final_lock["skills"].get("unrelated-skill") == neighbor_lock
        )
        if not attempt["unrelated_skill_preserved"]:
            raise ValueError("installation or removal changed an unrelated Skill")
        attempt["result"] = "passed"
    report["source_unchanged"] = snapshot_tree(source) == initial_source
    if not report["source_unchanged"]:
        raise ValueError("source payload changed during smoke")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path,
                        help="new evidence directory; an existing path is never overwritten")
    args = parser.parse_args()
    try:
        output = prepare_output(args.out_dir)
    except (OSError, ValueError):
        parser.error("output directory must be new, writable and outside the source Skill")
    report = {
        "schema_version": "siq-skills-distribution-smoke/v1",
        "created_at": datetime.now(timezone.utc).isoformat(), "result": "failed", "cases": [],
        "environment": {"os": platform.system(), "architecture": platform.machine(),
                        "python": platform.python_version()},
        "scope": "Instrumented upstream CLI, local source, project copy install/remove only",
        "isolated_homedir_preload": True, "skill_scripts_executed": False,
        "synthetic_agent_detection_markers": [".codex", ".zcode", ".minimax"],
        "runtime_enforcement_tested": False, "signature_verification_tested": False,
        "network_isolation_verified": False, "official_signature": False,
        "published": False, "frozen_v5_denominator_changed": False,
    }
    try:
        if sys.platform not in ("linux", "darwin"):
            raise ValueError("live CLI smoke currently supports Linux and macOS hosts")
        pin = load_pin(PIN_PATH)
        report["upstream"] = pin["upstream"]
        report["packages"] = pin["packages"]
        report["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report["verifier_sha256"] = hashlib.sha256(Path(__file__).with_name("verify_skill_distribution.py").read_bytes()).hexdigest()
        report["pin_sha256"] = hashlib.sha256(PIN_PATH.read_bytes()).hexdigest()
        node = shutil.which("node")
        if not node:
            raise ValueError("Node.js 24 or newer is required")
        version = node_version(node)
        if not re.fullmatch(r"v\d+\.\d+\.\d+", version) or int(version.split(".")[0][1:]) < 24:
            raise ValueError("Node.js 24 or newer is required")
        report["environment"]["node"] = version
        with tempfile.TemporaryDirectory(prefix="siq-skills-compat-", dir="/tmp") as directory:
            runtime = Path(directory).resolve()
            for name in ("home", "state", "config", "tmp"):
                (runtime / name).mkdir()
            # remove scans all known agents, even with --agent. These empty
            # markers short-circuit probes of /etc/codex and /Applications.
            for name in (".codex", ".zcode", ".minimax"):
                (runtime / "home" / name).mkdir()
            (runtime / "preload.cjs").write_text(PRELOAD)
            report["node_read_scope"] = "/private" if sys.platform == "darwin" else "/tmp"
            report["node_write_scope"] = "new temporary runtime only"
            report["node_permission_negative_probes"] = verify_node_permissions(Path(node).resolve(), runtime)
            fetch_packages(pin, runtime)
            source, commit = source_snapshot(runtime)
            report["source"] = {"commit": commit, "skill_path": SKILL_PATH,
                                "materialization": "git archive HEAD; includes no uncommitted Skill changes"}
            exercise_agents(Path(node).resolve(), runtime, source, report)
        report["result"] = "passed"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, tarfile.TarError) as error:
        # Raw subprocess/network errors may contain local paths or credentials.
        report["error_category"] = type(error).__name__
        if isinstance(error, ValueError):
            report["error"] = str(error)
    with (output / "result.json").open("x") as result_file:
        json.dump(report, result_file, indent=2)
        result_file.write("\n")
    print(json.dumps({"result": report["result"], "cases": len(report["cases"]),
                      "report": str(output / "result.json")}))
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
