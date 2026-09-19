#!/usr/bin/env python3
"""Check the public LX00-LX10 evidence bundle without reading private contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO / "docs/evidence/personal-experience/linux-dual-host-20260918-211200"
HASH = re.compile(r"[0-9a-f]{64}\Z")
MANIFEST_LINE = re.compile(r"([0-9a-f]{64})  (.+)\Z")
STATUSES = {"passed", "failed", "partial", "blocked", "skipped", "not_run", "out_of_scope"}
ROW_FIELDS = {
    "id", "host_os", "host_platform", "level", "candidate_sha256", "driver_sha256",
    "expected_safety_summary", "observed_safety_summary", "status", "evidence_ref",
    "unresolved_condition",
}


def is_private(relative: Path) -> bool:
    return any(part.endswith("-private") for part in relative.parts)


def safe_relative(value: str) -> Path:
    path = Path(value)
    if (not value or path.is_absolute() or value != path.as_posix()
            or any(part in {".", ".."} for part in path.parts)):
        raise ValueError(f"unsafe relative path: {value!r}")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contains_exact_value(value: object, expected: str) -> bool:
    if isinstance(value, dict):
        return any(contains_exact_value(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(contains_exact_value(item, expected) for item in value)
    return value == expected


def check(root: Path) -> dict:
    root = root.resolve(strict=True)
    errors: list[str] = []
    manifest: dict[str, str] = {}
    for number, line in enumerate((root / "SHA256SUMS").read_text().splitlines(), 1):
        matched = MANIFEST_LINE.fullmatch(line)
        if not matched:
            errors.append(f"manifest line {number}: malformed")
            continue
        expected, name = matched.groups()
        try:
            relative = safe_relative(name)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if name == "SHA256SUMS" or is_private(relative) or name in manifest:
            errors.append(f"manifest line {number}: forbidden or duplicate path {name}")
            continue
        manifest[name] = expected

    public: set[str] = set()
    private_roots: list[Path] = []
    private_files = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        name = relative.as_posix()
        if path.is_symlink():
            errors.append(f"symlink in evidence bundle: {name}")
            continue
        if is_private(relative):
            if path.is_dir():
                if relative.name.endswith("-private"):
                    private_roots.append(path)
                if stat.S_IMODE(path.stat().st_mode) != 0o700:
                    errors.append(f"private directory mode: {name}")
            elif path.is_file():
                private_files += 1
                if stat.S_IMODE(path.stat().st_mode) not in {0o600, 0o700}:
                    errors.append(f"private file mode: {name}")
            continue
        if path.is_file() and name != "SHA256SUMS":
            public.add(name)
    for name in sorted(public - manifest.keys()):
        errors.append(f"unlisted public file: {name}")
    for name in sorted(manifest.keys() - public):
        errors.append(f"missing public file: {name}")
    for name in sorted(public & manifest.keys()):
        if sha256(root / name) != manifest[name]:
            errors.append(f"public file digest mismatch: {name}")

    checks = json.loads((root / "checks.json").read_text())
    if checks.get("schema_version") != "linux-dual-host-integration-checks/v1":
        errors.append("checks schema version mismatch")
    rows = checks.get("results")
    if not isinstance(rows, list):
        raise ValueError("checks.results must be a list")
    ids: set[str] = set()
    counts: dict[str, int] = {}
    bound_digests = 0
    unknown_drivers: list[str] = []
    for row in rows:
        identifier = row.get("id")
        missing_fields = ROW_FIELDS - row.keys()
        if missing_fields:
            errors.append(f"{identifier}: missing required fields {sorted(missing_fields)}")
        driver_digest = row.get("driver_sha256")
        if driver_digest is None:
            unknown_drivers.append(str(identifier))
        elif not isinstance(driver_digest, str) or not HASH.fullmatch(driver_digest):
            errors.append(f"{identifier}: invalid driver_sha256")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            errors.append(f"missing or duplicate check id: {identifier!r}")
        ids.add(identifier)
        status = row.get("status")
        counts[status] = counts.get(status, 0) + 1
        if status not in STATUSES:
            errors.append(f"{identifier}: invalid status {status!r}")
        ref = row.get("evidence_ref")
        if not isinstance(ref, str):
            errors.append(f"{identifier}: missing evidence reference")
            continue
        if Path(ref).is_absolute() or ref != Path(ref).as_posix():
            errors.append(f"{identifier}: evidence reference must be a normalized relative path")
            continue
        # A task row may point at a repository document outside this bundle
        # (LX09 points at RESEARCH.md). Keep the bundle's own references
        # manifested, and constrain external references to this checkout.
        try:
            target = (root / ref).resolve(strict=True)
        except (OSError, RuntimeError):
            errors.append(f"{identifier}: missing evidence reference: {ref}")
            continue
        if (not target.is_file() or not target.is_relative_to(REPO)
                or is_private(target.relative_to(REPO))):
            errors.append(f"{identifier}: evidence reference outside public checkout: {ref}")
            continue
        if target.is_relative_to(root) and target.relative_to(root).as_posix() not in manifest:
            errors.append(f"{identifier}: evidence reference not manifested: {ref}")
            continue
        if target.suffix != ".json":
            continue
        summary = json.loads(target.read_text())
        for key in ("candidate_sha256", "private_report_sha256"):
            recorded = row.get(key)
            if recorded is None:
                continue
            if not isinstance(recorded, str) or not HASH.fullmatch(recorded):
                errors.append(f"{identifier}: invalid {key}")
            elif key in summary and summary[key] != recorded:
                errors.append(f"{identifier}: {key} differs from public summary")
            elif not contains_exact_value(summary, recorded):
                errors.append(f"{identifier}: {key} is absent from public summary")
            else:
                bound_digests += 1
    for path in private_roots:
        result = subprocess.run(["git", "check-ignore", "-q", str(path)],
                                cwd=REPO, check=False, capture_output=True)
        if result.returncode != 0:
            errors.append(f"private directory not ignored: {path.relative_to(root)}")
    return {
        "passed": not errors,
        "public_files": len(public),
        "manifest_entries": len(manifest),
        "check_rows": len(rows),
        "check_statuses": counts,
        "digest_values_found_in_json_references": bound_digests,
        "driver_digest_unknown_rows": unknown_drivers,
        "private_directories": len(private_roots),
        "private_files": private_files,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    result = check(args.root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"LX10 evidence check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
