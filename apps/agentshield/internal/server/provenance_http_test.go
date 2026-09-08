package server

import (
	"net/http/httptest"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"testing"
	"time"
)

func TestProvenanceManagementCannotUseDecisionToken(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, path := range []string{"/v1/provenance-issuers", "/v1/provenance-issuers/i1", "/v1/provenance-issuers/i1/revoke", "/v1/provenance-assertions", "/v1/provenance-assertions/import", "/v1/provenance-resolve"} {
		for _, method := range []string{"GET", "POST"} {
			r := loopbackRequest(method, path, map[string]any{})
			r.Header.Set("Authorization", "Bearer "+token)
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, r)
			if w.Code != 403 {
				t.Fatal("decision credential reached management", method, path, w.Code)
			}
		}
	}
}
func TestProvenanceManagementToV3DecisionAndRevocation(t *testing.T) {
	s, st := newServer(t, "warn")
	eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: "warn", IntentEnforcement: "required", IntentLookup: receipt.ResolveStore(s.intents), ProvenanceCheck: s.provenance.MatchParameters})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = eng
	c := apiIntent()
	c.SchemaVersion = "intent/v3"
	constraints := []provenance.Constraint{{ParameterPath: "/path", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: true}}
	c.ProvenanceConstraints = &constraints
	post := func(path string, body any, want int) map[string]any {
		t.Helper()
		status, out := call(t, s, "POST", path, s.bootAdmin, body)
		if status != want {
			t.Fatalf("%s: %d %v", path, status, out)
		}
		return out
	}
	post("/v1/intents", c, 201)
	post("/v1/intent-bindings", map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": c.IntentID}, 201)
	scope := provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: c.TaskID}
	now := time.Now().UTC()
	expires := now.Add(time.Hour).Format(time.RFC3339)
	issuer := provenance.Issuer{IssuerID: "issuer-api", LocalKeyRef: "local-state", AllowedSourceTypes: []string{"USER", "MCP"}, MaxTrustLevel: "authoritative", Scope: scope, ExpiresAt: expires}
	post("/v1/provenance-issuers", issuer, 201)
	digest, _ := provenance.ContentDigest("/company-a/report")
	a := provenance.Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: "user-api", Source: provenance.Source{Type: "USER", SourceID: "form", Trust: "authoritative"}, Scope: scope, ContentDigest: digest, Parents: []string{}, Derivation: "direct", IssuedAt: now.Add(-time.Minute).Format(time.RFC3339), ExpiresAt: expires, Issuer: issuer.IssuerID}
	issued := post("/v1/provenance-assertions", a, 201)
	post("/v1/provenance-assertions/import", issued, 201)
	query := map[string]any{"provenance_id": a.ProvenanceID, "scope": scope}
	post("/v1/provenance-resolve", query, 200)
	r := map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "tool": "read_file", "tool_call_id": "tc-1", "params": map[string]any{"path": "/company-a/report"}, "parameter_provenance": []provenance.ParameterBinding{{ParameterPath: "/path", ProvenanceRefs: []string{a.ProvenanceID}}}}
	status, decision := call(t, s, "POST", "/v1/decide", token, r)
	if status != 200 || decision["authority_status"] != "valid" || decision["action"] != "allow" {
		t.Fatal("valid authority failed in advisory mode", status, decision)
	}
	post("/v1/provenance-issuers/issuer-api/revoke", map[string]any{}, 200)
	status, decision = call(t, s, "POST", "/v1/decide", token, r)
	if status != 200 || decision["action"] != "deny" || decision["authority_reason_code"] != "provenance_issuer_untrusted" {
		t.Fatal("revocation bypassed warn hard gate", status, decision)
	}
	post("/v1/provenance-resolve", query, 400)
	post("/v1/provenance-issuers", `{"issuer_id":"bad","scope":{},"unexpected":true}`, 400)
	post("/v1/provenance-issuers/issuer-api/revoke", `{} {}`, 400)
	r["parameter_provenance"] = []map[string]any{{"parameter_path": "/path", "provenance_refs": []string{}, "trust": "authoritative"}}
	status, _ = call(t, s, "POST", "/v1/decide", token, r)
	if status != 400 {
		t.Fatal("malformed binding reached signed receipt", status)
	}
}
