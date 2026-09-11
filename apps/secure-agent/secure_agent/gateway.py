"""Only registered built-in tools can execute, after an online SIQ decision."""

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter, sleep
from typing import Protocol
from uuid import uuid4

from .contracts import AgentError, TaskState, canonical, strict_json
from .security import SecurityClient


class EffectObserver(Protocol):
    def begin(self, request: dict, decision: dict): ...
    def finish(self, handle, request: dict, decision: dict) -> dict | None: ...


class Blocked(AgentError):
    pass


class WaitingForApproval(AgentError):
    pass


@dataclass(frozen=True)
class ToolResult:
    value: dict
    decision: dict


class ToolGateway:
    def __init__(self, security: SecurityClient, executors: dict[str, Callable[[dict, dict], dict]],
                 state: TaskState, *, observer: EffectObserver | None = None,
                 prepare: Callable[[dict], str | dict | None] | None = None,
                 observation: Callable[[dict, dict, dict], dict] | None = None,
                 describe_provenance: Callable[[dict], list[dict]] | None = None,
                 changed: Callable[[TaskState], None] | None = None,
                 on_hold: Callable[[dict, dict], None] | None = None):
        self._security, self._executors, self._state = security, dict(executors), state
        self._observer, self._prepare = observer, prepare
        self._observation = observation
        self._describe_provenance = describe_provenance
        self._changed = changed
        self._on_hold = on_hold
        self._pending: dict[str, tuple[bytes, bytes, dict]] = {}

    def call(self, tool: str, params: dict, *, provenance: tuple[dict, ...] = ()) -> ToolResult:
        if self._changed:
            self._changed(self._state)
        if tool not in self._executors:
            raise AgentError("gateway_tool_unregistered")
        # Copy at the boundary. A caller cannot change what was authorized while
        # a request or approval is pending. Executors receive a separate copy.
        request = strict_json(canonical({**self._security.identity.request_fields(),
            "tool": tool, "tool_call_id": uuid4().hex, "params": params,
            "parameter_provenance": list(provenance)}))
        if self._prepare:
            reference = self._prepare(strict_json(canonical(request)))
            if isinstance(reference, dict):
                if set(reference) != {"context_assertion_id", "parameter_provenance"}:
                    raise AgentError("gateway_preparation_invalid")
                request.update(reference)
            elif reference:
                request["context_assertion_id"] = reference
        started = perf_counter()
        decision = self._security.decide(strict_json(canonical(request)))
        self._state.timings_ms.setdefault("siq_decision", []).append((perf_counter() - started) * 1000)
        event = {"tool": tool, "skill": self._state.current_skill,
                 "action_id": decision["action_id"], "receipt_id": decision["receipt_id"],
                 "decision": decision["action"], "reason_code": decision["reason_code"],
                 "authority_status": decision.get("authority_status"),
                 "decision_trifecta": decision.get("trifecta"),
                 "parameter_provenance": request.get("parameter_provenance", []),
                 "d2_attempted": True, "d3_materialized": False, "observation": "UNKNOWN",
                 "effect": None}
        self._state.actions.append(event)
        if tool == "send_message" and isinstance(request["params"].get("recipient"), str):
            event["routing_recipient"] = request["params"]["recipient"]
        if self._describe_provenance and decision["action"] != "allow":
            event["provenance_readbacks"] = self._describe_provenance(strict_json(canonical(request)))
        if self._changed:
            self._changed(self._state)
        if decision["action"] == "deny":
            raise Blocked(decision["reason_code"])
        # A transformed payload requires a new proposal/authorization, not silent
        # execution of either the old or the redacted payload under another digest.
        if "params" in decision and canonical(decision["params"]) != canonical(request["params"]):
            raise Blocked("gateway_parameters_transformed")
        if decision["action"] == "hold":
            self._pending[decision["action_id"]] = (canonical(request), canonical(decision), event)
            if self._on_hold:
                self._state.status, self._state.current_step = "waiting_approval", "human approval required"
                self._on_hold(strict_json(canonical(request)), strict_json(canonical(decision)))
                while True:
                    if self._changed:
                        self._changed(self._state)
                    try:
                        result = self.resume(decision["action_id"])
                        self._state.status, self._state.current_step = "running", "executing skill"
                        return result
                    except WaitingForApproval:
                        sleep(0.2)
            raise WaitingForApproval(decision["action_id"])
        return self._execute(request, decision, event)

    def resume(self, action_id: str) -> ToolResult:
        pending = self._pending.get(action_id)
        if pending is None:
            raise Blocked("gateway_pending_action_missing")
        raw, record, event = pending
        request, decision = strict_json(raw), strict_json(record)
        # This is an online recheck of original parameters, current Intent,
        # provenance and Grant. A UI click is not an execution authorization.
        status = self._security.recheck_hold(request, decision)
        event["approval_status"] = status["status"]
        event["approval_reason_code"] = status["reason_code"]
        event["approval_expires_at"] = status["expires_at"]
        if status["status"] == "pending":
            raise WaitingForApproval(action_id)
        del self._pending[action_id]
        if status["status"] != "approved":
            raise Blocked(status.get("reason_code", "hold_not_approved"))
        return self._execute(request, decision, event)

    def _execute(self, request, decision, event):
        handle = self._observer.begin(request, decision) if self._observer else None
        event["d3_materialized"] = True
        try:
            result = self._executors[request["tool"]](strict_json(canonical(request["params"])),
                                                       strict_json(canonical(decision)))
            if not isinstance(result, dict):
                raise AgentError("tool_result_invalid")
            if type(result.get("success")) is bool:
                event["reported_success"] = result["success"]
            # Observe the actual result for SIQ's stateful taint processing.
            observed = self._observation(request, decision, result) if self._observation else result
            self._security.observe(request, decision, observed)
            if observed != result:
                event["observation_scope"] = "payload_and_signed_routing_digests"
            event["observation"] = "REPORTED"
            if request["tool"] == "verify_report":
                event["reported_process"] = {k: result[k] for k in ("process_id", "exit_code", "digest")}
            return ToolResult(result, decision)
        finally:
            # Even if the tool/observation failed after causing an effect, collect
            # observer evidence. Never infer evidence from result.success.
            if self._observer:
                started = perf_counter()
                event["effect"] = self._observer.finish(handle, request, decision)
                self._state.timings_ms.setdefault("effect_processing", []).append(
                    (perf_counter() - started) * 1000)
            if self._describe_provenance and "provenance_readbacks" not in event:
                event["provenance_readbacks"] = self._describe_provenance(strict_json(canonical(request)))
            if self._changed:
                self._changed(self._state)
