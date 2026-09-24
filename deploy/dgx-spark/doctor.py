#!/usr/bin/env python3
"""Verify one frozen DGX Spark + OpenShell + Hermes candidate without secrets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = Path(__file__).with_name("runtime-lock.v1.json")
LEVELS = (
    "configuration_correct",
    "service_reachable",
    "identity_match",
    "security_behavior",
    "inference_verified",
    "business_completed",
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{12,64}$")
SAFE_ENDPOINT_HOSTS = {"127.0.0.1", "localhost", "::1", "172.23.0.1"}


class DoctorError(RuntimeError):
    """Stable configuration or collection error."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("redirect rejected")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DoctorError("duplicate_json_key")
        result[key] = value
    return result


def load_json(path: Path, *, max_bytes: int = 1 << 20) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise DoctorError("json_file_invalid")
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except DoctorError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise DoctorError("json_file_invalid") from exc
    if not isinstance(value, dict):
        raise DoctorError("json_root_invalid")
    return value


def sha256_file(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def run_command(args: list[str], *, timeout: float = 10.0) -> tuple[int | None, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return result.returncode, result.stdout.strip()


def http_json(url: str) -> tuple[int | None, dict[str, Any] | None]:
    if not _valid_locked_url(url):
        return None, None
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=5) as response:
            raw = response.read((1 << 20) + 1)
            if len(raw) > 1 << 20:
                return response.status, None
            value = json.loads(raw, object_pairs_hook=_strict_object)
            return response.status, value if isinstance(value, dict) else None
    except (DoctorError, URLError, OSError, UnicodeError, ValueError, TypeError):
        return None, None


def _relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise DoctorError("lock_relative_path_invalid")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise DoctorError("lock_relative_path_invalid")
    return path


def _require_sha(value: Any) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise DoctorError("lock_sha256_invalid")
    return value


def _valid_locked_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = urlsplit(value)
    try:
        port = parts.port
    except ValueError:
        return False
    return bool(
        parts.scheme == "http"
        and parts.hostname in SAFE_ENDPOINT_HOSTS
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and port is not None
    )


def validate_lock(lock: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "candidate_id",
        "recorded_at",
        "roots",
        "hardware",
        "repositories",
        "artifacts",
        "openshell",
        "hermes",
        "model",
        "runtime",
        "evidence",
    }
    if set(lock) != required or lock.get("schema_version") != "siq.dgx-spark.runtime-lock.v1":
        raise DoctorError("runtime_lock_schema_invalid")
    if not isinstance(lock.get("candidate_id"), str) or not lock["candidate_id"]:
        raise DoctorError("runtime_lock_candidate_invalid")
    roots = lock.get("roots")
    if roots != {"security": ".", "research": "SIQ_RESEARCH_ROOT", "hermes": "SIQ_HERMES_ROOT"}:
        raise DoctorError("runtime_lock_roots_invalid")
    if not isinstance(lock.get("repositories"), dict) or set(lock["repositories"]) != set(roots):
        raise DoctorError("runtime_lock_repositories_invalid")
    for item in lock["repositories"].values():
        if not isinstance(item, dict) or set(item) != {"head"} or COMMIT_RE.fullmatch(str(item["head"])) is None:
            raise DoctorError("runtime_lock_repository_invalid")
    artifacts = lock.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise DoctorError("runtime_lock_artifacts_invalid")
    seen: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"id", "root", "path", "sha256", "drift_sensitive"}:
            raise DoctorError("runtime_lock_artifact_invalid")
        if item["root"] not in roots or not isinstance(item["id"], str) or item["id"] in seen:
            raise DoctorError("runtime_lock_artifact_invalid")
        seen.add(item["id"])
        _relative_path(item["path"])
        _require_sha(item["sha256"])
        if not isinstance(item["drift_sensitive"], bool):
            raise DoctorError("runtime_lock_artifact_invalid")
    if not {"openshell_cli", "openshell_gateway"}.issubset(seen):
        raise DoctorError("runtime_lock_artifact_invalid")
    hardware = lock.get("hardware")
    if not isinstance(hardware, dict) or set(hardware) != {"product_names", "architectures"}:
        raise DoctorError("runtime_lock_hardware_invalid")
    if not all(
        isinstance(hardware.get(field), list)
        and hardware[field]
        and all(isinstance(value, str) and value for value in hardware[field])
        for field in ("product_names", "architectures")
    ):
        raise DoctorError("runtime_lock_hardware_invalid")
    openshell = lock.get("openshell")
    if not isinstance(openshell, dict) or set(openshell) != {"version", "cli", "gateway", "supervisor"}:
        raise DoctorError("runtime_lock_openshell_invalid")
    for name in ("cli", "gateway"):
        item = openshell.get(name)
        if not isinstance(item, dict) or set(item) != {"path", "version_output"}:
            raise DoctorError("runtime_lock_openshell_invalid")
        _relative_path(item["path"])
        if not isinstance(item["version_output"], str) or not item["version_output"]:
            raise DoctorError("runtime_lock_openshell_invalid")
    supervisor = openshell.get("supervisor")
    if not isinstance(supervisor, dict) or set(supervisor) != {"container_path", "sha256"}:
        raise DoctorError("runtime_lock_openshell_invalid")
    if not isinstance(supervisor["container_path"], str) or not supervisor["container_path"].startswith("/"):
        raise DoctorError("runtime_lock_openshell_invalid")
    _require_sha(supervisor["sha256"])
    hermes = lock.get("hermes")
    hermes_fields = {
        "version",
        "commit",
        "base_tree",
        "patched_tree_sha256",
        "integration_patch_sha256",
        "image_ref",
        "image_id",
        "context_sha256",
        "runtime_config_sha256",
    }
    if not isinstance(hermes, dict) or set(hermes) != hermes_fields:
        raise DoctorError("runtime_lock_hermes_invalid")
    if COMMIT_RE.fullmatch(str(hermes["commit"])) is None or COMMIT_RE.fullmatch(str(hermes["base_tree"])) is None:
        raise DoctorError("runtime_lock_hermes_invalid")
    for field in ("patched_tree_sha256", "integration_patch_sha256", "context_sha256", "runtime_config_sha256"):
        _require_sha(hermes[field])
    if not isinstance(hermes["image_id"], str) or re.fullmatch(r"sha256:[0-9a-f]{64}", hermes["image_id"]) is None:
        raise DoctorError("runtime_lock_hermes_invalid")
    model = lock.get("model")
    if not isinstance(model, dict) or set(model) != {"provider", "model_id", "bridge_unit", "endpoints"}:
        raise DoctorError("runtime_lock_model_invalid")
    if not all(isinstance(model.get(field), str) and model[field] for field in ("provider", "model_id", "bridge_unit")):
        raise DoctorError("runtime_lock_model_invalid")
    if not isinstance(model["endpoints"], list) or not model["endpoints"]:
        raise DoctorError("runtime_lock_model_invalid")
    for endpoint in model["endpoints"]:
        if not isinstance(endpoint, dict) or set(endpoint) != {"id", "url"} or not _valid_locked_url(endpoint["url"]):
            raise DoctorError("runtime_lock_model_invalid")
    runtime = lock.get("runtime")
    runtime_fields = {
        "market",
        "company",
        "pool_slot_id",
        "run_id",
        "sandbox_name",
        "mode",
        "readiness_effect",
        "route_base",
        "local_port",
        "target_port",
        "policy_sha256",
        "mount_plan_sha256",
        "active_path",
        "manifest_path",
        "health_endpoints",
    }
    if not isinstance(runtime, dict) or set(runtime) != runtime_fields or not _valid_locked_url(runtime["route_base"]):
        raise DoctorError("runtime_lock_runtime_invalid")
    if not all(isinstance(runtime.get(field), str) and runtime[field] for field in runtime_fields - {"local_port", "target_port", "health_endpoints"}):
        raise DoctorError("runtime_lock_runtime_invalid")
    if not all(isinstance(runtime.get(field), int) and 1 <= runtime[field] <= 65535 for field in ("local_port", "target_port")):
        raise DoctorError("runtime_lock_runtime_invalid")
    _require_sha(runtime["policy_sha256"])
    _require_sha(runtime["mount_plan_sha256"])
    _relative_path(runtime["active_path"])
    _relative_path(runtime["manifest_path"])
    if not isinstance(runtime["health_endpoints"], list) or not runtime["health_endpoints"]:
        raise DoctorError("runtime_lock_runtime_invalid")
    for endpoint in runtime["health_endpoints"]:
        if not isinstance(endpoint, dict) or set(endpoint) not in ({"id", "url"}, {"id", "url", "version"}):
            raise DoctorError("runtime_lock_runtime_invalid")
        if not _valid_locked_url(endpoint["url"]):
            raise DoctorError("runtime_lock_runtime_invalid")
    evidence = lock.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"upgrade_manifest", "routing_validation"}:
        raise DoctorError("runtime_lock_evidence_invalid")
    for name in ("upgrade_manifest", "routing_validation"):
        item = evidence.get(name)
        if not isinstance(item, dict) or set(item) != {"root", "path", "sha256"} or item["root"] not in roots:
            raise DoctorError("runtime_lock_evidence_invalid")
        _relative_path(item["path"])
        _require_sha(item["sha256"])


