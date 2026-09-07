package receipt

import (
	"testing"
	"time"
)

func TestIntentContractRejectsOutOfScopeEffectAndParameter(t *testing.T) {
	now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
	base := IntentContract{IntentID: "i-1", TaskID: "t-1", Principal: "user-1", AgentID: "a-1", Purpose: "send approved message", AllowedEffects: []string{"send_message"}, ParameterConstraints: map[string]any{"recipient": []any{"alice@example.com"}}, ValidUntil: now.Add(time.Hour).Format(time.RFC3339), AuthorityRevision: "rev-1", EvidenceIDs: []string{"ev-1"}}
	if err := base.validate(Request{AgentID: "a-1", Tool: "send_message", Params: map[string]any{"recipient": "alice@example.com"}}, now); err != nil {
		t.Fatalf("valid intent rejected: %v", err)
	}
	if err := base.validate(Request{AgentID: "a-1", Tool: "send_message", Params: map[string]any{"recipient": "mallory@example.com"}}, now); err == nil {
		t.Fatal("expected parameter constraint rejection")
	}
	if err := base.validate(Request{AgentID: "a-1", Tool: "delete_file", Params: map[string]any{}}, now); err == nil {
		t.Fatal("expected effect rejection")
	}
}

func TestIntentContractRejectsExpiredOrDifferentAgent(t *testing.T) {
	now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
	i := IntentContract{IntentID: "i-1", TaskID: "t-1", Principal: "u", AgentID: "a-1", Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: now.Format(time.RFC3339), AuthorityRevision: "r"}
	if err := i.validate(Request{AgentID: "a-2", Tool: "read_file"}, now); err == nil {
		t.Fatal("expected agent mismatch")
	}
	if err := i.validate(Request{AgentID: "a-1", Tool: "read_file"}, now); err == nil {
		t.Fatal("expected expiry rejection")
	}
}
