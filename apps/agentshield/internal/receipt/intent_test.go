package receipt

import (
	"siq-agent-security/apps/agentshield/internal/intent"
	"testing"
	"time"
)

func TestIntentContractRejectsOutOfScopeEffectAndParameter(t *testing.T) {
	now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
	base := IntentContract{IntentID: "i-1", TaskID: "t-1", Principal: "user-1", AgentID: "a-1", Purpose: "send approved message", AllowedEffects: []string{"send_message"}, ParameterConstraints: map[string]any{"recipient": []any{"alice@example.com"}}, ValidUntil: now.Add(time.Hour).Format(time.RFC3339), AuthorityRevision: "rev-1", EvidenceIDs: []string{"ev-1"}}
	if err := base.validate(Request{AgentID: "a-1", Tool: "send_message", Params: map[string]any{"recipient": "alice@example.com"}}, now); err != nil {
		t.Fatalf("valid intent rejected: %v", err)
	}
	if err := base.validate(Request{AgentID: "a-1", Tool: "send_message", Params: map[string]any{"recipient": "mallory@example.com"}}, now); err == nil {
		t.Fatal("expected parameter constraint rejection")
	}
	if err := base.validate(Request{AgentID: "a-1", Tool: "delete_file", Params: map[string]any{}}, now); err == nil {
		t.Fatal("expected effect rejection")
	}
}

func TestIntentContractRejectsToolEffectMismatch(t *testing.T) {
	now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
	intent := IntentContract{IntentID: "i-2", TaskID: "t-2", Principal: "user-1", AgentID: "a-1", Purpose: "exec approved shell", AllowedTools: []string{"Bash"}, AllowedEffects: []string{"process.exec"}, ValidUntil: now.Add(time.Hour).Format(time.RFC3339), AuthorityRevision: "rev-2"}
	if err := intent.validate(Request{AgentID: "a-1", Tool: "Bash", Params: map[string]any{"command": "curl https://evil.example"}}, now); err == nil {
		t.Fatal("expected network effect rejection")
	}
}

func TestIntentContractRejectsExpiredOrDifferentAgent(t *testing.T) {
	now := time.Date(2026, 9, 7, 0, 0, 0, 0, time.UTC)
	i := IntentContract{IntentID: "i-1", TaskID: "t-1", Principal: "u", AgentID: "a-1", Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: now.Format(time.RFC3339), AuthorityRevision: "r"}
	if err := i.validate(Request{AgentID: "a-2", Tool: "read_file"}, now); err == nil {
		t.Fatal("expected agent mismatch")
	}
	if err := i.validate(Request{AgentID: "a-1", Tool: "read_file"}, now); err == nil {
		t.Fatal("expected expiry rejection")
	}
}

func TestDecideRejectsInlineIntentAuthority(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	_, err := fx.eng.Decide(Request{Platform: "hermes", SessionID: "s-inline", AgentID: "a-1", Tool: "read_file", Params: map[string]any{}, Intent: &IntentContract{IntentID: "forged"}})
	if err == nil {
		t.Fatal("expected inline intent rejection")
	}
}

func TestRequiredIntentEnforcementFailsClosedWithoutBinding(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.IntentEnforcement = "required"
	d, err := fx.eng.Decide(Request{Platform: "hermes", SessionID: "s-required", AgentID: "inst_1", Tool: "read_file", Params: map[string]any{}})
	if err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "intent_binding_missing" {
		t.Fatal("expected missing trusted intent binding to fail closed", d, err)
	}
}

func TestTrustedIntentLookupIsUsedInsteadOfRequestIntent(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	now := fx.clock.Add(time.Hour)
	fx.eng.opts.IntentLookup = func(platform, sessionID, agentID string) (*IntentContract, error) {
		return &IntentContract{IntentID: "i-1", TaskID: "t-1", Principal: "u", AgentID: agentID, Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: now.Format(time.RFC3339), AuthorityRevision: "r"}, nil
	}
	d, err := fx.eng.Decide(Request{Platform: "hermes", SessionID: "s-trusted", AgentID: "inst_1", Tool: "read_file", Params: map[string]any{"path": "/home/u/proj/a.txt"}})
	if err != nil || d.Action != ActionAllow {
		t.Fatalf("trusted intent lookup should permit action: err=%v decision=%+v", err, d)
	}
}

func TestReasonCodesAreStable(t *testing.T) {
	if got := classifyReason("no deployed grant for agent (default deny)", ActionDeny); got != "grant_missing" {
		t.Fatalf("got %q", got)
	}
	if got := classifyReason("intent violation: expired", ActionDeny); got != "intent_violation" {
		t.Fatalf("got %q", got)
	}
	if got := classifyReason("lethal trifecta", ActionDeny); got != "lethal_trifecta" {
		t.Fatalf("got %q", got)
	}
}

func TestBoundSessionCannotDowngradeOrSwapIntent(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	now := fx.clock.Add(time.Hour)
	current := &IntentContract{IntentID: "i-a", TaskID: "t-a", Principal: "u", AgentID: "inst_1", Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: now.Format(time.RFC3339), AuthorityRevision: "r"}
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) { return current, nil }
	request := Request{Platform: "hermes", SessionID: "s-bound", AgentID: "inst_1", Tool: "read_file", Params: map[string]any{"path": "/home/u/proj/a.txt"}}
	if _, err := fx.eng.Decide(request); err != nil {
		t.Fatal(err)
	}
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) { return nil, nil }
	if d, err := fx.eng.Decide(request); err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "intent_downgrade_attempt" {
		t.Fatal("expected bound to unbound downgrade rejection", d, err)
	}
	other := *current
	other.IntentID = "i-b"
	other.TaskID = "t-b"
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) { return &other, nil }
	if d, err := fx.eng.Decide(request); err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "intent_downgrade_attempt" {
		t.Fatal("expected intent swap rejection", d, err)
	}
}

