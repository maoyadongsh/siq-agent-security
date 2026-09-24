#!/usr/bin/env python3
"""Issue and verify fail-closed DGX Spark native-candidate CI evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

POLICY_SCHEMA = "siq.dgx-spark.native-candidate-gate-policy.v1"
PLATFORM_SCHEMA = "siq.dgx-spark.native-platform-evidence.v1"
SUITE_SCHEMA = "siq.dgx-spark.native-suite-receipt.v1"
RESOURCE_BINDING_SCHEMA = "siq.dgx-spark.native-resource-audit-binding.v1"
FINAL_SCHEMA = "siq.dgx-spark.native-candidate-gate-report.v1"
LOCK_SCHEMA = "siq.dgx-spark.confidential-candidate-lock.v1"
DOCTOR_SCHEMA = "siq.dgx-spark.confidential-candidate-doctor-report.v1"
RESOURCE_SCHEMA = "siq.openshell.resource_governance_audit.v1"
ROOT_NAMES = ("security", "research", "hermes")
SHA40_RE = re.compile(r"[0-9a-f]{40}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
SENSITIVE_ENV_RE = re.compile(
    r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|SESSION)", re.IGNORECASE
)


class GateError(RuntimeError):
    """Stable validation or evidence failure."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise GateError("duplicate_json_key")
        value[key] = item
    return value


def load_json(path: Path, *, max_bytes: int = 2 << 20, private: bool = False) -> dict[str, Any]:
    try:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_nlink != 1
            or info.st_size > max_bytes
            or (private and stat.S_IMODE(info.st_mode) != 0o600)
        ):
            raise GateError("json_file_invalid")
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except GateError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise GateError("json_file_invalid") from exc
    if not isinstance(value, dict):
        raise GateError("json_root_invalid")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
            raise GateError("evidence_file_invalid")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise GateError("evidence_file_invalid") from exc


