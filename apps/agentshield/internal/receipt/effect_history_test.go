package receipt

import (
	"bytes"
	"os"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
)

func historyReference(d *Decision) []effectevidence.Record {
	return []effectevidence.Record{{Evidence: effectevidence.Evidence{ActionID: d.Receipt.ActionID, DecisionReceiptID: d.Receipt.ReceiptID}}}
}
func TestHistoricalEffectActionSurvivesWindowAndRestart(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	d, err := fx.eng.Decide(req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"}))
	if err != nil {
		t.Fatal(err)
	}
	fx.clock = fx.clock.Add(48 * time.Hour)
	restarted, err := New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = restarted.EffectAction(d.Receipt.ActionID, d.Receipt.ReceiptID); err == nil {
		t.Fatal("new submission window was extended")
	}
	lookup, err := restarted.HistoricalEffectActions(historyReference(d))
	if err != nil {
		t.Fatal(err)
	}
	a, err := lookup(d.Receipt.ActionID, d.Receipt.ReceiptID)
	if err != nil || !a.Authorized || len(a.Resources) != 1 {
		t.Fatal(a, err)
	}
	a.Resources[0].Digest = "mutated"
	fresh, err := lookup(d.Receipt.ActionID, d.Receipt.ReceiptID)
	if err != nil || fresh.Resources[0].Digest == "mutated" {
		t.Fatal("history projection mutable", err)
	}
	if _, err = lookup("forged", d.Receipt.ReceiptID); err == nil {
		t.Fatal("history identity mismatch accepted")
	}
}
func TestHistoricalEffectHoldResolution(t *testing.T) {
	for _, approve := range []bool{true, false} {
		fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
		d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "ls"}))
		if err != nil || d.Action != ActionHold {
			t.Fatal(d, err)
		}
		if _, err = fx.eng.ResolveHold(d.Receipt, approve, "admin"); err != nil {
			t.Fatal(err)
		}
		fx.clock = fx.clock.Add(48 * time.Hour)
		restarted, err := New(fx.eng.opts)
		if err != nil {
			t.Fatal(err)
		}
		lookup, err := restarted.HistoricalEffectActions(historyReference(d))
		if err != nil {
			t.Fatal(err)
		}
		a, err := lookup(d.Receipt.ActionID, d.Receipt.ReceiptID)
		if err != nil || a.Authorized != approve {
			t.Fatal(a, err)
		}
	}
}
func TestHistoricalEffectRejectsTruncatedOrTamperedLedger(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	d, err := fx.eng.Decide(req("hermes", "read_file", nil))
	if err != nil {
		t.Fatal(err)
	}
	if _, err = fx.eng.Decide(req("hermes", "send_message", nil)); err != nil {
		t.Fatal(err)
	}
	files, err := fx.chain.files()
	if err != nil || len(files) != 1 {
		t.Fatal(files, err)
	}
	raw, err := os.ReadFile(files[0])
	if err != nil {
		t.Fatal(err)
	}
	cut := bytes.IndexByte(raw, '\n')
	if cut < 0 {
		t.Fatal("missing ledger lines")
	}
	if err = os.WriteFile(files[0], raw[:cut+1], 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = fx.eng.HistoricalEffectActions(historyReference(d)); err == nil {
		t.Fatal("valid prefix hid missing ledger suffix")
	}
	bad := bytes.Replace(raw, []byte(`"read_file"`), []byte(`"write_file"`), 1)
	if err = os.WriteFile(files[0], bad, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = fx.eng.HistoricalEffectActions(historyReference(d)); err == nil {
		t.Fatal("tampered action accepted")
	}
}
