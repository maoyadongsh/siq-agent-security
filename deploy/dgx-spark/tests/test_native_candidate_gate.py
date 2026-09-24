import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATE_PATH = ROOT / "deploy/dgx-spark/native_candidate_gate.py"
POLICY_PATH = ROOT / "deploy/dgx-spark/native-candidate-gate.v1.json"

SPEC = importlib.util.spec_from_file_location("dgx_native_candidate_gate", GATE_PATH)
gate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = gate
SPEC.loader.exec_module(gate)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: dict, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(mode)


class NativeCandidateGateTest(unittest.TestCase):
    def test_repository_policy_is_strict_and_valid(self):
        policy = gate.validate_policy(gate.load_json(POLICY_PATH))
        self.assertEqual(policy["schema_version"], gate.POLICY_SCHEMA)
        self.assertEqual(
            {suite["id"] for suite in policy["suites"]},
            {
                "security_candidate_contracts",
                "security_hermes_adapter",
                "research_openshell_contracts",
                "hermes_native_regression",
            },
        )

    def test_duplicate_symlink_and_hardlink_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"schema_version":"a","schema_version":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(gate.GateError, "duplicate_json_key"):
                gate.load_json(duplicate)
            source = root / "source.json"
            write_json(source, {"schema_version": "fixture"})
            symlink = root / "symlink.json"
            symlink.symlink_to(source)
            with self.assertRaisesRegex(gate.GateError, "json_file_invalid"):
                gate.load_json(symlink)
            hardlink = root / "hardlink.json"
            os.link(source, hardlink)
            with self.assertRaisesRegex(gate.GateError, "json_file_invalid"):
                gate.load_json(source)

    def _fixture(self, root: Path) -> types.SimpleNamespace:
        candidate_id = "fixture-candidate"
        batch_id = "fixture-batch"
        github_sha = "a" * 40
        heads = {"security": github_sha, "research": "b" * 40, "hermes": "c" * 40}
        policy = {
            "schema_version": gate.POLICY_SCHEMA,
            "candidate_lock": {
                "path": "deploy/dgx-spark/runtime-lock.confidential-candidate.v1.json",
                "schema_version": gate.LOCK_SCHEMA,
            },
            "evidence_max_age_seconds": 3600,
            "runner": {
                "architectures": ["aarch64"],
                "product_names": ["NVIDIA_DGX_Spark"],
                "gpu_name_patterns": ["NVIDIA GB10"],
                "required_labels": ["self-hosted", "Linux", "ARM64", "dgx-spark", "siq-openshell"],
            },
            "suites": [
                {
                    "id": "fixture_suite",
                    "root": "security",
                    "timeout_seconds": 60,
                    "argv": ["python3", "-c", "raise SystemExit(0)"],
                }
            ],
        }
        lock = {
            "schema_version": gate.LOCK_SCHEMA,
            "candidate_id": candidate_id,
            "hardware": {
                "architectures": ["aarch64"],
                "product_names": ["NVIDIA_DGX_Spark"],
            },
            "repositories": {name: {"head": head} for name, head in heads.items()},
        }
        policy_path = root / "deploy/dgx-spark/native-candidate-gate.v1.json"
        lock_path = root / "deploy/dgx-spark/runtime-lock.confidential-candidate.v1.json"
        write_json(policy_path, policy)
        write_json(lock_path, lock)
        common = {
            "candidate_id": candidate_id,
            "batch_id": batch_id,
            "github_sha": github_sha,
            "recorded_at": now(),
        }
        repositories = {
            name: {
                "binding": "locked_baseline_ancestor" if name == "security" else "exact_head",
                "binding_matches": True,
                "clean": True,
                "head": head,
                "locked_head": head,
            }
            for name, head in heads.items()
        }
        platform = {
            "schema_version": gate.PLATFORM_SCHEMA,
            **common,
            "architecture": "aarch64",
            "checks": {
                "architecture": True,
                "gpu": True,
                "github_sha": True,
                "product": True,
                "repositories": True,
                "runner_labels": True,
            },
            "gpu_names": ["NVIDIA GB10"],
            "policy_sha256": gate._sha_bytes(gate._canonical(policy)),
            "product_name": "NVIDIA_DGX_Spark",
            "repositories": repositories,
            "runner_labels": ["ARM64", "Linux", "dgx-spark", "self-hosted", "siq-openshell"],
            "ready": True,
            "secrets_included": False,
        }
        doctor = {
            "schema_version": gate.DOCTOR_SCHEMA,
            **common,
            "levels": {
                "configuration_correct": "pass",
                "candidate_gateway": "pass",
                "identity_match": "pass",
                "data_security": "pass",
                "inference_verified": "pass",
                "promotion_boundary": "pass",
                "live_environment": "pass",
            },
            "candidate_package_ready": True,
            "current_environment_ready": True,
            "active_pool_promoted": False,
            "production_eligible": False,
            "deployment_verified": False,
            "secrets_included": False,
        }
        # Doctor reports do not carry CI batch/GitHub fields. They are removed
        # after sharing the common timestamp/candidate fixture.
        doctor.pop("batch_id")
        doctor.pop("github_sha")
        resource = {
            "schema_version": gate.RESOURCE_SCHEMA,
            "passed": True,
            "operational_ready": True,
            "production_evidence": False,
            "gateway_status": "healthy",
            "payload_column_read": False,
            "summary": {"total": 0},
        }
        paths = types.SimpleNamespace(
            policy=policy_path,
            lock=lock_path,
            platform=root / "platform.json",
            doctor=root / "doctor.json",
            resource=root / "resource.json",
            binding=root / "binding.json",
            receipt=root / "receipt.json",
            final=root / "final.json",
            policy_value=policy,
            lock_value=lock,
            batch_id=batch_id,
            github_sha=github_sha,
        )
        write_json(paths.platform, platform)
        write_json(paths.doctor, doctor)
        write_json(paths.resource, resource)
        binding = {
            "schema_version": gate.RESOURCE_BINDING_SCHEMA,
            **common,
            "audit_sha256": gate.sha256_file(paths.resource),
            "audit_source_age_seconds": 0,
            "bound": True,
            "gateway_status": "healthy",
            "operational_ready": True,
            "payload_column_read": False,
            "secrets_included": False,
        }
        receipt = {
            "schema_version": gate.SUITE_SCHEMA,
            **common,
            "argv_sha256": gate._sha_bytes(gate._canonical(policy["suites"][0]["argv"])),
            "ended_at": now(),
            "executable_sha256": "d" * 64,
            "exit_code": 0,
            "log_sha256": "e" * 64,
            "log_size_bytes": 1,
            "passed": True,
            "repository_clean_after": True,
            "repository_head": github_sha,
            "root": "security",
            "secrets_included": False,
            "started_at": now(),
            "suite_id": "fixture_suite",
            "timed_out": False,
        }
        write_json(paths.binding, binding)
        write_json(paths.receipt, receipt)
        return paths

    def _verify_args(self, fixture: types.SimpleNamespace, receipts: list[Path] | None = None):
        return types.SimpleNamespace(
            policy=fixture.policy,
            lock=fixture.lock,
            batch_id=fixture.batch_id,
            github_sha=fixture.github_sha,
            output=fixture.final,
            platform_report=fixture.platform,
            doctor_report=fixture.doctor,
            resource_report=fixture.resource,
            resource_binding=fixture.binding,
            suite_receipt=[fixture.receipt] if receipts is None else receipts,
        )

    def test_complete_fresh_evidence_passes_without_production_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            self.assertEqual(gate.verify(self._verify_args(fixture)), 0)
            report = gate.load_json(fixture.final)
            self.assertEqual(report["status"], "passed")
            self.assertTrue(report["candidate_verified"])
            self.assertFalse(report["production_eligible"])
            self.assertFalse(report["deployment_verified"])

    def test_missing_suite_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            self.assertEqual(gate.verify(self._verify_args(fixture, [])), 1)
            self.assertIn("suite_receipts_incomplete", gate.load_json(fixture.final)["failure_codes"])

    def test_live_doctor_failure_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            doctor = gate.load_json(fixture.doctor)
            doctor["levels"]["live_environment"] = "fail"
            doctor["current_environment_ready"] = False
            write_json(fixture.doctor, doctor)
            self.assertEqual(gate.verify(self._verify_args(fixture)), 1)
            self.assertIn("candidate_doctor_evidence_invalid", gate.load_json(fixture.final)["failure_codes"])

    def test_resource_governance_without_operational_readiness_cannot_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = self._fixture(Path(directory))
            resource = gate.load_json(fixture.resource)
            resource["operational_ready"] = False
            resource["gateway_status"] = "patch_identity_mismatch"
            write_json(fixture.resource, resource)
            self.assertEqual(gate.verify(self._verify_args(fixture)), 1)
            self.assertIn("resource_evidence_invalid", gate.load_json(fixture.final)["failure_codes"])

    def test_dirty_platform_or_wrong_github_sha_cannot_pass(self):
        for mutation in ("dirty", "github_sha"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                fixture = self._fixture(Path(directory))
                platform_report = gate.load_json(fixture.platform)
                if mutation == "dirty":
                    platform_report["repositories"]["security"]["clean"] = False
                else:
                    platform_report["github_sha"] = "f" * 40
                write_json(fixture.platform, platform_report)
                self.assertEqual(gate.verify(self._verify_args(fixture)), 1)
                self.assertIn("platform_evidence_invalid", gate.load_json(fixture.final)["failure_codes"])

    def test_non_native_hardware_or_missing_runner_label_cannot_pass(self):
        for failed_check in ("architecture", "gpu", "product", "runner_labels"):
            with self.subTest(failed_check=failed_check), tempfile.TemporaryDirectory() as directory:
                fixture = self._fixture(Path(directory))
                platform_report = gate.load_json(fixture.platform)
                platform_report["checks"][failed_check] = False
                platform_report["ready"] = False
                write_json(fixture.platform, platform_report)
                self.assertEqual(gate.verify(self._verify_args(fixture)), 1)
                self.assertIn("platform_evidence_invalid", gate.load_json(fixture.final)["failure_codes"])

    def test_stale_or_candidate_mismatched_suite_cannot_pass(self):
        for mutation in ("stale", "candidate"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                fixture = self._fixture(Path(directory))
                receipt = gate.load_json(fixture.receipt)
                if mutation == "stale":
                    receipt["recorded_at"] = "2000-01-01T00:00:00Z"
                else:
                    receipt["candidate_id"] = "different-candidate"
                write_json(fixture.receipt, receipt)
                self.assertEqual(gate.verify(self._verify_args(fixture)), 1)
                self.assertIn("suite_evidence_invalid", gate.load_json(fixture.final)["failure_codes"])

    def test_unknown_suite_is_rejected_before_execution(self):
        policy = gate.validate_policy(gate.load_json(POLICY_PATH))
        with self.assertRaisesRegex(gate.GateError, "suite_unknown"):
            gate._suite(policy, "operator-supplied-command")

    def test_private_json_requires_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            write_json(path, {"schema_version": "fixture"}, 0o644)
            with self.assertRaisesRegex(gate.GateError, "json_file_invalid"):
                gate.load_json(path, private=True)
            path.chmod(0o600)
            self.assertEqual(gate.load_json(path, private=True)["schema_version"], "fixture")


if __name__ == "__main__":
    unittest.main()
