package receipt

import (
	"encoding/json"
	"os"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
	"testing"
	"time"
)

func TestRuntimeStageBaseline(t *testing.T) {
	if os.Getenv("SIQ_STAGE_BASELINE") != "1" {
		t.Skip("explicit performance baseline only")
	}
	fx, intents, _ := revocableEngine(t, "required", "block")
	c, err := intents.Get("int-revocable")
	if err != nil {
		t.Fatal(err)
	}
	c.IntentID, c.SchemaVersion, c.Digest, c.Signature = "performance-v3", "intent/v3", "", ""
	constraints := []provenance.Constraint{{ParameterPath: "/path", AllowedSourceTypes: []string{"USER"}, MinimumTrust: "trusted", Required: true}}
	c.ProvenanceConstraints = &constraints
	if _, err = intents.Issue(c); err != nil {
		t.Fatal(err)
	}
	r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
	r.SessionID = "performance-session"
	if _, err = intents.Bind(intent.Binding{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, IntentID: c.IntentID}); err != nil {
		t.Fatal(err)
	}
	store, err := provenance.Open(t.TempDir(), fx.k)
	if err != nil {
		t.Fatal(err)
	}
	scope := provenance.Scope{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, TaskID: c.TaskID}
	expires := fx.clock.Add(time.Hour).Format(time.RFC3339)
	if _, err = store.RegisterIssuer(provenance.Issuer{IssuerID: "baseline", LocalKeyRef: "local-state", AllowedSourceTypes: []string{"USER"}, MaxTrustLevel: "authoritative", Scope: scope, ExpiresAt: expires}); err != nil {
		t.Fatal(err)
	}
	digest, _ := provenance.ContentDigest("/work/report")
	if _, err = store.IssueAssertion(provenance.Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: "source", Source: provenance.Source{Type: "USER", SourceID: "field", Trust: "authoritative"}, Scope: scope, ContentDigest: digest, Parents: []string{}, Derivation: "direct", IssuedAt: fx.clock.Add(-time.Minute).Format(time.RFC3339), ExpiresAt: expires, Issuer: "baseline"}, fx.clock); err != nil {
		t.Fatal(err)
	}
	r.ParameterProvenance = []provenance.ParameterBinding{{ParameterPath: "/path", ProvenanceRefs: []string{"source"}}}
	fx.eng.opts.ProvenanceCheck = store.MatchParameters
	fx.eng.opts.ContextLookup = intents.GetContext
	subject := trustedcontext.Subject{Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID}
	binding, err := trustedcontext.RequestBinding(subject, c.TaskID, r.Tool, r.ToolCallID, r.Params)
	if err != nil {
		t.Fatal(err)
	}
	context, err := intents.IssueContext(trustedcontext.Assertion{SchemaVersion: "context-assertion/v1", AssertionID: "performance-context", IssuerID: "local-admin", Subject: subject, TaskID: c.TaskID, Claims: trustedcontext.Claims{WorkspaceRoot: "/work"}, IssuedAt: fx.clock.Add(-time.Minute).Format(time.RFC3339), ExpiresAt: expires, RequestBinding: binding})
	if err != nil {
		t.Fatal(err)
	}
	r.ContextAssertionID = context.AssertionID
	// Warm caches before collecting; authority/crypto/fsync remain production code.
	for i := 0; i < 5; i++ {
		d, err := fx.eng.Decide(r)
		if err != nil || d.Action != ActionAllow {
			t.Fatal("warmup rejected", err)
		}
	}
	samples := map[string][]float64{}
	fx.eng.opts.StageTiming = func(stage string, d time.Duration) {
		samples[stage] = append(samples[stage], float64(d)/float64(time.Millisecond))
	}
	for i := 0; i < 100; i++ {
		started := time.Now()
		d, err := fx.eng.Decide(r)
		elapsed := time.Since(started)
		if err != nil || d.Action != ActionAllow {
			t.Fatal("baseline rejected", err)
		}
		samples["decision_total"] = append(samples["decision_total"], float64(elapsed)/float64(time.Millisecond))
	}
	if len(samples) != 8 {
		t.Fatal("missing stage", samples)
	}
	for stage, values := range samples {
		if len(values) != 100 {
			t.Fatal(stage, len(values))
		}
		for i, value := range values {
			if value > samples["decision_total"][i] {
				t.Fatal("stage exceeds its enclosing Decide duration", stage, i)
			}
		}
	}
	raw, err := json.Marshal(samples)
	if err != nil {
		t.Fatal(err)
	}
	t.Log("SIQ_STAGE_SAMPLES=" + string(raw))
}
