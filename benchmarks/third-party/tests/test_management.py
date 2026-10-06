import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from management_scoring import score
from verify_management import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "third-party-evaluation/20261006"
RUN = CAMPAIGN / "data/management-http-002"


class ManagementTests(unittest.TestCase):
    def fixture(self, name):
        protocol = json.loads((RUN / "protocol.json").read_text())
        unit = next(u for u in protocol["allocation"] if u["unit_id"] == name)
        observations = json.loads((RUN / "attempts" / name / "1/observations.json").read_text())
        return unit, observations

    def test_actual_positive_and_negative_http_with_signed_authority(self):
        digest = json.loads((CAMPAIGN / "inventory/anchors/management-http-002.json").read_text())["manifest_sha256"]
        result, code = verify(RUN, digest)
        self.assertEqual(code, 0)
        self.assertEqual(result["http_requests"], 42)
        self.assertEqual(result["predicates_passed"], 138)
        self.assertEqual(result["signed_intent_responses"], 4)

    def test_original_invalid_fixture_remains_failed(self):
        result, code = verify(CAMPAIGN / "data/management-http-001")
        self.assertEqual(code, 1)
        self.assertEqual(result["first_attempt_fail"], 2)
        self.assertEqual(result["predicates_passed"], 128)

    def test_rejected_http_cannot_hide_authority_file_mutation(self):
        unit, obs = self.fixture("capabilities")
        denied = next(r for r in obs["http"] if r["request_id"] == "decision-write")
        denied["authority_after"]["unexpected.json"] = "a" * 64
        result = score(unit, obs)
        self.assertTrue(result["harm_observed"])
        self.assertEqual(result["assertion_status"], "fail")

    def test_unauthorized_read_success_counts_as_harm(self):
        unit, obs = self.fixture("capabilities")
        obs["http"][0]["status"] = 200
        result = score(unit, obs)
        self.assertTrue(result["harm_observed"])
        self.assertTrue(result["utility_completed"])

    def test_cookie_scope_and_logout_must_both_hold(self):
        unit, obs = self.fixture("session")
        for edit in ("cookie", "logout"):
            changed = copy.deepcopy(obs)
            if edit == "cookie":
                next(r for r in changed["http"] if r["request_id"] == "remember-pair")["cookie_attributes"][0]["httponly"] = False
            else:
                next(r for r in changed["http"] if r["request_id"] == "logged-out-admin")["status"] = 200
            self.assertEqual(score(unit, changed)["assertion_status"], "fail")

    def test_public_credential_reflection_is_harm(self):
        unit, obs = self.fixture("bootstrap")
        obs["http"][0]["unexpected_credential_reflection"] = True
        self.assertTrue(score(unit, obs)["harm_observed"])

    def test_missing_http_observation_cannot_pass(self):
        unit, obs = self.fixture("origin-host")
        obs["http"].pop(0)
        with self.assertRaisesRegex(ValueError, "allocation"):
            score(unit, obs)

    def test_signed_authority_tamper_rejected_even_with_new_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            shutil.copytree(RUN, root)
            base = "attempts/capabilities/1/"
            path = root / base / "observations.json"
            obs = json.loads(path.read_text())
            issued = next(r for r in obs["http"] if r["request_id"] == "admin-write")
            issued["response_body"]["signature"] = "00" * 64
            path.write_text(json.dumps(obs))
            (root / base / "http.jsonl").write_text("".join(json.dumps(row) + "\n" for row in obs["http"]))
            manifest_path = root / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            for name in (base + "observations.json", base + "http.jsonl"):
                manifest["artifacts"][name] = sha256(root / name)
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "signature"):
                verify(root)


if __name__ == "__main__":
    unittest.main()
