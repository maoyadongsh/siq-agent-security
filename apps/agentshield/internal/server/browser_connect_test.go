package server

import (
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

var browserHeaders = map[string]string{"X-SIQ-Session": "1", "Origin": "http://127.0.0.1:47611"}
var cliHeaders = map[string]string{"X-SIQ-Local-CLI": "1"}

func beginConnectTest(t *testing.T, s *Server) (string, *http.Cookie) {
	t.Helper()
	w := sessionRequest(t, s, "POST", "/v1/session/connect/request", nil, "", nil, browserHeaders)
	if w.Code != 200 {
		t.Fatalf("create: %d", w.Code)
	}
	body := sessionBody(t, w)
	id, _ := body["request_id"].(string)
	if !connectIDPattern.MatchString(id) || body["status"] != "pending" || len(w.Result().Cookies()) != 1 {
		t.Fatal("invalid request")
	}
	cookie := w.Result().Cookies()[0]
	if len(cookie.Value) != 64 || cookie.Path != "/v1/session/connect" || !cookie.HttpOnly || cookie.SameSite != http.SameSiteStrictMode || cookie.MaxAge != 300 {
		t.Fatal("unsafe cookie")
	}
	if strings.Contains(w.Body.String(), cookie.Value) {
		t.Fatal("proof leaked to body")
	}
	return id, cookie
}

func TestBrowserConnectRequiresLocalApprovalAndSameBrowser(t *testing.T) {
	s := newUnpairedServer(t, "block")
	s.d.RecoveryToken = strings.Repeat("c", 64)
	id, cookie := beginConnectTest(t, s)
	body := map[string]string{"request_id": id}
	_, other := beginConnectTest(t, s)
	if w := sessionRequest(t, s, "POST", "/v1/session/connect/poll", body, "", cookie, browserHeaders); w.Code != 200 || sessionBody(t, w)["status"] != "pending" || len(s.sessions) != 0 {
		t.Fatal("pending request authorized")
	}
	for _, credential := range []string{"", s.d.Token, strings.Repeat("d", 64)} {
		if sessionRequest(t, s, "POST", "/v1/session/connect/approve", body, credential, nil, cliHeaders).Code != 401 {
			t.Fatal("wrong credential approved")
		}
	}
	for _, field := range []string{"Origin", "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest", "Sec-Fetch-User"} {
		headers := map[string]string{"X-SIQ-Local-CLI": "1", field: "same-origin"}
		if field == "Origin" {
			headers[field] = "http://127.0.0.1:47611"
		}
		if sessionRequest(t, s, "POST", "/v1/session/connect/approve", body, s.d.RecoveryToken, nil, headers).Code != 403 {
			t.Fatal("browser approved", field)
		}
	}
	approved := sessionRequest(t, s, "POST", "/v1/session/connect/approve", body, s.d.RecoveryToken, nil, cliHeaders)
	if approved.Code != 200 || sessionBody(t, approved)["status"] != "approved" || len(s.sessions) != 0 {
		t.Fatal("approval returned a session")
	}
	for _, badCookie := range []*http.Cookie{nil, other} {
		if sessionRequest(t, s, "POST", "/v1/session/connect/poll", body, "", badCookie, browserHeaders).Code != 401 {
			t.Fatal("another browser claimed request")
		}
	}
	var wg sync.WaitGroup
	results := make(chan int, 2)
	for range 2 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			results <- sessionRequest(t, s, "POST", "/v1/session/connect/poll", body, "", cookie, browserHeaders).Code
		}()
	}
	wg.Wait()
	close(results)
	success := 0
	for code := range results {
		if code == 200 {
			success++
		} else if code != 410 {
			t.Fatal("unexpected claim status", code)
		}
	}
	if success != 1 || len(s.sessions) != 1 || len(s.refreshSessions) != 1 {
		t.Fatal("claim must be single-use")
	}
	for _, expires := range s.sessions {
		if remaining := time.Until(expires); remaining < 24*time.Hour-time.Minute || remaining > 24*time.Hour {
			t.Fatal("not 24-hour fixed TTL")
		}
	}
	audit, err := os.ReadFile(filepath.Join(s.d.Store.Dir, "audit.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	for _, secret := range []string{cookie.Value, s.d.RecoveryToken} {
		if strings.Contains(string(audit), secret) {
			t.Fatal("audit leaked secret")
		}
	}
}

