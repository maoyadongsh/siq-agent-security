package receipt

import (
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"testing"
	"time"
)

func TestV3DecisionUsesSignedParameterProvenance(t *testing.T) {
	for _, scenario := range []struct {
		mode     string
		explicit bool
	}{{"block", true}, {"warn", true}, {"audit_only", true}, {"block", false}, {"warn", false}, {"audit_only", false}} {
		mode := scenario.mode
		name := mode + "/default"
		if scenario.explicit {
			name = mode + "/explicit"
		}
		t.Run(name, func(t *testing.T) {
			fx, intents, _ := revocableEngine(t, "required", mode)
			c, err := intents.Get("int-revocable")
			if err != nil {
				t.Fatal(err)
			}
			c.IntentID, c.SchemaVersion = "int-v3", "intent/v3"
			c.Digest, c.Signature = "", ""
			constraints := []provenance.Constraint{{ParameterPath: "/path", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: true}}
			if !scenario.explicit {
				constraints = []provenance.Constraint{}
			}
			c.ProvenanceConstraints = &constraints
			if _, err := intents.Issue(c); err != nil {
				t.Fatal(err)
			}
			r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
			r.SessionID = "v3-session"
			if _, err := intents.Bind(intent.Binding{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, IntentID: c.IntentID}); err != nil {
				t.Fatal(err)
			}
			store, err := provenance.Open(t.TempDir(), fx.k)
			if err != nil {
				t.Fatal(err)
			}
			scope := provenance.Scope{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, TaskID: c.TaskID}
			expires := fx.clock.Add(time.Hour).Format(time.RFC3339)
			if _, err := store.RegisterIssuer(provenance.Issuer{IssuerID: "issuer-1", LocalKeyRef: "local-state", AllowedSourceTypes: []string{"USER", "MCP"}, MaxTrustLevel: "authoritative", Scope: scope, ExpiresAt: expires}); err != nil {
				t.Fatal(err)
			}
			digest, _ := provenance.ContentDigest("/work/report")
			a := provenance.Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: "user-source", Source: provenance.Source{Type: "USER", SourceID: "form-field", Trust: "authoritative"}, Scope: scope, ContentDigest: digest, Parents: []string{}, Derivation: "direct", IssuedAt: fx.clock.Add(-time.Minute).Format(time.RFC3339), ExpiresAt: expires, Issuer: "issuer-1"}
			if _, err := store.IssueAssertion(a, fx.clock); err != nil {
				t.Fatal(err)
			}
			a.ProvenanceID, a.Source.Type, a.Source.Trust = "mcp-source", "MCP", "untrusted"
			if _, err := store.IssueAssertion(a, fx.clock); err != nil {
				t.Fatal(err)
			}
			r.ParameterProvenance = []provenance.ParameterBinding{{ParameterPath: "/path", ProvenanceRefs: []string{"user-source"}}}
			d, err := fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny {
				t.Fatal("V3 ran without checker", err)
			}
			fx.eng.opts.ProvenanceCheck = store.MatchParameters
			d, err = fx.eng.Decide(r)
			if err != nil || d.Action != ActionAllow {
				t.Fatal("trusted same value rejected", d, err)
			}
			r.ParameterProvenance = []provenance.ParameterBinding{{ParameterPath: "/path", ProvenanceRefs: []string{"mcp-source"}}}
			d, err = fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityReasonCode != "provenance_source_not_allowed" {
				t.Fatal("MCP changed authorization", d, err)
			}
			r.ParameterProvenance = nil
			d, err = fx.eng.Decide(r)
			if err != nil || d.Action != ActionDeny || d.Receipt.AuthorityReasonCode != "provenance_missing" {
				t.Fatal("missing required provenance allowed", err)
			}
		})
	}
}
