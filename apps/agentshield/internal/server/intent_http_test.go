package server

import (
	"net/http/httptest"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"testing"
)

func apiIntent() intent.Contract {
	return intent.Contract{SchemaVersion: "intent/v2", IntentID: "int-api", TaskID: "task-1", Principal: intent.Principal{Type: "user", ID: "u-1"}, Agent: intent.Agent{ID: "a-1", Platform: "hermes"}, Purpose: "approved report", AllowedTools: []string{"read_file"}, AllowedEffects: []string{"file.read"}, ResourceConstraints: []intent.ResourceConstraint{{Domain: "filesystem", Operator: "prefix", Value: "/company-a/"}}, ParameterConstraints: []intent.ParameterConstraint{}, IssuedAt: "2026-01-01T00:00:00Z", ValidFrom: "2026-01-01T00:00:00Z", ExpiresAt: "2099-01-01T00:00:00Z", Authority: intent.Authority{Issuer: "local-admin", Revision: "r1", EvidenceIDs: []string{}}}
}
func TestIntentManagementRequiresAdmin(t *testing.T) {
	s, _ := newServer(t, "block")
	for _, path := range []string{"/v1/intents", "/v1/intents/int-api", "/v1/intent-bindings", "/v1/intent-bindings/bind-1"} {
		for _, method := range []string{"GET", "POST"} {
			req := loopbackRequest(method, path, apiIntent())
			req.Header.Set("Authorization", "Bearer "+token)
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, req)
			if w.Code != 403 {
				t.Fatalf("%s %s: %d", method, path, w.Code)
			}
		}
	}
	list, err := s.intents.List()
	if err != nil || len(list) != 0 {
		t.Fatal("decision token created authority", err)
	}
}

func TestAuthorityHardGateHTTPModes(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			s, st := newServer(t, mode)
			eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: mode, IntentEnforcement: "required", IntentLookup: receipt.ResolveStore(s.intents)})
			if err != nil {
				t.Fatal(err)
			}
			s.d.Engine = eng
			r := map[string]any{"platform": "hermes", "session_id": "unbound", "agent_id": "a-1", "tool": "read_file", "params": map[string]any{"path": "/work/report"}}
			status, d := call(t, s, "POST", "/v1/decide", token, r)
			if status != 200 || d["action"] != "deny" || d["effective_action"] != "deny" || d["authority_status"] != "invalid" || d["authority_reason_code"] != "intent_binding_missing" || d["policy_action"] != nil || d["advisory_action"] != nil {
				t.Fatalf("invalid authority response: %d %v", status, d)
			}
			r["action_id"], r["decision_receipt_id"], r["result"] = d["action_id"], d["receipt_id"], "synthetic success"
			status, observed := call(t, s, "POST", "/v1/observe", token, r)
			if status != 400 || observed["reason_code"] != "observation_action_not_authorized" {
				t.Fatalf("denied action accepted success: %d %v", status, observed)
			}
			chain, err := s.d.Chain.Read()
			if err != nil || len(chain) != 1 || chain[0].AuthorityStatus != "invalid" {
				t.Fatal("denied observation changed signed chain", err)
			}
		})
	}
}
func TestIntentAdminLifecycleAndRuntimeRejection(t *testing.T) {
	s, st := newServer(t, "block")
	eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: "block", IntentEnforcement: "required", IntentLookup: receipt.ResolveStore(s.intents)})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = eng
	c := apiIntent()
	status, issued := call(t, s, "POST", "/v1/intents", s.bootAdmin, c)
	if status != 201 || issued["digest"] == "" {
		t.Fatalf("issue: %d %v", status, issued)
	}
	for _, path := range []string{"/v1/intents", "/v1/intents/int-api"} {
		status, _ = call(t, s, "GET", path, s.bootAdmin, nil)
		if status != 200 {
			t.Fatal(status)
		}
	}
	body := map[string]any{"platform": "hermes", "session_id": "s-1", "agent_id": "a-1", "intent_id": "int-api"}
	status, b := call(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, body)
	if status != 201 {
		t.Fatalf("bind %d %v", status, b)
	}
	for _, path := range []string{"/v1/intent-bindings", "/v1/intent-bindings/" + b["binding_id"].(string)} {
		status, _ = call(t, s, "GET", path, s.bootAdmin, nil)
		if status != 200 {
			t.Fatal(status)
		}
	}
	body["intent_digest"] = "forged"
	status, _ = call(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, body)
	if status != 400 {
		t.Fatal("accepted forged binding", status)
	}
	req := map[string]any{"platform": "hermes", "session_id": "s-1", "agent_id": "a-1", "tool": "read_file", "params": map[string]any{"path": "/company-b/secret"}}
	status, d := call(t, s, "POST", "/v1/decide", token, req)
	if status != 200 || d["action"] != "deny" || d["reason_code"] != "intent_resource_not_allowed" {
		t.Fatalf("resource: %d %v", status, d)
	}
	req["session_id"] = "unbound"
	status, d = call(t, s, "POST", "/v1/decide", token, req)
	if status != 200 || d["reason_code"] != "intent_binding_missing" {
		t.Fatal(status, d)
	}
	req["intent"] = map[string]any{"intent_id": "forged"}
	status, _ = call(t, s, "POST", "/v1/decide", token, req)
	if status != 400 {
		t.Fatal("inline status", status)
	}
	status, _ = call(t, s, "POST", "/v1/intents", s.bootAdmin, `{} {}`)
	if status != 400 {
		t.Fatal("trailing document", status)
	}
}
