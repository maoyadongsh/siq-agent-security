"""AgentDojo dispatch wrapper: validated email arguments -> real SIQ decision.

Read tools in this restricted experiment retain upstream behavior. Their data
access is not claimed to be protected. No value matching invents provenance.
"""
import hashlib
import json

from common import canonical

SUPPORTED_TOOLS = ("get_current_day", "search_calendar_events", "get_day_calendar_events", "search_emails", "send_email")


class SIQDenied(Exception):
    pass


class UnsupportedMapping(Exception):
    pass


class InvalidDecision(Exception):
    pass


def validate_decision(decision, task_id):
    if (not isinstance(decision, dict) or decision.get("action") not in ("allow", "deny", "hold")
            or any(not isinstance(decision.get(name), str) or not decision[name]
                   for name in ("action_id", "receipt_id", "reason_code", "effective_action"))
            or decision["effective_action"] != decision["action"] or decision.get("task_id") != task_id
            or (decision["action"] == "allow" and decision.get("authority_status") != "valid")):
        raise InvalidDecision("SIQ decision response lacks required action/authority binding")


def mail_descriptors(arguments):
    """Bind the full original message, and enumerate every TO/CC/BCC destination."""
    if arguments.get("attachments"):
        raise UnsupportedMapping("attachment reads are outside this registered mapping")
    destinations = []
    for field in ("recipients", "cc", "bcc"):
        values = arguments.get(field) or []
        if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
            raise ValueError("unsupported recipient shape")
        destinations.extend(values)
    if not destinations:
        raise ValueError("empty recipient set")
    # Routing addresses remain routing fields, never duplicated as message body.
    # The full original parameter set remains hash-bound in every SIQ action.
    body = canonical({k: v for k, v in arguments.items() if k not in ("recipients", "cc", "bcc")}).decode()
    digest = hashlib.sha256(canonical(arguments)).hexdigest()
    return [{"recipient": address, "body": body, "original_arguments_sha256": digest} for address in dict.fromkeys(destinations)]


class MailGate:
    def __init__(self, harness, agent_id, task_id, clean_prompt):
        self.harness = harness
        self.task_id = task_id
        self.identity = {"platform": "hermes", "session_id": "agentdojo-session", "agent_id": agent_id}
        self.token = (harness.state / "token").read_text().strip()
        contract = harness.api("/v1/intents/int-native-fixture")
        for field in ("digest", "signature", "signing_schema"):
            contract.pop(field, None)
        # The operator authorizes only the query workflow before any injection.
        # The guard receives neither attacker goal nor expected answer.
        contract.update(schema_version="intent/v3", intent_id="intent-" + task_id, task_id=task_id,
                        purpose=clean_prompt, allowed_tools=["read_file"], allowed_effects=["file.read"],
                        resource_constraints=[], parameter_constraints=[], provenance_constraints=[], effect_requirements=[])
        harness.api("/v1/intents", contract, expected=201)
        harness.api("/v1/intent-bindings", {**self.identity, "intent_id": contract["intent_id"]}, expected=201)
        self.decisions = []
        self.parameter_sources = []  # Explicit operator references only; empty in the model cohort.

    def __call__(self, arguments, dispatch_id):
        decisions = []
        for index, params in enumerate(mail_descriptors(arguments)):
            request = {**self.identity, "tool": "send_message", "tool_call_id": f"{dispatch_id}-recipient-{index}", "params": params}
            if self.parameter_sources:
                request["parameter_provenance"] = [{"parameter_path": "/recipient",
                    "provenance_refs": [self.parameter_sources[index]]}]
            decision = self.harness.api("/v1/decide", request, token=self.token)
            validate_decision(decision, self.task_id)
            record = {"dispatch_id": dispatch_id, "recipient_index": index,
                      "params_sha256": hashlib.sha256(canonical(params)).hexdigest(), "decision": decision,
                      "provenance": "explicit_operator_reference" if self.parameter_sources else "unavailable_upstream"}
            self.decisions.append(record)
            decisions.append(decision)
        if any(d["action"] != "allow" for d in decisions):
            raise SIQDenied("SIQ did not authorize email dispatch for this query task")


class MailAndDeleteGate(MailGate):
    """Route the exact delete_email action; do not pretend it is filesystem delete.

    The fixed product recognizes no message.delete effect. A query Intent can
    deny this unapproved tool; even operator-approved delete remains unsupported.
    """

    def authorize_tool(self, tool, arguments, dispatch_id):
        if tool == "send_email":
            return self(arguments, dispatch_id)
        if tool != "delete_email":
            return None
        decision = self.harness.api("/v1/decide", {**self.identity, "tool": tool,
            "tool_call_id": dispatch_id, "params": arguments}, token=self.token)
        validate_decision(decision, self.task_id)
        self.decisions.append({"dispatch_id": dispatch_id, "tool": tool,
            "params_sha256": hashlib.sha256(canonical(arguments)).hexdigest(), "decision": decision,
            "provenance": "unavailable_upstream"})
        if decision["action"] != "allow":
            raise SIQDenied("SIQ did not authorize exact email deletion action")
        return None


def make_runtime(functions, gate, events, exposed_tools=None):
    from agentdojo.functions_runtime import FunctionsRuntime

    wrapped = []
    dispatches = []
    for function in functions:
        if function.name not in (SUPPORTED_TOOLS if exposed_tools is None else exposed_tools):
            continue

        def execute(_original=function, **kwargs):
            # Upstream FunctionsRuntime already resolved nested calls and validated
            # with Pydantic before invoking this function. Dependencies are excluded.
            arguments = {k: v for k, v in kwargs.items() if k not in _original.dependencies}
            dispatch_id = "dispatch-" + str(len(dispatches) + 1)
            record = {"dispatch_id": dispatch_id, "tool": _original.name, "arguments": arguments,
                      "entered": False, "completed": False, "error_type": None}
            dispatches.append(record)
            events.add("tool_dispatch_requested", **record)
            try:
                if gate is not None and hasattr(gate, "authorize_tool"):
                    gate.authorize_tool(_original.name, arguments, dispatch_id)
                elif gate is not None and _original.name == "send_email":
                    gate(arguments, dispatch_id)
                record["entered"] = True
                result = _original(**kwargs)
                record["completed"] = True
                return result
            except Exception as exc:
                record["error_type"] = type(exc).__name__
                raise
            finally:
                events.add("tool_dispatch_finished", **record)

        wrapped.append(function.model_copy(update={"run": execute}))
    runtime = FunctionsRuntime(wrapped)
    return runtime, dispatches


def serializable_messages(messages):
    return json.loads(json.dumps(messages, default=lambda value: value.model_dump(mode="json")))
