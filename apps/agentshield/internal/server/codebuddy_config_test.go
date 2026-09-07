package server

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestCodeBuddyCustomConfigThroughAdminAPI(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "custom-codebuddy")
	t.Setenv("CODEBUDDY_CONFIG_DIR", dir)
	s, store := newServer(t, "block")
	body := map[string]any{"platform": "codebuddy"}
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
	code, res := call(t, s, "POST", "/v1/adapter/install", token, body)
	if code != 200 {
		t.Fatalf("install: %d %v", code, res)
	}
	paths := res["paths"].([]any)
	if len(paths) != 1 || paths[0] != filepath.Join(dir, "settings.json") {
		t.Fatalf("wrong target: %v", paths)
	}
	if _, err := os.Stat(filepath.Join(s.d.Home, ".codebuddy")); !os.IsNotExist(err) {
		t.Fatal("default home config touched")
	}
	code, status := call(t, s, "GET", "/v1/adapter/status", token, nil)
	if code != 200 {
		t.Fatal(status)
	}
	found := false
	for _, raw := range status["platforms"].([]any) {
		platform := raw.(map[string]any)
		if platform["name"] == "codebuddy" {
			found = platform["adapter"] == "installed"
		}
	}
	if !found {
		t.Fatal("API status did not use custom config")
	}
	code, res = call(t, s, "POST", "/v1/adapter/uninstall", token, body)
	if code != 200 || res["action"] != "uninstall" {
		t.Fatalf("uninstall: %d %v", code, res)
	}
	events, err := store.TailAudit(20)
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int{}
	for _, event := range events {
		if event.Target == "codebuddy" {
			counts[event.Event]++
		}
	}
	if counts["adapter_install"] != 1 || counts["adapter_uninstall"] != 1 {
		t.Fatalf("expected only successful admin mutations in audit: %v", counts)
	}
}
