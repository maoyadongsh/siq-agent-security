package server

import (
	"encoding/json"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/receipt"
)

func effectCall(t *testing.T, s *Server, method, path, tok string, body any, want int) map[string]any {
	t.Helper()
	r := loopbackRequest(method, path, body)
	r.Header.Set("Authorization", "Bearer "+tok)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != want {
		t.Fatalf("%s %s: %d %s", method, path, w.Code, w.Body.String())
	}
	var out map[string]any
	if w.Body.Len() != 0 {
		if err := json.Unmarshal(w.Body.Bytes(), &out); err != nil {
			t.Fatal(err)
		}
	}
	return out
}
func TestEffectObserverHTTPSeparationScopeRevocationAndIncident(t *testing.T) {
	s, st := newServer(t, "block")
	eng, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: "block", IntentLookup: receipt.ResolveStore(s.intents)})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = eng
	effectCall(t, s, "POST", "/v1/intents", s.bootAdmin, apiIntent(), 201)
	effectCall(t, s, "POST", "/v1/intent-bindings", s.bootAdmin, map[string]any{"platform": "hermes", "session_id": "s1", "agent_id": "a-1", "intent_id": "int-api"}, 201)
	d, err := eng.Decide(receipt.Request{Platform: "hermes", SessionID: "s1", AgentID: "a-1", Tool: "write_file", ToolCallID: "call-1", Params: map[string]any{"path": "/company-a/report"}})
	if err != nil || d.Action != "deny" {
		t.Fatal(d, err)
	}
	a, err := eng.EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID)
	if err != nil || a.TaskID != "task-1" || len(a.Resources) != 1 {
		t.Fatal(a, err)
	}
	source := effectevidence.Source{Type: "host_observer", SourceID: "local-file-observer", Independence: "host_independent"}
	body := map[string]any{"source": source, "scope": provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a-1", TaskID: "task-1"}, "expires_in": 60}
	effectCall(t, s, "POST", "/v1/effect-observers", token, body, 403)
	issued := effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, body, 201)
	observer := issued["token"].(string)
	ref, _ := effectevidence.ResourceReference(a.Resources[0])
	e := effectevidence.Evidence{SchemaVersion: "effect-evidence/v1", EvidenceID: "eff-http", ActionID: a.ActionID, DecisionReceiptID: a.DecisionReceiptID, EffectType: "file.write", ResourceRef: ref, ExecutionState: "completed", Source: source, Coverage: "partial", Result: "expected", EvidenceDigest: strings.Repeat("a", 64), ObservedAt: time.Now().UTC().Format(time.RFC3339), SigningSchema: "local_canonical/v1"}
	for _, tok := range []string{token, s.bootAdmin} {
		effectCall(t, s, "POST", "/v1/effect-evidence", tok, e, 403)
	}
	bad := e
	bad.Source.Independence = "external_independent"
	effectCall(t, s, "POST", "/v1/effect-evidence", observer, bad, 403)
	bad = e
	bad.DecisionReceiptID = "forged"
	effectCall(t, s, "POST", "/v1/effect-evidence", observer, bad, 400)
	s.observerMu.Lock()
	wrong := s.observers[tokenDigest(observer)]
	wrong.Scope.TaskID = "wrong"
	s.observers[tokenDigest(observer)] = wrong
	s.observerMu.Unlock()
	effectCall(t, s, "POST", "/v1/effect-evidence", observer, e, 403)
	s.observerMu.Lock()
	wrong.Scope.TaskID = "task-1"
	s.observers[tokenDigest(observer)] = wrong
	s.observerMu.Unlock()
	record := effectCall(t, s, "POST", "/v1/effect-evidence", observer, e, 201)
	if record["finding_code"] != "unauthorized_effect_observed" {
		t.Fatal(record)
	}
	got := effectCall(t, s, "GET", "/v1/effect-evidence/eff-http", s.bootAdmin, nil, 200)
	if got["signature"] != record["signature"] {
		t.Fatal("record changed")
	}
	list := effectCall(t, s, "GET", "/v1/actions/"+a.ActionID+"/effect-evidence", s.bootAdmin, nil, 200)
	if len(list["items"].([]any)) != 1 {
		t.Fatal(list)
	}
	effectCall(t, s, "GET", "/v1/effect-evidence/eff-http", token, nil, 403)
	effectCall(t, s, "POST", "/v1/decide", observer, map[string]any{}, 401)
	revokedSession := s.observers[tokenDigest(observer)]
	effectCall(t, s, "DELETE", "/v1/effect-observers/"+issued["observer_id"].(string), s.bootAdmin, nil, 204)
	revoked, revokeErr := s.effects.ObserverRevoked(tokenDigest(observer))
	if revokeErr != nil || !revoked {
		t.Fatal("revocation not persisted", revokeErr)
	}
	// Simulate a stale in-memory credential entry; the durable tombstone must still reject it.
	s.observers[tokenDigest(observer)] = revokedSession
	effectCall(t, s, "POST", "/v1/effect-evidence", observer, e, 403)
	issued = effectCall(t, s, "POST", "/v1/effect-observers", s.bootAdmin, body, 201)
	observer = issued["token"].(string)
	restarted, restartErr := New(s.d)
	if restartErr != nil {
		t.Fatal(restartErr)
	}
	effectCall(t, restarted, "POST", "/v1/effect-evidence", observer, e, 403)
	persisted, readErr := restarted.effects.Get(e.EvidenceID, time.Now())
	if readErr != nil || persisted.FindingCode != "unauthorized_effect_observed" {
		t.Fatal("evidence lost across server restart", persisted, readErr)
	}
	s.observerMu.Lock()
	expired := s.observers[tokenDigest(observer)]
	expired.Expires = time.Now().Add(-time.Second)
	s.observers[tokenDigest(observer)] = expired
	s.observerMu.Unlock()
	effectCall(t, s, "POST", "/v1/effect-evidence", observer, e, 403)
}