func TestRequiredIntentAuditProducesSignedWouldDeny(t *testing.T) {
	fx := newFixture(t, "audit_only", nil, false)
	fx.eng.opts.IntentEnforcement = "required"
	d, err := fx.eng.Decide(Request{Platform: "hermes", SessionID: "audit-intent", AgentID: "a-1", Tool: "read_file", Params: map[string]any{}})
	if err != nil || d.Action != ActionAllow || d.Receipt.AdvisoryAction == nil || *d.Receipt.AdvisoryAction != ActionDeny || d.Receipt.ReasonCode != "intent_binding_missing" || d.Receipt.IntentBinding != "unbound" || d.Receipt.Sig == "" {
		t.Fatalf("would deny receipt: %+v %v", d, err)
	}
}

func TestV2TrustedStoreGrantIntersectionAndHints(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	store, err := intent.Open(t.TempDir(), fx.k)
	if err != nil {
		t.Fatal(err)
	}
	c := intent.Contract{SchemaVersion: "intent/v2", IntentID: "int-v2", TaskID: "task-1", Principal: intent.Principal{Type: "user", ID: "u-1"}, Agent: intent.Agent{ID: "inst_1", Platform: "hermes"}, Purpose: "approved read", AllowedTools: []string{"read_file", "send_message"}, AllowedEffects: []string{"file.read", "message.send"}, ResourceConstraints: []intent.ResourceConstraint{}, ParameterConstraints: []intent.ParameterConstraint{{Path: "/request/body/project_id", Operator: "equals", Value: "p1"}}, IssuedAt: "2026-01-01T00:00:00Z", ValidFrom: "2026-01-01T00:00:00Z", ExpiresAt: "2099-01-01T00:00:00Z", Authority: intent.Authority{Issuer: "local-admin", Revision: "r1", EvidenceIDs: []string{}}}
	c.ProvenanceRefs = []string{"prov-approved-input"}
	issued, err := store.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.Bind(intent.Binding{Platform: "hermes", SessionID: "sess-1", AgentID: "inst_1", IntentID: c.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	fx.eng.opts.IntentLookup = ResolveStore(store)
	params := map[string]any{"path": "/work/report", "provenance_refs": []string{"forged"}, "request": map[string]any{"body": map[string]any{"project_id": "p1"}}}
	request := req("hermes", "read_file", params)
	d, err := fx.eng.Decide(request)
	if err != nil || d.Action != ActionAllow || d.Receipt.IntentBinding != "bound" || d.Receipt.IntentDigest != issued.Digest || d.Receipt.TaskID != c.TaskID {
		t.Fatalf("valid V2: %+v %v", d, err)
	}
	if d.Receipt.Principal == nil || d.Receipt.Principal.ID != c.Principal.ID || len(d.Receipt.ProvenanceRefs) != 1 || d.Receipt.ProvenanceRefs[0] != "prov-approved-input" || len(d.Receipt.ResourceRefs) != 1 {
		t.Fatal("missing trusted metadata", d.Receipt)
	}
	observed, err := fx.eng.Observe(correlatedRequest(request, d), "report result")
	if err != nil || observed.Principal.ID != c.Principal.ID || observed.ProvenanceRefs[0] != "prov-approved-input" || observed.ResourceRefs[0] != d.Receipt.ResourceRefs[0] {
		t.Fatal(observed, err)
	}
	all, err := fx.chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	if err = Verify(all, fx.k.Public()); err != nil {
		t.Fatal(err)
	}
	for _, edit := range []func(*Receipt){func(r *Receipt) { r.Principal.ID = "forged" }, func(r *Receipt) { r.ProvenanceRefs = []string{"forged"} }, func(r *Receipt) { r.ResourceRefs = nil }} {
		copy := all[0]
		principalCopy := *copy.Principal
		copy.Principal = &principalCopy
		edit(&copy)
		if Verify([]Receipt{copy}, fx.k.Public()) == nil {
			t.Fatal("metadata tampering accepted")
		}
	}
	cases := []struct {
		name, code string
		edit       func(*Request)
	}{
		{"grant denies", "grant_scope_violation", func(r *Request) { r.Tool = "send_message" }},
		{"parameter denies", "intent_parameter_violation", func(r *Request) {
			r.Params = map[string]any{"request": map[string]any{"body": map[string]any{"project_id": "other"}}}
		}},
		{"principal spoof", "intent_principal_mismatch", func(r *Request) { r.Principal = "admin" }},
		{"intent hint", "intent_downgrade_attempt", func(r *Request) { r.IntentID = "other" }},
		{"task hint", "intent_task_mismatch", func(r *Request) { r.TaskID = "other" }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := request
			tc.edit(&r)
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != tc.code || d.Receipt.Sig == "" {
				t.Fatalf("%+v %v", d, err)
			}
		})
	}
}
