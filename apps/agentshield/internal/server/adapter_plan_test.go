package server

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func adapterApplyCall(t *testing.T, s *Server, platform, action string) (int, map[string]any) {
	t.Helper()
	code, view := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": platform, "action": action})
	if code != 200 {
		t.Fatalf("preview: %d %v", code, view)
	}
	return call(t, s, "POST", "/v1/adapter/"+action, token, map[string]any{"platform": platform, "plan_id": view["plan_id"], "plan_digest": view["plan_digest"]})
}

func TestAdapterPlanRequiresSameAdminAndUnchangedConfiguration(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, route := range []string{"preview", "install", "uninstall", "recover"} {
		res := sessionRequest(t, s, "POST", "/v1/adapter/"+route, map[string]any{"platform": "hermes", "action": "install"}, token, nil, nil)
		if res.Code != 403 {
			t.Fatalf("decision credential reached %s: %d", route, res.Code)
		}
	}
	code, _ := call(t, s, "POST", "/v1/adapter/install", token, map[string]any{"platform": "hermes"})
	if code != 400 {
		t.Fatal("unreviewed install accepted")
	}
	code, view := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "hermes", "action": "install"})
	if code != 200 {
		t.Fatal(view)
	}
	if _, err := os.Stat(filepath.Join(s.d.Home, ".hermes")); !os.IsNotExist(err) {
		t.Fatal("preview changed platform")
	}
	body := map[string]any{"platform": "hermes", "plan_id": view["plan_id"], "plan_digest": view["plan_digest"]}
	s.sessMu.Lock()
	s.sessions["different-admin"] = time.Now().Add(time.Hour)
	s.sessMu.Unlock()
	if res := sessionRequest(t, s, "POST", "/v1/adapter/install", body, "different-admin", nil, nil); res.Code != 409 {
		t.Fatal("other session used preview")
	}
	path := filepath.Join(s.d.Home, ".hermes", "plugins", "siq-agent-security", "config.json")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("external edit"), 0600); err != nil {
		t.Fatal(err)
	}
	code, _ = call(t, s, "POST", "/v1/adapter/install", token, body)
	if code != 409 {
		t.Fatal("stale preview accepted")
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "external edit" {
		t.Fatal("external edit lost")
	}
}

func TestAdapterPlanModeChangeAndIdempotentReplay(t *testing.T) {
	s, store := newServer(t, "block")
	code, view := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "codebuddy", "action": "install"})
	if code != 200 {
		t.Fatal(view)
	}
	body := map[string]any{"platform": "codebuddy", "plan_id": view["plan_id"], "plan_digest": view["plan_digest"]}
	call(t, s, "PUT", "/v1/config", token, map[string]any{"enforcement_mode": "warn"})
	if code, _ := call(t, s, "POST", "/v1/adapter/install", token, body); code != 409 {
		t.Fatal("mode drift accepted")
	}
	call(t, s, "PUT", "/v1/config", token, map[string]any{"enforcement_mode": "block"})
	for range 2 {
		if code, res := call(t, s, "POST", "/v1/adapter/install", token, body); code != 200 {
			t.Fatalf("apply: %v", res)
		}
	}
	events, _ := store.TailAudit(100)
	count := 0
	for _, ev := range events {
		if ev.Event == "adapter_files_applied" {
			count++
		}
	}
	if count != 1 {
		t.Fatalf("retry reapplied: %d", count)
	}
}

func TestAdapterPlanFixture(t *testing.T) {
	s, _ := newServer(t, "block")
	code, view := call(t, s, "POST", "/v1/adapter/preview", token, map[string]any{"platform": "trae", "action": "install"})
	if code != 200 {
		t.Fatal(view)
	}
	view["plan_id"] = "ap-00000000000000000000000000000000"
	view["plan_digest"] = "0000000000000000000000000000000000000000000000000000000000000000"
	view["expires_at"] = "2026-09-10T09:00:00Z"
	raw, _ := json.MarshalIndent(view, "", "  ")
	path := filepath.Join("..", "..", "testdata", "contracts", "adapter-plan.json")
	if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
		if err := os.WriteFile(path, append(raw, '\n'), 0644); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil || string(expected) != string(append(raw, '\n')) {
		t.Fatal("adapter plan contract changed")
	}
}
