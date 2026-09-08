package receipt

import (
	"testing"
	"time"
)

func TestSignedToolApprovalConditionHoldsButCannotOverrideDeny(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	for i, f := range g.Facts {
		if f.Domain == "tool" && f.Resource.Value == "web_fetch" {
			g.Facts[i].Conditions = map[string]any{"require_approval": true}
		}
	}
	fx := newFixture(t, "block", g, false)
	r := req("hermes", "web_fetch", map[string]any{"url": "https://api.github.com/report"})
	held, err := fx.eng.Decide(r)
	if err != nil || held.Action != ActionHold {
		t.Fatal(held, err)
	}
	denied, err := fx.eng.Decide(req("hermes", "web_fetch", map[string]any{"url": "https://ungranted.example/report"}))
	if err != nil || denied.Action != ActionDeny {
		t.Fatal("approval condition bypassed host restriction", denied, err)
	}
	fx.clock = fx.clock.Add(61 * time.Second)
	if _, err := fx.eng.ResolveHold(held.Receipt, true, "operator"); err == nil {
		t.Fatal("expired approval accepted")
	}
}
