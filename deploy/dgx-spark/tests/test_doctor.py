import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCTOR_PATH = ROOT / "deploy/dgx-spark/doctor.py"
LOCK_PATH = ROOT / "deploy/dgx-spark/runtime-lock.v1.json"

SPEC = importlib.util.spec_from_file_location("dgx_flagship_doctor", DOCTOR_PATH)
doctor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = doctor
SPEC.loader.exec_module(doctor)


def locked() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DoctorTest(unittest.TestCase):
    def test_repository_runtime_lock_is_strict_and_valid(self):
        doctor.validate_lock(doctor.load_json(LOCK_PATH))

    def test_duplicate_json_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"schema_version":"a","schema_version":"b"}\n', encoding="utf-8")
            with self.assertRaisesRegex(doctor.DoctorError, "duplicate_json_key"):
                doctor.load_json(path)

    def test_absolute_or_parent_artifact_path_is_rejected(self):
        for invalid in ("/etc/passwd", "../secret", "safe/../../secret"):
            with self.subTest(invalid=invalid):
                payload = locked()
                payload["artifacts"][0]["path"] = invalid
                with self.assertRaisesRegex(doctor.DoctorError, "lock_relative_path_invalid"):
                    doctor.validate_lock(payload)

    def test_remote_and_credentialed_probe_targets_are_rejected(self):
        for url in (
            "http://remote.example/v1/models",
            "https://127.0.0.1/v1/models",
            "http://user:secret@127.0.0.1/v1/models",
            "http://127.0.0.1/v1/models?secret=value",
            "http://127.0.0.1:invalid/v1/models",
        ):
            with self.subTest(url=url):
                self.assertEqual(doctor.http_json(url), (None, None))

    def test_drifted_openshell_binary_is_not_executed(self):
        payload = locked()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            for name in ("openshell", "openshell-gateway"):
                binary = root / "var/openshell/toolchains/v0.0.83/bin" / name
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
                binary.chmod(0o755)
            instance = doctor.Doctor(
                payload,
                security_root=root,
                research_root=root,
                hermes_root=root,
                offline=True,
            )
            instance.check_openshell_binaries()
            self.assertFalse(marker.exists())
            version_checks = [item for item in instance.checks if item.name.endswith(".version")]
            self.assertEqual([item.reason for item in version_checks], [
                "binary_digest_mismatch_not_executed",
                "binary_digest_mismatch_not_executed",
            ])

    def test_artifact_drift_is_explicit_failure(self):
        payload = locked()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "candidate.bin"
            artifact.write_bytes(b"changed")
            required = [
                item
                for item in payload["artifacts"]
                if item["id"] in {"openshell_cli", "openshell_gateway"}
            ]
            payload["artifacts"] = required + [
                {
                    "id": "candidate",
                    "root": "security",
                    "path": "candidate.bin",
                    "sha256": hashlib.sha256(b"locked").hexdigest(),
                    "drift_sensitive": True,
                }
            ]
            instance = doctor.Doctor(
                payload,
                security_root=root,
                research_root=root,
                hermes_root=root,
                offline=True,
            )
            instance.check_artifacts()
            result = next(item for item in instance.checks if item.name == "artifact.candidate")
            self.assertEqual(result.status, "fail")
            self.assertEqual(result.reason, "drift_detected")
            self.assertEqual(result.observed, hashlib.sha256(b"changed").hexdigest())

    def test_security_inference_and_business_evidence_remain_separate(self):
        payload = locked()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            routing = root / "routing.json"
            validations = {f"V{index:02d}": "passed" for index in range(1, 19)}
            manifest.write_text(
                json.dumps(
                    {
                        "validation": validations,
                        "business_evidence": {
                            "full_report": {"status": "passed"},
                            "missing_evidence": {"status": "passed_after_one_retry"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            routing.write_text(
                json.dumps(
                    {
                        "route_target": "openshell",
                        "route_base": payload["runtime"]["route_base"],
                        "pool_run_id": payload["runtime"]["run_id"],
                        "terminal_status": "completed",
                        "output_exact_match": True,
                        "secrets_included": False,
                    }
                ),
                encoding="utf-8",
            )
            payload["evidence"] = {
                "upgrade_manifest": {
                    "root": "security",
                    "path": manifest.name,
                    "sha256": digest(manifest),
                },
                "routing_validation": {
                    "root": "security",
                    "path": routing.name,
                    "sha256": digest(routing),
                },
            }
            instance = doctor.Doctor(
                payload,
                security_root=root,
                research_root=root,
                hermes_root=root,
                offline=True,
            )
            instance.check_evidence()
            self.assertEqual(
                [(item.level, item.status) for item in instance.checks],
                [
                    ("security_behavior", "pass"),
                    ("inference_verified", "pass"),
                    ("business_completed", "pass"),
                ],
            )

    def test_changed_routing_evidence_does_not_inherit_locked_success(self):
        payload = locked()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("manifest.json", "routing.json"):
                (root / name).write_text("{}\n", encoding="utf-8")
            payload["evidence"] = {
                "upgrade_manifest": {
                    "root": "security",
                    "path": "manifest.json",
                    "sha256": hashlib.sha256(b"different").hexdigest(),
                },
                "routing_validation": {
                    "root": "security",
                    "path": "routing.json",
                    "sha256": hashlib.sha256(b"different").hexdigest(),
                },
            }
            instance = doctor.Doctor(
                payload,
                security_root=root,
                research_root=root,
                hermes_root=root,
                offline=True,
            )
            instance.check_evidence()
            self.assertTrue(all(item.status == "fail" for item in instance.checks))

    def test_required_level_is_cumulative(self):
        report = {"levels": {level: "pass" for level in doctor.LEVELS}}
        self.assertTrue(doctor.required_levels_pass(report, "business_completed"))
        report = copy.deepcopy(report)
        report["levels"]["identity_match"] = "fail"
        self.assertFalse(doctor.required_levels_pass(report, "security_behavior"))
        self.assertFalse(doctor.required_levels_pass(report, "business_completed"))


if __name__ == "__main__":
    unittest.main()
