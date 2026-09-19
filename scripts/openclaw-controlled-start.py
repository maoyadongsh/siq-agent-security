#!/usr/bin/env python3
"""Prepare and launch a pinned, isolated OpenClaw checkpoint host.

This is a Linux/POSIX controlled-start entrypoint for the current SIQ adapter.
It never patches the source installation or silently copies a user's profile.
The profile must already contain a SIQ-managed adapter registration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PROFILE_STEMS = {
    "2026.5.12": "2026.5.12-approval-execution-recheck-v2",
    "2026.9.4": "2026.9.4-approval-execution-recheck-v1",
}
ADAPTER = ROOT / "adapters/runtime/openclaw-agentshield/index.ts"
MARKER = ".siq-controlled-runtime.json"


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_digest(root: Path) -> str:
    """Bind every copied package file and internal symlink, excluding our marker."""
    h = hashlib.sha256()
    for item in sorted(root.rglob("*")):
        relative = item.relative_to(root).as_posix()
        if relative == MARKER:
            continue
        if item.is_symlink():
            require(item.resolve(strict=True).is_relative_to(root),
                    "controlled_runtime_external_symlink")
            value = "link:" + os.readlink(item)
        elif item.is_file():
            value = "file:" + digest(item)
        elif item.is_dir():
            value = "dir"
        else:
            raise RuntimeError("controlled_runtime_special_file")
        h.update((relative + "\0" + value + "\n").encode())
    return h.hexdigest()


def private_directory(path: Path) -> Path:
    path = path.absolute()
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            "private_directory_required")
    info = path.stat()
    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            "private_directory_owner_or_mode_invalid")
    return path


def regular(path: Path) -> Path:
    path = path.absolute()
    require(path.is_file() and not path.is_symlink() and path.resolve() == path,
            "regular_file_required")
    return path


def profile(version: str) -> tuple[dict, Path]:
    stem = PROFILE_STEMS.get(version)
    require(stem is not None, "unsupported_package_version")
    profile_path = ROOT / f"patches/openclaw/{stem}.json"
    patch = ROOT / f"patches/openclaw/{stem}.patch"
    data = json.loads(regular(profile_path).read_text())
    require(data.get("version") == version, "patch_profile_version_mismatch")
    require(digest(regular(patch)) == data["patch_sha256"], "patch_checksum_mismatch")
    require(digest(ADAPTER) == data["adapter_sha256"], "adapter_checksum_mismatch")
    return data, patch


def source_runtime(path: Path) -> tuple[Path, dict, Path]:
    path = path.absolute()
    require(path.is_dir() and not path.is_symlink() and path.resolve() == path,
            "source_runtime_directory_required")
    package = json.loads(regular(path / "package.json").read_text())
    metadata, patch = profile(str(package.get("version", "")))
    require(package.get("name") == metadata["package"]
            and package.get("version") == metadata["version"],
            "unsupported_package_version")
    require(digest(regular(path / metadata["target"])) == metadata["before_sha256"],
            "source_runtime_fingerprint_changed")
    regular(path / "openclaw.mjs")
    for item in path.rglob("*"):
        if item.is_symlink():
            require(item.resolve(strict=True).is_relative_to(path),
                    "source_external_symlink_rejected")
    return path, metadata, patch


def inspect_runtime(path: Path) -> dict:
    path = private_directory(path)
    marker_path = regular(path / MARKER)
    marker = json.loads(marker_path.read_text())
    metadata, _ = profile(str(marker.get("version", "")))
    expected = {
        "schema_version": "siq-openclaw-controlled-runtime/v1",
        "package": metadata["package"],
        "version": metadata["version"],
        "target": metadata["target"],
        "stock_sha256": metadata["before_sha256"],
        "checkpoint_sha256": metadata["after_sha256"],
        "patch_sha256": metadata["patch_sha256"],
        "adapter_sha256": metadata["adapter_sha256"],
        "payload_sha256": tree_digest(path),
    }
    require(marker == expected, "controlled_runtime_marker_changed")
    require(stat.S_IMODE(marker_path.stat().st_mode) == 0o600,
            "controlled_runtime_marker_mode_invalid")
    package = json.loads(regular(path / "package.json").read_text())
    require(package.get("name") == metadata["package"]
            and package.get("version") == metadata["version"],
            "controlled_runtime_package_changed")
    require(digest(regular(path / metadata["target"])) == metadata["after_sha256"],
            "controlled_runtime_checkpoint_changed")
    regular(path / "openclaw.mjs")
    return {"status": "ready", "version": metadata["version"],
            "checkpoint_sha256": metadata["after_sha256"], "runtime": str(path)}


def prepare(source: Path, destination: Path, node: Path) -> dict:
    require(os.name == "posix", "posix_controlled_start_required")
    source, metadata, patch = source_runtime(source)
    node = regular(node)
    destination = destination.absolute()
    parent = private_directory(destination.parent)
    require(destination.parent == parent and not destination.exists()
            and not destination.is_symlink(), "new_destination_required")
    require(not destination.is_relative_to(source) and not source.is_relative_to(destination),
            "runtime_source_destination_overlap")
    destination.mkdir(mode=0o700)
    try:
        shutil.copytree(source, destination, symlinks=True, dirs_exist_ok=True)
        destination.chmod(0o700)
        target = regular(destination / metadata["target"])
        require(digest(target) == metadata["before_sha256"], "copied_runtime_changed")
        subprocess.run(["git", "apply", "--check", str(patch)], cwd=destination,
                       check=True, timeout=30, capture_output=True)
        subprocess.run(["git", "apply", str(patch)], cwd=destination,
                       check=True, timeout=30, capture_output=True)
        require(digest(target) == metadata["after_sha256"], "patched_runtime_changed")
        subprocess.run([str(node), "--check", str(target)], check=True,
                       timeout=30, capture_output=True)
        marker = {
            "schema_version": "siq-openclaw-controlled-runtime/v1",
            "package": metadata["package"], "version": metadata["version"],
            "target": metadata["target"],
            "stock_sha256": metadata["before_sha256"],
            "checkpoint_sha256": metadata["after_sha256"],
            "patch_sha256": metadata["patch_sha256"],
            "adapter_sha256": metadata["adapter_sha256"],
            "payload_sha256": tree_digest(destination),
        }
        fd = os.open(destination / MARKER,
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(marker, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        dir_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return inspect_runtime(destination)
    except Exception:
        # A partial copy stays private and lacks the complete marker. Never
        # delete an operator-selected path after an interrupted preparation.
        destination.chmod(0o700)
        raise


def inspect_profile(home: Path, metadata: dict) -> Path:
    home = private_directory(home)
    require(home != Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(),
            "shared_account_home_rejected")
    state = private_directory(home / ".openclaw")
    config = json.loads(regular(state / "openclaw.json").read_text())
    plugin = private_directory(state / "plugins" / "siq-agent-security")
    require(digest(regular(plugin / "index.ts")) == metadata["adapter_sha256"],
            "profile_adapter_changed")
    plugins = config.get("plugins") or {}
    require(isinstance(plugins, dict) and plugins.get("enabled") is not False,
            "profile_plugins_disabled")
    allowed = plugins.get("allow")
    denied = plugins.get("deny", [])
    loaded = plugins.get("load")
    entries = plugins.get("entries")
    require(isinstance(allowed, list) and "siq-agent-security" in allowed,
            "profile_adapter_not_allowed")
    require(isinstance(denied, list) and "siq-agent-security" not in denied,
            "profile_adapter_denied")
    require(isinstance(loaded, dict) and isinstance(loaded.get("paths"), list)
            and str(plugin) in loaded["paths"],
            "profile_adapter_not_loaded")
    require(isinstance(entries, dict) and isinstance(entries.get("siq-agent-security"), dict)
            and entries["siq-agent-security"].get("enabled") is True,
            "profile_adapter_not_enabled")
    connection = json.loads(regular(state / "siq-agent-security.json").read_text())
    endpoint = urlsplit(connection.get("endpoint", ""))
    require(endpoint.scheme == "http" and endpoint.hostname in {"127.0.0.1", "::1", "localhost"}
            and endpoint.port is not None and not endpoint.username and not endpoint.password,
            "profile_endpoint_not_loopback")
    require(connection.get("enforcementMode") == "block", "profile_not_block_mode")
    token = regular(Path(connection.get("tokenPath", "")))
    require(token.stat().st_uid == os.getuid() and stat.S_IMODE(token.stat().st_mode) & 0o077 == 0,
            "profile_credential_mode_invalid")
    return home


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("prepare", help="copy and patch one pinned host into a new private directory")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--destination", type=Path, required=True)
    create.add_argument("--node", type=Path, required=True)
    inspect = commands.add_parser("inspect", help="verify a previously prepared runtime")
    inspect.add_argument("--runtime", type=Path, required=True)
    run = commands.add_parser("run", help="launch a prepared runtime with an isolated SIQ profile")
    run.add_argument("--runtime", type=Path, required=True)
    run.add_argument("--profile-home", type=Path, required=True)
    run.add_argument("--node", type=Path, required=True)
    run.add_argument("--fixture-guard", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("host_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare(args.source, args.destination, args.node)
    elif args.action == "inspect":
        result = inspect_runtime(args.runtime)
    else:
        runtime = inspect_runtime(args.runtime)
        metadata, _ = profile(runtime["version"])
        home = inspect_profile(args.profile_home, metadata)
        node = regular(args.node)
        host_args = args.host_args[1:] if args.host_args[:1] == ["--"] else args.host_args
        require(host_args, "openclaw_arguments_required")
        # Legacy AGENTSHIELD_* variables are still read by the adapter. Node
        # preload/module-path variables can execute code before the pinned host.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("OPENCLAW_", "SIQ_AGENT_SECURITY_", "AGENTSHIELD_"))
               and key not in {"NODE_OPTIONS", "NODE_PATH"}}
        env.update({
            "HOME": str(home), "USERPROFILE": str(home),
            "OPENCLAW_STATE_DIR": str(home / ".openclaw"),
            "OPENCLAW_CONFIG_PATH": str(home / ".openclaw/openclaw.json"),
            "OPENCLAW_HOME": str(home),
            "PI_CODING_AGENT_DIR": str(home / ".pi"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local/share"),
        })
        fixture_import = (["--import", str(regular(ROOT / "scripts/openclaw-fixture-guard.mjs"))]
                          if args.fixture_guard else [])
        os.execve(node, [str(node), *fixture_import,
                         str(Path(runtime["runtime"]) / "openclaw.mjs"), *host_args], env)
        raise AssertionError("execve returned")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"openclaw controlled start: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
