package server

import (
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/state"
)

func selectedGrantFixture(t *testing.T, s *Server, store *state.Store, suffix, path string, approval bool, subjects ...string) (grant.Grant, int) {
	t.Helper()
	subject := "a-1"
	if len(subjects) > 0 {
		subject = subjects[0]
	}
	facts := []admission.DeclaredFact{}
	for _, tool := range []string{"read_file", "write_file", "web_fetch"} {
		facts = append(facts, admission.DeclaredFact{Domain: "tool", Action: "tool.invoke", Resource: admission.Resource{Type: "tool", Value: tool}, Effect: "allow", State: "declared", Authority: "skill_manifest"})
	}
	facts = append(facts, admission.DeclaredFact{Domain: "filesystem", Action: "fs.write", Resource: admission.Resource{Type: "path", Value: path}, Effect: "allow", State: "declared", Authority: "skill_manifest"})
	r, err := grant.Build(admission.Admission{AdmissionID: "adm-" + suffix, ContentHash: strings.Repeat(suffix, 64), Verdict: "admit", DeclaredFacts: facts}, grant.Options{Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: subject}, Now: time.Date(2026, 9, 10, int(suffix[0]-'a'), 0, 0, 0, time.UTC), Key: s.d.Key})
	if err != nil {
		t.Fatal(err)
	}
	g := r.Grant
	if approval {
		g, err = grant.RequireToolApproval(g, []string{"read_file"}, s.d.Key)
		if err != nil {
			t.Fatal(err)
		}
	}
	g, err = grant.Approve(g, grant.Approval{ActorType: "human", ActorID: "fixture-operator", ApprovedAt: time.Now().UTC().Format(time.RFC3339), Channel: "console"}, s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	g, err = grant.MarkDeployed(g, s.d.Key)
	if err != nil {
		t.Fatal(err)
	}
	seq, err := store.PutGrantCAS(g, -1)
	if err != nil {
		t.Fatal(err)
	}
	return g, seq
}

func selectedBindingRequest(g grant.Grant, revision int, session string) map[string]any {
	return map[string]any{"schema_version": "intent-grant-bind/v1", "platform": g.Platform, "session_id": session, "agent_id": g.Subject.ID, "intent_id": "int-api", "grant_id": g.GrantID, "expected_grant_revision": revision}
}

func grantBindingServer(t *testing.T, mode string) (*Server, *state.Store) {
	t.Helper()
	s, st := newServer(t, mode)
	engine, err := receipt.New(receipt.Options{Pack: s.d.Pack, Chain: s.d.Chain, Grants: st.ActiveGrant, EnforcementMode: mode, IntentEnforcement: "optional", IntentLookup: receipt.ResolveStore(s.intents)})
	if err != nil {
		t.Fatal(err)
	}
	s.d.Engine = engine
	c := apiIntent()
	c.AllowedTools = []string{"read_file", "write_file", "web_fetch"}
	c.AllowedEffects = []string{"file.read", "file.write", "network.request"}
	c.ResourceConstraints = []intent.ResourceConstraint{}
	if code, out := call(t, s, "POST", "/v1/intents", token, c); code != 201 {
		t.Fatal(out)
	}
	return s, st
}

