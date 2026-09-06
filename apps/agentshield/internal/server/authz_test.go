package server

import (
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPairingIssuesAdminSessionOnce(t *testing.T) {
	s := newUnpairedServer(t, "block")
	code, cfg := call(t, s, "GET", "/ui-config.json", "", nil)
	if code != 200 || cfg["pairing_required"] != true {
		t.Fatalf("pairing should be required: %d %v", code, cfg)
	}
	if _, ok := cfg["token"]; ok {
		t.Fatal("ui-config returned a credential before pairing")
	}
	code, out := call(t, s, "POST", "/v1/pair", "", map[string]any{"code": testPairingCode})
	if code != 200 {
		t.Fatalf("pair: %d %v", code, out)
	}
	session, _ := out["session"].(string)
	if len(session) < 32 {
		t.Fatalf("session too short: %v", out)
	}
	if code, again := call(t, s, "POST", "/v1/pair", "", map[string]any{"code": testPairingCode}); code != 401 {
		t.Fatalf("replayed pairing must fail: %d %v", code, again)
	}
	if code, st := call(t, s, "GET", "/v1/status", session, nil); code != 200 || st["local_mode"] != true {
		t.Fatalf("admin session must reach status: %d %v", code, st)
	}
}

func TestDecisionTokenCannotCallAdmin(t *testing.T) {
	s, _ := newServer(t, "block")
	req := loopbackRequest("GET", "/v1/status", nil)
	req.Header.Set("Authorization", "Bearer "+token)
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 || !strings.Contains(rr.Body.String(), "decision credential") {
		t.Fatalf("decision token must not reach admin endpoints: %d %s", rr.Code, rr.Body.String())
	}
	req = loopbackRequest("POST", "/v1/admit", map[string]any{"path": "/tmp"})
	req.Header.Set("Authorization", "Bearer "+token)
	rr = httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("decision token admit: %d %s", rr.Code, rr.Body.String())
	}
}

func TestAdminSessionCannotCallDecide(t *testing.T) {
	s, _ := newServer(t, "block")
	req := loopbackRequest("POST", "/v1/decide", map[string]any{"platform": "openclaw", "session_id": "s", "tool": "exec"})
	req.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 401 {
		t.Fatalf("admin session must not be a decision credential: %d %s", rr.Code, rr.Body.String())
	}
}

func TestHostAndOriginAreEnforced(t *testing.T) {
	s, _ := newServer(t, "block")
	req := loopbackRequest("POST", "/v1/pair", map[string]any{"code": "x"})
	req.Host = "attacker.test:47611"
	rr := httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("bad Host: %d", rr.Code)
	}
	req = loopbackRequest("POST", "/v1/config", map[string]any{"enforcement_mode": "warn"})
	req.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	req.Header.Set("Origin", "http://evil.example")
	rr = httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("bad Origin: %d %s", rr.Code, rr.Body.String())
	}
	req = loopbackRequest("POST", "/v1/config", map[string]any{"enforcement_mode": "warn"})
	req.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	req.Header.Set("Origin", "http://127.0.0.1:47611")
	rr = httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 200 {
		t.Fatalf("same-origin write: %d %s", rr.Code, rr.Body.String())
	}
	req = loopbackRequest("POST", "/v1/config", map[string]any{"enforcement_mode": "block"})
	req.Header.Set("Authorization", "Bearer "+s.bootAdmin)
	req.Header.Set("Sec-Fetch-Site", "cross-site")
	rr = httptest.NewRecorder()
	s.Handler().ServeHTTP(rr, req)
	if rr.Code != 403 {
		t.Fatalf("cross-site fetch metadata: %d %s", rr.Code, rr.Body.String())
	}
}

func TestPairingAttemptBudget(t *testing.T) {
	s := newUnpairedServer(t, "block")
	for i := 0; i < pairingMaxAttempts; i++ {
		if code, _ := call(t, s, "POST", "/v1/pair", "", map[string]any{"code": "wrong"}); code != 401 {
			t.Fatalf("attempt %d: %d", i, code)
		}
	}
	if code, out := call(t, s, "POST", "/v1/pair", "", map[string]any{"code": testPairingCode}); code != 401 {
		t.Fatalf("budget must lock pairing: %d %v", code, out)
	}
}
