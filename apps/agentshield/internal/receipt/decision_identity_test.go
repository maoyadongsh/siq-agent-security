package receipt

import (
	"errors"
	"testing"
	"time"
)

func TestDecisionIdentitySurvivesRepeatedClockAndRestart(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	now := fx.clock
	fx.eng.opts.Now = func() time.Time { return now }
	r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	seen := map[string]bool{}
	for i := 0; i < 4; i++ {
		if i == 2 {
			var err error
			fx.eng, err = New(fx.eng.opts)
			if err != nil {
				t.Fatal(err)
			}
		}
		if i == 3 {
			now = now.Add(24 * time.Hour)
		}
		d, err := fx.eng.Decide(r)
		if err != nil || d.Action != ActionHold {
			t.Fatal(d, err)
		}
		if seen[d.Receipt.ReceiptID] {
			t.Fatal("different decisions reused a receipt ID under a repeated clock")
		}
		seen[d.Receipt.ReceiptID] = true
		resolution, err := fx.eng.ResolveHold(d.Receipt, i%2 == 0, "reviewer")
		if err != nil || resolution.DecisionReceiptID != d.Receipt.ReceiptID || resolution.ActionID != d.Receipt.ActionID {
			t.Fatal("approval resolved a different decision", resolution, err)
		}
	}
	rows, err := fx.chain.Read()
	if err != nil || len(rows) != 8 || Verify(rows, fx.k.Public()) != nil {
		t.Fatal("decisions and resolutions must remain independently signed", err)
	}
}

func TestHoldRejectsHistoricalDuplicateIdentity(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "printf fixture"}))
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	// A signed historical duplicate is not a signature failure. Its ID alone
	// cannot identify which action the operator intended to approve.
	other := d.Receipt
	other.ActionID = "other-historical-action"
	if err = fx.chain.Append(&other); err != nil {
		t.Fatal(err)
	}
	before, err := fx.chain.Read()
	if err != nil || Verify(before, fx.k.Public()) != nil {
		t.Fatal("fixture must have valid historical signatures", err)
	}
	for _, held := range []Receipt{d.Receipt, other} {
		if _, err = fx.eng.ResolveHold(held, true, "reviewer"); !errors.Is(err, ErrHoldConflict) {
			t.Fatalf("ambiguous historical identity must refuse approval: %v", err)
		}
	}
	after, err := fx.chain.Read()
	if err != nil || len(after) != len(before) || after[len(after)-1].Hash != before[len(before)-1].Hash {
		t.Fatal("ambiguous approval changed the signed chain", err)
	}
}

func TestHoldRejectsMismatchedOrDuplicateResolution(t *testing.T) {
	for _, scenario := range []string{"wrong_action", "wrong_decision", "duplicate"} {
		t.Run(scenario, func(t *testing.T) {
			fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
			d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "printf fixture"}))
			if err != nil || d.Action != ActionHold {
				t.Fatal(d, err)
			}
			resolution := d.Receipt
			resolution.ReceiptID = holdResolutionID(d.Receipt.ReceiptID)
			resolution.DecisionReceiptID = d.Receipt.ReceiptID
			resolution.RecordType, resolution.Action = "hold_resolution", ActionAllow
			resolution.Hold = nil
			switch scenario {
			case "wrong_action":
				resolution.ActionID = "different-action"
			case "wrong_decision":
				resolution.DecisionReceiptID = "different-decision"
			}
			if err = fx.chain.Append(&resolution); err != nil {
				t.Fatal(err)
			}
			if scenario == "duplicate" {
				if err = fx.chain.Append(&resolution); err != nil {
					t.Fatal(err)
				}
			}
			seq, head := fx.chain.Head()
			if _, err = fx.eng.ResolveHold(d.Receipt, true, "reviewer"); !errors.Is(err, ErrHoldConflict) {
				t.Fatalf("invalid resolution reused: %v", err)
			}
			if afterSeq, afterHead := fx.chain.Head(); afterSeq != seq || afterHead != head {
				t.Fatal("rejected resolution changed the chain")
			}
		})
	}
}

func TestHoldUniqueLegacyIdentityStillResolves(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "printf fixture"}))
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	legacy := d.Receipt
	legacy.ReceiptID = "rcp-0123456789ab-070000.000000"
	legacy.ActionID = "separate-legacy-action"
	if err = fx.chain.Append(&legacy); err != nil {
		t.Fatal(err)
	}
	resolution, err := fx.eng.ResolveHold(legacy, true, "reviewer")
	if err != nil || resolution.DecisionReceiptID != legacy.ReceiptID {
		t.Fatal("unique legacy identity lost compatibility", err)
	}
	again, err := fx.eng.ResolveHold(legacy, true, "reviewer")
	if err != nil || again.Hash != resolution.Hash {
		t.Fatal("unique legacy approval lost idempotency", err)
	}
}