func TestBrowserConnectExpiryCancellationAndLimits(t *testing.T) {
	s := newUnpairedServer(t, "block")
	s.d.RecoveryToken = strings.Repeat("c", 64)
	id, cookie := beginConnectTest(t, s)
	body := map[string]string{"request_id": id}
	if w := sessionRequest(t, s, "POST", "/v1/session/connect/cancel", body, "", cookie, browserHeaders); w.Code != 200 {
		t.Fatal("cancel failed")
	}
	if sessionRequest(t, s, "POST", "/v1/session/connect/approve", body, s.d.RecoveryToken, nil, cliHeaders).Code != 410 {
		t.Fatal("cancelled request approved")
	}
	id, cookie = beginConnectTest(t, s)
	body["request_id"] = id
	request := s.connectRequests[id]
	request.Expires = time.Now().Add(-time.Second)
	s.connectRequests[id] = request
	if sessionRequest(t, s, "POST", "/v1/session/connect/approve", body, s.d.RecoveryToken, nil, cliHeaders).Code != 410 {
		t.Fatal("expired request approved")
	}
	if sessionRequest(t, s, "POST", "/v1/session/connect/poll", body, "", cookie, browserHeaders).Code != 410 {
		t.Fatal("expired request claimed")
	}
	for range 32 {
		beginConnectTest(t, s)
	}
	if sessionRequest(t, s, "POST", "/v1/session/connect/request", nil, "", nil, browserHeaders).Code != 429 {
		t.Fatal("unbounded requests")
	}
}

func TestBrowserConnectOriginMethodAndAuditFailures(t *testing.T) {
	s := newUnpairedServer(t, "block")
	s.d.RecoveryToken = strings.Repeat("c", 64)
	for _, headers := range []map[string]string{nil, {"X-SIQ-Session": "1", "Origin": "http://evil.example"}, {"X-SIQ-Session": "1", "Sec-Fetch-Site": "cross-site"}} {
		if sessionRequest(t, s, "POST", "/v1/session/connect/request", nil, "", nil, headers).Code != 403 {
			t.Fatal("unsafe request origin")
		}
	}
	if sessionRequest(t, s, "GET", "/v1/session/connect/request", nil, "", nil, browserHeaders).Code != 405 {
		t.Fatal("GET caused mutation")
	}
	id, cookie := beginConnectTest(t, s)
	body := map[string]string{"request_id": id}
	if sessionRequest(t, s, "POST", "/v1/session/connect/approve", map[string]string{"request_id": id, "unknown": "value"}, s.d.RecoveryToken, nil, cliHeaders).Code != 400 {
		t.Fatal("unknown fields accepted")
	}
	if err := os.Mkdir(filepath.Join(s.d.Store.Dir, "audit.jsonl"), 0o700); err != nil {
		t.Fatal(err)
	}
	if sessionRequest(t, s, "POST", "/v1/session/connect/approve", body, s.d.RecoveryToken, nil, cliHeaders).Code != 500 || s.connectRequests[id].Approved {
		t.Fatal("audit failure approved")
	}
	request := s.connectRequests[id]
	request.Approved = true
	s.connectRequests[id] = request
	if sessionRequest(t, s, "POST", "/v1/session/connect/poll", body, "", cookie, browserHeaders).Code != 500 || len(s.sessions) != 0 {
		t.Fatal("audit failure issued session")
	}
}

func TestBrowserConnectFixture(t *testing.T) {
	s := newUnpairedServer(t, "block")
	w := sessionRequest(t, s, "POST", "/v1/session/connect/request", nil, "", nil, browserHeaders)
	body := sessionBody(t, w)
	body["request_id"] = strings.Repeat("a", 32)
	body["expires_in"] = float64(299)
	raw, err := os.ReadFile("../../testdata/contracts/local-browser-connect.json")
	if err != nil {
		t.Fatal(err)
	}
	var expected map[string]any
	if json.Unmarshal(raw, &expected) != nil {
		t.Fatal("fixture invalid")
	}
	for key, value := range expected {
		if body[key] != value {
			t.Fatal("fixture drift", key)
		}
	}
	if len(body) != len(expected) {
		t.Fatal("extra response fields")
	}
}