def _exact(value: Any, keys: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise GateError(code)
    return value


def _identifier(value: Any, code: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise GateError(code)
    return value


def _sha40(value: Any, code: str) -> str:
    if not isinstance(value, str) or SHA40_RE.fullmatch(value) is None:
        raise GateError(code)
    return value


def _relative(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise GateError(code)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or str(path) == ".":
        raise GateError(code)
    return value


def validate_policy(value: dict[str, Any]) -> dict[str, Any]:
    _exact(
        value,
        {"schema_version", "candidate_lock", "evidence_max_age_seconds", "runner", "suites"},
        "policy_schema_invalid",
    )
    if value["schema_version"] != POLICY_SCHEMA:
        raise GateError("policy_schema_invalid")
    lock = _exact(value["candidate_lock"], {"path", "schema_version"}, "policy_lock_invalid")
    _relative(lock["path"], "policy_lock_invalid")
    if lock["schema_version"] != LOCK_SCHEMA:
        raise GateError("policy_lock_invalid")
    age = value["evidence_max_age_seconds"]
    if isinstance(age, bool) or not isinstance(age, int) or not 300 <= age <= 86400:
        raise GateError("policy_age_invalid")
    runner = _exact(
        value["runner"],
        {"architectures", "product_names", "gpu_name_patterns", "required_labels"},
        "policy_runner_invalid",
    )
    for field in ("architectures", "product_names", "gpu_name_patterns", "required_labels"):
        items = runner[field]
        if (
            not isinstance(items, list)
            or not items
            or len(items) != len(set(items))
            or not all(isinstance(item, str) and 0 < len(item) <= 128 for item in items)
        ):
            raise GateError("policy_runner_invalid")
    suites = value["suites"]
    if not isinstance(suites, list) or not suites:
        raise GateError("policy_suites_invalid")
    seen: set[str] = set()
    for suite in suites:
        _exact(suite, {"id", "root", "timeout_seconds", "argv"}, "policy_suite_invalid")
        suite_id = _identifier(suite["id"], "policy_suite_invalid")
        if suite_id in seen or suite["root"] not in ROOT_NAMES:
            raise GateError("policy_suite_invalid")
        seen.add(suite_id)
        timeout = suite["timeout_seconds"]
        argv = suite["argv"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 30 <= timeout <= 3600
            or not isinstance(argv, list)
            or not 3 <= len(argv) <= 64
            or not all(isinstance(item, str) and item and len(item) <= 512 and "\x00" not in item for item in argv)
        ):
            raise GateError("policy_suite_invalid")
        executable = argv[0]
        if "/" in executable:
            _relative(executable, "policy_suite_invalid")
    return value


def validate_lock(value: dict[str, Any]) -> dict[str, Any]:
    if value.get("schema_version") != LOCK_SCHEMA:
        raise GateError("candidate_lock_schema_invalid")
    _identifier(value.get("candidate_id"), "candidate_lock_id_invalid")
    repositories = value.get("repositories")
    if not isinstance(repositories, dict) or set(repositories) != set(ROOT_NAMES):
        raise GateError("candidate_lock_repositories_invalid")
    for entry in repositories.values():
        if not isinstance(entry, dict) or set(entry) != {"head"}:
            raise GateError("candidate_lock_repositories_invalid")
        _sha40(entry["head"], "candidate_lock_repositories_invalid")
    hardware = value.get("hardware")
    if not isinstance(hardware, dict) or set(hardware) != {"architectures", "product_names"}:
        raise GateError("candidate_lock_hardware_invalid")
    return value


def load_contracts(policy_path: Path, lock_path: Path | None) -> tuple[dict[str, Any], dict[str, Any], Path]:
    policy = validate_policy(load_json(policy_path))
    expected = (policy_path.resolve().parents[2] / policy["candidate_lock"]["path"]).resolve()
    selected = expected if lock_path is None else lock_path.resolve()
    if selected != expected:
        raise GateError("candidate_lock_path_mismatch")
    lock = validate_lock(load_json(selected))
    if lock["schema_version"] != policy["candidate_lock"]["schema_version"]:
        raise GateError("candidate_lock_schema_invalid")
    if set(lock["hardware"]["architectures"]) != set(policy["runner"]["architectures"]):
        raise GateError("policy_lock_hardware_mismatch")
    if set(lock["hardware"]["product_names"]) != set(policy["runner"]["product_names"]):
        raise GateError("policy_lock_hardware_mismatch")
    return policy, lock, selected


def _run(argv: Sequence[str], *, cwd: Path | None = None, timeout: int = 30, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv), cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("command_execution_failed") from exc


def _git(root: Path, *args: str) -> str:
    result = _run(["git", "-C", str(root), *args], timeout=30)
    if result.returncode != 0:
        raise GateError("repository_inspection_failed")
    return result.stdout.strip()


def _safe_root(path: Path) -> Path:
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise GateError("repository_root_invalid") from exc
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or resolved != path.absolute():
        raise GateError("repository_root_invalid")
    if _git(resolved, "rev-parse", "--show-toplevel") != str(resolved):
        raise GateError("repository_root_invalid")
    return resolved


def _repository_state(root: Path, expected: str, *, allow_descendant: bool) -> dict[str, Any]:
    head = _git(root, "rev-parse", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain=v1", "--untracked-files=all"))
    if allow_descendant:
        ancestor = _run(["git", "-C", str(root), "merge-base", "--is-ancestor", expected, head], timeout=30)
        binding_matches = ancestor.returncode == 0
        binding = "locked_baseline_ancestor"
    else:
        binding_matches = head == expected
        binding = "exact_head"
    return {
        "binding": binding,
        "binding_matches": binding_matches,
        "clean": not dirty,
        "head": head if SHA40_RE.fullmatch(head) else "",
        "locked_head": expected,
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> float:
    if not isinstance(value, str) or len(value) > 64:
        raise GateError("evidence_timestamp_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError("evidence_timestamp_invalid") from exc
    if parsed.tzinfo is None:
        raise GateError("evidence_timestamp_invalid")
    return parsed.timestamp()


def _fresh(value: Any, max_age: int, *, now: float | None = None) -> bool:
    current = time.time() if now is None else now
    observed = _parse_timestamp(value)
    return current - max_age <= observed <= current + 300


def _write_json(path: Path, value: Mapping[str, Any], *, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o755)
    if path.parent.is_symlink() or path.is_symlink():
        raise GateError("output_path_invalid")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600 if private else 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=True, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600 if private else 0o644, follow_symlinks=False)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _base_report(schema: str, lock: Mapping[str, Any], batch_id: str, github_sha: str) -> dict[str, Any]:
    return {
        "schema_version": schema,
        "candidate_id": lock["candidate_id"],
        "batch_id": _identifier(batch_id, "batch_id_invalid"),
        "github_sha": _sha40(github_sha, "github_sha_invalid"),
        "recorded_at": _timestamp(),
    }


def capture_platform(args: argparse.Namespace) -> int:
    policy, lock, _ = load_contracts(args.policy, args.lock)
    roots = {name: _safe_root(getattr(args, f"{name}_root")) for name in ROOT_NAMES}
    try:
        labels_value = json.loads(args.runner_labels_json, object_pairs_hook=_strict_object)
    except (ValueError, TypeError) as exc:
        raise GateError("runner_labels_invalid") from exc
    if (
        not isinstance(labels_value, list)
        or len(labels_value) != len(set(labels_value))
        or not all(isinstance(item, str) and 0 < len(item) <= 128 for item in labels_value)
    ):
        raise GateError("runner_labels_invalid")
    architecture = platform.machine()
    try:
        product = Path("/sys/devices/virtual/dmi/id/product_name").read_text(encoding="utf-8").strip()
    except OSError:
        product = ""
    gpu_result = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=30)
    gpu_names = [line.strip() for line in gpu_result.stdout.splitlines() if line.strip()][:16]
    repositories = {
        name: _repository_state(
            roots[name], lock["repositories"][name]["head"], allow_descendant=name == "security"
        )
        for name in ROOT_NAMES
    }
    checks = {
        "architecture": architecture in policy["runner"]["architectures"],
        "gpu": gpu_result.returncode == 0
        and bool(gpu_names)
        and any(pattern in name for pattern in policy["runner"]["gpu_name_patterns"] for name in gpu_names),
        "github_sha": repositories["security"]["head"] == args.github_sha,
        "product": product in policy["runner"]["product_names"],
        "repositories": all(item["binding_matches"] and item["clean"] for item in repositories.values()),
        "runner_labels": set(policy["runner"]["required_labels"]).issubset(labels_value),
    }
    report = {
        **_base_report(PLATFORM_SCHEMA, lock, args.batch_id, args.github_sha),
        "architecture": architecture,
        "checks": checks,
        "gpu_names": gpu_names,
        "policy_sha256": _sha_bytes(_canonical(policy)),
        "product_name": product,
        "repositories": repositories,
        "runner_labels": sorted(labels_value),
        "ready": all(checks.values()),
        "secrets_included": False,
    }
    _write_json(args.output, report)
    return 0 if report["ready"] or not args.require_ready else 1


def _suite(policy: Mapping[str, Any], suite_id: str) -> dict[str, Any]:
    for suite in policy["suites"]:
        if suite["id"] == suite_id:
            return suite
    raise GateError("suite_unknown")


def _isolated_environment(private_root: Path) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not SENSITIVE_ENV_RE.search(key)
        and key not in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"}
    }
    home = private_root / "home"
    temporary = private_root / "tmp"
    for directory in (home, temporary):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
    environment.update(
        {
            "HOME": str(home),
            "HERMES_HOME": str(home / ".hermes"),
            "TMPDIR": str(temporary),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
        }
    )
    return environment


def run_suite(args: argparse.Namespace) -> int:
    policy, lock, _ = load_contracts(args.policy, args.lock)
    suite = _suite(policy, args.suite)
    roots = {name: _safe_root(getattr(args, f"{name}_root")) for name in ROOT_NAMES}
    platform_report = load_json(args.platform_report)
    _validate_platform(platform_report, policy, lock, args.batch_id, args.github_sha, roots)
    root = roots[suite["root"]]
    before = _repository_state(
        root, lock["repositories"][suite["root"]]["head"], allow_descendant=suite["root"] == "security"
    )
    if not before["binding_matches"] or not before["clean"] or before["head"] != platform_report["repositories"][suite["root"]]["head"]:
        raise GateError("suite_repository_state_invalid")
    private_root = args.log.parent
    private_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(private_root, 0o700)
    if args.log.exists() or args.log.is_symlink():
        raise GateError("suite_log_already_exists")
    argv = list(suite["argv"])
    executable = argv[0]
    if "/" in executable:
        candidate = root / executable
        if not candidate.exists() or candidate.is_dir():
            raise GateError("suite_executable_invalid")
        argv[0] = str(candidate)
        executable_path = candidate.resolve(strict=True)
    else:
        located = shutil.which(executable)
        if not located:
            raise GateError("suite_executable_invalid")
        argv[0] = located
        executable_path = Path(located).resolve(strict=True)
    started = _timestamp()
    timed_out = False
    try:
        log_descriptor = os.open(
            args.log,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise GateError("suite_log_create_failed") from exc
    try:
        with os.fdopen(log_descriptor, "w", encoding="utf-8") as stream:
            result = subprocess.run(
                argv,
                cwd=root,
                env=_isolated_environment(private_root),
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=suite["timeout_seconds"],
                check=False,
            )
            exit_code: int | None = result.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        exit_code = None
    after = _repository_state(
        root, lock["repositories"][suite["root"]]["head"], allow_descendant=suite["root"] == "security"
    )
    passed = exit_code == 0 and not timed_out and after["clean"] and after["head"] == before["head"]
    receipt = {
        **_base_report(SUITE_SCHEMA, lock, args.batch_id, args.github_sha),
        "argv_sha256": _sha_bytes(_canonical(suite["argv"])),
        "ended_at": _timestamp(),
        "executable_sha256": sha256_file(executable_path),
        "exit_code": exit_code,
        "log_sha256": sha256_file(args.log),
        "log_size_bytes": args.log.stat().st_size,
        "passed": passed,
        "repository_clean_after": after["clean"],
        "repository_head": after["head"],
        "root": suite["root"],
        "secrets_included": False,
        "started_at": started,
        "suite_id": suite["id"],
        "timed_out": timed_out,
    }
    _write_json(args.output, receipt)
    return 0 if passed else 1


def bind_resource(args: argparse.Namespace) -> int:
    policy, lock, _ = load_contracts(args.policy, args.lock)
    report = load_json(args.resource_report)
    age_seconds = time.time() - args.resource_report.stat().st_mtime
    valid = _resource_ready(report) and -300 <= age_seconds <= min(300, policy["evidence_max_age_seconds"])
    binding = {
        **_base_report(RESOURCE_BINDING_SCHEMA, lock, args.batch_id, args.github_sha),
        "audit_sha256": sha256_file(args.resource_report),
        "audit_source_age_seconds": max(0, int(age_seconds)),
        "bound": valid,
        "gateway_status": report.get("gateway_status"),
        "operational_ready": report.get("operational_ready") is True,
        "payload_column_read": report.get("payload_column_read"),
        "secrets_included": False,
    }
    _write_json(args.output, binding)
    return 0 if valid else 1


def _validate_platform(
    report: dict[str, Any],
    policy: Mapping[str, Any],
    lock: Mapping[str, Any],
    batch_id: str,
    github_sha: str,
    roots: Mapping[str, Path] | None = None,
) -> None:
    if (
        report.get("schema_version") != PLATFORM_SCHEMA
        or report.get("candidate_id") != lock["candidate_id"]
        or report.get("batch_id") != batch_id
        or report.get("github_sha") != github_sha
        or report.get("policy_sha256") != _sha_bytes(_canonical(policy))
        or report.get("ready") is not True
        or report.get("secrets_included") is not False
        or not _fresh(report.get("recorded_at"), policy["evidence_max_age_seconds"])
    ):
        raise GateError("platform_evidence_invalid")
    checks = report.get("checks")
    if not isinstance(checks, dict) or set(checks) != {
        "architecture", "gpu", "github_sha", "product", "repositories", "runner_labels"
    } or not all(value is True for value in checks.values()):
        raise GateError("platform_evidence_invalid")
    repositories = report.get("repositories")
    if not isinstance(repositories, dict) or set(repositories) != set(ROOT_NAMES):
        raise GateError("platform_evidence_invalid")
    for name in ROOT_NAMES:
        item = repositories[name]
        if (
            not isinstance(item, dict)
            or item.get("binding_matches") is not True
            or item.get("clean") is not True
            or item.get("locked_head") != lock["repositories"][name]["head"]
            or SHA40_RE.fullmatch(str(item.get("head", ""))) is None
        ):
            raise GateError("platform_evidence_invalid")
        if roots is not None:
            current = _repository_state(
                roots[name], lock["repositories"][name]["head"], allow_descendant=name == "security"
            )
            if current != item:
                raise GateError("platform_repository_state_changed")


def _validate_doctor(report: dict[str, Any], policy: Mapping[str, Any], lock: Mapping[str, Any]) -> None:
    levels = report.get("levels")
    if (
        report.get("schema_version") != DOCTOR_SCHEMA
        or report.get("candidate_id") != lock["candidate_id"]
        or not _fresh(report.get("recorded_at"), policy["evidence_max_age_seconds"])
        or not isinstance(levels, dict)
        or set(levels) != {
            "configuration_correct",
            "candidate_gateway",
            "identity_match",
            "data_security",
            "inference_verified",
            "promotion_boundary",
            "live_environment",
        }
        or any(value != "pass" for value in levels.values())
        or report.get("candidate_package_ready") is not True
        or report.get("current_environment_ready") is not True
        or report.get("active_pool_promoted") is not False
        or report.get("production_eligible") is not False
        or report.get("deployment_verified") is not False
        or report.get("secrets_included") is not False
    ):
        raise GateError("candidate_doctor_evidence_invalid")


def _resource_ready(report: Mapping[str, Any]) -> bool:
    return bool(
        report.get("schema_version") == RESOURCE_SCHEMA
        and report.get("passed") is True
        and report.get("operational_ready") is True
        and report.get("production_evidence") is False
        and report.get("gateway_status") == "healthy"
        and report.get("payload_column_read") is False
        and isinstance(report.get("summary"), dict)
    )


def _validate_resource(
    report: dict[str, Any],
    binding: dict[str, Any],
    policy: Mapping[str, Any],
    lock: Mapping[str, Any],
    batch_id: str,
    github_sha: str,
    report_path: Path,
) -> None:
    if not _resource_ready(report):
        raise GateError("resource_evidence_invalid")
    if (
        binding.get("schema_version") != RESOURCE_BINDING_SCHEMA
        or binding.get("candidate_id") != lock["candidate_id"]
        or binding.get("batch_id") != batch_id
        or binding.get("github_sha") != github_sha
        or binding.get("audit_sha256") != sha256_file(report_path)
        or binding.get("bound") is not True
        or binding.get("gateway_status") != "healthy"
        or binding.get("operational_ready") is not True
        or binding.get("payload_column_read") is not False
        or binding.get("secrets_included") is not False
        or not _fresh(binding.get("recorded_at"), policy["evidence_max_age_seconds"])
    ):
        raise GateError("resource_binding_invalid")


def _validate_suite(
    receipt: dict[str, Any],
    suite: Mapping[str, Any],
    policy: Mapping[str, Any],
    lock: Mapping[str, Any],
    platform_report: Mapping[str, Any],
    batch_id: str,
    github_sha: str,
) -> None:
    if (
        receipt.get("schema_version") != SUITE_SCHEMA
        or receipt.get("candidate_id") != lock["candidate_id"]
        or receipt.get("batch_id") != batch_id
        or receipt.get("github_sha") != github_sha
        or receipt.get("suite_id") != suite["id"]
        or receipt.get("root") != suite["root"]
        or receipt.get("argv_sha256") != _sha_bytes(_canonical(suite["argv"]))
        or receipt.get("repository_head") != platform_report["repositories"][suite["root"]]["head"]
        or receipt.get("passed") is not True
        or receipt.get("exit_code") != 0
        or receipt.get("timed_out") is not False
        or receipt.get("repository_clean_after") is not True
        or receipt.get("secrets_included") is not False
        or SHA256_RE.fullmatch(str(receipt.get("executable_sha256", ""))) is None
        or SHA256_RE.fullmatch(str(receipt.get("log_sha256", ""))) is None
        or not _fresh(receipt.get("recorded_at"), policy["evidence_max_age_seconds"])
        or not _fresh(receipt.get("started_at"), policy["evidence_max_age_seconds"])
        or not _fresh(receipt.get("ended_at"), policy["evidence_max_age_seconds"])
    ):
        raise GateError("suite_evidence_invalid")


def verify(args: argparse.Namespace) -> int:
    batch_id = _identifier(args.batch_id, "batch_id_invalid")
    github_sha = _sha40(args.github_sha, "github_sha_invalid")
    policy: dict[str, Any] | None = None
    lock: dict[str, Any] | None = None
    failures: list[str] = []
    suite_results: dict[str, bool] = {}
    platform_ready = doctor_ready = resource_ready = False
    candidate_id = "unknown"
    try:
        policy, lock, _ = load_contracts(args.policy, args.lock)
        candidate_id = lock["candidate_id"]
        platform_report = load_json(args.platform_report)
        _validate_platform(platform_report, policy, lock, batch_id, github_sha)
        platform_ready = True
        doctor_report = load_json(args.doctor_report)
        _validate_doctor(doctor_report, policy, lock)
        doctor_ready = True
        resource_report = load_json(args.resource_report)
        resource_binding = load_json(args.resource_binding)
        _validate_resource(
            resource_report,
            resource_binding,
            policy,
            lock,
            batch_id,
            github_sha,
            args.resource_report,
        )
        resource_ready = True
        receipts = {}
        for path in args.suite_receipt:
            receipt = load_json(path)
            suite_id = receipt.get("suite_id")
            if not isinstance(suite_id, str) or suite_id in receipts:
                raise GateError("suite_receipts_invalid")
            receipts[suite_id] = receipt
        expected_ids = {suite["id"] for suite in policy["suites"]}
        if set(receipts) != expected_ids:
            raise GateError("suite_receipts_incomplete")
        for suite in policy["suites"]:
            _validate_suite(
                receipts[suite["id"]],
                suite,
                policy,
                lock,
                platform_report,
                batch_id,
                github_sha,
            )
            suite_results[suite["id"]] = True
    except GateError as exc:
        failures.append(str(exc))
    passed = not failures and policy is not None and lock is not None
    report = {
        "schema_version": FINAL_SCHEMA,
        "candidate_id": candidate_id,
        "batch_id": batch_id,
        "github_sha": github_sha,
        "recorded_at": _timestamp(),
        "status": "passed" if passed else "failed",
        "candidate_verified": passed,
        "platform_ready": platform_ready,
        "doctor_ready": doctor_ready,
        "resource_governance_ready": resource_ready,
        "suite_results": suite_results,
        "failure_codes": failures,
        "active_pool_promoted": False,
        "production_eligible": False,
        "deployment_verified": False,
        "secrets_included": False,
    }
    _write_json(args.output, report)
    return 0 if passed else 1


def _common(parser: argparse.ArgumentParser, *, roots: bool = False) -> None:
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--github-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    if roots:
        for name in ROOT_NAMES:
            parser.add_argument(f"--{name}-root", type=Path, required=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture-platform")
    _common(capture, roots=True)
    capture.add_argument("--runner-labels-json", required=True)
    capture.add_argument("--require-ready", action="store_true")
    suite = commands.add_parser("run-suite")
    _common(suite, roots=True)
    suite.add_argument("--suite", required=True)
    suite.add_argument("--platform-report", type=Path, required=True)
    suite.add_argument("--log", type=Path, required=True)
    resource = commands.add_parser("bind-resource-audit")
    _common(resource)
    resource.add_argument("--resource-report", type=Path, required=True)
    final = commands.add_parser("verify")
    _common(final)
    final.add_argument("--platform-report", type=Path, required=True)
    final.add_argument("--doctor-report", type=Path, required=True)
    final.add_argument("--resource-report", type=Path, required=True)
    final.add_argument("--resource-binding", type=Path, required=True)
    final.add_argument("--suite-receipt", type=Path, action="append", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "capture-platform":
            return capture_platform(args)
        if args.command == "run-suite":
            return run_suite(args)
        if args.command == "bind-resource-audit":
            return bind_resource(args)
        return verify(args)
    except GateError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
