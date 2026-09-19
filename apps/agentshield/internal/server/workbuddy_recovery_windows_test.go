package server

import (
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
)

func TestWorkBuddyRecoveryHTTPRequiresDiscoveredInstanceAndAdmin(t *testing.T) {
	t.Setenv("WORKBUDDY_CONFIG_DIR", "")
	t.Setenv("CODEBUDDY_CONFIG_DIR", "")
	s, _ := newServer(t, "block")
	root := filepath.Join(s.d.Home, ".workbuddy")
	if err := os.Mkdir(root, 0700); err != nil {
		t.Fatal(err)
	}
	body := map[string]any{"platform": "workbuddy", "instance_id": hermeshome.Identifier(root)}
	res := sessionRequest(t, s, "POST", "/v1/adapter/recover", body, token, nil, nil)
	if res.Code != 403 {
		t.Fatalf("decision token reached recovery: %d", res.Code)
	}
	res = sessionRequest(t, s, "POST", "/v1/adapter/recover", body, s.bootAdmin, nil, nil)
	if res.Code != 200 || res.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("valid discovered instance recovery: %d %s", res.Code, res.Body.String())
	}
	if code, got := call(t, s, "POST", "/v1/adapter/recover", token, map[string]any{"platform": "workbuddy"}); code != 400 {
		t.Fatalf("missing instance accepted: %d %v", code, got)
	}
	body["instance_id"] = hermeshome.Identifier(filepath.Join(s.d.Home, "foreign"))
	if code, got := call(t, s, "POST", "/v1/adapter/recover", token, body); code != 409 {
		t.Fatalf("foreign instance accepted: %d %v", code, got)
	}
	body["instance_id"] = hermeshome.Identifier(root)
	if err := os.Remove(root); err != nil {
		t.Fatal(err)
	}
	if code, got := call(t, s, "POST", "/v1/adapter/recover", token, body); code != 409 {
		t.Fatalf("missing root accepted: %d %v", code, got)
	}
}
