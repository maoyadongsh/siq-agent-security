package server

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestCodeBuddyNewIntegrationRejectedButHistoricalUninstallAllowed(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "custom-codebuddy")
	t.Setenv("CODEBUDDY_CONFIG_DIR", dir)
	s, store := newServer(t, "block")
	body := map[string]any{"platform": "codebuddy"}
	req := loopbackRequest("POST", "/v1/adapter/install", body)
	req.Header.Set("Authorization", "Bearer "+token)
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("decision credential reached adapter mutation: %d", rr.Code)
	}
	if code, _ := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "codebuddy", "action": "install"}); code != 400 {
		t.Fatalf("CodeBuddy preview: got %d, want 400", code)
	}
	if code, _ := call(t, s, "POST", "/v1/adapter/install", token, map[string]any{"platform": "codebuddy", "plan_id": "old", "plan_digest": "old"}); code != 400 {
		t.Fatalf("CodeBuddy install: got %d, want 400", code)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("rejected CodeBuddy install touched config")
	}
	// A direct package fixture represents a historical installation predating
	// the product scope decision; public new-install entrypoints stay closed.
	if _, err := adapterinstall.Install(s.adapterOptions(adapterinstall.CodeBuddy)); err != nil {
		t.Fatalf("create historical CodeBuddy fixture: %v", err)
	}
	code, status := call(t, s, "GET", "/v1/adapter/status", token, nil)
	if code != 200 {
		t.Fatal(status)
	}
	found := false
	for _, raw := range status["platforms"].([]any) {
		platform := raw.(map[string]any)
		if platform["name"] != "codebuddy" {
			continue
		}
		found = true
		if platform["adapter"] != "installed" || !strings.Contains(platform["note"].(string), "退出全平台") {
			t.Fatalf("historical adapter not disclosed: %v", platform)
		}
		if platform["diagnosis"].(map[string]any)["configuration_state"] != "unsupported" {
			t.Fatalf("CodeBuddy diagnosis claimed support: %v", platform)
		}
	}
	if !found {
		t.Fatal("historical CodeBuddy adapter disappeared from status")
	}
	if code, out := adapterApplyCall(t, s, "codebuddy", "uninstall"); code != 200 || out["action"] != "uninstall" {
		t.Fatalf("historical uninstall: %d %v", code, out)
	}
	events, err := store.TailAudit(20)
	if err != nil {
		t.Fatal(err)
	}
	installs, uninstalls := 0, 0
	for _, event := range events {
		if event.Event != "adapter_files_applied" {
			continue
		}
		switch event.Note {
		case "codebuddy:install":
			installs++
		case "codebuddy:uninstall":
			uninstalls++
		}
	}
	if installs != 1 || uninstalls != 1 {
		t.Fatalf("unexpected historical mutation counts: install=%d uninstall=%d", installs, uninstalls)
	}
}

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