func TestSessionGrantSelectionCannotBorrowOrResurrectAuthority(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			s, st := grantBindingServer(t, mode)
			narrow, nrev := selectedGrantFixture(t, s, st, "a", "/work/public", false)
			broad, brev := selectedGrantFixture(t, s, st, "b", "/work", false)
			for _, selection := range []struct {
				g       grant.Grant
				rev     int
				session string
			}{{narrow, nrev, "narrow"}, {broad, brev, "broad"}} {
				if code, out := call(t, s, "POST", "/v1/intent-bindings", token, selectedBindingRequest(selection.g, selection.rev, selection.session)); code != 201 {
					t.Fatal(code, out)
				}
			}
			for _, session := range []string{"narrow", "broad"} {
				_, out := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "hermes", "agent_id": "a-1", "session_id": session, "tool": "read_file", "params": map[string]any{"path": "/work/private/report", "skill_id": "forged-broad-skill"}})
				want := "allow"
				if session == "narrow" && mode == "block" {
					want = "deny"
				}
				if out["action"] != want {
					t.Fatal(session, out)
				}
				if session == "narrow" && mode != "block" && out["policy_action"] != "deny" {
					t.Fatal("lost policy advisory", out)
				}
				records, err := s.d.Chain.Read()
				if err != nil || len(records) == 0 {
					t.Fatal("missing signed decision", err)
				}
				last := records[len(records)-1]
				if last.ReceiptID != out["receipt_id"] || last.MatchedGrantID == nil {
					t.Fatal("missing correlated grant identity")
				}
				matched := *last.MatchedGrantID
				expected := narrow.GrantID
				if session == "broad" {
					expected = broad.GrantID
				}
				if matched != expected {
					t.Fatal("selected different grant", out)
				}
			}
			code, out := call(t, s, "POST", "/v1/grants/"+narrow.GrantID+"/revoke", token, withRevision(map[string]any{"actor_id": "fixture-operator"}, nrev))
			if code != 200 {
				t.Fatal(out)
			}
			if st.ActiveGrant("hermes", "a-1") == nil {
				t.Fatal("test requires another legacy active grant")
			}
			_, out = call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "hermes", "agent_id": "a-1", "session_id": "narrow", "tool": "read_file", "params": map[string]any{"path": "/work/public/report"}})
			if out["action"] != "deny" || out["authority_status"] != "invalid" || out["authority_reason_code"] != "intent_grant_inactive" || out["advisory_action"] != nil {
				t.Fatal("revoked selection borrowed old grant", out)
			}
		})
	}
}

func TestGrantBindingHTTPRejectsNonAdminConflictAndMutation(t *testing.T) {
	s, st := grantBindingServer(t, "block")
	g, rev := selectedGrantFixture(t, s, st, "a", "/work", false)
	body := selectedBindingRequest(g, rev, "selected")
	for _, field := range []string{"schema_version", "grant_id", "expected_grant_revision"} {
		body := map[string]any{"platform": "hermes", "session_id": "null-selection", "agent_id": "a-1", "intent_id": "int-api", field: nil}
		if code, out := call(t, s, "POST", "/v1/intent-bindings", token, body); code != 400 {
			t.Fatal("null selection became legacy authority", code, out)
		}
	}
	req := loopbackRequest("POST", "/v1/intent-bindings", body)
	req.Header.Set("Authorization", "Bearer "+token)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, req)
	if w.Code != 403 {
		t.Fatal("decision credential selected grant")
	}
	for _, change := range []map[string]any{{"schema_version": "wrong"}, {"grant_id": "missing"}, {"expected_grant_revision": -1}, {"expected_grant_revision": nil}, {"agent_id": "other"}, {"session_id": strings.Repeat("x", 257)}, {"grant_ref": map[string]any{"permission_digest": "forged"}}} {
		invalid := selectedBindingRequest(g, rev, "invalid")
		for k, v := range change {
			invalid[k] = v
		}
		if code, out := call(t, s, "POST", "/v1/intent-bindings", token, invalid); code != 400 && code != 404 {
			t.Fatal(change, code, out)
		}
	}
	stale := selectedBindingRequest(g, rev+1, "stale")
	if code, _ := call(t, s, "POST", "/v1/intent-bindings", token, stale); code != 409 {
		t.Fatal("stale preview selected grant")
	}
	if code, out := call(t, s, "POST", "/v1/intent-bindings", token, body); code != 201 {
		t.Fatal(out)
	}
	if code, _ := call(t, s, "POST", "/v1/intent-bindings", token, map[string]any{"platform": "hermes", "agent_id": "a-1", "session_id": "selected", "intent_id": "int-api"}); code != 409 {
		t.Fatal("selection downgraded")
	}
	other, otherRev := selectedGrantFixture(t, s, st, "b", "/elsewhere", false)
	if code, _ := call(t, s, "POST", "/v1/intent-bindings", token, selectedBindingRequest(other, otherRev, "selected")); code != 409 {
		t.Fatal("selection replaced")
	}
}

