import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = ROOT / "deploy/dgx-spark/candidate_doctor.py"
LOCK_PATH = ROOT / "deploy/dgx-spark/runtime-lock.confidential-candidate.v1.json"
RESEARCH_ROOT = Path("/home/maoyd/siq-research-engine")
HERMES_ROOT = Path("/home/maoyd/siq/hermes-agent")

SPEC = importlib.util.spec_from_file_location("dgx_confidential_candidate_doctor", DOCTOR_PATH)
doctor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = doctor
SPEC.loader.exec_module(doctor)


def locked() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


class CandidateDoctorTest(unittest.TestCase):
    def test_repository_candidate_lock_is_strict_and_valid(self):
        doctor.validate_lock(doctor.load_json(LOCK_PATH))

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":"a","schema_version":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(doctor.CandidateDoctorError, "duplicate_json_key"):
                doctor.load_json(path)

    def test_path_escape_and_remote_or_credentialed_endpoints_are_rejected(self):
        for invalid in ("/etc/passwd", "../secret", "safe/../../secret"):
            with self.subTest(path=invalid):
                payload = locked()
                payload["artifacts"][0]["path"] = invalid
                with self.assertRaisesRegex(doctor.CandidateDoctorError, "lock_relative_path_invalid"):
                    doctor.validate_lock(payload)
        for invalid in (
            "https://127.0.0.1:8006/v1/models",
            "http://remote.example:8006/v1/models",
            "http://user:secret@127.0.0.1:8006/v1/models",
            "http://127.0.0.1:8006/v1/models?token=secret",
        ):
            with self.subTest(url=invalid):
                payload = locked()
                payload["model"]["endpoints"][0]["url"] = invalid
                with self.assertRaisesRegex(doctor.CandidateDoctorError, "candidate_lock_model_invalid"):
                    doctor.validate_lock(payload)

    def test_release_boundary_cannot_claim_active_promotion_or_production(self):
        for field in ("active_pool_promoted", "production_eligible"):
            payload = locked()
            payload["release_state"][field] = True
            with self.subTest(field=field), self.assertRaisesRegex(
                doctor.CandidateDoctorError, "candidate_lock_release_state_invalid"
            ):
                doctor.validate_lock(payload)

    def test_live_environment_failure_does_not_rewrite_package_evidence(self):
        class ControlledDoctor(doctor.CandidateDoctor):
            def check_configuration(self):
                self.add("configuration_correct", "fixture.configuration", True, "fixture")

            def check_gateway(self):
                self.add("candidate_gateway", "fixture.gateway_binary", True, "fixture")
                self.add("live_environment", "fixture.gateway_process", True, "fixture")

            def check_identity(self):
                self.add("identity_match", "fixture.identity", True, "fixture")

            def check_data_security(self):
                self.add("data_security", "fixture.security", True, "fixture")

            def check_inference(self):
                self.add("inference_verified", "fixture.evidence", True, "fixture")
                self.add("live_environment", "fixture.current_model", False, "model_drift")

            def check_promotion_boundary(self):
                self.add("promotion_boundary", "fixture.boundary", True, "fixture")

        report = ControlledDoctor(
            locked(), security_root=ROOT, research_root=RESEARCH_ROOT, hermes_root=HERMES_ROOT
        ).collect()

        self.assertTrue(report["candidate_package_ready"])
        self.assertFalse(report["current_environment_ready"])
        self.assertEqual(report["levels"]["live_environment"], "fail")
        self.assertTrue(doctor.required_levels_pass(report, "promotion_boundary"))
        self.assertFalse(doctor.required_levels_pass(report, "live_environment"))

    def test_security_repository_accepts_locked_baseline_ancestor(self):
        checker = doctor.CandidateDoctor(
            locked(), security_root=ROOT, research_root=RESEARCH_ROOT, hermes_root=HERMES_ROOT
        )
        checker.check_configuration()
        repository_check = next(item for item in checker.checks if item.name == "repository.security.head")
        self.assertEqual(repository_check.status, "pass")
        self.assertEqual(repository_check.reason, "locked_baseline_ancestor")

    def test_security_repository_rejects_unrelated_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "fixture@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Fixture"], check=True)
            (root / "fixture").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "fixture"], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
            checker = doctor.CandidateDoctor(
                locked(), security_root=root, research_root=RESEARCH_ROOT, hermes_root=HERMES_ROOT
            )
            checker.check_configuration()
            repository_check = next(item for item in checker.checks if item.name == "repository.security.head")
            self.assertEqual(repository_check.status, "fail")
            self.assertEqual(repository_check.reason, "locked_baseline_not_ancestor")

    def test_candidate_equal_to_active_runtime_fails_separation_boundary(self):
        checker = doctor.CandidateDoctor(
            locked(), security_root=ROOT, research_root=RESEARCH_ROOT, hermes_root=HERMES_ROOT
        )
        manifest = checker.artifact_json("profile_manifest")
        assert manifest is not None
        mutated = copy.deepcopy(manifest)
        mutated["comparisons"]["active_runtime_equals_candidate_image"] = True
        mutated["active_runtime"]["image_id"] = mutated["image"]["image_id"]
        checker.artifact_json = lambda artifact_id: mutated if artifact_id == "profile_manifest" else None

        checker.check_promotion_boundary()

        self.assertEqual(checker.checks[0].status, "fail")
        self.assertEqual(checker.checks[0].reason, "candidate_and_active_state_ambiguous")

    def test_source_baseline_and_compatibility_patch_are_required(self):
        for artifact_id in ("candidate_source_baseline", "hermes_auth_compatibility_patch"):
            payload = locked()
            payload["artifacts"] = [item for item in payload["artifacts"] if item["id"] != artifact_id]
            with self.subTest(artifact_id=artifact_id), self.assertRaisesRegex(
                doctor.CandidateDoctorError, "candidate_lock_artifacts_invalid"
            ):
                doctor.validate_lock(payload)

    def test_aiohttp_compatibility_probe_uses_hardened_container(self):
        checker = doctor.CandidateDoctor(
            locked(), security_root=ROOT, research_root=RESEARCH_ROOT, hermes_root=HERMES_ROOT
        )
        with mock.patch.object(
            doctor,
            "run_command",
            return_value=(0, "aiohttp_optional_request_key_compat=true"),
        ) as command:
            checker.check_aiohttp_image_compatibility()

        arguments = command.call_args.args[0]
        self.assertEqual(arguments[:2], ["docker", "run"])
        self.assertIn("--network", arguments)
        self.assertIn("none", arguments)
        self.assertIn("--read-only", arguments)
        self.assertIn("--cap-drop", arguments)
        self.assertIn("ALL", arguments)
        self.assertIn("no-new-privileges", arguments)
        self.assertIn("--user", arguments)
        self.assertIn("sandbox", arguments)
        self.assertEqual(checker.checks[-1].status, "pass")

    def test_aiohttp_compatibility_probe_failure_is_not_accepted(self):
        checker = doctor.CandidateDoctor(
            locked(), security_root=ROOT, research_root=RESEARCH_ROOT, hermes_root=HERMES_ROOT
        )
        with mock.patch.object(doctor, "run_command", return_value=(1, "")):
            checker.check_aiohttp_image_compatibility()

        self.assertEqual(checker.checks[-1].status, "fail")
        self.assertEqual(checker.checks[-1].reason, "locked_image_aiohttp_compatibility_failed")


if __name__ == "__main__":
    unittest.main()
