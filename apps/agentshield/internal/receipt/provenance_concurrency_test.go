package receipt

import (
	"fmt"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/provenance"
)

func TestConcurrentProvenanceIssueDecideAndRevoke(t *testing.T) {
	for _, mode := range []string{"block", "warn", "audit_only"} {
		t.Run(mode, func(t *testing.T) {
			fx, intents, _ := revocableEngine(t, "required", mode)
			c, err := intents.Get("int-revocable")
			if err != nil {
				t.Fatal(err)
			}
			c.IntentID, c.SchemaVersion, c.Digest, c.Signature = "int-concurrent-v3", "intent/v3", "", ""
			constraints := []provenance.Constraint{{ParameterPath: "/path", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: true}}
			c.ProvenanceConstraints = &constraints
			if _, err = intents.Issue(c); err != nil {
				t.Fatal(err)
			}
			r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
			r.SessionID = "concurrent-v3-session"
			if _, err = intents.Bind(intent.Binding{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, IntentID: c.IntentID}); err != nil {
				t.Fatal(err)
			}
			store, err := provenance.Open(t.TempDir(), fx.k)
			if err != nil {
				t.Fatal(err)
			}
			scope := provenance.Scope{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, TaskID: c.TaskID}
			issuedAt := fx.clock
			expires := issuedAt.Add(time.Hour).Format(time.RFC3339)
			if _, err = store.RegisterIssuer(provenance.Issuer{IssuerID: "concurrent-issuer", LocalKeyRef: "local-state", AllowedSourceTypes: []string{"USER"}, MaxTrustLevel: "authoritative", Scope: scope, ExpiresAt: expires}); err != nil {
				t.Fatal(err)
			}
			digest, _ := provenance.ContentDigest("/work/report")
			fx.eng.opts.ProvenanceCheck = store.MatchParameters
			start, revoked := make(chan struct{}), make(chan struct{})
			failures := make(chan error, 16)
			var first, wg sync.WaitGroup
			first.Add(16)
			for i := 0; i < 16; i++ {
				wg.Add(1)
				go func(i int) {
					defer wg.Done()
					<-start
					id := fmt.Sprintf("concurrent-source-%d", i)
					a := provenance.Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: id, Source: provenance.Source{Type: "USER", SourceID: "form-field", Trust: "authoritative"}, Scope: scope, ContentDigest: digest, Parents: []string{}, Derivation: "direct", IssuedAt: issuedAt.Add(-time.Minute).Format(time.RFC3339), ExpiresAt: expires, Issuer: "concurrent-issuer"}
					if _, err := store.IssueAssertion(a, issuedAt); err != nil {
						first.Done()
						failures <- err
						return
					}
					own := r
					own.ToolCallID = fmt.Sprintf("concurrent-call-%d", i)
					own.ParameterProvenance = []provenance.ParameterBinding{{ParameterPath: "/path", ProvenanceRefs: []string{id}}}
					d, err := fx.eng.Decide(own)
					first.Done()
					if err != nil || d == nil || d.Action != ActionAllow {
						failures <- fmt.Errorf("published source not usable: %v", err)
						return
					}
					for j := 0; j < 4; j++ {
						d, err = fx.eng.Decide(own)
						if err != nil || d == nil || (d.Action != ActionAllow && (d.Action != ActionDeny || d.Receipt.AuthorityReasonCode != "provenance_issuer_untrusted")) {
							failures <- fmt.Errorf("invalid concurrent decision: %v", err)
							return
						}
					}
					<-revoked
					for j := 0; j < 4; j++ {
						d, err = fx.eng.Decide(own)
						if err != nil || d == nil || d.Action != ActionDeny || d.Receipt.AdvisoryAction != nil || d.Receipt.AuthorityStatus != "invalid" || d.Receipt.AuthorityReasonCode != "provenance_issuer_untrusted" {
							failures <- fmt.Errorf("revoked source retained authority in %s: %v", mode, err)
							return
						}
					}
				}(i)
			}
			close(start)
			first.Wait()
			_, revokeErr := store.RevokeIssuer("concurrent-issuer", issuedAt)
			close(revoked)
			wg.Wait()
			close(failures)
			if revokeErr != nil {
				t.Fatal(revokeErr)
			}
			for err := range failures {
				t.Error(err)
			}
		})
	}
}
