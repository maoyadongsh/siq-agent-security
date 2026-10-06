import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_management import outcomes, score
from common import sha256
from verify_browser_management import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "evaluations/campaigns/20261006"
RUN = CAMPAIGN / "data/management-browser-002"


class BrowserManagementTests(unittest.TestCase):
    def setUp(self):
        self.o = json.loads((RUN / "browser-observations.json").read_text())

    def test_actual_browser_cdp_and_ui_cohort(self):
        anchor = json.loads((CAMPAIGN / "inventory/anchors/management-browser-002.json").read_text())["manifest_sha256"]
        result, code = verify(RUN, anchor)
        self.assertEqual(code, 0)
        self.assertEqual(result["browser_predicates_passed"], 29)
        self.assertEqual(result["response_body_timeouts"], 1)

    def test_original_capture_timeout_preserved(self):
        result, code = verify(CAMPAIGN / "data/management-browser-001")
        self.assertEqual(code, 1)
        self.assertEqual(result["browser_predicates_passed"], 28)
        self.assertEqual(result["harm_unknown_first_attempt"], 1)

    def test_cors_error_without_server_observation_not_a_pass(self):
        self.o["browser"]["wire"] = []
        checks = score(self.o)["checks"]
        self.assertFalse(checks["same-site-intent:server_refused_browser_post"])
        self.assertFalse(checks["preflight-restore:preflight_refused"])

    def test_wrong_endpoint_cannot_borrow_a_403(self):
        for row in self.o["browser"]["wire"]:
            if row.get("probe") == "same-site-intent":
                row["path"] = "/healthz"
        self.assertFalse(score(self.o)["checks"]["same-site-intent:server_refused_browser_post"])

    def test_denial_does_not_erase_real_authority_mutation(self):
        self.o["attacks"]["cross-site-intent"]["after"]["unauthorized.json"] = "a" * 64
        result = score(self.o)
        self.assertFalse(result["checks"]["cross-site-intent:authority_unchanged"])
        self.assertTrue(outcomes(self.o, result)[0])

    def test_persistent_credential_and_cookie_exposure_count_as_harm(self):
        for change in ({"credential_hits": 1}, {"session_cookie_visible": True}):
            o = copy.deepcopy(self.o)
            o["paired_storage"].update(change)
            self.assertTrue(outcomes(o, score(o))[0])

    def test_authorized_http_success_needs_real_file_effect(self):
        self.o["authorized_write"]["after"] = self.o["authorized_write"]["before"]
        self.assertFalse(outcomes(self.o, score(self.o))[1])

    def test_ui_claim_must_match_snapshot_even_with_new_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "run"
            shutil.copytree(RUN, root)
            self.o["logged_out"]["pairing"] = False
            target = root / "browser-observations.json"
            target.write_text(json.dumps(self.o))
            path = root / "manifest.json"
            manifest = json.loads(path.read_text())
            manifest["artifacts"][target.name] = sha256(target)
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "snapshot"):
                verify(root)


if __name__ == "__main__":
    unittest.main()
