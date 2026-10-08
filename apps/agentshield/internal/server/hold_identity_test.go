package server

import (
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestHoldHTTPRejectsAmbiguousHistoricalIdentity(t *testing.T) {
	s, _ := newServer(t, "block")
	held := receipt.Receipt{ReceiptID: "legacy-duplicate", RecordType: "decision",
		ActionID: "action-one", Action: receipt.ActionHold, Tool: "exec", Platform: "openclaw",
		SessionID: nativeOpenClawSession(t, "collision"), IssuedAt: time.Now().UTC().Format(time.RFC3339)}
	if err := s.d.Chain.Append(&held); err != nil {
		t.Fatal(err)
	}
	held.ActionID = "action-two"
	if err := s.d.Chain.Append(&held); err != nil {
		t.Fatal(err)
	}
	seq, head := s.d.Chain.Head()
	code, _ := call(t, s, "POST", "/v1/hold/legacy-duplicate", s.bootAdmin,
		map[string]any{"approve": true, "actor_id": "test-reviewer"})
	if code != 409 {
		t.Fatalf("ambiguous approval returned %d; want conflict", code)
	}
	if afterSeq, afterHead := s.d.Chain.Head(); afterSeq != seq || afterHead != head {
		t.Fatal("ambiguous HTTP approval mutated chain")
	}
}
