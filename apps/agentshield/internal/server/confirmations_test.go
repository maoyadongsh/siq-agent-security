package server

import (
	"encoding/json"
	"io"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
)

func confirmationHTTPFixture(t *testing.T) (*Server, map[string]any, string) {
	t.Helper()
	s, _ := newServer(t, "block")
	skill, _ := filepath.Abs(filepath.Join("..", "admission", "testdata", "skills", "benign", "official-like"))
	code, a := call(t, s, "POST", "/v1/admit", token, map[string]any{"path": skill})
	if code != 200 {
		t.Fatal(a)
	}
	code, g := call(t, s, "POST", "/v1/grants", token, map[string]any{"admission_id": a["admission"].(map[string]any)["admission_id"], "platform": "openclaw", "subject_id": "inbox-agent"})
	if code != 200 {
		t.Fatal(g)
	}
	gid := g["grant"].(map[string]any)["grant_id"].(string)
	code, a = approveChallenged(t, s, gid, "reviewer", stateRevision(t, g))
	if code != 200 {
		t.Fatal(a)
	}
	code, a = call(t, s, "POST", "/v1/grants/"+gid+"/deploy", token, withRevision(map[string]any{}, stateRevision(t, a)))
	if code != 200 {
		t.Fatal(a)
	}
	code, d := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "openclaw", "agent_id": "inbox-agent", "session_id": "inbox-session", "tool": "exec", "tool_call_id": "call-fixture", "params": map[string]any{"command": "printf fixture"}})
	if code != 200 || d["action"] != "hold" {
		t.Fatal(d)
	}
	code, items := call(t, s, "GET", "/v1/confirmations", token, nil)
	if code != 200 {
		t.Fatal(items)
	}
	item := items["items"].([]any)[0].(map[string]any)
	body := map[string]any{"schema_version": "local-confirmation-resolve/v1", "decision_receipt_id": item["decision_receipt_id"], "decision_hash": item["decision_hash"], "params_digest": item["params_digest"], "approve": true, "actor_id": "reviewer"}
	return s, body, "/v1/confirmations/" + item["action_id"].(string) + "/resolve"
}
func TestConfirmationHTTPStrictAndAdminOnly(t *testing.T) {
	s, body, route := confirmationHTTPFixture(t)
	for _, endpoint := range []string{"/v1/confirmations", route} {
		method := "GET"
		if endpoint == route {
			method = "POST"
		}
		r := loopbackRequest(method, endpoint, body)
		r.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 403 {
			t.Fatal("decision credential crossed admin boundary", w.Code)
		}
	}
	raw, _ := json.Marshal(body)
	cases := []string{strings.Replace(string(raw), `"approve":true`, `"approve":true,"approve":false`, 1), strings.Replace(string(raw), `"approve":true`, `"Approve":true`, 1), strings.Replace(string(raw), `"approve":true`, `"approve":null`, 1), strings.Replace(string(raw), `"approve":true,`, "", 1), string(raw) + " {}", strings.Replace(string(raw), `"actor_id":"reviewer"`, `"actor_id":"`+strings.Repeat("a", 17000)+`"`, 1)}
	for _, value := range cases {
		r := loopbackRequest("POST", route, nil)
		r.Body = io.NopCloser(strings.NewReader(value))
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("malformed confirmation accepted", w.Code)
		}
	}
	var wg sync.WaitGroup
	var count atomic.Int32
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			code, out := call(t, s, "POST", route, token, body)
			if code == 200 {
				count.Add(1)
			} else if code != 409 {
				t.Error(code, out)
			}
		}()
	}
	wg.Wait()
	if count.Load() != 1 {
		t.Fatal("duplicate approval", count.Load())
	}
	code, out := call(t, s, "GET", "/v1/confirmations", token, nil)
	if code != 200 || out["items"].([]any)[0].(map[string]any)["status"] != "approved" {
		t.Fatal(out)
	}
}
