package server

import (
	"crypto/sha256"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func sessionRequest(t *testing.T, s *Server, method, path string, body any, bearer string, cookie *http.Cookie, headers map[string]string) *httptest.ResponseRecorder {
	t.Helper()
	r := loopbackRequest(method, path, body)
	if bearer != "" {
		r.Header.Set("Authorization", "Bearer "+bearer)
	}
	if cookie != nil {
		r.AddCookie(cookie)
	}
	for name, value := range headers {
		r.Header.Set(name, value)
	}
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	return w
}

func sessionBody(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatal("invalid JSON response")
	}
	return body
}

func rememberPair(t *testing.T, s *Server, code string) (string, *http.Cookie) {
	t.Helper()
	w := sessionRequest(t, s, "POST", "/v1/pair", map[string]any{"code": code, "remember": true}, "", nil, map[string]string{"X-SIQ-Session": "1"})
	if w.Code != 200 {
		t.Fatalf("pair status: %d", w.Code)
	}
	body := sessionBody(t, w)
	access, ok := body["session"].(string)
	if !ok || len(access) != 64 {
		t.Fatal("missing admin session")
	}
	cookies := w.Result().Cookies()
	if len(cookies) != 1 {
		t.Fatal("missing recovery cookie")
	}
	c := cookies[0]
	if c.Value == access || len(c.Value) != 64 || !c.HttpOnly || c.SameSite != http.SameSiteStrictMode ||
		c.Path != "/v1/session" || c.Domain != "" || c.MaxAge != 43200 {
		t.Fatal("invalid cookie scope")
	}
	return access, c
}

func TestSessionRestoreAndLogout(t *testing.T) {
	s := newUnpairedServer(t, "block")
	access, cookie := rememberPair(t, s, testPairingCode)
	headers := map[string]string{"X-SIQ-Session": "1", "Origin": "http://127.0.0.1:47611"}
	w := sessionRequest(t, s, "POST", "/v1/session/restore", nil, "", cookie, headers)
	if w.Code != 200 || sessionBody(t, w)["session"] != access || w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("refresh must recover paired session")
	}
	if len(w.Result().Cookies()) != 0 {
		t.Fatal("restoration must not extend cookie lifetime")
	}
	// Cookie access never falls back to authorization on privileged endpoints.
	for _, path := range []string{"/v1/status", "/v1/config", "/v1/decide", "/v1/session/logout"} {
		w := sessionRequest(t, s, "POST", path, nil, "", cookie, headers)
		if w.Code != 401 {
			t.Fatalf("cookie authorized %s: %d", path, w.Code)
		}
	}
	w = sessionRequest(t, s, "POST", "/v1/session/logout", nil, access, cookie, headers)
	if w.Code != 200 || len(w.Result().Cookies()) != 1 || w.Result().Cookies()[0].MaxAge != -1 {
		t.Fatal("logout must expire cookie")
	}
	if s.validAdminSession(access) {
		t.Fatal("logout did not revoke bearer")
	}
	w = sessionRequest(t, s, "POST", "/v1/session/restore", nil, "", cookie, headers)
	if w.Code != 401 {
		t.Fatal("revoked cookie restored access")
	}
}

func TestSessionRestoreRequiresHeaderAndSameOrigin(t *testing.T) {
	s := newUnpairedServer(t, "block")
	w := sessionRequest(t, s, "POST", "/v1/pair", map[string]any{"code": testPairingCode, "remember": true}, "", nil, nil)
	if w.Code != 403 {
		t.Fatal("remember must require explicit session header")
	}
	_, cookie := rememberPair(t, s, testPairingCode) // rejected request must not consume code
	for name, headers := range map[string]map[string]string{
		"missing-header": {},
		"cross-origin":   {"X-SIQ-Session": "1", "Origin": "http://evil.example"},
		"other-port":     {"X-SIQ-Session": "1", "Origin": "http://127.0.0.1:9999"},
		"fetch-site":     {"X-SIQ-Session": "1", "Sec-Fetch-Site": "cross-site"},
		"invalid-bearer": {"X-SIQ-Session": "1", "Authorization": "Bearer invalid"},
	} {
		t.Run(name, func(t *testing.T) {
			if w := sessionRequest(t, s, "POST", "/v1/session/restore", nil, "", cookie, headers); w.Code != 403 {
				t.Fatalf("request accepted: %d", w.Code)
			}
		})
	}
	if w := sessionRequest(t, s, "GET", "/v1/session/restore", nil, "", cookie, nil); w.Code != 405 {
		t.Fatal("GET restored session")
	}
}

func TestSessionLifetimeAndRestart(t *testing.T) {
	s := newUnpairedServer(t, "block")
	access, cookie := rememberPair(t, s, testPairingCode)
	hash := sha256.Sum256([]byte(cookie.Value))
	expires := time.Now().Add(10 * time.Minute)
	s.sessions[access] = expires
	s.refreshSessions[hash] = refreshSession{Access: access, Expires: expires}
	headers := map[string]string{"X-SIQ-Session": "1"}
	w := sessionRequest(t, s, "POST", "/v1/session/restore", nil, "", cookie, headers)
	remaining, _ := sessionBody(t, w)["expires_in"].(float64)
	if w.Code != 200 || remaining < 598 || remaining > 600 || !s.sessions[access].Equal(expires) {
		t.Fatal("restore extended lifetime")
	}
	s.sessions[access] = time.Now().Add(-time.Second)
	if w := sessionRequest(t, s, "POST", "/v1/session/restore", nil, "", cookie, headers); w.Code != 401 {
		t.Fatal("expired session restored")
	}
	restarted := newUnpairedServer(t, "block")
	if w := sessionRequest(t, restarted, "POST", "/v1/session/restore", nil, "", cookie, headers); w.Code != 401 {
		t.Fatal("cookie survived restart")
	}
}

