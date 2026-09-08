package receipt

import (
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/provenance"
)

func TestTrustedMessageRoutingDoesNotDeclassifyPayload(t *testing.T) {
	for _, tc := range []struct {
		name, body, trust             string
		required, priorPII, wantAllow bool
	}{
		{"trusted_mailbox", "public report", "trusted", true, false, true},
		{"payload_mailbox", "customer@private.example", "trusted", true, false, false},
		{"payload_ssn", "123-45-6789", "trusted", true, false, false},
		{"payload_secret", "sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "trusted", true, false, false},
		{"existing_taint", "public report", "trusted", true, true, false},
		{"untrusted_route", "public report", "untrusted", true, false, false},
		{"optional_route", "public report", "trusted", false, false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			fx, intents, _ := revocableEngine(t, "required", "block")
			g := fx.eng.opts.Grants("hermes", "inst_1")
			*g.HermesToolsetAllowlist = append(*g.HermesToolsetAllowlist, "send_message")
			c, err := intents.Get("int-revocable")
			if err != nil {
				t.Fatal(err)
			}
			c.IntentID, c.SchemaVersion, c.Digest, c.Signature = "int-message", "intent/v3", "", ""
			c.AllowedTools, c.AllowedEffects = []string{"send_message"}, []string{"message.send"}
			c.ResourceConstraints = []intent.ResourceConstraint{{Domain: "message", Operator: "equals", Value: "alice@company.example"}}
			constraints := []provenance.Constraint{{ParameterPath: "/recipient", AllowedSourceTypes: []string{"TRUSTED_DATABASE"}, MinimumTrust: tc.trust, Required: tc.required}}
			c.ProvenanceConstraints = &constraints
			if _, err := intents.Issue(c); err != nil {
				t.Fatal(err)
			}
			r := req("hermes", "send_message", map[string]any{"recipient": "alice@company.example", "body": tc.body})
			r.SessionID = "message-session"
			if _, err := intents.Bind(intent.Binding{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, IntentID: c.IntentID}); err != nil {
				t.Fatal(err)
			}
			store, err := provenance.Open(t.TempDir(), fx.k)
			if err != nil {
				t.Fatal(err)
			}
			scope := provenance.Scope{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, TaskID: c.TaskID}
			expires := fx.clock.Add(time.Hour).Format(time.RFC3339)
			if _, err := store.RegisterIssuer(provenance.Issuer{IssuerID: "directory", LocalKeyRef: "local-state", AllowedSourceTypes: []string{"TRUSTED_DATABASE"}, MaxTrustLevel: "trusted", Scope: scope, ExpiresAt: expires}); err != nil {
				t.Fatal(err)
			}
			digest, _ := provenance.ContentDigest("alice@company.example")
			assertion := provenance.Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: "alice", Source: provenance.Source{Type: "TRUSTED_DATABASE", SourceID: "contacts", Trust: tc.trust}, Scope: scope, ContentDigest: digest, Parents: []string{}, Derivation: "direct", IssuedAt: fx.clock.Add(-time.Minute).Format(time.RFC3339), ExpiresAt: expires, Issuer: "directory"}
			if _, err := store.IssueAssertion(assertion, fx.clock); err != nil {
				t.Fatal(err)
			}
			fx.eng.opts.ProvenanceCheck = store.MatchParameters
			r.ParameterProvenance = []provenance.ParameterBinding{{ParameterPath: "/recipient", ProvenanceRefs: []string{"alice"}}}
			if tc.priorPII {
				prior := r
				prior.Params = map[string]any{"recipient": "alice@company.example", "body": "123-45-6789"}
				prior.ToolCallID = "prior-tainted"
				if d, err := fx.eng.Decide(prior); err != nil || d.Action != ActionDeny {
					t.Fatal(d, err)
				}
			}
			d, err := fx.eng.Decide(r)
			if err != nil {
				t.Fatal(err)
			}
			if (d.Action == ActionAllow) != tc.wantAllow {
				t.Fatalf("unexpected decision: %+v", d.Receipt)
			}
			if tc.wantAllow {
				if contains(d.Receipt.TaintLabels, taintPII) {
					t.Fatal("routing metadata became PII payload")
				}
				// Observation data is not covered by the routing-only exemption.
				r.ActionID, r.DecisionReceiptID = d.Receipt.ActionID, d.Receipt.ReceiptID
				if _, err := fx.eng.Observe(r, "customer@private.example"); err != nil {
					t.Fatal(err)
				}
				r.ActionID, r.DecisionReceiptID, r.ToolCallID = "", "", "after-observed-pii"
				if after, err := fx.eng.Decide(r); err != nil || after.Action != ActionDeny || !contains(after.Receipt.TaintLabels, taintPII) {
					t.Fatal(after, err)
				}
			} else if d.Receipt.ReasonCode != "session_taint_violation" {
				t.Fatalf("payload no longer checked by taint policy: %+v", d.Receipt)
			}
		})
	}
}
