"""Exercise the operator HTTP boundary with actual SIQ and fixture effects."""

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from secure_agent.authority import LocalDaemon
from secure_agent.contracts import canonical, strict_json
from secure_agent.fixtures import FixtureServices
from secure_agent.models import OrnithProvider
from secure_agent.service import API, DemoService

ROOT = Path(__file__).resolve().parents[3]


class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="siq-demo-service-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        cls.binary = cls.root / "siq-agent-security"
        subprocess.run(["go", "build", "-o", str(cls.binary), "./cmd/agentshield"],
                       cwd=ROOT / "apps/agentshield", check=True, capture_output=True)

    def setUp(self):
        self.daemon = self.enterContext(LocalDaemon(self.binary, self.root / self._testMethodName))
        self.fixtures = self.enterContext(FixtureServices(ROOT / "demo/fixtures"))
        self.service = self.enterContext(DemoService(ROOT, self.daemon, self.fixtures, mode="test"))
        self.http = build_opener(ProxyHandler({}))

    def request(self, path, body=None, *, headers=None, authenticated=True):
        values = {"Content-Type": "application/json", "X-SIQ-Demo": "1"}
        if authenticated:
            values["Authorization"] = "Bearer " + self.service.token
        values.update(headers or {})
        request = Request(self.service.endpoint + path, data=None if body is None else canonical(body), headers=values)
        try:
            response = self.http.open(request, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, strict_json(response.read()), response.headers

    def wait_task(self, identity):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            status, task, _ = self.request(API + "/tasks/" + identity)
            self.assertEqual(status, 200)
            if task["phase"] in ("finished", "failed"):
                return task
            time.sleep(0.02)
        self.fail("application task did not finish")

    def test_pairing_is_single_use_cookie_is_private_and_origin_is_enforced(self):
        self.assertEqual(self.request(API + "/tasks", authenticated=False)[0], 401)
        code = self.service.pairing_code
        status, body, headers = self.request(API + "/pair", {"code": code}, authenticated=False)
        self.assertEqual((status, body), (200, {"status": "paired"}))
        cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertEqual(self.request(API + "/tasks", headers={"Cookie": cookie.split(";")[0]}, authenticated=False)[0], 200)
        self.assertEqual(self.request(API + "/pair", {"code": code}, authenticated=False)[0], 401)
        for headers in ({"Origin": "https://attacker.example"}, {"Host": "attacker.example"}, {"X-SIQ-Demo": ""}):
            self.assertEqual(self.request(API + "/tasks", {"scenario": "normal", "prompt": "review"}, headers=headers)[0], 403)
        self.assertEqual(self.request(API + "/tasks", headers={"Host": "attacker.example"})[0], 403)
        self.assertFalse(self.fixtures.messages())

    def test_http_task_has_real_effects_idempotency_and_no_authority_credential(self):
        request_id = uuid4().hex
        body = {"scenario": "normal", "prompt": "Review the repository and deliver to Alice"}
        status, accepted, _ = self.request(API + "/tasks", body, headers={"Idempotency-Key": request_id})
        self.assertEqual(status, 202)
        self.assertEqual(self.request(API + "/tasks", body, headers={"Idempotency-Key": request_id})[1], accepted)
        changed = {**body, "scenario": "fake-success"}
        self.assertEqual(self.request(API + "/tasks", changed, headers={"Idempotency-Key": request_id})[0], 409)
        task = self.wait_task(accepted["id"])
        self.assertEqual(task["task"]["status"], "verified")
        self.assertEqual(task["provider"], "fixture")
        self.assertEqual(len(self.fixtures.messages()), 1)
        self.assertEqual(len(task["result"]["messages"]), 1)
        self.assertTrue(task["intent"]["digest"])
        public = canonical(self.request(API + "/tasks")[1]).decode()
        for secret in (self.service.token, self.daemon.admin._token, self.daemon.decision._token):
            self.assertNotIn(secret, public)
        self.assertTrue(self.daemon.admin.request("/v1/receipts")["verified"])

    def test_pairing_renewal_requires_operator_and_preserves_task_history(self):
        status, accepted, _ = self.request(API + "/tasks", {"scenario": "normal", "prompt": "Review and deliver"},
            headers={"Idempotency-Key": uuid4().hex})
        self.assertEqual(status, 202)
        original = self.wait_task(accepted["id"])
        old_code, old_token = self.service.pairing_code, self.service.token
        self.service._pairing_expires = time.monotonic() - 1
        self.assertEqual(self.request(API + "/pair", {"code": old_code}, authenticated=False)[0], 401)
        self.assertEqual(self.request(API + "/pairing/renew", {}, authenticated=False)[0], 401)
        self.assertEqual(self.request(API + "/pairing/renew", {"expires_in": 999999})[0], 400)
        self.assertEqual(self.request(API + "/pairing/renew", {}, headers={"Origin": "https://attacker.example"})[0], 403)
        status, renewed, _ = self.request(API + "/pairing/renew", {})
        self.assertEqual(status, 200)
        self.assertEqual(renewed["expires_in"], 300)
        self.assertNotEqual(renewed["pairing_code"], old_code)
        self.assertEqual(self.service.token, old_token)
        self.assertEqual(self.request(API + "/pair", {"code": old_code}, authenticated=False)[0], 401)
        self.assertEqual(self.request(API + "/pair", {"code": renewed["pairing_code"]}, authenticated=False)[0], 200)
        self.assertEqual(self.request(API + "/pair", {"code": renewed["pairing_code"]}, authenticated=False)[0], 401)
        self.assertEqual(self.request(API + "/tasks/" + accepted["id"])[1], original)
        public = canonical(self.request(API + "/tasks")[1]).decode()
        self.assertNotIn(renewed["pairing_code"], public)
        self.assertNotIn(old_token, public)

    def test_sequential_tasks_keep_authority_and_effects_separate(self):
        grant_ids = set()
        for scenario, expected, count in (("normal", "verified", 1), ("mcp-attack", "blocked", 0),
                                           ("fake-success", "incomplete", 0)):
            with self.subTest(scenario=scenario):
                status, accepted, _ = self.request(API + "/tasks", {"scenario": scenario, "prompt": "Review and deliver"},
                    headers={"Idempotency-Key": uuid4().hex})
                self.assertEqual(status, 202)
                task = self.wait_task(accepted["id"])
                self.assertEqual(task["phase"], "finished", task["error_code"])
                self.assertEqual(task["task"]["status"], expected)
                self.assertEqual(len(task["result"]["messages"]), count)
                grant_ids.add(task["result"]["grant"]["grant_id"])
        self.assertEqual(len(grant_ids), 3)
        self.assertEqual(len(self.fixtures.messages()), 1)
        self.assertTrue(self.daemon.admin.request("/v1/receipts")["verified"])

    def test_failed_model_planning_keeps_only_current_task_diagnostics(self):
        # Real HTTP provider transport and SIQ task initialization; malformed
        # content is controlled test data, not a claim about real ornith quality.
        from http.server import ThreadingHTTPServer
        from threading import Thread

        import test_models

        server = ThreadingHTTPServer(("127.0.0.1", 0), test_models.ProviderServer)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        server.requests, server.redirect, server.raw_response = [], None, None
        server.content = '{"goal":"private-model-output","goal":"duplicate","skills":[]}'
        server.finish_reason, server.usage = "stop", {"total_tokens": 19}
        self.service.mode = "demo"
        self.service.model = OrnithProvider(f"http://127.0.0.1:{server.server_port}/v1", "test-model")
        self.service.provider = "ornith"
        for _ in range(2):
            status, accepted, _ = self.request(API + "/tasks", {"scenario": "normal", "prompt": "Review and deliver"},
                headers={"Idempotency-Key": uuid4().hex})
            self.assertEqual(status, 202)
            task = self.wait_task(accepted["id"])
            self.assertEqual(task["phase"], "failed")
            self.assertEqual(task["error_code"], "json_duplicate_key")
            self.assertEqual(task["task"]["actions"], [])
            call, = task["model_calls"]
            self.assertEqual((call["status"], call["operation"], call["usage"]), ("failed", "plan", {"total_tokens": 19}))
            self.assertNotIn("private-model-output", canonical(task).decode())
        self.assertEqual(len(server.requests), 2)
        self.assertFalse(self.fixtures.messages())

    def test_unknown_scenarios_authority_fields_and_path_reads_are_rejected(self):
        for body in ({"scenario": "shell", "prompt": "review"},
                     {"scenario": "normal", "prompt": "review", "grant": "forged"},
                     {"scenario": "normal", "prompt": "review", "scope": ["/etc/passwd"]}):
            self.assertEqual(self.request(API + "/tasks", body, headers={"Idempotency-Key": uuid4().hex})[0], 400)
        for path in ("/service.json", "/../service.json", "/assets/../../service.json"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertFalse(self.fixtures.messages())

    def test_preparation_failure_is_terminal_in_published_task_state(self):
        self.service.scope = ("missing.py",)
        status, accepted, _ = self.request(API + "/tasks", {"scenario": "normal", "prompt": "Review"},
                                          headers={"Idempotency-Key": uuid4().hex})
        self.assertEqual(status, 202)
        task = self.wait_task(accepted["id"])
        self.assertEqual(task["phase"], "failed")
        self.assertEqual(task["task"]["status"], "failed")
        self.assertEqual(task["error_code"], "tool_http_failed")
        self.assertFalse(self.fixtures.messages())

    def test_human_http_approval_resumes_original_task_and_real_process(self):
        status, accepted, _ = self.request(API + "/tasks", {"scenario": "approval", "prompt": "Review with human-approved report verification"},
                                          headers={"Idempotency-Key": uuid4().hex})
        self.assertEqual(status, 202)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            _, task, _ = self.request(API + "/tasks/" + accepted["id"])
            if task.get("approval") and task["task"]["status"] == "waiting_approval":
                break
            time.sleep(0.02)
        else:
            self.fail(str(task))
        held = task["task"]["actions"][-1]
        self.assertEqual(held["tool"], "verify_report")
        self.assertEqual(held["decision"], "hold")
        self.assertFalse(held["d3_materialized"])
        self.assertFalse(self.fixtures.messages())
        route = API + "/tasks/" + accepted["id"] + "/approval"
        body = {"action_id": held["action_id"], "approve": True}
        self.assertEqual(self.request(route, body, authenticated=False)[0], 401)
        self.assertEqual(self.request(route, {**body, "action_id": "other"})[0], 400)
        self.assertEqual(self.request(route, {**body, "params": {"path": "/replaced"}})[0], 400)
        self.assertEqual(self.request(route, body)[0], 200)
        result = self.wait_task(accepted["id"])
        self.assertEqual(result["task"]["status"], "verified", result)
        process = next(a for a in result["task"]["actions"] if a["tool"] == "verify_report")
        self.assertEqual(process["action_id"], held["action_id"])
        self.assertEqual(process["approval_status"], "approved")
        self.assertTrue(process["d3_materialized"])
        self.assertGreater(process["reported_process"]["process_id"], 0)
        self.assertEqual(process["reported_process"]["digest"], result["result"]["report"]["digest"])
        self.assertIsNone(process["effect"])
        self.assertEqual(len(self.fixtures.messages()), 1)


if __name__ == "__main__":
    unittest.main()
