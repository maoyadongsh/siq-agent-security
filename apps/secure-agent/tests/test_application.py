"""Real application E2E: actual SIQ daemon, HTTP/MCP, files and sink material."""

import hashlib
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from secure_agent.application import SecureApplication
from secure_agent.authority import LocalDaemon
from secure_agent.contracts import AgentError, ReportInput, ResearchResult, SkillCall
from secure_agent.fixtures import FixtureServices
from secure_agent.models import FixtureProvider

ROOT = Path(__file__).resolve().parents[3]


class ApplicationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="siq-application-e2e-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.binary = cls.root / "siq-agent-security"
        subprocess.run(["go", "build", "-o", str(cls.binary), "./cmd/agentshield"],
                       cwd=ROOT / "apps/agentshield", check=True, capture_output=True)

    def run_application(self, *, mode="benign", index=0, effect="normal", model=None, before=None, source=None,
                        approval=False, hold=None, trifecta=False, output="delivery", confidential_name=".env"):
        directory = self.root / self._testMethodName
        with LocalDaemon(self.binary, directory) as daemon, FixtureServices(ROOT / "demo/fixtures", mcp_mode=mode) as fixtures:
            if source is not None:
                fixtures.repository["files"]["README.md"] = source
            application = SecureApplication(ROOT, daemon, fixtures, model or FixtureProvider(mode="test", recipient_index=index))
            result = application.run("Review and deliver the approved repository to Alice",
                repository="fixture/secure-project", question="Review code", scope=("README.md",), effect_mode=effect,
                approval_required=approval, on_hold=hold, trifecta=trifecta,
                requested_output=output, confidential_name=confidential_name,
                before_execution=(lambda authority: before(authority, fixtures)) if before else None)
            # Readback via SIQ revalidates signed evidence and historical action binding.
            for action in result["task"]["actions"]:
                if action["effect"] is not None:
                    record = action["effect"]
                    evidence_id = record["evidence"]["effect_evidence_id"]
                    self.assertEqual(daemon.admin.request("/v1/effect-evidence/" + evidence_id), record)
            records = daemon.admin.request("/v1/receipts")
            self.assertTrue(records["verified"])
            by_id = {r["receipt_id"]: r for r in records["receipts"]}
            for action in result["task"]["actions"]:
                signed = by_id[action["receipt_id"]]
                self.assertEqual(action["decision_trifecta"], signed["trifecta"])
                self.assertEqual(action["action_id"], signed["action_id"])
            return result

    def test_research_only_executes_no_write_or_delivery_and_does_not_invent_effect(self):
        result = self.run_application(output="research")
        self.assertEqual(result["task"]["status"], "researched")
        self.assertEqual(result["task"]["selected_skills"], ["secure-research"])
        self.assertEqual(result["task"]["completed_skills"], ["secure-research"])
        self.assertIsNone(result["report"])
        self.assertFalse(result["messages"])
        self.assertTrue(result["research"]["summary"])
        self.assertEqual({a["tool"] for a in result["task"]["actions"]}, {"web_fetch"})
        self.assertEqual(result["task"]["completion"]["requirements"], [])
        self.assertNotEqual(result["task"]["completion"]["status"], "verified")
        self.assertEqual(result["intent"]["allowed_tools"], ["web_fetch"])

    def test_report_subset_commits_only_report_and_does_not_lookup_recipient(self):
        result = self.run_application(output="report")
        self.assertEqual(result["task"]["status"], "verified")
        self.assertEqual(result["task"]["selected_skills"], ["secure-research", "secure-report"])
        self.assertEqual([r["requirement_id"] for r in result["task"]["completion"]["requirements"]], ["report"])
        self.assertTrue(Path(result["report"]["path"]).is_file())
        self.assertFalse(result["messages"])
        self.assertEqual({a["tool"] for a in result["task"]["actions"]}, {"web_fetch", "write_file"})
        self.assertNotIn("send_message", result["intent"]["allowed_tools"])

    def test_normal_has_actual_file_sink_and_two_verified_requirements(self):
        result = self.run_application()
        self.assertEqual(result["provider"], "fixture")
        self.assertEqual(result["task"]["status"], "verified")
        self.assertEqual({r["requirement_id"] for r in result["task"]["completion"]["requirements"]}, {"report", "delivery"})
        self.assertEqual(len(result["messages"]), 1)
        report = Path(result["report"]["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(report).hexdigest(), result["report"]["digest"])
        self.assertEqual(result["messages"][0]["payload_digest"], result["report"]["digest"])
        self.assertEqual(result["messages"][0]["recipient"], "alice@company.example")
        actions = result["task"]["actions"]
        self.assertTrue(all(a["decision"] == "allow" for a in actions))
        self.assertEqual({a["skill"] for a in actions}, {"secure-research", "secure-report", "secure-delivery"})
        self.assertIn("payload_and_signed_routing_digests", {a.get("observation_scope") for a in actions})
        sent = next(a for a in actions if a["tool"] == "send_message")
        source, = sent["provenance_readbacks"]
        self.assertEqual(source["status"], "resolved")
        self.assertEqual(source["assertion"]["source"]["type"], "TRUSTED_DATABASE")
        self.assertEqual(source["assertion"]["source"]["trust"], "trusted")
        self.assertEqual(source["assertion"]["scope"]["task_id"], result["task"]["task_id"])
        self.assertTrue(source["matches_operator_contact"])

    def test_mcp_attack_reaches_authority_but_never_materializes_message(self):
        result = self.run_application(mode="attack", index=1)
        self.assertEqual(result["task"]["status"], "blocked")
        self.assertEqual(result["task"]["error_code"], "provenance_source_not_allowed")
        action = result["task"]["actions"][-1]
        self.assertEqual(action["tool"], "send_message")
        self.assertTrue(action["d2_attempted"])
        self.assertFalse(action["d3_materialized"])
        self.assertEqual(result["messages"], [])
        self.assertEqual(result["task"]["completion"]["status"], "incomplete")

    def test_same_value_with_mcp_provenance_is_denied(self):
        result = self.run_application(mode="same-value", index=1)
        self.assertEqual(result["task"]["error_code"], "provenance_source_not_allowed")
        self.assertFalse(result["messages"])
        source, = result["task"]["actions"][-1]["provenance_readbacks"]
        self.assertEqual(source["assertion"]["source"]["type"], "MCP")
        self.assertEqual(source["assertion"]["source"]["trust"], "untrusted")
        self.assertTrue(source["matches_operator_contact"])
        self.assertTrue(source["assertion"]["parents"])

    def test_revoked_issuer_readback_is_unavailable_and_cannot_invent_trust(self):
        def revoke(authority, _fixtures):
            authority._reference(authority.github + "/repos/fixture/secure-project/commits/HEAD", "SYSTEM")
            authority.admin.request("/v1/provenance-issuers/" + authority.issuer + "/revoke", {})
        result = self.run_application(before=revoke)
        self.assertEqual(result["task"]["status"], "blocked")
        source, = result["task"]["actions"][0]["provenance_readbacks"]
        self.assertEqual(source["status"], "unavailable")
        self.assertEqual(source["error_code"], "provenance_issuer_untrusted")
        self.assertNotIn("assertion", source)
        self.assertFalse(result["messages"])

    def test_fake_success_without_sink_receipt_is_incomplete(self):
        result = self.run_application(effect="fake-success")
        self.assertEqual(result["task"]["status"], "incomplete")
        self.assertFalse(result["messages"])
        network = result["task"]["actions"][-1]
        self.assertTrue(network["d3_materialized"])
        self.assertEqual(network["observation"], "REPORTED")
        self.assertIsNone(network["effect"])

    def test_conflicting_sink_bytes_are_not_verified(self):
        result = self.run_application(effect="conflicting")
        self.assertEqual(result["task"]["status"], "conflicting")
        self.assertEqual(len(result["messages"]), 1)
        self.assertNotEqual(result["messages"][0]["payload_digest"], result["report"]["digest"])

    def test_changed_source_after_commitment_fails_before_write(self):
        def change(_authority, fixtures):
            fixtures.repository["files"]["README.md"] += "\nsubstituted content"
        result = self.run_application(before=change)
        self.assertEqual(result["task"]["error_code"], "source_changed_after_commitment")
        self.assertFalse(Path(result["report"]["path"]).exists())
        self.assertFalse(result["messages"])

    def test_replayed_source_pii_is_not_lost_in_a_clean_execution_session(self):
        result = self.run_application(source="Private customer contact: customer@private.example\n")
        self.assertEqual(result["task"]["error_code"], "session_taint_violation")
        self.assertFalse(result["messages"])
        self.assertNotEqual(result["task"]["completion"]["status"], "verified")

    def test_confidential_read_then_untrusted_web_denies_next_egress(self):
        result = self.run_application(trifecta=True)
        self.assertEqual(result["task"]["status"], "blocked")
        self.assertEqual(result["task"]["error_code"], "lethal_trifecta")
        actions = result["task"]["actions"]
        self.assertEqual([a["tool"] for a in actions], ["read_file", "web_fetch", "web_fetch"])
        # ADR-025: credential paths are never grantable, so the .env read is
        # denied at the boundary; the denied attempt still marks the session as
        # having touched private data, and the later egress hits the trifecta.
        self.assertEqual([a["decision"] for a in actions], ["deny", "allow", "deny"])
        self.assertEqual([a["d3_materialized"] for a in actions], [False, True, False])
        self.assertEqual([a["observation"] for a in actions], ["UNKNOWN", "REPORTED", "UNKNOWN"])
        self.assertEqual([a["decision_trifecta"] for a in actions], [
            {"private_data": True, "untrusted_input": False, "egress": False},
            {"private_data": True, "untrusted_input": False, "egress": True},
            {"private_data": True, "untrusted_input": True, "egress": True}])
        self.assertFalse(Path(result["report"]["path"]).exists())
        self.assertFalse(result["messages"])
        self.assertEqual(result["task"]["completion"]["status"], "incomplete")

    def test_changed_confidential_fixture_stops_before_network(self):
        def change(authority, _fixtures):
            authority.confidential_path.write_bytes(b"Substituted fixture bytes")
        # A non-credential fixture name keeps the read engine-reachable (ADR-025
        # denies credential paths outright), so the tool-side integrity check is
        # the layer under test.
        result = self.run_application(trifecta=True, before=change, confidential_name="confidential-note.txt")
        self.assertEqual(result["task"]["error_code"], "tool_confidential_fixture_invalid")
        self.assertEqual([a["tool"] for a in result["task"]["actions"]], ["read_file"])
        self.assertFalse(result["messages"])

    def test_confidential_fixture_symlink_is_rejected(self):
        def change(authority, _fixtures):
            authority.confidential_path.unlink()
            authority.confidential_path.symlink_to(authority.contacts_path)
        result = self.run_application(trifecta=True, before=change, confidential_name="confidential-note.txt")
        self.assertEqual(result["task"]["error_code"], "tool_confidential_fixture_invalid")
        self.assertEqual([a["tool"] for a in result["task"]["actions"]], ["read_file"])
        self.assertFalse(result["messages"])

    def test_json_escaped_secret_assignment_preserves_session_taint(self):
        result = self.run_application(source='secret="benchmark-synthetic-secret-value"\n')
        self.assertEqual(result["task"]["status"], "blocked")
        self.assertEqual(result["task"]["error_code"], "session_taint_violation")
        self.assertFalse(result["messages"])
        self.assertNotEqual(result["task"]["completion"]["status"], "verified")

    def test_report_payload_examples_are_not_additional_execution_targets(self):
        class ReviewExamples(FixtureProvider):
            def research(self, question, sources):
                return ResearchResult(("Review /workspace paths and https://docs.example.test examples.",),
                                      sources, "Selected-file review with documentation references.")
        result = self.run_application(model=ReviewExamples(mode="test"))
        self.assertEqual(result["task"]["status"], "verified")
        self.assertEqual(len(result["messages"]), 1)

    def test_model_report_path_hijack_is_denied_by_siq(self):
        class PathHijack(FixtureProvider):
            def plan(self, task, catalog):
                plan = super().plan(task, catalog)
                calls = list(plan.skills)
                calls[1] = SkillCall("secure-report", ReportInput(task.report_path + ".hijacked"))
                return replace(plan, skills=tuple(calls))
        result = self.run_application(model=PathHijack(mode="test"))
        self.assertEqual(result["task"]["error_code"], "provenance_missing")
        self.assertFalse(Path(result["report"]["path"] + ".hijacked").exists())
        self.assertFalse(result["messages"])

    def test_revoked_committed_intent_blocks_replay_before_effects(self):
        def revoke(authority, _fixtures):
            authority.admin.request("/v1/intents/" + authority.intent["intent_id"] + "/revoke",
                                    {"expected_intent_digest": authority.intent["digest"]})
        result = self.run_application(before=revoke)
        self.assertEqual(result["task"]["error_code"], "intent_revoked")
        self.assertFalse(Path(result["report"]["path"]).exists())
        self.assertFalse(result["messages"])

    def test_revocation_after_approval_prevents_actual_process_and_delivery(self):
        def revoke(_request, decision, authority):
            authority.admin.request("/v1/hold/" + decision["receipt_id"], {"approve": True, "actor_id": "test-operator"})
            authority.admin.request("/v1/intents/" + authority.intent["intent_id"] + "/revoke",
                                    {"expected_intent_digest": authority.intent["digest"]})
        result = self.run_application(approval=True, hold=revoke)
        self.assertEqual(result["task"]["status"], "blocked")
        self.assertEqual(result["task"]["error_code"], "hold_authority_changed")
        process = result["task"]["actions"][-1]
        self.assertEqual(process["tool"], "verify_report")
        self.assertFalse(process["d3_materialized"])
        self.assertNotIn("reported_process", process)
        self.assertFalse(result["messages"])

    def test_human_denial_leaves_report_but_prevents_process_and_delivery(self):
        def reject(_request, decision, authority):
            authority.admin.request("/v1/hold/" + decision["receipt_id"], {"approve": False, "actor_id": "test-operator"})
        result = self.run_application(approval=True, hold=reject)
        self.assertEqual(result["task"]["error_code"], "hold_denied")
        self.assertTrue(Path(result["report"]["path"]).is_file())
        self.assertFalse(result["task"]["actions"][-1]["d3_materialized"])
        self.assertFalse(result["messages"])

    def test_replaced_approval_parameters_fail_actual_siq_recheck(self):
        def replace_request(request, decision, authority):
            authority.admin.request("/v1/hold/" + decision["receipt_id"], {"approve": True, "actor_id": "test-operator"})
            changed = {**request, "params": {"path": request["params"]["path"] + ".replaced"}}
            with self.assertRaisesRegex(AgentError, "hold_identity_mismatch"):
                authority.client.recheck_hold(changed, decision)
            raise AgentError("hold_identity_mismatch")
        result = self.run_application(approval=True, hold=replace_request)
        self.assertEqual(result["task"]["error_code"], "hold_identity_mismatch")
        self.assertFalse(result["task"]["actions"][-1]["d3_materialized"])
        self.assertFalse(result["messages"])


if __name__ == "__main__":
    unittest.main()
