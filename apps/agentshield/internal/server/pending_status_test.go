package server

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/pending"
)

func TestPendingPromotionFailureIsVisibleAndRecoverable(t *testing.T) {
	s, store := newServer(t, "block")
	status := s.pendingPromotionSnapshot()
	if status.Status != "unknown" || status.Attempts != 0 {
		t.Fatal("unattempted promotion claimed success")
	}
	dir := filepath.Join(store.Dir, "pending")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "decisions.jsonl")
	if err := os.WriteFile(path, []byte("private-malformed-fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	s.promotePendingBestEffort()
	code, body := call(t, s, "GET", "/v1/status", token, nil)
	if code != 200 {
		t.Fatal(code)
	}
	state := body["pending_promotion"].(map[string]any)
	if state["status"] != "failed" || state["failures"] != float64(1) {
		t.Fatal(state)
	}
	raw, err := os.ReadFile(path)
	if err != nil || !strings.Contains(string(raw), "private-malformed-fixture") {
		t.Fatal("failed event lost")
	}
	// Repair only this test fixture; production diagnostics never discard input.
	if err := os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	if err := pending.Append(store.Dir, pending.Record{Platform: "hermes", Outcome: "deny", Reason: "service_unavailable", EnforcementMode: "block"}); err != nil {
		t.Fatal(err)
	}
	s.promotePendingBestEffort()
	state2 := s.pendingPromotionSnapshot()
	if state2.Status != "ok" || state2.Attempts != 2 || state2.Failures != 1 || state2.LastPromoted != 1 {
		t.Fatal(state2)
	}
}
