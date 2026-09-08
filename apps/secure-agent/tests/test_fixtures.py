import importlib.util
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from secure_agent.contracts import canonical, strict_json
from secure_agent.fixtures import FixtureServices

ROOT = Path(__file__).resolve().parents[3]


class FixturesTest(unittest.TestCase):
    def test_uncredentialed_message_write_fails_and_public_health_is_read_only(self):
        with FixtureServices(ROOT / "demo/fixtures") as service:
            http = build_opener(ProxyHandler({}))
            with http.open(service.endpoint + "/health", timeout=2) as response:
                self.assertEqual(strict_json(response.read()), {"service": "siq-hackathon-fixtures", "status": "ready"})
            with self.assertRaises(HTTPError) as failure:
                http.open(Request(service.endpoint + "/messages/unknown", data=canonical({"body": "report"})), timeout=2)
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()
            self.assertFalse(service.messages())

    def test_forged_host_cannot_reach_fixture_with_valid_credential(self):
        with FixtureServices(ROOT / "demo/fixtures") as service:
            headers = {**service.headers(), "Host": "attacker.example"}
            with self.assertRaises(HTTPError) as failure:
                build_opener(ProxyHandler({})).open(Request(service.endpoint + "/messages", headers=headers), timeout=2)
            self.assertEqual(failure.exception.code, 403)
            failure.exception.close()

    def test_preflight_recognizes_fixture_and_rejects_wrong_service_contract(self):
        spec = importlib.util.spec_from_file_location("dgx_preflight", ROOT / "deploy/dgx-spark/preflight.py")
        preflight = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(preflight)
        with FixtureServices(ROOT / "demo/fixtures") as service:
            self.assertEqual(preflight.probe(service.endpoint, "/health", service="fixtures")["status"], "reachable")
            self.assertEqual(preflight.probe(service.endpoint, "/health", service="siq")["status"], "service_contract_invalid")
        self.assertEqual(preflight.probe(None, "/models")["status"], "unconfigured")
        self.assertEqual(preflight.probe("http://remote.example", "/models")["status"], "invalid_endpoint")
        self.assertEqual(preflight.probe("https://user:secret@remote.example", "/models")["status"], "invalid_endpoint")


if __name__ == "__main__":
    unittest.main()
