package server

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

func TestBindingRevocationHTTPAuthorityAndDenial(t *testing.T) {
	s, st := newServer(t, "block")
	eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: "block", IntentEnforcement: "optional", IntentLookup: receipt.ResolveStore(s.intents)})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = eng
	code, issued := call(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent())
	if code != 201 {
		t.Fatal(code, issued)
	}
	bindingBody := map[string]any{"platform": "hermes", "session_id": "revoke-session", "agent_id": "a-1", "intent_id": "int-api"}
	code, b := call(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, bindingBody)
	if code != 201 {
		t.Fatal(code, b)
	}
	path := "/v1/intent-bindings/" + b["binding_id"].(string)
	if code, _ = call(t, s, "GET", path+"/revocation", s.bootAdmin, nil); code != 404 {
		t.Fatal("nonexistent revocation must 404", code)
	}
	body := map[string]any{"expected_intent_digest": issued["digest"]}
	for _, bearer := range []string{"", token} {
		for _, route := range []string{"/revoke", "/revocation"} {
			method := "POST"
			if route == "/revocation" {
				method = "GET"
			}
			req := loopbackRequest(method, path+route, body)
			if bearer != "" {
				req.Header.Set("Authorization", "Bearer "+bearer)
			}
			out := httptest.NewRecorder()
			s.Handler().ServeHTTP(out, req)
			want := 401
			if bearer == token {
				want = 403
			}
			if out.Code != want {
				t.Fatalf("untrusted credential reached revocation: %d", out.Code)
			}
		}
	}
	if code, _ = call(t, s, "GET", path+"/revocation", s.bootAdmin, nil); code != 404 {
		t.Fatal("unauthorized request wrote revocation")
	}
	for _, bad := range []any{map[string]any{}, map[string]any{"expected_intent_digest": "bad"}, map[string]any{"expected_intent_digest": issued["digest"], "signature": "forged"}, `{} {}`} {
		if code, _ = call(t, s, "POST", path+"/revoke", s.bootAdmin, bad); code != 400 {
			t.Fatal("invalid revoke request accepted", code)
		}
	}
	code, out := call(t, s, "POST", path+"/revoke", s.bootAdmin, map[string]any{"expected_intent_digest": strings.Repeat("0", 64)})
	if code != 409 || out["reason_code"] != "intent_binding_revoke_conflict" {
		t.Fatal(code, out)
	}
	code, revoked := call(t, s, "POST", path+"/revoke", s.bootAdmin, body)
	if code != 200 || revoked["reason_code"] != "intent_binding_revoked" || revoked["signature"] == "" {
		t.Fatal(code, revoked)
	}
	expected, _ := json.Marshal(revoked)
	for _, request := range []struct {
		method, path string
		body         any
	}{{"POST", path + "/revoke", body}, {"GET", path + "/revocation", nil}} {
		code, out = call(t, s, request.method, request.path, s.bootAdmin, request.body)
		raw, _ := json.Marshal(out)
		if code != 200 || string(raw) != string(expected) {
			t.Fatal("idempotent read/revoke changed signed audit record")
		}
	}
	code, original := call(t, s, "GET", path, s.bootAdmin, nil)
	originalRaw, _ := json.Marshal(original)
	bindingRaw, _ := json.Marshal(b)
	if code != 200 || string(originalRaw) != string(bindingRaw) {
		t.Fatal("revocation rewrote binding")
	}
	code, out = call(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, bindingBody)
	if code != 400 || out["reason_code"] != "intent_binding_revoked" {
		t.Fatal("revoked identity rebound", code, out)
	}
	code, d := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "hermes", "session_id": "revoke-session", "agent_id": "a-1", "tool": "read_file", "params": map[string]any{"path": "/company-a/report"}})
	if code != 200 || d["action"] != "deny" || d["reason_code"] != "intent_binding_revoked" {
		t.Fatal("optional downgrade after revoke", code, d)
	}
	records, err := s.d.Chain.Read()
	if err != nil || len(records) != 1 || records[0].IntentBinding != "bound" || records[0].ReceiptID != d["receipt_id"] {
		t.Fatal("revocation denial receipt lost binding metadata", err)
	}
}
