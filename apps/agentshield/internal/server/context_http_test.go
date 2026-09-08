package server

import (
	"net/http/httptest"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
	"testing"
)

func TestContextIssuanceIsAdminOnly(t *testing.T) {
	s, _ := newServer(t, "block")
	subject := trustedcontext.Subject{Platform: "hermes", SessionID: "s-1", AgentID: "a-1"}
	binding, _ := trustedcontext.RequestBinding(subject, "task-1", "read_file", "tc-1", map[string]any{"path": "/work/report"})
	a := trustedcontext.Assertion{SchemaVersion: "context-assertion/v1", AssertionID: "ctx-http", IssuerID: "local-admin", Subject: subject, TaskID: "task-1", Claims: trustedcontext.Claims{WorkspaceRoot: "/work"}, IssuedAt: "2026-01-01T00:00:00Z", ExpiresAt: "2099-01-01T00:00:00Z", RequestBinding: binding}
	for _, method := range []string{"GET", "POST"} {
		for _, path := range []string{"/v1/context-assertions", "/v1/context-assertions/ctx-http"} {
			r := loopbackRequest(method, path, a)
			r.Header.Set("Authorization", "Bearer "+token)
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, r)
			if w.Code != 403 {
				t.Fatal("decision token gained context authority", method, path, w.Code)
			}
		}
	}
	status, d := call(t, s, "POST", "/v1/context-assertions", s.bootAdmin, a)
	if status != 201 || d["signature"] == "" {
		t.Fatal(status, d)
	}
	status, got := call(t, s, "GET", "/v1/context-assertions/ctx-http", s.bootAdmin, nil)
	if status != 200 || got["signature"] != d["signature"] {
		t.Fatal("signed context readback", status, got)
	}
	status, _ = call(t, s, "POST", "/v1/context-assertions", s.bootAdmin, a)
	if status != 409 {
		t.Fatal("replaced assertion", status)
	}
	a.AssertionID = "ctx-forged"
	a.IssuerID = "trusted-host-i-say-so"
	status, _ = call(t, s, "POST", "/v1/context-assertions", s.bootAdmin, a)
	if status != 400 {
		t.Fatal("unknown issuer accepted", status)
	}
	status, _ = call(t, s, "POST", "/v1/context-assertions", s.bootAdmin, `{"claims":{"workspace_root":"/work","role":"admin"}}`)
	if status != 400 {
		t.Fatal("unknown claim accepted", status)
	}
}