func TestSelectedGrantHoldCannotBeApprovedAfterRevocation(t *testing.T) {
	s, st := grantBindingServer(t, "block")
	g, rev := selectedGrantFixture(t, s, st, "a", "/work", true)
	if code, out := call(t, s, "POST", "/v1/intent-bindings", token, selectedBindingRequest(g, rev, "held")); code != 201 {
		t.Fatal(out)
	}
	_, held := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": "hermes", "agent_id": "a-1", "session_id": "held", "tool": "read_file", "tool_call_id": "held-call", "params": map[string]any{"path": "/work/report"}})
	if held["action"] != "hold" {
		t.Fatal(held)
	}
	if code, out := call(t, s, "POST", "/v1/grants/"+g.GrantID+"/revoke", token, withRevision(map[string]any{"actor_id": "fixture-operator"}, rev)); code != 200 {
		t.Fatal(out)
	}
	if code, out := call(t, s, "POST", "/v1/hold/"+held["receipt_id"].(string), token, map[string]any{"approve": true, "actor_id": "fixture-operator"}); code == 200 {
		t.Fatal("revoked selected grant approved", out)
	}
}

func TestSameAdmissionSelectedForTwoAgentsWithDifferentScopes(t *testing.T) {
	s, st := grantBindingServer(t, "block")
	first, firstRev := selectedGrantFixture(t, s, st, "a", "/work/public", false)
	second, secondRev := selectedGrantFixture(t, s, st, "a", "/work/private", false, "a-2")
	if first.AdmissionID != second.AdmissionID || first.GrantID == second.GrantID {
		t.Fatal("test needs same Skill version and distinct subjects")
	}
	c := apiIntent()
	c.IntentID = "int-other"
	c.Agent.ID = "a-2"
	c.ResourceConstraints = []intent.ResourceConstraint{}
	if code, out := call(t, s, "POST", "/v1/intents", token, c); code != 201 {
		t.Fatal(out)
	}
	for _, tc := range []struct {
		g                       grant.Grant
		rev                     int
		intentID, session, want string
	}{{first, firstRev, "int-api", "first-agent", "deny"}, {second, secondRev, "int-other", "second-agent", "allow"}} {
		body := selectedBindingRequest(tc.g, tc.rev, tc.session)
		body["intent_id"] = tc.intentID
		if code, out := call(t, s, "POST", "/v1/intent-bindings", token, body); code != 201 {
			t.Fatal(out)
		}
		_, out := call(t, s, "POST", "/v1/decide", token, map[string]any{"platform": tc.g.Platform, "agent_id": tc.g.Subject.ID, "session_id": tc.session, "tool": "read_file", "params": map[string]any{"path": "/work/private/report"}})
		if out["action"] != tc.want {
			t.Fatal("cross-agent permissions mixed", out)
		}
	}
}

func TestSelectedGrantHoldStatusUsesSelectionAndRechecksRevocation(t *testing.T) {
	s, st := grantBindingServer(t, "block")
	g, rev := selectedGrantFixture(t, s, st, "a", "/work/public", true)
	broader, _ := selectedGrantFixture(t, s, st, "b", "/work", false)
	if active := st.ActiveGrant("hermes", "a-1"); active == nil || active.GrantID != broader.GrantID {
		t.Fatal("test requires newer legacy grant")
	}
	if code, out := call(t, s, "POST", "/v1/intent-bindings", token, selectedBindingRequest(g, rev, "held-selected")); code != 201 {
		t.Fatal(out)
	}
	body := map[string]any{"platform": "hermes", "agent_id": "a-1", "session_id": "held-selected", "tool": "read_file", "tool_call_id": "held-call", "params": map[string]any{"path": "/work/public/report"}}
	_, held := call(t, s, "POST", "/v1/decide", token, body)
	if held["action"] != "hold" {
		t.Fatal(held)
	}
	if code, out := call(t, s, "POST", "/v1/hold/"+held["receipt_id"].(string), token, map[string]any{"approve": true, "actor_id": "fixture-operator"}); code != 200 {
		t.Fatal(out)
	}
	body["action_id"], body["decision_receipt_id"] = held["action_id"], held["receipt_id"]
	if code, out := call(t, s, "POST", "/v1/hold-status", token, body); code != 200 || out["status"] != "approved" {
		t.Fatal("hold checked implicit newer grant", out)
	}
	if code, out := call(t, s, "POST", "/v1/grants/"+g.GrantID+"/revoke", token, withRevision(map[string]any{"actor_id": "fixture-operator"}, rev)); code != 200 {
		t.Fatal(out)
	}
	if code, out := call(t, s, "POST", "/v1/hold-status", token, body); code != 200 || out["status"] != "denied" {
		t.Fatal("revocation retained executable approval", out)
	}
}
