package server

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func requestHTTPFixture(t *testing.T) (*Server, string, map[string]any, map[string]any) {
	t.Helper()
	s, issued, credential, _ := managedIdentityFixture(t, "block")
	id := issued["identity"].(map[string]any)["identity_id"]
	cap := map[string]any{"schema_version": "local-runtime-request-issuer-create/v1", "parent_identity_id": id, "scope_id": strings.Repeat("a", 24), "max_identity_seconds": float64(600), "expires_at": time.Now().UTC().Add(time.Hour).Format(time.RFC3339), "actor_id": "fixture-operator"}
	req := map[string]any{"schema_version": "local-runtime-request-identity-create/v1", "request_id": "qwen-request-2222222222222222", "execution_sha256": strings.Repeat("d", 64), "expires_at": time.Now().UTC().Add(300 * time.Second).Format(time.RFC3339)}
	return s, credential, cap, req
}
func assertRequestSample(t *testing.T, name string, value any) {
	t.Helper()
	raw, err := os.ReadFile("../../testdata/contracts/" + name + ".json")
	if err != nil {
		t.Fatal(err)
	}
	var expected any
	if json.Unmarshal(raw, &expected) != nil {
		t.Fatal("invalid shared fixture")
	}
	actualRaw, _ := json.Marshal(value)
	var actual any
	_ = json.Unmarshal(actualRaw, &actual)
	if !reflect.DeepEqual(expected, actual) {
		t.Fatal("shared contract sample differs", name)
	}
}
func TestRuntimeRequestHTTPAndSharedWireSamples(t *testing.T) {
	s, parent, cap, req := requestHTTPFixture(t)
	code, issuer := call(t, s, "POST", "/v1/runtime-request-issuers", token, cap)
	if code != 201 {
		t.Fatal(code, issuer)
	}
	if _, ok := issuer["signature"]; ok {
		t.Fatal("private signature returned")
	}
	code, issued := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", parent, req)
	if code != 201 {
		t.Fatal(code, issued)
	}
	code, retry := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", parent, req)
	if code != 201 || !reflect.DeepEqual(retry, issued) {
		t.Fatal("HTTP retry changed authority", code)
	}
	childBytes, err := os.ReadFile(issued["credential_path"].(string))
	if err != nil {
		t.Fatal(err)
	}
	child := string(childBytes)
	raw, _ := json.Marshal(issued)
	for _, private := range []string{parent, child, "credential_hash", "signature"} {
		if bytes.Contains(raw, []byte(private)) {
			t.Fatal("private material returned")
		}
	}
	scope := issued["request"].(map[string]any)
	session := scope["session_namespace"].(string) + ":" + strings.Repeat("b", 64)
	code, _ = scopedCall(t, s, "/v1/runtime-sessions", child, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": session})
	if code != 200 {
		t.Fatal("child session", code)
	}
	if code, _ = scopedCall(t, s, "/v1/runtime-sessions", child, map[string]any{"schema_version": "local-runtime-session-enroll/v1", "session_id": "other"}); code == 200 {
		t.Fatal("unscoped enrollment")
	}
	cancellation := map[string]any{"schema_version": "local-runtime-request-identity-cancel/v1", "request_id": req["request_id"], "execution_sha256": req["execution_sha256"]}
	code, cancelled := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests/cancel", parent, cancellation)
	if code != 200 || cancelled["issued"] != true || cancelled["cancelled"] != true {
		t.Fatal(code, cancelled)
	}
	if code, _ = selfCall(t, s, "GET", "/v1/runtime-identity/self", child, nil); code != 401 {
		t.Fatal("cancelled child active")
	}
	if code, _ = selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", parent, req); code != 409 {
		t.Fatal("late issuance", code)
	}
	// Normalize only generated identifiers/digests/timestamps. Field presence,
	// scalar types, fixed semantics and absence of private fields remain exact.
	cap["parent_identity_id"] = "ri-" + strings.Repeat("1", 32)
	cap["expires_at"] = "2026-09-23T12:00:00Z"
	issuer["parent_identity_id"] = cap["parent_identity_id"]
	issuer["parent_sha256"] = strings.Repeat("b", 64)
	issuer["expires_at"] = cap["expires_at"]
	issuer["created_at"] = "2026-09-23T11:00:00Z"
	req["expires_at"] = "2026-09-23T12:00:00Z"
	identity := issued["identity"].(map[string]any)
	identity["identity_id"] = "ri-" + strings.Repeat("3", 32)
	identity["instance_id"] = "hi-" + strings.Repeat("1", 32)
	identity["agent_id"] = "hri-" + strings.Repeat("1", 32)
	identity["created_at"] = "2026-09-23T11:55:00Z"
	identity["grant_ref"] = map[string]any{"grant_id": "grt-runtime-fixture", "admission_id": "adm-runtime-fixture", "permission_digest": strings.Repeat("a", 64)}
	scope["parent_identity_id"] = cap["parent_identity_id"]
	scope["parent_sha256"] = strings.Repeat("b", 64)
	scope["issuer_sha256"] = strings.Repeat("c", 64)
	scope["expires_at"] = req["expires_at"]
	issued["credential_path"] = "/synthetic/runtime-identity-secrets/ri-" + strings.Repeat("3", 32) + ".token"
	cancelled["identity_id"] = identity["identity_id"]
	for name, value := range map[string]any{"local-runtime-request-issuer-create": cap, "local-runtime-request-issuer": issuer, "local-runtime-request-identity-create": req, "local-runtime-request-identity-issued": issued, "local-runtime-request-identity-cancel": cancellation, "local-runtime-request-identity-cancelled": cancelled} {
		assertRequestSample(t, name, value)
	}
}
func TestRuntimeRequestHTTPAuthorizationAndStrictInput(t *testing.T) {
	s, parent, cap, req := requestHTTPFixture(t)
	if code, _ := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", parent, req); code == 201 {
		t.Fatal("ordinary identity delegated")
	}
	for _, cred := range []string{"", parent, token} {
		r := loopbackRequest("POST", "/v1/runtime-request-issuers", cap)
		r.Header.Set("Authorization", "Bearer "+cred)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code < 400 {
			t.Fatal("issuer setup bypassed admin boundary")
		}
	}
	if code, _ := call(t, s, "POST", "/v1/runtime-request-issuers", token, cap); code != 201 {
		t.Fatal(code)
	}
	cancel := map[string]any{"schema_version": "local-runtime-request-identity-cancel/v1", "request_id": req["request_id"], "execution_sha256": req["execution_sha256"]}
	for path, body := range map[string]map[string]any{"/v1/runtime-identity/self/requests": req, "/v1/runtime-identity/self/requests/cancel": cancel} {
		for _, cred := range []string{"", token, s.bootAdmin, parent[:36] + strings.Repeat("0", 64)} {
			if code, _ := selfCall(t, s, "POST", path, cred, body); code != 401 {
				t.Fatal("wrong bearer", code)
			}
		}
		for _, suffix := range []string{"?", "?x=1"} {
			if code, _ := selfCall(t, s, "POST", path+suffix, parent, body); code != 400 {
				t.Fatal("query accepted", code)
			}
		}
		if code, _ := selfCall(t, s, "GET", path, parent, nil); code != 405 {
			t.Fatal("wrong method")
		}
		for field := range body {
			for _, mode := range []string{"missing", "null", "case"} {
				bad := map[string]any{}
				for k, v := range body {
					bad[k] = v
				}
				switch mode {
				case "missing":
					delete(bad, field)
				case "null":
					bad[field] = nil
				case "case":
					delete(bad, field)
					bad[strings.ToUpper(field)] = body[field]
				}
				if code, _ := selfCall(t, s, "POST", path, parent, bad); code != 400 {
					t.Fatal("invalid required field accepted", field, mode, code)
				}
			}
		}
		for _, bad := range []string{`{}`, `{"schema_version":"x","schema_version":"x"}`, strings.Repeat(" ", 16385)} {
			if code, _ := selfCall(t, s, "POST", path, parent, bad); code != 400 {
				t.Fatal("invalid JSON accepted")
			}
		}
		bad := map[string]any{}
		for k, v := range body {
			bad[k] = v
		}
		bad["identity_id"] = "other"
		if code, _ := selfCall(t, s, "POST", path, parent, bad); code != 400 {
			t.Fatal("identity override accepted")
		}
		r := loopbackRequest("POST", path, body)
		r.Header.Add("Authorization", "Bearer "+parent)
		r.Header.Add("Authorization", "Bearer "+parent)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 401 {
			t.Fatal("duplicate bearer accepted")
		}
	}
	// Invalid and unauthorized cancellation requests above must have no effects.
	if code, _ := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", parent, req); code != 201 {
		t.Fatal("invalid request caused mutation", code)
	}
}
func TestRuntimeRequestHTTPUnknownCancellationAndExpiredResponse(t *testing.T) {
	s, parent, cap, req := requestHTTPFixture(t)
	if code, _ := call(t, s, "POST", "/v1/runtime-request-issuers", token, cap); code != 201 {
		t.Fatal(code)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	r := loopbackRequest("POST", "/v1/runtime-identity/self/requests", req).WithContext(ctx)
	r.Header.Set("Authorization", "Bearer "+parent)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code < 400 {
		t.Fatal("cancelled response accepted")
	}
	entries, err := os.ReadDir(filepath.Join(s.d.Store.Dir, "runtime-request-attempts"))
	if err != nil || len(entries) != 0 {
		t.Fatal("dead response mutated authority")
	}
	body := map[string]any{"schema_version": "local-runtime-request-identity-cancel/v1", "request_id": req["request_id"], "execution_sha256": req["execution_sha256"]}
	code, out := selfCall(t, s, "POST", "/v1/runtime-identity/self/requests/cancel", parent, body)
	if code != 200 || out["issued"] != false || out["cancelled"] != true {
		t.Fatal(code, out)
	}
	if code, _ = selfCall(t, s, "POST", "/v1/runtime-identity/self/requests", parent, req); code != 409 {
		t.Fatal("late issuance after absent cancellation")
	}
	path := filepath.Join(s.d.Store.Dir, "runtime-request-cancellations", out["identity_id"].(string)+".json")
	if err := os.WriteFile(path, []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	code, out = selfCall(t, s, "POST", "/v1/runtime-identity/self/requests/cancel", parent, body)
	if code != 503 || out["cancelled"] == true {
		t.Fatal("unknown persistence reported successful", code)
	}
}
