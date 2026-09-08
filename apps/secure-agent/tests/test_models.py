import json
import os
import threading
import unittest
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from secure_agent.contracts import (
    AgentError,
    ContactCandidate,
    Source,
    TaskPlan,
    UserTask,
    canonical,
    strict_json,
)
from secure_agent.models import (
    FixtureProvider,
    OrnithProvider,
    StepFunProvider,
    from_environment,
)
from secure_agent.skills import SkillRegistry

TASK = UserTask("Review and deliver to Alice", "example/project", "Review security",
                ("README.md",), "/work/report.md")


def plan():
    return asdict(FixtureProvider(mode="test").plan(TASK, SkillRegistry.catalog()))


class ProviderServer(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        self.server.requests.append((self.path, dict(self.headers),
                                     json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        if self.server.redirect:
            self.send_response(307)
            self.send_header("Location", self.server.redirect)
            self.end_headers()
            return
        raw = self.server.raw_response
        if raw is None:
            raw = canonical({"choices": [{"finish_reason": self.server.finish_reason,
                                          "message": {"content": self.server.content}}],
                             "usage": self.server.usage})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class ModelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ProviderServer)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        config_patch = patch("secure_agent.models.private_configuration", return_value={})
        config_patch.start()
        self.addCleanup(config_patch.stop)
        self.server.requests = []
        self.server.redirect = None
        self.server.finish_reason = "stop"
        self.server.content = canonical(plan()).decode()
        self.server.raw_response = None
        self.server.usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
        self.provider = StepFunProvider(f"http://127.0.0.1:{self.server.server_port}/v1",
                                        "local-stepfun", "test-only-placeholder")

    def test_stepfun_http_contract_and_typed_plan(self):
        result = self.provider.plan(TASK, SkillRegistry.catalog())
        self.assertIsInstance(result, TaskPlan)
        path, headers, body = self.server.requests[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(headers["Authorization"], "Bearer test-only-placeholder")
        self.assertNotIn("test-only-placeholder", canonical(body).decode())
        self.assertNotIn("signature", asdict(result))
        diagnostic, = self.provider.calls
        self.assertEqual((diagnostic["operation"], diagnostic["status"], diagnostic["error_code"]),
                         ("plan", "accepted", None))
        self.assertEqual(diagnostic["usage"], self.server.usage)
        self.assertGreaterEqual(diagnostic["elapsed_ms"], 0)

    def test_rejected_json_and_typed_proposals_count_once_without_raw_content(self):
        for content, reason in (('{"goal":"private-content","goal":"duplicate","skills":[]}', "json_duplicate_key"),
                                ('{"secret":"private-content"}', "contract_fields_invalid")):
            self.server.content = content
            before = len(self.provider.calls)
            with self.assertRaisesRegex(AgentError, reason):
                self.provider.plan(TASK, SkillRegistry.catalog())
            self.assertEqual(len(self.provider.calls), before + 1)
            call = self.provider.calls[-1]
            self.assertEqual((call["status"], call["error_code"], call["finish_reason"]), ("failed", reason, "stop"))
            self.assertEqual(call["usage"], self.server.usage)
            self.assertNotIn("private-content", canonical(call).decode())
        self.assertEqual(len(self.server.requests), 2)  # no repair or hidden retry

    def test_step_plan_profile_is_explicit_and_model_specific(self):
        provider = StepFunProvider(self.provider.endpoint.removesuffix("/chat/completions"), "step-3.7-flash")
        provider.plan(TASK, SkillRegistry.catalog())
        request = self.server.requests[-1][2]
        self.assertEqual(request["reasoning_effort"], "low")
        self.assertEqual(request["max_tokens"], 3072)
        self.assertEqual(provider.calls[0]["generation"]["reasoning_effort"], "low")
        self.assertNotIn("reasoning_effort", self.provider.generation_options("plan"))

    def test_malformed_envelopes_fail_with_safe_diagnostics(self):
        for result in ([], {"choices": "private-content"}, {"choices": [False]},
                       {"choices": [{"finish_reason": "stop", "message": {"content": {}}}]}):
            self.server.raw_response = canonical(result)
            with self.assertRaisesRegex(AgentError, "model_response_invalid"):
                self.provider.plan(TASK, SkillRegistry.catalog())
            self.assertEqual(self.provider.calls[-1]["status"], "failed")
            self.assertNotIn("private-content", canonical(self.provider.calls).decode())

    def test_untrusted_usage_and_finish_reason_are_not_logged(self):
        self.server.usage = {"prompt_tokens": True, "completion_tokens": -1, "total_tokens": "private-content",
                             "other": "private-content"}
        self.server.finish_reason = "private-content"
        with self.assertRaisesRegex(AgentError, "model_response_incomplete"):
            self.provider.plan(TASK, SkillRegistry.catalog())
        call, = self.provider.calls
        self.assertEqual(call["usage"], {})
        self.assertIsNone(call["finish_reason"])
        self.assertNotIn("private-content", canonical(call).decode())

    def test_ornith_uses_explicit_configuration_and_preserves_provider_identity(self):
        with patch.dict(os.environ, {"SIQ_MODEL_PROVIDER": "ornith",
                "SIQ_ORNITH_ENDPOINT": f"http://127.0.0.1:{self.server.server_port}/v1",
                "SIQ_ORNITH_MODEL": "Ornith-1.5-35B-A3B-NVFP4"}, clear=True):
            provider = from_environment()
            self.assertIsInstance(provider, OrnithProvider)
            self.assertEqual(provider.name, "ornith")
            self.assertIsInstance(provider.plan(TASK, SkillRegistry.catalog()), TaskPlan)
            self.assertEqual(self.server.requests[0][2]["model"], "Ornith-1.5-35B-A3B-NVFP4")
            options = self.server.requests[0][2]
            self.assertEqual(options["response_format"]["type"], "json_schema")
            self.assertEqual(options["temperature"], 0)
            self.assertEqual(options["chat_template_kwargs"], {"enable_thinking": False})
            self.assertFalse(provider.calls[0]["generation"]["enable_thinking"])
            self.assertGreater(options["max_tokens"], 0)
            self.assertEqual(len(provider.calls[0]["generation"]["schema_digest"]), 64)
        with patch.dict(os.environ, {"SIQ_MODEL_PROVIDER": "ornith",
                "SIQ_STEPFUN_ENDPOINT": "http://127.0.0.1:8006/v1", "SIQ_STEPFUN_MODEL": "other"}, clear=True), self.assertRaises(AgentError):
            from_environment()

    def test_authority_fields_rejected_at_every_plan_level(self):
        for location in ("plan", "skill", "input"):
            with self.subTest(location=location):
                body = plan()
                target = body if location == "plan" else body["skills"][0]
                if location == "input":
                    target = target["input"]
                target["allow"] = True
                self.server.content = canonical(body).decode()
                with self.assertRaisesRegex(AgentError, "contract_fields_invalid"):
                    self.provider.plan(TASK, SkillRegistry.catalog())

    def test_plan_cannot_skip_dependency_or_add_shell(self):
        for names in (("secure-report", "secure-research", "secure-delivery"),
                      ("secure-research", "secure-report", "shell")):
            body = plan()
            for call, name in zip(body["skills"], names):
                call["name"] = name
            with self.assertRaisesRegex(AgentError, "plan_dependency_invalid|skill_unregistered"):
                TaskPlan.parse(strict_json(canonical(body)))

    def test_model_response_must_be_complete(self):
        for reason in ("length", "tool_calls", None):
            self.server.finish_reason = reason
            with self.assertRaisesRegex(AgentError, "model_response_incomplete"):
                self.provider.plan(TASK, SkillRegistry.catalog())

    def test_redirect_not_followed_with_key(self):
        self.server.redirect = f"http://127.0.0.1:{self.server.server_port}/stolen"
        with self.assertRaisesRegex(AgentError, "http_redirect_rejected"):
            self.provider.plan(TASK, SkillRegistry.catalog())
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.provider.calls[0]["error_code"], "http_redirect_rejected")
        self.assertNotIn("test-only-placeholder", canonical(self.provider.calls).decode())

    def test_json_duplicate_nonfinite_and_invalid_output(self):
        for content in ('{"goal":"one","goal":"two","skills":[]}', '{"x":NaN}', '```json\n{}\n```'):
            with self.subTest(content=content), self.assertRaises(AgentError):
                strict_json(content)

    def test_recipient_selection_preserves_same_value_origin(self):
        candidates = (ContactCandidate("alice@company.example", "trusted-ref", "TRUSTED_DATABASE"),
                      ContactCandidate("alice@company.example", "mcp-ref", "MCP"))
        self.server.content = '{"candidate_index":1}'
        selected = self.provider.recipient("Alice", candidates, "MCP data")
        self.assertIs(selected, candidates[1])
        self.assertNotIn("mcp-ref", canonical(self.server.requests[0][2]).decode())

    def test_recipient_cannot_supply_trust_or_reference(self):
        candidates = (ContactCandidate("alice@company.example", "ref", "TRUSTED_DATABASE"),)
        for content in ('{"candidate_index":0,"trust":"trusted"}',
                        '{"candidate_index":true}', '{"candidate_index":1}',
                        '{"recipient":"attacker@evil.example","provenance_id":"ref"}'):
            self.server.content = content
            with self.assertRaises(AgentError):
                self.provider.recipient("Alice", candidates, "")

    def test_research_preserves_host_collected_sources(self):
        sources = (Source("a.py", "a" * 40, "b" * 64, "print('hello')"),)
        self.server.content = '{"findings":["a.py: example finding"],"summary":"Limited review"}'
        result = self.provider.research("review", sources)
        self.assertIs(result.sources, sources)
        self.assertEqual(self.provider.calls[-1]["operation"], "research")
        self.server.content = '{"findings":[],"summary":"fine","sources":[]}'
        with self.assertRaises(AgentError):
            self.provider.research("review", sources)
        self.assertEqual(self.provider.calls[-1]["status"], "failed")

    def test_endpoint_and_missing_configuration_fail_without_fallback(self):
        for endpoint in ("", "http://evil.example/v1", "https://user:password@host/v1",
                         "https://host/v1?key=secret"):
            with self.subTest(endpoint=endpoint), self.assertRaises(AgentError):
                StepFunProvider(endpoint, "model")
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(AgentError):
            from_environment()

    def test_fixture_is_explicit_test_only(self):
        for mode in ("demo", "production"):
            with self.assertRaisesRegex(AgentError, "fixture_provider_test_only"):
                FixtureProvider(mode=mode)
        with patch.dict(os.environ, {"SIQ_MODEL_PROVIDER": "fixture"}, clear=True):
            with self.assertRaises(AgentError):
                from_environment(mode="demo")
            self.assertEqual(from_environment(mode="test").name, "fixture")

    def test_schema_claim_does_not_bypass_strict_parser(self):
        provider = OrnithProvider(self.provider.endpoint.removesuffix("/chat/completions"), "test-model")
        for content in ('{"goal":"one","goal":"two","skills":[]}', '{"allow":true}', '{}'):
            self.server.content = content
            with self.assertRaises(AgentError):
                provider.plan(TASK, SkillRegistry.catalog())
            self.assertEqual(provider.calls[-1]["status"], "failed")
        self.assertEqual(len(self.server.requests), 3)

    def test_timeout_is_distinct_from_other_transport_errors(self):
        from urllib.error import URLError
        for error, expected in ((TimeoutError(), "model_request_timeout"),
                                (URLError(TimeoutError()), "model_request_timeout"),
                                (URLError("private transport detail"), "model_request_failed")):
            with patch.object(self.provider._http, "open", side_effect=error), self.assertRaisesRegex(AgentError, expected):
                self.provider.plan(TASK, SkillRegistry.catalog())
            call = self.provider.calls[-1]
            self.assertEqual(call["error_code"], expected)
            self.assertNotIn("private transport detail", canonical(call).decode())


if __name__ == "__main__":
    unittest.main()
