package server

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
)

// A real loopback transport and one deadline model the existing managed Pre
// HTTP budget. This test does not invoke a host, model or external tool.
func TestWorkBuddyWindowsFreshSessionHTTPBudget(t *testing.T) {
	f := newWindowsAuthorityHTTPFixtureForPlatform(t, "block", false, "workbuddy")
	server := httptest.NewServer(f.s.Handler())
	defer server.Close()
	session, _ := runtimeidentity.WorkBuddySessionID("fresh-budget-session")
	call, _ := runtimeidentity.WorkBuddyCallID("fresh-budget-session", "call-1")
	started := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	post := func(route string, body any) map[string]any {
		t.Helper()
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		req, err := http.NewRequestWithContext(ctx, "POST", server.URL+route, bytes.NewReader(raw))
		if err != nil {
			t.Fatal(err)
		}
		req.Host = "127.0.0.1:47611"
		req.Header.Set("Authorization", "Bearer "+f.credential)
		req.Header.Set("Content-Type", "application/json")
		resp, err := server.Client().Do(req)
		if err != nil {
			t.Fatalf("combined 4-second budget failed after %s at %s: %v", time.Since(started), route, err)
		}
		defer resp.Body.Close()
		var out map[string]any
		if err := json.NewDecoder(resp.Body).Decode(&out); err != nil || resp.StatusCode != 200 {
			t.Fatalf("%s: status=%d error=%v", route, resp.StatusCode, err)
		}
		t.Logf("%s cumulative elapsed=%s", route, time.Since(started).Round(time.Millisecond))
		return out
	}
	post("/v1/runtime-sessions", map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session})
	body := map[string]any{"platform": "workbuddy", "agent_id": f.agent, "session_id": session, "tool": "read_file", "tool_call_id": call, "params": map[string]any{"path": f.input}}
	out := post("/v1/decide", body)
	if out["action"] != "allow" || out["authority_status"] != "valid" {
		t.Fatal("budget result was not effective allow", out)
	}
}
