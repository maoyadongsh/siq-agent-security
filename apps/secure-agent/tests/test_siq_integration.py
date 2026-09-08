"""Real daemon contract checks; isolated test bootstrap reuses the existing harness.

These are integration tests, not claimed as full StepFun/DGX Agent E2E evidence.
No test harness is imported by the application package.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from secure_agent.contracts import AgentError, TaskState, digest
from secure_agent.gateway import Blocked, ToolGateway
from secure_agent.security import EvidenceClient, Identity, JsonAPI, SecurityClient

ROOT = Path(__file__).resolve().parents[3]


class SIQIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("native_fixture", ROOT / "scripts/validate-intent-v2-hermes.py")
        cls.base = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.base)
        cls.temporary = tempfile.TemporaryDirectory(prefix="siq-secure-agent-test-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.h = cls.base.Harness(Path(cls.temporary.name), SimpleNamespace())
        cls.addClassCleanup(cls.h.stop)
        cls.h.read_tool = "send_message"
        cls.h.build()
        cls.h.start()
        cls.h.setup_authority()

    def setUp(self):
        suffix = uuid4().hex
        contract = self.h.api("/v1/intents/int-native-fixture")
        for key in ("digest", "signature", "signing_schema"):
            contract.pop(key, None)
        contract.update(schema_version="intent/v3", intent_id="intent-" + suffix, task_id="task-" + suffix,
            allowed_tools=["send_message"], allowed_effects=["message.send"],
            resource_constraints=[{"domain": "message", "operator": "equals", "value": "alice@company.example"}],
            provenance_constraints=[{"parameter_path": "/recipient", "allowed_source_types": ["TRUSTED_DATABASE"],
                                     "minimum_trust": "trusted", "required": True}])
        self.h.api("/v1/intents", contract, expected=201)
        self.identity = Identity("hermes", "session-" + suffix, self.base.AGENT, contract["task_id"])
        self.h.api("/v1/intent-bindings", {**self.identity.request_fields(), "intent_id": contract["intent_id"]}, expected=201)
        self.api = JsonAPI(self.h.endpoint, (self.h.state / "token").read_text().strip())
        self.client = SecurityClient(self.api, self.identity)
        scope = {**self.identity.request_fields(), "task_id": contract["task_id"]}
        self.h.api("/v1/provenance-issuers", {"issuer_id": "directory-" + suffix, "local_key_ref": "local-state",
            "allowed_source_types": ["TRUSTED_DATABASE"], "max_trust_level": "trusted", "scope": scope,
            "expires_at": contract["expires_at"]}, expected=201)
        self.trusted = self.h.api("/v1/provenance-assertions", {
            "schema_version": "provenance-assertion/v1", "provenance_id": "trusted-" + suffix,
            "source": {"type": "TRUSTED_DATABASE", "source_id": "deterministic-contacts", "trust": "trusted"},
            "scope": scope, "content_digest": digest("alice@company.example"), "parents": [], "derivation": "direct",
            "issued_at": contract["issued_at"], "expires_at": contract["expires_at"], "issuer": "directory-" + suffix}, expected=201)
        raw = {"recipient": "alice@company.example", "source": "USER", "trust": "authoritative"}
        parent = self.client.report_source("mcp-contact", raw, "controlled-mcp")
        self.low = self.client.select_source(parent["provenance_id"], "/recipient", raw)

    def gateway(self):
        self.executions = []
        def execute(params, _decision):
            self.executions.append(params)
            return {"success": True}
        state = TaskState(self.identity.task_id, "contact integration", "fixture")
        return ToolGateway(self.client, {"send_message": execute}, state), state

    def test_actual_trusted_database_recipient_allowed(self):
        gateway, state = self.gateway()
        gateway.call("send_message", {"recipient": "alice@company.example", "body": "synthetic report"},
            provenance=({"parameter_path": "/recipient", "provenance_refs": [self.trusted["provenance_id"]]},))
        self.assertEqual(len(self.executions), 1)
        self.assertEqual(state.actions[0]["decision"], "allow")
        self.assertEqual(state.actions[0]["observation"], "REPORTED")

    def test_actual_same_value_mcp_source_denied_before_executor(self):
        gateway, state = self.gateway()
        self.assertEqual(self.low["source"]["type"], "MCP")
        self.assertEqual(self.low["source"]["trust"], "untrusted")
        with self.assertRaisesRegex(Blocked, "provenance_source_not_allowed"):
            gateway.call("send_message", {"recipient": "alice@company.example", "body": "synthetic report"},
                provenance=({"parameter_path": "/recipient", "provenance_refs": [self.low["provenance_id"]]},))
        self.assertFalse(self.executions)
        self.assertFalse(state.actions[0]["d3_materialized"])

    def test_actual_missing_provenance_is_not_a_string_whitelist(self):
        gateway, _state = self.gateway()
        with self.assertRaisesRegex(Blocked, "provenance_missing"):
            gateway.call("send_message", {"recipient": "alice@company.example", "body": "synthetic report"})
        self.assertFalse(self.executions)

    def test_decision_credential_cannot_mint_trusted_assertions(self):
        with self.assertRaises(AgentError):
            self.api.request("/v1/provenance-assertions", self.trusted, expected=201)

    def test_actual_completion_does_not_infer_message_delivery(self):
        completion = EvidenceClient(JsonAPI(self.h.endpoint, self.h.admin)).completion(self.identity.task_id)
        self.assertEqual(completion["status"], "unknown")
        self.assertEqual(completion["reason_code"], "not_required")


if __name__ == "__main__":
    unittest.main()
