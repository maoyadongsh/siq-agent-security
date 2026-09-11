#!/usr/bin/env python3
"""Offline UX-001 evidence indexing; never a runtime authorization or certification.

init emits an untested matrix. verify checks identities, bounded local evidence
and coverage. Neither command executes a host, scans user configuration, contacts
a network service, nor updates the support matrix automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

PLATFORMS = ("openclaw", "hermes", "workbuddy")
# Candidate test inventory from taskbook section 7, not a compatibility promise.
ENVIRONMENTS = (("windows", "amd64", "native"), ("windows", "amd64", "wsl2"),
                ("macos", "arm64", "native"), ("macos", "amd64", "native"),
                ("linux", "amd64", "native"), ("linux", "arm64", "native"))
CHECKS = ("discovery", "normal_execution", "pre_execution_denial",
          "service_unavailable_denial", "approval_resume", "final_parameter_recheck",
          "skill_attribution", "install_interception")
METHODS = ("none", "source_review", "component_fixture", "native_cli", "native_desktop")
REASONS = ("environment_unavailable", "upstream_runtime_unconfirmed", "not_implemented",
           "host_capability_missing", "not_tested", "observed_failure")
SHA40 = re.compile(r"[0-9a-f]{40}")
SHA64 = re.compile(r"[0-9a-f]{64}")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+ -]{0,79}")
COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}(?:\.[A-Za-z0-9_-]{1,16})?")
MAX_MANIFEST = 512 * 1024
MAX_EVIDENCE = 8 * 1024 * 1024
MAX_TOTAL = 32 * 1024 * 1024


class Invalid(ValueError):
    """Only fixed categories may escape the verifier; no input text in errors."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Invalid(code)


def keys(value: Any, expected: set[str]) -> None:
    require(type(value) is dict and set(value) == expected, "invalid_fields")


def matches(pattern: re.Pattern, value: Any) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


def unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def load_manifest(path: Path) -> dict:
    # A caller-selected local input, not a URL. Refuse special files before read.
    try:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode), "manifest_not_regular")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            require(stat.S_ISREG(opened.st_mode) and os.path.samestat(info, opened), "manifest_changed")
            require(opened.st_size <= MAX_MANIFEST, "manifest_budget_exceeded")
            raw = stream.read(MAX_MANIFEST + 1)
        require(len(raw) <= MAX_MANIFEST, "manifest_budget_exceeded")
        return json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(Invalid("invalid_json")))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Invalid("manifest_unreadable") from exc


def template(candidate: str) -> dict:
    require(matches(SHA40, candidate), "invalid_candidate")
    cases = []
    for platform in PLATFORMS:
        for system, arch, mode in ENVIRONMENTS:
            cases.append({
                "platform": platform, "os": system, "arch": arch, "mode": mode,
                "os_version": None, "host_version": None, "guest_version": None,
                "binary_sha256": None,
                "checks": {name: {"status": "not_run", "method": "none",
                                  "reason": "not_tested", "evidence": []} for name in CHECKS},
            })
    return {"schema_version": "personal-platform-acceptance/v1", "candidate_sha": candidate,
            "source_dirty": False, "cases": cases}


def regular_file(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not (getattr(info, "st_file_attributes", 0) & 0x400))


class EvidenceReader:
    """Private immutable evidence roots only; not a same-UID adversary sandbox."""

    def __init__(self, root: Path):
        try:
            self.root = root.resolve(strict=True)
            require(self.root.is_dir(), "invalid_evidence_root")
        except OSError as exc:
            raise Invalid("invalid_evidence_root") from exc
        self.total = 0
        self.cache: dict[str, tuple[str, tuple]] = {}
        self.owners: dict[str, tuple] = {}

    def check(self, ref: Any, case_id: tuple) -> None:
        keys(ref, {"path", "sha256"})
        require(matches(SHA64, ref["sha256"]), "invalid_evidence_digest")
        relative = ref["path"]
        require(type(relative) is str and 0 < len(relative) <= 240, "invalid_evidence_path")
        parts = relative.split("/")
        require(all(matches(COMPONENT, part) for part in parts), "invalid_evidence_path")
        require(parts[-1].endswith((".json", ".txt", ".log", ".png")), "invalid_evidence_type")
        # Reject Windows devices even when validating on Linux; no ADS or aliases.
        devices = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
                   *(f"lpt{i}" for i in range(1, 10))}
        require(all(part.split(".")[0].lower() not in devices for part in parts), "invalid_evidence_path")
        digest = ref["sha256"]
        require(digest not in self.owners or self.owners[digest] == case_id, "evidence_reused_across_cases")
        self.owners[digest] = case_id
        if relative in self.cache:
            require(self.cache[relative] == (digest, case_id), "inconsistent_evidence_reference")
            return
        target = self.root
        try:
            for index, part in enumerate(parts):
                target /= part
                info = target.lstat()
                require(not stat.S_ISLNK(info.st_mode)
                        and not (getattr(info, "st_file_attributes", 0) & 0x400), "evidence_link_refused")
                if index < len(parts) - 1:
                    require(stat.S_ISDIR(info.st_mode), "evidence_parent_not_directory")
            require(regular_file(info), "evidence_not_regular")
            require(info.st_size <= MAX_EVIDENCE, "evidence_budget_exceeded")
            require(self.total + info.st_size <= MAX_TOTAL, "evidence_budget_exceeded")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            with os.fdopen(os.open(target, flags), "rb") as stream:
                before = os.fstat(stream.fileno())
                require(regular_file(before) and os.path.samestat(before, info), "evidence_changed")
                raw = stream.read(MAX_EVIDENCE + 1)
                after = os.fstat(stream.fileno())
            require(len(raw) <= MAX_EVIDENCE and self.total + len(raw) <= MAX_TOTAL,
                    "evidence_budget_exceeded")
            require(before.st_size == after.st_size == len(raw)
                    and before.st_mtime_ns == after.st_mtime_ns, "evidence_changed")
            require(hashlib.sha256(raw).hexdigest() == digest, "evidence_digest_mismatch")
            self.total += len(raw)
            self.cache[relative] = (digest, case_id)
        except OSError as exc:
            raise Invalid("evidence_unreadable") from exc


