package receipt

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestResolveHoldIdempotentConflictAndExpiry(t *testing.T) {
	g := deployedGrant(t, "openclaw", false)
	fx := newFixture(t, "block", g, false)
	d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "ls"}))
	if err != nil || d.Action != ActionHold {
		t.Fatalf("%v %+v", err, d)
	}
	first, err := fx.eng.ResolveHold(d.Receipt, true, "u-admin")
	if err != nil || first.Action != ActionAllow {
		t.Fatalf("%v %+v", err, first)
	}
	again, err := fx.eng.ResolveHold(d.Receipt, true, "u-admin")
	if err != nil || again.ReceiptID != first.ReceiptID || again.Hash != first.Hash {
		t.Fatalf("same decision must be idempotent: %v %+v", err, again)
	}
	if _, err := fx.eng.ResolveHold(d.Receipt, false, "u-admin"); !errors.Is(err, ErrHoldConflict) {
		t.Fatalf("opposite decision must conflict: %v", err)
	}
	all, err := fx.chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	resCount := 0
	for _, r := range all {
		if r.ReceiptID == holdResolutionID(d.Receipt.ReceiptID) {
			resCount++
		}
	}
	if resCount != 1 {
		t.Fatalf("want one resolution receipt, got %d", resCount)
	}
}

func TestResolveHoldExpired(t *testing.T) {
	g := deployedGrant(t, "openclaw", false)
	fx := newFixture(t, "block", g, false)
	fx.eng.opts.HoldTimeoutMS = 1
	fx.eng.opts.Now = func() time.Time { return time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC) }
	d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "ls"}))
	if err != nil || d.Hold == nil {
		t.Fatalf("%v %+v", err, d)
	}
	fx.eng.opts.Now = func() time.Time { return time.Date(2026, 9, 6, 12, 0, 1, 0, time.UTC) }
	if _, err := fx.eng.ResolveHold(d.Receipt, true, "u-admin"); !errors.Is(err, ErrHoldExpired) {
		t.Fatalf("expired hold must refuse: %v", err)
	}
}

func TestChainReadSkipsIncompleteTrailingLine(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	if _, err := fx.eng.Decide(req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})); err != nil {
		t.Fatal(err)
	}
	files, err := fx.chain.files()
	if err != nil || len(files) == 0 {
		t.Fatalf("%v %v", err, files)
	}
	f, err := os.OpenFile(files[len(files)-1], os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.WriteString(`{"receipt_id":"partial`); err != nil {
		t.Fatal(err)
	}
	_ = f.Close()
	all, err := fx.chain.Read()
	if err != nil || len(all) != 1 {
		t.Fatalf("incomplete trailer must be skipped: %v n=%d", err, len(all))
	}
	_ = filepath.Base(files[0])
}
