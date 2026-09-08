package receipt

import (
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
)

func TestApprovalCannotRetroactivelyAuthorizeEffect(t *testing.T) {
	g := deployedGrant(t, "openclaw", false)
	g.OpenClawToolPolicy.RequireApproval = append(g.OpenClawToolPolicy.RequireApproval, "web_fetch")
	fx := newFixture(t, "block", g, false)
	d, err := fx.eng.Decide(req("openclaw", "web_fetch", map[string]any{"url": "https://api.github.com/report"}))
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	observed := fx.clock.Add(100 * time.Millisecond)
	fx.clock = fx.clock.Add(500 * time.Millisecond)
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	for _, engine := range []*Engine{fx.eng, mustRestartEffectEngine(t, fx.eng)} {
		a, err := engine.EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID)
		if err != nil || !a.Authorized || len(a.Resources) != 1 {
			t.Fatal(a, err)
		}
		ref, _ := effectevidence.ResourceReference(a.Resources[0])
		source := effectevidence.Source{Type: "test_oracle", SourceID: "oracle", Independence: "external_independent"}
		e := effectevidence.Evidence{SchemaVersion: "effect-evidence/v1", EvidenceID: "early-effect", ActionID: a.ActionID, DecisionReceiptID: a.DecisionReceiptID, EffectType: "network.request", ResourceRef: ref, ExecutionState: "completed", Source: source, Coverage: "partial", Result: "expected", EvidenceDigest: strings.Repeat("a", 64), ObservedAt: observed.Format(time.RFC3339Nano), SigningSchema: "local_canonical/v1"}
		got, code, err := effectevidence.Correlate(e, a, source, fx.clock)
		if err != nil || got.Result != "unexpected" || code != "unauthorized_effect_observed" {
			t.Fatal("later approval legitimized earlier effect", got, code, err)
		}
		lookup, err := engine.HistoricalEffectActions(historyReference(d))
		if err != nil {
			t.Fatal(err)
		}
		historical, err := lookup(a.ActionID, a.DecisionReceiptID)
		if err != nil || historical.AuthorizedAt.IsZero() || !historical.AuthorizedAt.Equal(a.AuthorizedAt) {
			t.Fatal("approval timestamp changed on recovery", historical, err)
		}
		got, code, err = effectevidence.Correlate(e, historical, source, fx.clock)
		if err != nil || got.Result != "unexpected" || code != "unauthorized_effect_observed" {
			t.Fatal("historical approval elevated early effect", got, code, err)
		}
		e.ObservedAt = a.AuthorizedAt.Format(time.RFC3339Nano)
		got, code, err = effectevidence.Correlate(e, historical, source, fx.clock)
		if err != nil || got.Result != "expected" || code != "" {
			t.Fatal("effect at approval boundary rejected", got, code, err)
		}
	}
}
