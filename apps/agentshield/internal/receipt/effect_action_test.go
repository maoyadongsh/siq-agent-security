package receipt

import (
	"errors"
	"testing"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
)

func TestEffectActionExactCorrelationAndRecovery(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	d, err := fx.eng.Decide(req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"}))
	if err != nil {
		t.Fatal(err)
	}
	denied, err := fx.eng.Decide(req("hermes", "send_message", nil))
	if err != nil || denied.Action != ActionDeny {
		t.Fatal(denied, err)
	}
	for _, engine := range []*Engine{fx.eng, mustRestartEffectEngine(t, fx.eng)} {
		a, err := engine.EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID)
		if err != nil || !a.Authorized || a.IssuedAt.IsZero() || len(a.Resources) != 1 {
			t.Fatal(a, err)
		}
		a.Resources[0].Digest = "mutated"
		fresh, err := engine.EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID)
		if err != nil || fresh.Resources[0].Digest == "mutated" {
			t.Fatal("caller mutated action ledger", err)
		}
		a, err = engine.EffectAction(denied.Receipt.ActionID, denied.Receipt.ReceiptID)
		if err != nil || a.Authorized {
			t.Fatal("denied action unavailable for incident or authorized", a, err)
		}
		for _, pair := range [][2]string{{"", d.Receipt.ReceiptID}, {"forged", d.Receipt.ReceiptID}, {d.Receipt.ActionID, denied.Receipt.ReceiptID}} {
			if _, err := engine.EffectAction(pair[0], pair[1]); !errors.Is(err, effectevidence.ErrCorrelation) {
				t.Fatal(pair, err)
			}
		}
	}
	fx.clock = fx.clock.Add(actionWindow)
	if _, err := fx.eng.EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID); !errors.Is(err, effectevidence.ErrCorrelation) {
		t.Fatal("expired action accepted", err)
	}
}

func mustRestartEffectEngine(t *testing.T, e *Engine) *Engine {
	t.Helper()
	restarted, err := New(e.opts)
	if err != nil {
		t.Fatal(err)
	}
	return restarted
}

func TestEffectActionHoldApproval(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "ls"}))
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	a, err := fx.eng.EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID)
	if err != nil || a.Authorized {
		t.Fatal(a, err)
	}
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	a, err = mustRestartEffectEngine(t, fx.eng).EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID)
	if err != nil || !a.Authorized {
		t.Fatal(a, err)
	}
}
