package server

import (
	"encoding/json"
	"strings"

	"siq-agent-security/apps/agentshield/internal/adapters"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// workBuddyRuntimeCall closes the managed hold protocol without extending the
// legacy global-token wire. The ordinary handlers still validate request types.
func workBuddyRuntimeCall(path string, raw []byte) bool {
	var calls, allowed []string
	switch path {
	case "/v1/decide", "/v1/observe":
		calls = []string{"tool_call_id"}
	case "/v1/hold-status":
		calls = []string{"tool_call_id"}
		allowed = []string{"platform", "session_id", "agent_id", "tool", "tool_call_id", "action_id", "decision_receipt_id", "params", "task_id", "runtime_task_id"}
	case "/v1/hold-executions/reserve":
		calls = []string{"original_tool_call_id", "retry_tool_call_id"}
		allowed = []string{"schema_version", "platform", "session_id", "agent_id", "tool", "original_tool_call_id", "retry_tool_call_id", "action_id", "decision_receipt_id", "params", "task_id", "runtime_task_id"}
	case "/v1/hold-executions/status":
		calls = []string{"retry_tool_call_id"}
		allowed = []string{"schema_version", "platform", "session_id", "agent_id", "tool", "retry_tool_call_id", "action_id", "decision_receipt_id", "reservation_receipt_id", "params", "task_id", "runtime_task_id"}
	default:
		return true
	}
	var fields map[string]json.RawMessage
	if json.Unmarshal(raw, &fields) != nil || fields == nil {
		return false
	}
	if allowed == nil {
		for key := range fields {
			allowed = append(allowed, key)
		}
	}
	if adapters.DecodeWorkBuddyObject(raw, calls, allowed, &fields) != nil {
		return false
	}
	values := make(map[string]string, len(calls))
	for name, value := range fields {
		for _, required := range calls {
			if strings.EqualFold(name, required) {
				var call string
				if name != required || json.Unmarshal(value, &call) != nil || !runtimeidentity.ValidWorkBuddyCallID(call) {
					return false
				}
				values[required] = call
			}
		}
	}
	return len(calls) != 2 || values[calls[0]] != values[calls[1]]
}
