"""Protected runtime callback mapping; no publisher credential or policy rules."""

import hashlib
import json


class CallbackError(RuntimeError):
    pass


class Callbacks:
    @classmethod
    def via_host(cls, channel):
        """Use the already authenticated host; keep runtime credentials there."""
        return cls(channel, lambda body: channel.exchange({"schema_version": "native-decision-relay/v1", "request": body}))

    def __init__(self, channel, decide):
        # decide is the existing bounded, scoped-credential HTTP transport,
        # installed by trusted bootstrap, never selected in tool parameters.
        if not callable(decide):
            raise CallbackError("native_host_unavailable")
        self.channel, self.decide = channel, decide

    def observe(self, event):
        result = self.channel.exchange(event)
        if type(result) is not dict or set(result) != {"accepted"} or result["accepted"] is not True:
            raise CallbackError("native_host_unavailable")

    def authorize(self, request, load):
        raw = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
        binding = hashlib.sha256(raw).hexdigest()
        event = {"schema_version": "native-hermes-lifecycle/v1", "kind": "call_prepare",
                 "agent_id": request["agent_id"], "session_id": request["session_id"], "task_id": request["task_id"],
                 "tool": request["tool"], "tool_call_id": request["tool_call_id"], "request_binding": binding,
                 "load_id": "" if load is None else load}
        self.observe(event)
        # Business task identity remains daemon-derived; this is the actual
        # Hermes task, separated in the existing HTTP decision contract.
        body = {k: v for k, v in request.items() if k != "task_id"}
        body["runtime_task_id"] = request["task_id"]
        result = self.decide(body)
        if (type(result) is not dict or result.get("action") not in ("allow", "deny", "hold")
                or type(result.get("receipt_id")) is not str or not result["receipt_id"] or "params" in result):
            raise CallbackError("native_host_unavailable")
        return {"action": result["action"], "request_binding": binding, "decision_id": result["receipt_id"]}
