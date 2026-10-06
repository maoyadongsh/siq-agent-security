import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import sha256
from verify_openshell_fixture import verify

CAMPAIGN = Path(__file__).resolve().parents[3] / "third-party-evaluation/20261006"
SOURCE = CAMPAIGN / "data/openshell-preflight-003"
ANCHOR = "dba390418da00ff29586440f5054edb5cdf08d1a4d187e7cbc0482539946c16f"


class OpenShellFixtureTests(unittest.TestCase):
    def test_positive_preserves_environment_only_scope(self):
        result = verify(SOURCE, ANCHOR)
        self.assertTrue(result["preflight_passed"])
        self.assertTrue(result["cleanup_confirmed"])
        self.assertFalse(result["product_deployment_tested"])

    def test_initial_create_failure_preserved(self):
        result = verify(CAMPAIGN / "data/openshell-preflight-001",
                        "f602899db05704d052eebe1953cd3c517d1b5938e847b47acb1e5b48c13b73ea")
        self.assertTrue(result["integrity_verified"])
        self.assertFalse(result["preflight_passed"])

    def test_resealed_scope_inflation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "copy"
            shutil.copytree(SOURCE, target)
            result = json.loads((target / "result.json").read_text())
            result["product_deployment_tested"] = True
            (target / "result.json").write_text(json.dumps(result))
            manifest = json.loads((target / "manifest.json").read_text())
            manifest["artifacts"]["result.json"] = sha256(target / "result.json")
            (target / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "scope inflated"):
                verify(target, sha256(target / "manifest.json"))


if __name__ == "__main__":
    unittest.main()