func TestRenewPairingSeparatesCredentialsAndPreservesSessions(t *testing.T) {
	s := newUnpairedServer(t, "block")
	s.d.RecoveryToken = strings.Repeat("b", 64)
	access, cookie := rememberPair(t, s, testPairingCode)
	headers := map[string]string{"X-SIQ-Local-CLI": "1"}
	for _, credential := range []string{"", token, access, cookie.Value} {
		w := sessionRequest(t, s, "POST", "/v1/session/pairing", nil, credential, nil, headers)
		if w.Code != 401 {
			t.Fatal("wrong credential renewed pairing")
		}
	}
	for _, header := range []string{"Origin", "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest", "Sec-Fetch-User"} {
		h := map[string]string{"X-SIQ-Local-CLI": "1", header: "same-origin"}
		if header == "Origin" {
			h[header] = "http://127.0.0.1:47611"
		}
		w := sessionRequest(t, s, "POST", "/v1/session/pairing", nil, s.d.RecoveryToken, nil, h)
		if w.Code != 403 {
			t.Fatalf("browser metadata %s accepted", header)
		}
	}
	for _, path := range []string{"/v1/status", "/v1/decide"} {
		w := sessionRequest(t, s, "POST", path, nil, s.d.RecoveryToken, nil, nil)
		if w.Code != 401 {
			t.Fatal("recovery credential crossed capability boundary")
		}
	}
	w := sessionRequest(t, s, "POST", "/v1/session/pairing", nil, s.d.RecoveryToken, nil, headers)
	if w.Code != 200 {
		t.Fatalf("renew pairing: %d", w.Code)
	}
	code, _ := sessionBody(t, w)["code"].(string)
	if !s.validAdminSession(access) {
		t.Fatal("renew revoked independent session")
	}
	if _, err := s.RedeemPairing(testPairingCode); err == nil {
		t.Fatal("old code still accepted")
	}
	second, _ := rememberPair(t, s, code)
	if second == access {
		t.Fatal("new pairing reused another session")
	}
	sessionRequest(t, s, "POST", "/v1/session/logout", nil, second, nil, nil)
	if !s.validAdminSession(access) {
		t.Fatal("logout revoked independent session")
	}
	audit, err := os.ReadFile(filepath.Join(s.d.Store.Dir, "audit.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	for _, secret := range []string{s.d.RecoveryToken, code, access, cookie.Value} {
		if strings.Contains(string(audit), secret) {
			t.Fatal("audit leaked credential")
		}
	}
}

func TestRenewPairingAuditFailureDoesNotChangeCode(t *testing.T) {
	s := newUnpairedServer(t, "block")
	s.d.RecoveryToken = strings.Repeat("c", 64)
	if err := os.Mkdir(filepath.Join(s.d.Store.Dir, "audit.jsonl"), 0o700); err != nil {
		t.Fatal(err)
	}
	w := sessionRequest(t, s, "POST", "/v1/session/pairing", nil, s.d.RecoveryToken, nil, map[string]string{"X-SIQ-Local-CLI": "1"})
	if w.Code != 500 || s.PairingDisplay() != testPairingCode {
		t.Fatal("failed audit changed pairing")
	}
}

func TestLocalSessionContractFixtures(t *testing.T) {
	s := newUnpairedServer(t, "block")
	health := sessionBody(t, sessionRequest(t, s, "GET", "/healthz", nil, "", nil, nil))
	uiConfig := sessionBody(t, sessionRequest(t, s, "GET", "/ui-config.json", nil, "", nil, nil))
	pair := sessionRequest(t, s, "POST", "/v1/pair", map[string]any{"code": testPairingCode}, "", nil, nil)
	if len(pair.Result().Cookies()) != 0 {
		t.Fatal("legacy pairing set cookie")
	}
	session := sessionBody(t, pair)
	access, _ := session["session"].(string)
	session["session"] = strings.Repeat("a", 64) // fixture placeholders never contain real credentials
	logout := sessionBody(t, sessionRequest(t, s, "POST", "/v1/session/logout", nil, access, nil, nil))
	s.d.RecoveryToken = strings.Repeat("d", 64)
	renew := sessionBody(t, sessionRequest(t, s, "POST", "/v1/session/pairing", nil, s.d.RecoveryToken, nil, map[string]string{"X-SIQ-Local-CLI": "1"}))
	renew["code"] = "aaaa-bbbb-cccc-dddd"
	for name, body := range map[string]map[string]any{"health": health, "session": session, "logout": logout, "pairing": renew, "ui-config": uiConfig} {
		raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", "local-"+name+".json"))
		if err != nil {
			t.Fatal(err)
		}
		var expected map[string]any
		if json.Unmarshal(raw, &expected) != nil || !reflect.DeepEqual(expected, body) {
			t.Fatalf("%s differs from contract fixture", name)
		}
	}
}