def verify(bundle: Any, root: Path, candidate: str) -> dict:
    keys(bundle, {"schema_version", "candidate_sha", "source_dirty", "cases"})
    require(bundle["schema_version"] == "personal-platform-acceptance/v1", "invalid_schema_version")
    require(matches(SHA40, candidate) and bundle["candidate_sha"] == candidate, "candidate_mismatch")
    require(bundle["source_dirty"] is False, "dirty_candidate")
    rows = bundle["cases"]
    require(type(rows) is list and len(rows) == len(PLATFORMS) * len(ENVIRONMENTS), "incomplete_target_matrix")
    expected = {(p, *env) for p in PLATFORMS for env in ENVIRONMENTS}
    reader = EvidenceReader(root)
    seen = set()
    results = []
    for row in rows:
        keys(row, {"platform", "os", "arch", "mode", "os_version", "host_version",
                   "guest_version", "binary_sha256", "checks"})
        identity = tuple(row[k] for k in ("platform", "os", "arch", "mode"))
        require(all(type(x) is str for x in identity), "invalid_target")
        require(identity in expected and identity not in seen, "invalid_or_duplicate_target")
        seen.add(identity)
        for field in ("os_version", "host_version", "guest_version"):
            require(row[field] is None or matches(LABEL, row[field]), "invalid_version")
        require(row["binary_sha256"] is None or matches(SHA64, row["binary_sha256"]), "invalid_binary_digest")
        require(row["mode"] == "wsl2" or row["guest_version"] is None, "unexpected_guest_version")
        keys(row["checks"], set(CHECKS))
        native = []
        gaps = []
        for name in CHECKS:
            check = row["checks"][name]
            keys(check, {"status", "method", "reason", "evidence"})
            require(type(check["status"]) is str and check["status"] in ("not_run", "blocked", "pass", "fail"), "invalid_status")
            require(type(check["method"]) is str and check["method"] in METHODS, "invalid_method")
            require(type(check["evidence"]) is list and len(check["evidence"]) <= 4, "invalid_evidence_list")
            reason = check["reason"]
            require(reason is None or (type(reason) is str and reason in REASONS), "invalid_reason")
            if check["status"] in ("pass", "fail"):
                require(check["method"] != "none" and bool(check["evidence"]), "result_without_evidence")
                require(reason is None if check["status"] == "pass" else reason == "observed_failure", "invalid_result_reason")
                require(row["os_version"] is not None and row["host_version"] is not None
                        and row["binary_sha256"] is not None, "missing_execution_identity")
                require(row["mode"] != "wsl2" or row["guest_version"] is not None, "missing_guest_identity")
            else:
                require(reason is not None, "missing_gap_reason")
                require(check["status"] != "not_run" or
                        (check["method"] == "none" and not check["evidence"]), "invalid_not_run")
            refs = set()
            for ref in check["evidence"]:
                reader.check(ref, identity)
                require(ref["path"] not in refs, "duplicate_evidence_reference")
                refs.add(ref["path"])
            method_ok = check["method"] in ("native_cli", "native_desktop")
            if row["platform"] == "workbuddy":
                method_ok = check["method"] == "native_desktop"
            if check["status"] == "pass" and method_ok:
                native.append(name)
            else:
                gaps.append(name)
        results.append({"target": "/".join(identity), "native_checks_recorded": native,
                        "gaps": gaps, "status": "ready_for_review" if not gaps else "needs_native_evidence"})
    return {"schema_version": "personal-platform-acceptance-report/v1", "candidate_sha": candidate,
            "status": "ready_for_review" if all(not r["gaps"] for r in results) else "needs_native_evidence",
            "support_claim": "not_assessed", "evidence_files_checked": len(reader.cache),
            "cases": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="emit untested candidate inventory; detects no host")
    init.add_argument("--candidate", required=True)
    init.add_argument("--out", type=Path)
    check = commands.add_parser("verify", help="offline evidence/identity/coverage verification")
    check.add_argument("manifest", type=Path)
    check.add_argument("--evidence-root", type=Path, required=True)
    check.add_argument("--candidate", required=True)
    check.add_argument("--require-native", action="store_true")
    check.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        result = (template(args.candidate) if args.command == "init" else
                  verify(load_manifest(args.manifest), args.evidence_root, args.candidate))
        text = json.dumps(result, ensure_ascii=True, indent=2) + "\n"
        if args.out:
            # Explicit output only; never overwrite existing evidence or mkdir.
            descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
        else:
            print(text, end="")
        return 3 if args.command == "verify" and args.require_native and result["status"] != "ready_for_review" else 0
    except Invalid as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}), file=sys.stderr)
        return 2
    except (OSError, ValueError, RecursionError):
        print(json.dumps({"status": "invalid", "error": "local_io_or_encoding_failure"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
