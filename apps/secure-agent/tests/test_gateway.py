import unittest
from unittest.mock import Mock

from secure_agent.contracts import AgentError, TaskState
from secure_agent.gateway import Blocked, ToolGateway, WaitingForApproval
from secure_agent.security import EvidenceClient, Identity, SecurityClient


def decision(action="allow", **extra):
    return {"action": action, "effective_action": action, "authority_status": "valid",
            "receipt_id": "receipt", "action_id": "action", "reason_code": action, **extra}


class GatewayTest(unittest.TestCase):
    def test_display_readback_runs_after_allowed_tool_entry(self):
        order = []
        self.executor.side_effect = lambda *_args: (order.append("tool"), {"success": True})[1]
        gateway = ToolGateway(self.security, {"write_file": self.executor}, self.state,
            describe_provenance=lambda _request: (order.append("display"), [])[1])
        gateway.call("write_file", {"path": "/work/report.md"})
        self.assertEqual(order, ["tool", "display"])

    def setUp(self):
        self.api = Mock()
        self.api.request.return_value = decision()
        self.security = SecurityClient(self.api, Identity("hermes", "session", "agent", "task"))
        self.executor = Mock(return_value={"success": True})
        self.state = TaskState("task", "goal", "fixture")
        self.gateway = ToolGateway(self.security, {"write_file": self.executor}, self.state)

    def test_allow_executes_and_records_only_reported(self):
        self.gateway.call("write_file", {"path": "/work/report.md"})
        self.executor.assert_called_once()
        self.assertEqual(self.api.request.call_args_list[-1].args[0], "/v1/observe")
        self.assertEqual(self.state.actions[0]["observation"], "REPORTED")
        self.assertIsNone(self.state.actions[0]["effect"])

    def test_denied_action_never_enters_executor(self):
        self.api.request.return_value = decision("deny", reason_code="provenance_source_not_allowed")
        with self.assertRaisesRegex(Blocked, "provenance_source_not_allowed"):
            self.gateway.call("write_file", {"path": "/work/report.md"})
        self.executor.assert_not_called()
        self.assertFalse(self.state.actions[0]["d3_materialized"])

    def test_unavailable_or_malformed_decision_fails_closed(self):
        responses = [{}, {"action": "allow"}, decision(effective_action="deny"),
                     decision(authority_status="unbound_legacy"), decision(authority_status="invalid")]
        for response in responses:
            self.api.request.return_value = response
            with self.subTest(response=response), self.assertRaises(AgentError):
                self.gateway.call("write_file", {"path": "/work/report.md"})
        self.api.request.side_effect = AgentError("siq_unavailable")
        with self.assertRaisesRegex(AgentError, "siq_unavailable"):
            self.gateway.call("write_file", {"path": "/work/report.md"})
        self.executor.assert_not_called()

    def test_unregistered_tool_cannot_bypass_gateway(self):
        with self.assertRaisesRegex(AgentError, "gateway_tool_unregistered"):
            self.gateway.call("exec", {"command": "arbitrary command"})
        self.api.request.assert_not_called()
        self.executor.assert_not_called()

    def test_hold_uses_original_parameters_and_online_recheck_once(self):
        params = {"path": "/work/report.md", "nested": {"value": "original"}}
        self.api.request.return_value = decision("hold")
        with self.assertRaises(WaitingForApproval):
            self.gateway.call("write_file", params)
        params["nested"]["value"] = "replaced"
        self.executor.assert_not_called()
        self.api.request.return_value = {"schema_version": "hold-status/v1", "action_id": "action",
                                        "decision_receipt_id": "receipt", "status": "approved",
                                        "reason_code": "hold_approved", "expires_at": "2026-09-08T00:00:00Z"}
        self.gateway.resume("action")
        self.assertEqual(self.executor.call_args.args[0]["nested"]["value"], "original")
        with self.assertRaisesRegex(Blocked, "gateway_pending_action_missing"):
            self.gateway.resume("action")
        self.executor.assert_called_once()

    def test_revoked_expired_and_unavailable_hold_never_executes(self):
        for status in ("denied", "expired", "consumed", "unavailable"):
            self.api.request.side_effect = None
            self.api.request.return_value = decision("hold")
            with self.assertRaises(WaitingForApproval):
                self.gateway.call("write_file", {"path": "/work/report.md"})
            self.api.request.return_value = {"schema_version": "hold-status/v1", "action_id": "action",
                                            "decision_receipt_id": "receipt", "status": status,
                                            "reason_code": "hold_" + status, "expires_at": "2026-09-08T00:00:00Z"}
            if status == "unavailable":
                self.api.request.side_effect = AgentError("siq_unavailable")
            with self.assertRaises(AgentError):
                self.gateway.resume("action")
        self.executor.assert_not_called()

    def test_parameter_transform_cannot_execute_old_or_new_payload(self):
        self.api.request.return_value = decision(params={"path": "/different"})
        with self.assertRaisesRegex(Blocked, "gateway_parameters_transformed"):
            self.gateway.call("write_file", {"path": "/work/report.md"})
        self.executor.assert_not_called()

    def test_effect_observer_runs_after_tool_exception(self):
        observer = Mock()
        observer.finish.return_value = {"result": "conflicting"}
        self.executor.side_effect = OSError("simulated failure after effect")
        gateway = ToolGateway(self.security, {"write_file": self.executor}, self.state, observer=observer)
        with self.assertRaises(OSError):
            gateway.call("write_file", {"path": "/work/report.md"})
        observer.begin.assert_called_once()
        observer.finish.assert_called_once()
        self.assertEqual(self.state.actions[0]["effect"]["result"], "conflicting")

    def test_tool_cannot_mutate_observed_request(self):
        def execute(params, _decision):
            params["path"] = "/changed"
            return {"success": True}
        gateway = ToolGateway(self.security, {"write_file": execute}, self.state)
        gateway.call("write_file", {"path": "/work/report.md"})
        observed = self.api.request.call_args.args[1]
        self.assertEqual(observed["params"]["path"], "/work/report.md")

    def test_completion_rejects_unknown_server_status(self):
        self.api.request.return_value = {"status": "success"}
        with self.assertRaisesRegex(AgentError, "siq_completion_invalid"):
            EvidenceClient(self.api).completion("task")


if __name__ == "__main__":
    unittest.main()