@dataclass
class Check:
    level: str
    name: str
    status: str
    reason: str
    observed: Any = None

    def payload(self) -> dict[str, Any]:
        result = {"level": self.level, "name": self.name, "status": self.status, "reason": self.reason}
        if self.observed is not None:
            result["observed"] = self.observed
        return result


class Doctor:
    def __init__(
        self,
        lock: dict[str, Any],
        *,
        security_root: Path,
        research_root: Path,
        hermes_root: Path,
        offline: bool = False,
    ) -> None:
        validate_lock(lock)
        self.lock = lock
        self.roots = {
            "security": security_root.resolve(),
            "research": research_root.resolve(),
            "hermes": hermes_root.resolve(),
        }
        self.offline = offline
        self.checks: list[Check] = []

    def add(self, level: str, name: str, passed: bool | None, reason: str, observed: Any = None) -> None:
        status = "pass" if passed is True else "fail" if passed is False else "unverified"
        self.checks.append(Check(level, name, status, reason, observed))

    def path(self, root: str, relative: str) -> Path:
        base = self.roots[root]
        unresolved = base / _relative_path(relative)
        if unresolved.is_symlink():
            raise DoctorError("runtime_lock_path_symlink")
        candidate = unresolved.resolve(strict=False)
        if candidate != base and base not in candidate.parents:
            raise DoctorError("runtime_lock_path_escape")
        return candidate

    def check_repositories(self) -> None:
        for name, expected in self.lock["repositories"].items():
            code, output = run_command(["git", "-C", str(self.roots[name]), "rev-parse", "HEAD"])
            self.add(
                "configuration_correct",
                f"repository.{name}.head",
                code == 0 and output == expected["head"],
                "head_matches_lock" if code == 0 and output == expected["head"] else "head_drift_or_unavailable",
                output if COMMIT_RE.fullmatch(output or "") else None,
            )
            dirty_code, dirty = run_command(["git", "-C", str(self.roots[name]), "status", "--porcelain"])
            self.add(
                "configuration_correct",
                f"repository.{name}.dirty_state_recorded",
                dirty_code == 0,
                "dirty_state_observed" if dirty_code == 0 else "dirty_state_unavailable",
                {"dirty": bool(dirty)} if dirty_code == 0 else None,
            )

    def check_artifacts(self) -> None:
        for item in self.lock["artifacts"]:
            observed = sha256_file(self.path(item["root"], item["path"]))
            match = observed == item["sha256"]
            reason = "digest_matches_lock" if match else "drift_detected" if item["drift_sensitive"] else "artifact_mismatch"
            self.add("configuration_correct", f"artifact.{item['id']}", match, reason, observed)

    def check_hardware(self) -> None:
        hardware = self.lock["hardware"]
        product_path = Path("/sys/devices/virtual/dmi/id/product_name")
        try:
            product = product_path.read_text(encoding="utf-8").strip()
        except OSError:
            product = None
        architecture = platform.machine()
        passed = architecture in hardware["architectures"] and product in hardware["product_names"]
        self.add(
            "configuration_correct",
            "hardware.dgx_spark_identity",
            passed,
            "hardware_matches_lock" if passed else "hardware_identity_mismatch",
            {"architecture": architecture, "product": product},
        )

    def check_openshell_binaries(self) -> None:
        openshell = self.lock["openshell"]
        for name in ("cli", "gateway"):
            item = openshell[name]
            binary = self.path("research", item["path"])
            artifact = next(value for value in self.lock["artifacts"] if value["id"] == f"openshell_{name}")
            if sha256_file(binary) != artifact["sha256"]:
                self.add("identity_match", f"openshell.{name}.version", False, "binary_digest_mismatch_not_executed")
                continue
            code, output = run_command([str(binary), "--version"])
            self.add(
                "identity_match",
                f"openshell.{name}.version",
                code == 0 and output == item["version_output"],
                "version_matches_lock" if code == 0 and output == item["version_output"] else "version_mismatch",
                output or None,
            )
        gateway_path = str(self.path("research", openshell["gateway"]["path"]))
        code, output = run_command(["pgrep", "-f", f"^{re.escape(gateway_path)}$"])
        self.add(
            "service_reachable",
            "openshell.gateway_process",
            code == 0 and bool(output),
            "gateway_process_running" if code == 0 and bool(output) else "gateway_process_not_found",
        )

    def check_endpoints(self) -> None:
        if self.offline:
            for endpoint in self.lock["model"]["endpoints"]:
                self.add("service_reachable", f"endpoint.{endpoint['id']}", None, "offline_mode")
            for endpoint in self.lock["runtime"]["health_endpoints"]:
                self.add("service_reachable", f"endpoint.{endpoint['id']}", None, "offline_mode")
            return
        model_id = self.lock["model"]["model_id"]
        for endpoint in self.lock["model"]["endpoints"]:
            status, payload = http_json(endpoint["url"])
            models = [
                item.get("id")
                for item in (payload or {}).get("data", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
            reachable = status == 200 and payload is not None
            self.add(
                "service_reachable",
                f"endpoint.{endpoint['id']}",
                reachable,
                "http_200_json" if reachable else "endpoint_unreachable",
            )
            self.add(
                "identity_match",
                f"model.{endpoint['id']}.id",
                reachable and model_id in models,
                "model_id_matches_lock" if reachable and model_id in models else "model_id_mismatch",
                models,
            )
        for endpoint in self.lock["runtime"]["health_endpoints"]:
            status, payload = http_json(endpoint["url"])
            reachable = status == 200 and payload is not None and payload.get("status") == "ok"
            self.add(
                "service_reachable",
                f"endpoint.{endpoint['id']}",
                reachable,
                "health_ok" if reachable else "health_unavailable",
            )
            expected_version = endpoint.get("version")
            if expected_version is not None:
                self.add(
                    "identity_match",
                    f"endpoint.{endpoint['id']}.version",
                    reachable and payload.get("version") == expected_version,
                    "version_matches_lock" if reachable and payload.get("version") == expected_version else "version_mismatch",
                    payload.get("version") if payload else None,
                )

    def check_bridge(self) -> None:
        unit = self.lock["model"]["bridge_unit"]
        if self.offline:
            self.add("service_reachable", "model.bridge_unit", None, "offline_mode")
            return
        active_code, active = run_command(["systemctl", "--user", "is-active", unit])
        enabled_code, enabled = run_command(["systemctl", "--user", "is-enabled", unit])
        passed = active_code == 0 and active == "active" and enabled_code == 0 and enabled == "enabled"
        self.add(
            "service_reachable",
            "model.bridge_unit",
            passed,
            "bridge_active_enabled" if passed else "bridge_not_active_enabled",
        )

    def _runtime_files(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        runtime = self.lock["runtime"]
        try:
            active = load_json(self.path("research", runtime["active_path"]), max_bytes=64 * 1024)
            manifest = load_json(self.path("research", runtime["manifest_path"]), max_bytes=128 * 1024)
        except DoctorError:
            return None, None
        return active, manifest

    def check_runtime_identity(self) -> None:
        runtime = self.lock["runtime"]
        active, manifest = self._runtime_files()
        active_expected = {
            "market": runtime["market"],
            "company": runtime["company"],
            "run_id": runtime["run_id"],
            "mode": runtime["mode"],
            "readiness_effect": runtime["readiness_effect"],
        }
        active_ok = active is not None and all(active.get(key) == value for key, value in active_expected.items())
        self.add(
            "identity_match",
            "runtime.active_binding",
            active_ok,
            "active_binding_matches_lock" if active_ok else "active_binding_mismatch",
        )
        manifest_expected = {
            **active_expected,
            "phase": "running",
            "sandbox_name": runtime["sandbox_name"],
            "image_id": self.lock["hermes"]["image_id"],
            "image_ref": self.lock["hermes"]["image_ref"],
            "policy_sha256": runtime["policy_sha256"],
            "mount_plan_sha256": runtime["mount_plan_sha256"],
        }
        manifest_ok = manifest is not None and all(manifest.get(key) == value for key, value in manifest_expected.items())
        self.add(
            "identity_match",
            "runtime.manifest",
            manifest_ok,
            "runtime_manifest_matches_lock" if manifest_ok else "runtime_manifest_mismatch",
        )
        if self.offline or manifest is None:
            self.add("identity_match", "openshell.supervisor.digest", None, "offline_or_manifest_missing")
            self.add("identity_match", "runtime.container_image", None, "offline_or_manifest_missing")
            return
        container = str(manifest.get("container_id") or "")
        if CONTAINER_ID_RE.fullmatch(container) is None:
            self.add("identity_match", "runtime.container_image", False, "container_id_invalid")
            self.add("identity_match", "openshell.supervisor.digest", False, "container_id_invalid")
            return
        code, output = run_command(["docker", "inspect", container, "--format", "{{.Image}} {{.State.Status}}"])
        expected = f"{self.lock['hermes']['image_id']} running"
        self.add(
            "identity_match",
            "runtime.container_image",
            code == 0 and output == expected,
            "container_image_matches_lock" if code == 0 and output == expected else "container_image_mismatch",
            output or None,
        )
        supervisor = self.lock["openshell"]["supervisor"]
        code, output = run_command(["docker", "exec", container, "sha256sum", supervisor["container_path"]])
        observed = output.split()[0] if code == 0 and output else None
        self.add(
            "identity_match",
            "openshell.supervisor.digest",
            observed == supervisor["sha256"],
            "supervisor_digest_matches_lock" if observed == supervisor["sha256"] else "supervisor_digest_mismatch",
            observed,
        )

    def _evidence(self, name: str) -> dict[str, Any] | None:
        item = self.lock["evidence"][name]
        path = self.path(item["root"], item["path"])
        if sha256_file(path) != item["sha256"]:
            return None
        try:
            return load_json(path)
        except DoctorError:
            return None

    def check_evidence(self) -> None:
        manifest = self._evidence("upgrade_manifest")
        routing = self._evidence("routing_validation")
        validations = manifest.get("validation", {}) if manifest else {}
        security_ok = all(str(validations.get(f"V{index:02d}", "")).startswith("passed") for index in range(1, 13))
        self.add(
            "security_behavior",
            "evidence.security_validation",
            security_ok,
            "v01_v12_evidence_matches_lock" if security_ok else "security_evidence_missing_or_invalid",
        )
        runtime = self.lock["runtime"]
        inference_ok = bool(
            routing
            and routing.get("route_target") == "openshell"
            and routing.get("route_base") == runtime["route_base"]
            and routing.get("pool_run_id") == runtime["run_id"]
            and routing.get("terminal_status") == "completed"
            and routing.get("output_exact_match") is True
            and routing.get("secrets_included") is False
        )
        self.add(
            "inference_verified",
            "evidence.routed_inference",
            inference_ok,
            "routed_inference_matches_lock" if inference_ok else "inference_evidence_missing_or_invalid",
        )
        business = manifest.get("business_evidence", {}) if manifest else {}
        business_ok = bool(
            business.get("full_report", {}).get("status") == "passed"
            and business.get("missing_evidence", {}).get("status") == "passed_after_one_retry"
            and all(str(validations.get(f"V{index:02d}", "")).startswith("passed") for index in range(13, 19))
        )
        self.add(
            "business_completed",
            "evidence.business_completion",
            business_ok,
            "v13_v18_evidence_matches_lock" if business_ok else "business_evidence_missing_or_invalid",
        )

    def collect(self) -> dict[str, Any]:
        self.check_hardware()
        self.check_repositories()
        self.check_artifacts()
        self.check_openshell_binaries()
        self.check_endpoints()
        self.check_bridge()
        self.check_runtime_identity()
        self.check_evidence()
        levels: dict[str, str] = {}
        for level in LEVELS:
            statuses = [check.status for check in self.checks if check.level == level]
            levels[level] = (
                "fail" if "fail" in statuses else "unverified" if "unverified" in statuses or not statuses else "pass"
            )
        return {
            "schema_version": "siq.dgx-spark.doctor-report.v1",
            "candidate_id": self.lock["candidate_id"],
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "levels": levels,
            "checks": [check.payload() for check in self.checks],
            "candidate_ready": all(value == "pass" for value in levels.values()),
            "deployment_verified": False,
            "secrets_included": False,
            "limitations": [
                "Candidate readiness does not grant production approval.",
                "Locked evidence proves only its recorded candidate, scope, fixtures, and observations.",
            ],
        }


def required_levels_pass(report: dict[str, Any], required: str) -> bool:
    index = LEVELS.index(required)
    return all(report["levels"].get(level) == "pass" for level in LEVELS[: index + 1])


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    value.add_argument("--out", type=Path, default=Path("dgx-spark-doctor.json"))
    value.add_argument("--security-root", type=Path, default=ROOT)
    value.add_argument(
        "--research-root",
        type=Path,
        default=Path(os.environ.get("SIQ_RESEARCH_ROOT", "/home/maoyd/siq-research-engine")),
    )
    value.add_argument(
        "--hermes-root",
        type=Path,
        default=Path(os.environ.get("SIQ_HERMES_ROOT", "/home/maoyd/siq/hermes-agent")),
    )
    value.add_argument("--offline", action="store_true")
    value.add_argument("--require-level", choices=LEVELS)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        lock = load_json(args.lock)
        report = Doctor(
            lock,
            security_root=args.security_root,
            research_root=args.research_root,
            hermes_root=args.hermes_root,
            offline=args.offline,
        ).collect()
    except DoctorError as exc:
        print(json.dumps({"status": "error", "reason": str(exc)}))
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(args.out),
                "candidate_id": report["candidate_id"],
                "levels": report["levels"],
                "candidate_ready": report["candidate_ready"],
                "deployment_verified": False,
            },
            ensure_ascii=False,
        )
    )
    return 1 if args.require_level and not required_levels_pass(report, args.require_level) else 0


if __name__ == "__main__":
    raise SystemExit(main())
