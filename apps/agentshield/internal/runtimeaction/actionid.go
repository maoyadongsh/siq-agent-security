package runtimeaction

import (
	"crypto/sha256"
	"encoding/hex"

	"siq-agent-security/apps/agentshield/internal/canon"
)

// ActionID returns a boundary-generated stable identifier for one tool call.
// The value is derived from the stable request envelope, not wall-clock time.
func ActionID(e Envelope) string {
	effects := make([]any, len(e.Effects))
	for i, effect := range e.Effects {
		effects[i] = effect
	}
	m := map[string]any{
		"sequence":      e.Sequence,
		"platform":      e.Platform,
		"session_id":    e.SessionID,
		"agent_id":      e.AgentID,
		"task_id":       e.TaskID,
		"intent_id":     e.IntentID,
		"tool":          e.Tool,
		"tool_call_id":  e.ToolCallID,
		"operation":     e.Operation,
		"effects":       effects,
		"params_digest": e.ParamsDigest,
	}
	raw, err := canon.Marshal(m)
	if err != nil {
		panic("runtimeaction: invalid canonical identity")
	}
	sum := sha256.Sum256(raw)
	return "act-" + hex.EncodeToString(sum[:])[:24]
}
