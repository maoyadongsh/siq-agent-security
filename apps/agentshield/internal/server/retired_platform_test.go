package server

import (
	"bytes"
	"encoding/json"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestCodeBuddyNewGrantAndHistoricalActivationRejected(t *testing.T) {
	s, store := newServer(t, "block")
	if code, out := call(t, s, "POST", "/v1/grants", token, map[string]any{
		"admission_id": "missing", "platform": "codebuddy", "subject_id": "historical-agent",
	}); code != 400 || out["error"] != "platform_out_of_scope" {
		t.Fatalf("new CodeBuddy grant was not rejected before state lookup: %d %v", code, out)
	}
	legacy := grant.Grant{
		GrantID: "grt-historical-codebuddy", AdmissionID: "adm-historical", Platform: "codebuddy",
		Subject: grant.Subject{Type: "agent_instance", ID: "historical-agent"},
		Status:  "draft", DefaultEffect: "deny", EnforcementMode: "block",
	}
	if err := store.PutGrant(legacy); err != nil {
		t.Fatal(err)
	}
	path := "/v1/grants/" + legacy.GrantID
	if code, out := call(t, s, "GET", path, token, nil); code != 200 || out["grant"].(map[string]any)["platform"] != "codebuddy" {
		t.Fatalf("historical grant unreadable: %d %v", code, out)
	}
	for _, action := range []string{"draft", "challenge", "approve", "require-approval"} {
		if code, out := call(t, s, "POST", path+"/"+action, token, map[string]any{}); code != 400 || out["error"] != "platform_out_of_scope" {
			t.Fatalf("historical CodeBuddy %s not blocked: %d %v", action, code, out)
		}
	}
	if code, out := call(t, s, "POST", path+"/reject", token, withRevision(map[string]any{"actor_id": "admin"}, 0)); code != 200 {
		t.Fatalf("historical grant cannot be rejected: %d %v", code, out)
	}
}

func TestRetiredPlatformHasNoAdapterEntry(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, endpoint := range []string{"/v1/adapter/status", "/v1/adapter/diagnostics"} {
		code, out := call(t, s, "GET", endpoint, token, nil)
		if code != 200 {
			t.Fatalf("%s: %d %v", endpoint, code, out)
		}
		raw, _ := json.Marshal(out)
		if bytes.Contains(raw, []byte(`"codebuddy"`)) {
			t.Fatalf("retired platform exposed by %s", endpoint)
		}
	}
	for _, action := range []string{"install", "uninstall"} {
		code, out := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "codebuddy", "action": action})
		if code != 400 {
			t.Fatalf("retired %s preview accepted: %d %v", action, code, out)
		}
	}
}
