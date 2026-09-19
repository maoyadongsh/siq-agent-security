package server

import (
	"siq-agent-security/apps/agentshield/internal/intent"
	"testing"
)

// Synthetic host context for HTTP tests, not native-host evidence.
func nativeOpenClawSession(t *testing.T, key string) string {
	t.Helper()
	session, err := intent.OpenClawSessionID(key, "11111111-1111-4111-8111-111111111111")
	if err != nil {
		t.Fatal(err)
	}
	return session
}

func TestOpenClawRawSessionHTTPHardDeny(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		s, _ := newServer(t, mode)
		code, out := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "session_id": "agent:fixture:main", "agent_id": "fixture", "tool": "read", "params": map[string]any{"path": "/work/report"}})
		if code != 200 || out["action"] != "deny" || out["reason_code"] != "native_session_epoch_required" {
			t.Fatalf("%s: %d %v", mode, code, out)
		}
	}
}
