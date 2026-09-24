#!/usr/bin/env python3
"""Verify the isolated confidential Hermes/OpenShell candidate package."""

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
DEFAULT_LOCK = Path(__file__).with_name("runtime-lock.confidential-candidate.v1.json")
LEVELS = (
    "configuration_correct",
    "candidate_gateway",
    "identity_match",
    "data_security",
    "inference_verified",
    "promotion_boundary",
    "live_environment",
)
PACKAGE_LEVELS = LEVELS[:-1]
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_ENDPOINT_HOSTS = {"127.0.0.1", "localhost", "::1", "172.23.0.1"}


class CandidateDoctorError(RuntimeError):
    """Stable lock, path, or collection failure."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("redirect rejected")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateDoctorError("duplicate_json_key")
        result[key] = value
    return result


def load_json(path: Path, *, max_bytes: int = 2 << 20) -> dict[str, Any]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
            raise CandidateDoctorError("json_file_invalid")
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except CandidateDoctorError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        raise CandidateDoctorError("json_file_invalid") from exc
    if not isinstance(value, dict):
        raise CandidateDoctorError("json_root_invalid")
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


def _sha(value: Any) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise CandidateDoctorError("lock_sha256_invalid")
    return value


def _string(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise CandidateDoctorError(code)
    return value


def _relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise CandidateDoctorError("lock_relative_path_invalid")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise CandidateDoctorError("lock_relative_path_invalid")
    return path


def _safe_url(value: Any) -> bool:
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


def _exact_keys(value: Any, expected: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise CandidateDoctorError(code)
    return value


def validate_lock(lock: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "candidate_id",
        "recorded_at",
        "roots",
        "hardware",
        "repositories",
        "artifacts",
        "gateway",
        "hermes",
        "profile_manifest",
        "model",
        "evidence",
        "release_state",
    }
    _exact_keys(lock, required, "candidate_lock_schema_invalid")
    if lock["schema_version"] != "siq.dgx-spark.confidential-candidate-lock.v1":
        raise CandidateDoctorError("candidate_lock_schema_invalid")
    _string(lock["candidate_id"], "candidate_lock_id_invalid")
    _string(lock["recorded_at"], "candidate_lock_timestamp_invalid")
    roots = _exact_keys(lock["roots"], {"security", "research", "hermes"}, "candidate_lock_roots_invalid")
    if roots != {"security": ".", "research": "SIQ_RESEARCH_ROOT", "hermes": "SIQ_HERMES_ROOT"}:
        raise CandidateDoctorError("candidate_lock_roots_invalid")
    hardware = _exact_keys(
        lock["hardware"], {"product_names", "architectures"}, "candidate_lock_hardware_invalid"
    )
    for field in ("product_names", "architectures"):
        if not isinstance(hardware[field], list) or not hardware[field] or not all(
            isinstance(item, str) and item for item in hardware[field]
        ):
            raise CandidateDoctorError("candidate_lock_hardware_invalid")
    repositories = _exact_keys(
        lock["repositories"], {"security", "research", "hermes"}, "candidate_lock_repositories_invalid"
    )
    for item in repositories.values():
        _exact_keys(item, {"head"}, "candidate_lock_repository_invalid")
        if COMMIT_RE.fullmatch(str(item["head"])) is None:
            raise CandidateDoctorError("candidate_lock_repository_invalid")
    artifacts = lock["artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise CandidateDoctorError("candidate_lock_artifacts_invalid")
    artifact_ids: set[str] = set()
    for item in artifacts:
        _exact_keys(item, {"id", "root", "path", "sha256", "role"}, "candidate_lock_artifact_invalid")
        artifact_id = _string(item["id"], "candidate_lock_artifact_invalid")
        if artifact_id in artifact_ids or item["root"] not in roots:
            raise CandidateDoctorError("candidate_lock_artifact_invalid")
        artifact_ids.add(artifact_id)
        _relative_path(item["path"])
        _sha(item["sha256"])
        _string(item["role"], "candidate_lock_artifact_invalid")
    required_artifacts = {
        "candidate_gateway_binary",
        "candidate_gateway_record",
        "candidate_image_state",
        "candidate_image_smoke",
        "candidate_source_baseline",
        "profile_manifest",
        "governed_model_routes",
        "hermes_auth_compatibility_patch",
        "nw01_evidence",
        "dt01_evidence",
        "model_host_proof",
        "model_sandbox_proof",
    }
    if not required_artifacts.issubset(artifact_ids):
        raise CandidateDoctorError("candidate_lock_artifacts_invalid")
    gateway = _exact_keys(
        lock["gateway"],
        {"namespace", "version", "binary_sha256", "health_url", "expected_inventory_count"},
        "candidate_lock_gateway_invalid",
    )
    if gateway["namespace"] != "siq-openshell-scope-validation" or gateway["version"] != "0.0.83":
        raise CandidateDoctorError("candidate_lock_gateway_invalid")
    _sha(gateway["binary_sha256"])
    if not _safe_url(gateway["health_url"]) or gateway["expected_inventory_count"] != 0:
        raise CandidateDoctorError("candidate_lock_gateway_invalid")
    hermes = _exact_keys(
        lock["hermes"],
        {
            "version",
            "commit",
            "image_ref",
            "image_id",
            "context_sha256",
            "runtime_config_sha256",
            "data_classification",
        },
        "candidate_lock_hermes_invalid",
    )
    if (
        hermes["version"] != "0.21.0"
        or COMMIT_RE.fullmatch(str(hermes["commit"])) is None
        or IMAGE_ID_RE.fullmatch(str(hermes["image_id"])) is None
        or hermes["data_classification"] != "confidential_local"
    ):
        raise CandidateDoctorError("candidate_lock_hermes_invalid")
    _string(hermes["image_ref"], "candidate_lock_hermes_invalid")
    _sha(hermes["context_sha256"])
    _sha(hermes["runtime_config_sha256"])
    manifest = _exact_keys(
        lock["profile_manifest"],
        {
            "artifact_id",
            "schema_version",
            "candidate_build_consistent",
            "release_consistent",
            "production_eligible",
            "active_runtime_matches_candidate",
        },
        "candidate_lock_profile_manifest_invalid",
    )
    if manifest != {
        "artifact_id": "profile_manifest",
        "schema_version": "siq.hermes.profile-manifest.v1",
        "candidate_build_consistent": True,
        "release_consistent": False,
        "production_eligible": False,
        "active_runtime_matches_candidate": False,
    }:
        raise CandidateDoctorError("candidate_lock_profile_manifest_invalid")
    model = _exact_keys(
        lock["model"],
        {"alias", "model_id", "route_sha256", "endpoints", "cloud_fallback"},
        "candidate_lock_model_invalid",
    )
    _string(model["alias"], "candidate_lock_model_invalid")
    _string(model["model_id"], "candidate_lock_model_invalid")
    _sha(model["route_sha256"])
    if model["cloud_fallback"] != "forbidden" or not isinstance(model["endpoints"], list) or not model["endpoints"]:
        raise CandidateDoctorError("candidate_lock_model_invalid")
    for endpoint in model["endpoints"]:
        _exact_keys(endpoint, {"id", "url"}, "candidate_lock_model_invalid")
        _string(endpoint["id"], "candidate_lock_model_invalid")
        if not _safe_url(endpoint["url"]):
            raise CandidateDoctorError("candidate_lock_model_invalid")
    evidence = _exact_keys(
        lock["evidence"], {"nw01", "dt01", "model_host", "model_sandbox"}, "candidate_lock_evidence_invalid"
    )
    for item in evidence.values():
        _exact_keys(item, {"artifact_id", "schema_version"}, "candidate_lock_evidence_invalid")
        if item["artifact_id"] not in artifact_ids:
            raise CandidateDoctorError("candidate_lock_evidence_invalid")
        _string(item["schema_version"], "candidate_lock_evidence_invalid")
    release = _exact_keys(
        lock["release_state"],
        {"scope", "candidate_package_expected_ready", "active_pool_promoted", "production_eligible"},
        "candidate_lock_release_state_invalid",
    )
    if release != {
        "scope": "isolated_confidential_canary",
        "candidate_package_expected_ready": True,
        "active_pool_promoted": False,
        "production_eligible": False,
    }:
        raise CandidateDoctorError("candidate_lock_release_state_invalid")


def run_command(
    args: list[str], *, timeout: float = 10.0, environment: dict[str, str] | None = None
) -> tuple[int | None, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, ""
    return result.returncode, result.stdout.strip()


def http_json(url: str) -> tuple[int | None, dict[str, Any] | None]:
    if not _safe_url(url):
        return None, None
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=5) as response:
            raw = response.read((1 << 20) + 1)
            if len(raw) > 1 << 20:
                return response.status, None
            value = json.loads(raw, object_pairs_hook=_strict_object)
            return response.status, value if isinstance(value, dict) else None
    except (CandidateDoctorError, URLError, OSError, UnicodeError, ValueError, TypeError):
        return None, None


@dataclass
class Check:
    level: str
    name: str
    status: str
    reason: str
    observed: Any = None

    def payload(self) -> dict[str, Any]:
        payload = {"level": self.level, "name": self.name, "status": self.status, "reason": self.reason}
        if self.observed is not None:
            payload["observed"] = self.observed
        return payload


class CandidateDoctor:
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
            "security": security_root.resolve(strict=True),
            "research": research_root.resolve(strict=True),
            "hermes": hermes_root.resolve(strict=True),
        }
        self.offline = offline
        self.checks: list[Check] = []
        self.artifacts = {item["id"]: item for item in lock["artifacts"]}

    def add(self, level: str, name: str, passed: bool | None, reason: str, observed: Any = None) -> None:
        status = "pass" if passed is True else "fail" if passed is False else "unverified"
        self.checks.append(Check(level, name, status, reason, observed))

    def path(self, root: str, relative: str) -> Path:
        base = self.roots[root]
        unresolved = base / _relative_path(relative)
        if unresolved.is_symlink():
            raise CandidateDoctorError("candidate_lock_path_symlink")
        candidate = unresolved.resolve(strict=False)
        if candidate != base and base not in candidate.parents:
            raise CandidateDoctorError("candidate_lock_path_escape")
        return candidate

    def artifact_path(self, artifact_id: str) -> Path:
        item = self.artifacts[artifact_id]
        return self.path(item["root"], item["path"])

    def artifact_json(self, artifact_id: str) -> dict[str, Any] | None:
        item = self.artifacts[artifact_id]
        path = self.artifact_path(artifact_id)
        if sha256_file(path) != item["sha256"]:
            return None
        try:
            return load_json(path)
        except CandidateDoctorError:
            return None

    def check_configuration(self) -> None:
        hardware = self.lock["hardware"]
        try:
            product = Path("/sys/devices/virtual/dmi/id/product_name").read_text(encoding="utf-8").strip()
        except OSError:
            product = None
        architecture = platform.machine()
        self.add(
            "configuration_correct",
            "hardware.dgx_spark_identity",
            product in hardware["product_names"] and architecture in hardware["architectures"],
            "hardware_matches_lock"
            if product in hardware["product_names"] and architecture in hardware["architectures"]
            else "hardware_identity_mismatch",
            {"architecture": architecture, "product": product},
        )
        for name, expected in self.lock["repositories"].items():
            code, output = run_command(["git", "-C", str(self.roots[name]), "rev-parse", "HEAD"])
            if name == "security" and code == 0 and COMMIT_RE.fullmatch(output or ""):
                # The lock is itself stored in the security repository, so an
                # enclosing Git commit cannot contain its own commit hash.
                # Bind this repository to the locked reviewed baseline plus
                # per-artifact digests; the native CI gate separately requires
                # the checked-out GitHub SHA and a clean worktree. Sibling
                # repositories remain exact-head bindings.
                ancestor_code, _ = run_command(
                    [
                        "git",
                        "-C",
                        str(self.roots[name]),
                        "merge-base",
                        "--is-ancestor",
                        expected["head"],
                        output,
                    ]
                )
                repository_matches = ancestor_code == 0
                reason = "locked_baseline_ancestor" if repository_matches else "locked_baseline_not_ancestor"
            else:
                repository_matches = code == 0 and output == expected["head"]
                reason = "head_matches_lock" if repository_matches else "head_drift_or_unavailable"
            self.add(
                "configuration_correct",
                f"repository.{name}.head",
                repository_matches,
                reason,
                output if COMMIT_RE.fullmatch(output or "") else None,
            )
        for item in self.lock["artifacts"]:
            observed = sha256_file(self.path(item["root"], item["path"]))
            self.add(
                "configuration_correct",
                f"artifact.{item['id']}",
                observed == item["sha256"],
                "digest_matches_lock" if observed == item["sha256"] else "artifact_drift",
                observed,
            )

    def check_gateway(self) -> None:
        gateway = self.lock["gateway"]
        binary = self.artifact_path("candidate_gateway_binary")
        code, output = run_command([str(binary), "--version"])
        self.add(
            "candidate_gateway",
            "gateway.binary_version",
            code == 0 and output == f"openshell-gateway {gateway['version']}",
            "version_matches_lock" if code == 0 and output == f"openshell-gateway {gateway['version']}" else "version_mismatch",
            output or None,
        )
        record_path = self.artifact_path("candidate_gateway_record")
        try:
            lines = record_path.read_text(encoding="ascii").splitlines()
            pairs = [line.split("=", 1) for line in lines if "=" in line]
            record = dict(pairs)
            record_ok = bool(
                len(record) == len(pairs)
                and record.get("schema") == "siq.openshell.gateway_candidate.v1"
                and record.get("version") == gateway["version"]
                and record.get("binary_sha256") == gateway["binary_sha256"]
                and record.get("installed") == "false"
            )
        except (OSError, UnicodeError, ValueError):
            record_ok = False
        self.add(
            "candidate_gateway",
            "gateway.build_record",
            record_ok,
            "gateway_build_record_matches_lock" if record_ok else "gateway_build_record_mismatch",
        )
        if self.offline:
            self.add("live_environment", "gateway.process_identity", None, "offline_mode")
            self.add("live_environment", "gateway.health", None, "offline_mode")
            self.add("live_environment", "gateway.inventory_empty", None, "offline_mode")
            return
        validator = self.path("research", "scripts/openshell/validate_gateway_candidate.py")
        code, _ = run_command(["python3", str(validator), "--project-root", str(self.roots["research"])])
        self.add(
            "live_environment",
            "gateway.process_identity",
            code == 0,
            "candidate_process_valid" if code == 0 else "candidate_process_invalid",
        )
        status, payload = http_json(gateway["health_url"])
        healthy = status == 200 and payload is not None and payload.get("status") == "healthy"
        self.add(
            "live_environment",
            "gateway.health",
            healthy,
            "gateway_healthy" if healthy else "gateway_unhealthy",
        )
        environment = os.environ.copy()
        environment.update(
            {
                "SIQ_OPENSHELL_CANDIDATE_VALIDATION": "1",
                "OPENSHELL_GATEWAY": gateway["namespace"],
            }
        )
        run_cli = self.path("research", "scripts/openshell/run_cli.sh")
        code, output = run_command(
            [str(run_cli), "sandbox", "list", "--limit", "1", "-o", "json"], environment=environment
        )
        try:
            inventory = json.loads(output) if code == 0 else None
        except (TypeError, ValueError):
            inventory = None
        empty = isinstance(inventory, list) and len(inventory) == gateway["expected_inventory_count"]
        self.add(
            "live_environment",
            "gateway.inventory_empty",
            empty,
            "candidate_inventory_empty" if empty else "candidate_inventory_not_empty_or_unreadable",
            {"count": len(inventory)} if isinstance(inventory, list) else None,
        )

    def check_identity(self) -> None:
        hermes = self.lock["hermes"]
        state = self.artifact_json("candidate_image_state")
        expected_state = {
            "image_ref": hermes["image_ref"],
            "image_id": hermes["image_id"],
            "context_sha256": hermes["context_sha256"],
            "runtime_config_sha256": hermes["runtime_config_sha256"],
            "data_classification": hermes["data_classification"],
            "hermes_commit": hermes["commit"],
        }
        state_ok = state is not None and all(state.get(key) == value for key, value in expected_state.items())
        self.add(
            "identity_match",
            "hermes.candidate_state",
            state_ok,
            "candidate_state_matches_lock" if state_ok else "candidate_state_mismatch",
        )
        smoke = self.artifact_json("candidate_image_smoke")
        smoke_ok = bool(
            smoke
            and smoke.get("status") == "passed"
            and smoke.get("image_id") == hermes["image_id"]
            and smoke.get("image_ref") == hermes["image_ref"]
            and smoke.get("candidate_state_sha256") == self.artifacts["candidate_image_state"]["sha256"]
        )
        self.add(
            "identity_match",
            "hermes.candidate_smoke",
            smoke_ok,
            "candidate_smoke_matches_lock" if smoke_ok else "candidate_smoke_mismatch",
        )
        baseline = self.artifact_json("candidate_source_baseline")
        auth_patch = self.artifacts["hermes_auth_compatibility_patch"]
        baseline_ok = bool(
            baseline
            and baseline.get("schema_version") == "siq.openshell.siq_analysis_context.v1"
            and baseline.get("hermes_baseline") == "v0210"
            and baseline.get("hermes_version") == hermes["version"]
            and baseline.get("hermes_commit") == hermes["commit"]
            and baseline.get("data_classification") == hermes["data_classification"]
            and baseline.get("runtime_config_sha256") == hermes["runtime_config_sha256"]
            and baseline.get("hermes_auth_patch_sha256") == auth_patch["sha256"]
            and baseline.get("contains_credentials") is False
            and baseline.get("contains_credential_placeholders_only") is True
            and baseline.get("contains_host_runtime_state") is False
            and baseline.get("contains_wiki_data") is False
        )
        self.add(
            "identity_match",
            "hermes.source_baseline",
            baseline_ok,
            "source_baseline_binds_compatibility_patch"
            if baseline_ok
            else "source_baseline_or_compatibility_patch_mismatch",
        )
        manifest = self.artifact_json("profile_manifest")
        manifest_expected = self.lock["profile_manifest"]
        manifest_ok = bool(
            manifest
            and manifest.get("schema_version") == manifest_expected["schema_version"]
            and manifest.get("candidate_build_consistent") is True
            and manifest.get("release_consistent") is False
            and manifest.get("production_eligible") is False
            and manifest.get("comparisons", {}).get("active_runtime_equals_candidate_image") is False
            and manifest.get("image", {}).get("image_id") == hermes["image_id"]
            and manifest.get("image", {}).get("image_ref") == hermes["image_ref"]
            and manifest.get("image", {}).get("data_classification") == "confidential_local"
        )
        self.add(
            "identity_match",
            "hermes.profile_manifest",
            manifest_ok,
            "candidate_profile_manifest_matches_lock" if manifest_ok else "candidate_profile_manifest_mismatch",
        )
        if self.offline:
            self.add("identity_match", "hermes.local_image", None, "offline_mode")
        else:
            code, output = run_command(
                ["docker", "image", "inspect", hermes["image_ref"], "--format", "{{json .}}"]
            )
            try:
                image = json.loads(output) if code == 0 else None
            except (TypeError, ValueError):
                image = None
            labels = image.get("Config", {}).get("Labels", {}) if isinstance(image, dict) else {}
            image_ok = bool(
                image
                and image.get("Id") == hermes["image_id"]
                and labels.get("org.opencontainers.image.revision") == hermes["commit"]
                and labels.get("ai.siq.openshell.context-sha256") == hermes["context_sha256"]
                and labels.get("ai.siq.openshell.runtime-config-sha256") == hermes["runtime_config_sha256"]
                and labels.get("ai.siq.openshell.data-classification") == "confidential_local"
            )
            self.add(
                "identity_match",
                "hermes.local_image",
                image_ok,
                "local_image_labels_match_lock" if image_ok else "local_image_or_labels_mismatch",
            )
        self.check_aiohttp_image_compatibility()
        host = self.artifact_json("model_host_proof")
        model = self.lock["model"]
        routes = self.artifact_json("governed_model_routes")
        try:
            bound_alias = routes["profile_bindings"]["siq_analysis"]["confidential_local"]
            route = routes["aliases"][bound_alias]
            canonical_route = json.dumps(
                {"alias": bound_alias, "data_classification": "confidential_local", **route},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("ascii")
            governed_contract_ok = bool(
                routes.get("schema_version") == "siq.model.governed-routes.v1"
                and bound_alias == model["alias"]
                and route.get("model_id") == model["model_id"]
                and route.get("cloud_fallback") == "forbidden"
                and "confidential_local" in route.get("allowed_data_classifications", [])
                and hashlib.sha256(canonical_route).hexdigest() == model["route_sha256"]
            )
        except (KeyError, TypeError, UnicodeError, ValueError):
            governed_contract_ok = False
        self.add(
            "identity_match",
            "model.governed_route_contract",
            governed_contract_ok,
            "governed_route_contract_matches_lock" if governed_contract_ok else "governed_route_contract_mismatch",
        )
        route_ok = bool(
            host
            and host.get("passed") is True
            and host.get("alias") == model["alias"]
            and host.get("model_id") == model["model_id"]
            and host.get("route_sha256") == model["route_sha256"]
            and host.get("compiled_runtime_sha256") == hermes["runtime_config_sha256"]
        )
        self.add(
            "identity_match",
            "model.governed_route",
            route_ok,
            "governed_route_matches_lock" if route_ok else "governed_route_mismatch",
        )

    def check_aiohttp_image_compatibility(self) -> None:
        if self.offline:
            self.add("identity_match", "hermes.aiohttp_compatibility", None, "offline_mode")
            return
        hermes = self.lock["hermes"]
        code, output = run_command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--user",
                "sandbox",
                "--entrypoint",
                "/opt/siq/hermes/venv/bin/python",
                hermes["image_ref"],
                "-I",
                "-B",
                "-c",
                (
                    "import gateway.platforms.api_server_runs as module;"
                    "assert module.web is not None;"
                    "print('aiohttp_optional_request_key_compat=true')"
                ),
            ],
            timeout=30.0,
        )
        passed = code == 0 and output == "aiohttp_optional_request_key_compat=true"
        self.add(
            "identity_match",
            "hermes.aiohttp_compatibility",
            passed,
            "locked_image_keeps_aiohttp_web_available"
            if passed
            else "locked_image_aiohttp_compatibility_failed",
        )

    def check_data_security(self) -> None:
        nw = self.artifact_json("nw01_evidence")
        dt = self.artifact_json("dt01_evidence")
        sandbox = self.artifact_json("model_sandbox_proof")
        nw_ok = bool(
            nw
            and nw.get("schema_version") == self.lock["evidence"]["nw01"]["schema_version"]
            and nw.get("status") == "completed"
            and nw.get("runtime_proof", {}).get("passed") is True
            and nw.get("enforcement", {}).get("confidential_local", {}).get("public_egress_route_present") is False
            and nw.get("sanitization", {}).get("contains_credentials") is False
        )
        self.add("data_security", "evidence.nw01", nw_ok, "nw01_evidence_valid" if nw_ok else "nw01_evidence_invalid")
        dt_ok = bool(
            dt
            and dt.get("schema_version") == self.lock["evidence"]["dt01"]["schema_version"]
            and dt.get("status") == "completed"
            and dt.get("runtime_proof", {}).get("passed") is True
            and dt.get("enforcement", {}).get("filesystem", {}).get("whole_wiki_root_mounted") is False
            and dt.get("enforcement", {}).get("filesystem", {}).get("company_directory_read_only_count") == 1
        )
        self.add("data_security", "evidence.dt01", dt_ok, "dt01_evidence_valid" if dt_ok else "dt01_evidence_invalid")
        checks = sandbox.get("checks", {}) if sandbox else {}
        sandbox_ok = bool(
            sandbox
            and sandbox.get("schema_version") == self.lock["evidence"]["model_sandbox"]["schema_version"]
            and sandbox.get("passed") is True
            and sandbox.get("data_classification") == "confidential_local"
            and checks.get("provider_count") == 0
            and checks.get("fallback_count") == 0
            and checks.get("public_egress_route_present") is False
            and checks.get("original_policy_restored") is True
            and checks.get("prompt_or_response_stored") is False
        )
        self.add(
            "data_security",
            "evidence.confidential_sandbox",
            sandbox_ok,
            "confidential_sandbox_controls_valid" if sandbox_ok else "confidential_sandbox_controls_invalid",
        )

    def check_inference(self) -> None:
        model = self.lock["model"]
        if self.offline:
            for endpoint in model["endpoints"]:
                self.add("live_environment", f"endpoint.{endpoint['id']}", None, "offline_mode")
        else:
            for endpoint in model["endpoints"]:
                status, payload = http_json(endpoint["url"])
                models = [
                    item.get("id")
                    for item in (payload or {}).get("data", [])
                    if isinstance(item, dict) and isinstance(item.get("id"), str)
                ]
                passed = status == 200 and model["model_id"] in models
                self.add(
                    "live_environment",
                    f"endpoint.{endpoint['id']}",
                    passed,
                    "served_model_matches_lock" if passed else "model_endpoint_or_identity_mismatch",
                    models,
                )
        host = self.artifact_json("model_host_proof")
        host_checks = host.get("checks", {}) if host else {}
        host_ok = bool(
            host
            and host.get("schema_version") == self.lock["evidence"]["model_host"]["schema_version"]
            and host.get("passed") is True
            and host_checks.get("real_inference_loopback") is True
            and host_checks.get("real_inference_openshell_bridge") is True
            and host_checks.get("served_model_exact") is True
        )
        self.add(
            "inference_verified",
            "evidence.host_model_inference",
            host_ok,
            "host_model_inference_valid" if host_ok else "host_model_inference_invalid",
        )
        sandbox = self.artifact_json("model_sandbox_proof")
        checks = sandbox.get("checks", {}) if sandbox else {}
        sandbox_ok = bool(
            sandbox
            and sandbox.get("passed") is True
            and checks.get("real_hermes_inference_completed") is True
            and checks.get("outage_run_failed") is True
            and checks.get("outage_success_marker_absent") is True
            and sandbox.get("positive_run", {}).get("terminal_status") == "completed"
            and sandbox.get("outage_run", {}).get("terminal_status") == "failed"
        )
        self.add(
            "inference_verified",
            "evidence.sandbox_model_and_outage",
            sandbox_ok,
            "sandbox_inference_and_outage_valid" if sandbox_ok else "sandbox_inference_or_outage_invalid",
        )

    def check_promotion_boundary(self) -> None:
        release = self.lock["release_state"]
        manifest = self.artifact_json("profile_manifest")
        separated = bool(
            manifest
            and manifest.get("comparisons", {}).get("active_runtime_equals_candidate_image") is False
            and manifest.get("active_runtime", {}).get("image_id") != manifest.get("image", {}).get("image_id")
            and release["active_pool_promoted"] is False
        )
        self.add(
            "promotion_boundary",
            "release.active_pool_separated",
            separated,
            "active_pool_remains_separate" if separated else "candidate_and_active_state_ambiguous",
        )
        eligibility = bool(
            release["production_eligible"] is False
            and manifest
            and manifest.get("production_eligible") is False
            and manifest.get("release_consistent") is False
        )
        self.add(
            "promotion_boundary",
            "release.production_not_claimed",
            eligibility,
            "production_eligibility_false" if eligibility else "production_boundary_invalid",
        )

    def collect(self) -> dict[str, Any]:
        self.check_configuration()
        self.check_gateway()
        self.check_identity()
        self.check_data_security()
        self.check_inference()
        self.check_promotion_boundary()
        levels: dict[str, str] = {}
        for level in LEVELS:
            statuses = [check.status for check in self.checks if check.level == level]
            levels[level] = (
                "fail" if "fail" in statuses else "unverified" if "unverified" in statuses or not statuses else "pass"
            )
        return {
            "schema_version": "siq.dgx-spark.confidential-candidate-doctor-report.v1",
            "candidate_id": self.lock["candidate_id"],
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "levels": levels,
            "checks": [check.payload() for check in self.checks],
            "candidate_package_ready": all(levels[level] == "pass" for level in PACKAGE_LEVELS),
            "current_environment_ready": all(value == "pass" for value in levels.values()),
            "active_pool_promoted": False,
            "production_eligible": False,
            "deployment_verified": False,
            "secrets_included": False,
            "limitations": [
                "Readiness applies only to the locked isolated confidential candidate.",
                "The active non-production pool remains separately identified and is not this confidential candidate.",
                "This report does not grant production approval or deployment verification.",
            ],
        }


def required_levels_pass(report: dict[str, Any], required: str) -> bool:
    index = LEVELS.index(required)
    return all(report["levels"].get(level) == "pass" for level in LEVELS[: index + 1])


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    value.add_argument("--out", type=Path, default=Path("confidential-candidate-doctor.json"))
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
        report = CandidateDoctor(
            lock,
            security_root=args.security_root,
            research_root=args.research_root,
            hermes_root=args.hermes_root,
            offline=args.offline,
        ).collect()
    except (CandidateDoctorError, OSError) as exc:
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
                "candidate_package_ready": report["candidate_package_ready"],
                "current_environment_ready": report["current_environment_ready"],
                "active_pool_promoted": False,
                "production_eligible": False,
            },
            ensure_ascii=False,
        )
    )
    return 1 if args.require_level and not required_levels_pass(report, args.require_level) else 0


if __name__ == "__main__":
    raise SystemExit(main())
