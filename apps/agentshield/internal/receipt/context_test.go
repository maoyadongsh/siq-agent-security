package receipt

import (
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
	"testing"
	"time"
)

func TestContextReferenceHardGateAndRecovery(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			fx, store, _ := revocableEngine(t, "required", mode)
			fx.eng.opts.ContextLookup = store.GetContext
			r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
			subject := trustedcontext.Subject{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID}
			binding, err := trustedcontext.RequestBinding(subject, "task-revocable", r.Tool, r.ToolCallID, r.Params)
			if err != nil {
				t.Fatal(err)
			}
			a, err := store.IssueContext(trustedcontext.Assertion{SchemaVersion: "context-assertion/v1", AssertionID: "ctx-runtime", IssuerID: "local-admin", Subject: subject, TaskID: "task-revocable", Claims: trustedcontext.Claims{WorkspaceRoot: "/work"}, IssuedAt: fx.clock.Add(-time.Hour).Format(time.RFC3339), ExpiresAt: fx.clock.Add(time.Hour).Format(time.RFC3339), RequestBinding: binding})
			if err != nil {
				t.Fatal(err)
			}
			r.ContextAssertionID = a.AssertionID
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionAllow || d.Receipt.ContextAssertionID != a.AssertionID {
				t.Fatal("valid context failed", err)
			}
			reopened, err := New(fx.eng.opts)
			if err != nil {
				t.Fatal(err)
			}
			fx.eng = reopened
			for _, tc := range []struct {
				name, code string
				edit       func(*Request)
			}{
				{"changed_call", "trusted_context_scope_mismatch", func(r *Request) { r.ToolCallID = "other" }},
				{"changed_params", "trusted_context_scope_mismatch", func(r *Request) { r.Params = map[string]any{"path": "/secret"} }},
				{"forged_reference", "trusted_context_invalid", func(r *Request) { r.ContextAssertionID = "forged" }},
			} {
				t.Run(tc.name, func(t *testing.T) {
					bad := r
					tc.edit(&bad)
					d, err := fx.eng.Decide(bad)
					if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityReasonCode != tc.code || d.Receipt.PolicyAction != "" {
						t.Fatal("invalid context bypassed hard gate", d, err)
					}
				})
			}
			fx.clock = fx.clock.Add(2 * time.Hour)
			d, err = fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityReasonCode != "trusted_context_expired" {
				t.Fatal("expired context allowed", err)
			}
		})
	}
}

func TestContextCannotReplaceGrantAndApprovalRechecksExpiry(t *testing.T) {
	fx, store, _ := revocableEngine(t, "required", "block")
	fx.eng.opts.ContextLookup = store.GetContext
	r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
	subject := trustedcontext.Subject{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID}
	binding, _ := trustedcontext.RequestBinding(subject, "task-revocable", r.Tool, r.ToolCallID, r.Params)
	a, err := store.IssueContext(trustedcontext.Assertion{SchemaVersion: "context-assertion/v1", AssertionID: "ctx-hold", IssuerID: "local-admin", Subject: subject, TaskID: "task-revocable", Claims: trustedcontext.Claims{WorkspaceRoot: "/work"}, IssuedAt: fx.clock.Add(-time.Hour).Format(time.RFC3339), ExpiresAt: fx.clock.Add(5 * time.Second).Format(time.RFC3339), RequestBinding: binding})
	if err != nil {
		t.Fatal(err)
	}
	r.ContextAssertionID = a.AssertionID
	fx.eng.opts.Grants = nil
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityStatus != "valid" || d.Receipt.PolicyAction != ActionDeny {
		t.Fatal("context replaced absent Grant", err)
	}
	g := deployedGrant(t, "hermes", false)
	g.OpenClawToolPolicy = &grant.OpenClawToolPolicy{RequireApproval: []string{"read_file"}}
	fx.eng.opts.Grants = func(_, _ string) *grant.Grant { return g }
	d, err = fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal("approval floor lost", d, err)
	}
	if _, err := fx.eng.ResolveHold(d.Receipt, true, "fixture-admin"); err != nil {
		t.Fatal(err)
	}
	status := statusRequest(r, d)
	if current, err := fx.eng.ReadHoldStatus(status); err != nil || current.Status != "approved" {
		t.Fatal("valid context approval failed", current, err)
	}
	fx.clock = fx.clock.Add(6 * time.Second)
	fx.eng, err = New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	if current, err := fx.eng.ReadHoldStatus(status); err != nil || current.Status != "denied" || current.ReasonCode != "hold_authority_changed" {
		t.Fatal("expired context retained approval after restart", current, err)
	}
}
