package server

import (
	"net/http/httptest"
	"testing"
)

func TestWorkBuddyLegacyGlobalDecisionTupleUnchanged(t *testing.T) {
	s := &Server{d: Deps{Token: "legacy-test-token"}}
	body := map[string]any{"platform": "workbuddy", "agent_id": "legacy-agent", "session_id": "raw-host-session", "tool_call_id": "raw-call", "tool": "read_file", "params": map[string]any{"path": "/legacy"}}
	r := loopbackRequest("POST", "/v1/decide", body)
	w := httptest.NewRecorder()
	if !s.authorizeDecision(w, r, "legacy-test-token") {
		t.Fatal("legacy global WorkBuddy parsing changed", w.Code, w.Body.String())
	}
	if workBuddyDecisionCall([]byte(`{"tool_call_id":"raw-call"}`)) {
		t.Fatal("managed call parser fell back to raw legacy ID")
	}
}
