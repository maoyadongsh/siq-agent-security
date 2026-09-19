package server

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
)

func TestWorkBuddyCustomConfigThroughAdminAPI(t *testing.T) {
	if runtime.GOOS == "linux" {
		t.Skip("Linux WorkBuddy new integration is outside current product scope")
	}
	dir := filepath.Join(t.TempDir(), "custom-workbuddy")
	t.Setenv("WORKBUDDY_CONFIG_DIR", dir)
	s, store := newServer(t, "block")
	body := map[string]any{"platform": "workbuddy"}
	req := loopbackRequest("POST", "/v1/adapter/install", body)
	req.Header.Set("Authorization", "Bearer "+token)
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("decision credential installed hooks: %d", rr.Code)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("denied install touched config")
	}
	code, res := adapterApplyCall(t, s, "workbuddy", "install")
	if code != 200 {
		t.Fatalf("install: %d %v", code, res)
	}
	paths := res["paths"].([]any)
	if len(paths) != 1 || paths[0] != filepath.Join(dir, "settings.json") {
		t.Fatalf("wrong target: %v", paths)
	}
	raw, err := os.ReadFile(filepath.Join(dir, "settings.json"))
	if err != nil || !strings.Contains(string(raw), "hook workbuddy") || strings.Contains(string(raw), "hook codebuddy") {
		t.Fatalf("installed command: %s %v", raw, err)
	}
	if !strings.Contains(string(raw), "--state-dir") {
		t.Fatal("desktop hook missing --state-dir")
	}
	if _, err := os.Stat(filepath.Join(s.d.Home, ".workbuddy")); !os.IsNotExist(err) {
		t.Fatal("default home config touched")
	}
	code, status := call(t, s, "GET", "/v1/adapter/status", token, nil)
	if code != 200 {
		t.Fatal(status)
	}
	found := false
	for _, raw := range status["platforms"].([]any) {
		platform := raw.(map[string]any)
		if platform["name"] == "workbuddy" {
			found = platform["adapter"] == "installed"
			note, _ := platform["note"].(string)
			if !strings.Contains(note, "不能沿用 CodeBuddy") {
				t.Fatalf("workbuddy note lost independent verification: %v", platform)
			}
		}
	}
	if !found {
		t.Fatal("API status did not use custom WorkBuddy config")
	}
	code, res = adapterApplyCall(t, s, "workbuddy", "uninstall")
	if code != 200 || res["action"] != "uninstall" {
		t.Fatalf("uninstall: %d %v", code, res)
	}
	events, err := store.TailAudit(20)
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int{}
	for _, event := range events {
		if event.Event == "adapter_files_applied" {
			counts[event.Note]++
		}
	}
	if counts["workbuddy:install"] != 1 || counts["workbuddy:uninstall"] != 1 {
		t.Fatalf("expected only successful admin mutations in audit: %v", counts)
	}
}

func TestLinuxWorkBuddyNewInstallRejectedButLegacyUninstallAllowed(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux-only product scope gate")
	}
	dir := filepath.Join(t.TempDir(), "custom-workbuddy")
	t.Setenv("WORKBUDDY_CONFIG_DIR", dir)
	s, _ := newServer(t, "block")
	if code, _ := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "workbuddy", "action": "install"}); code != 400 {
		t.Fatalf("Linux WorkBuddy preview: got %d, want 400", code)
	}
	if code, _ := call(t, s, "POST", "/v1/adapter/install", token, map[string]any{"platform": "workbuddy", "plan_id": "old", "plan_digest": "old"}); code != 400 {
		t.Fatalf("Linux WorkBuddy install: got %d, want 400", code)
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("rejected install created WorkBuddy configuration")
	}
	if _, err := adapterinstall.Install(s.adapterOptions(adapterinstall.WorkBuddy)); err != nil {
		t.Fatalf("create historical WorkBuddy fixture: %v", err)
	}
	code, status := call(t, s, "GET", "/v1/adapter/status", token, nil)
	if code != 200 {
		t.Fatal(status)
	}
	found := false
	for _, raw := range status["platforms"].([]any) {
		platform := raw.(map[string]any)
		if platform["name"] != "workbuddy" {
			continue
		}
		found = true
		if platform["adapter"] != "installed" || !strings.Contains(platform["note"].(string), "Linux") {
			t.Fatalf("historical adapter not disclosed: %v", platform)
		}
		if platform["diagnosis"].(map[string]any)["configuration_state"] != "unsupported" {
			t.Fatalf("Linux diagnosis claimed support: %v", platform)
		}
	}
	if !found {
		t.Fatal("historical WorkBuddy adapter disappeared from status")
	}
	if code, out := adapterApplyCall(t, s, "workbuddy", "uninstall"); code != 200 || out["action"] != "uninstall" {
		t.Fatalf("historical uninstall: %d %v", code, out)
	}
}
