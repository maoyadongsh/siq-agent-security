package receipt

import (
	"testing"
	"time"
)

func TestGrantExpirationDecisionBoundaryAndModes(t *testing.T) {
	deadline := time.Date(2026, 9, 4, 7, 1, 0, 0, time.UTC)
	value := deadline.Format(time.RFC3339Nano)
	for _, mode := range []string{"block", "warn", "audit_only"} {
		for _, tc := range []struct {
			name   string
			at     time.Time
			expiry *string
			denied bool
			reason string
		}{
			{"legacy", deadline, nil, false, ""},
			{"before", deadline.Add(-time.Nanosecond), &value, false, ""},
			{"equal", deadline, &value, true, "grant_expired"},
			{"after", deadline.Add(time.Nanosecond), &value, true, "grant_expired"},
			{"invalid", deadline, new(string), true, "grant_expiration_invalid"},
		} {
			t.Run(mode+"/"+tc.name, func(t *testing.T) {
				g := deployedGrant(t, "hermes", false)
				// The injected lookup represents trusted stored authority; expiry
				// is evaluated independently of the storage signature verification.
				g.ExpiresAt = tc.expiry
				fx := newFixture(t, mode, g, false)
				fx.eng.opts.Now = func() time.Time { return tc.at }
				d, err := fx.eng.Decide(req("hermes", "read_file", map[string]any{"path": "/home/u/proj/report.txt"}))
				if err != nil {
					t.Fatal(err)
				}
				want := ActionAllow
				if mode == "block" && tc.denied {
					want = ActionDeny
				}
				if d.Action != want {
					t.Fatalf("action %s, want %s", d.Action, want)
				}
				if tc.denied && d.Receipt.ReasonCode != tc.reason {
					t.Fatalf("reason %+v", d.Receipt)
				}
				if mode != "block" && tc.denied && (d.Receipt.AdvisoryAction == nil || *d.Receipt.AdvisoryAction != ActionDeny) {
					t.Fatal("lost advisory denial")
				}
			})
		}
	}
}

func TestGrantExpirationRevokesApprovedHoldExecution(t *testing.T) {
	g := deployedGrant(t, "openclaw", false)
	fx := newFixture(t, "block", g, false)
	deadline := fx.clock.Add(30 * time.Second)
	value := deadline.Format(time.RFC3339Nano)
	g.ExpiresAt = &value
	r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	if _, err := fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	request := statusRequest(r, d)
	current, err := fx.eng.ReadHoldStatus(request)
	if err != nil || current.Status != "approved" {
		t.Fatal(current, err)
	}
	fx.eng.opts.Now = func() time.Time { return deadline }
	current, err = fx.eng.ReadHoldStatus(request)
	if err != nil || current.Status != "denied" || current.ReasonCode != "hold_authority_changed" {
		t.Fatal(current, err)
	}
	all, err := fx.chain.Read()
	if err != nil || Verify(all, fx.k.Public()) != nil {
		t.Fatal("historical receipts must remain verifiable", err)
	}
}

func TestExpiredGrantCannotEnableRedaction(t *testing.T) {
	g := deployedGrant(t, "hermes", true)
	fx := newFixture(t, "block", g, false)
	r := req("hermes", "web_fetch", map[string]any{"url": "https://api.github.com"})
	if !fx.eng.redactAllowed(r, fx.clock) {
		t.Fatal("fixture lacks redaction authority")
	}
	expiry := fx.clock.Format(time.RFC3339Nano)
	g.ExpiresAt = &expiry
	if fx.eng.redactAllowed(r, fx.clock) {
		t.Fatal("expired grant still permits redaction")
	}
}

func TestCompletedObservationRemainsRecordableAfterGrantExpiry(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	deadline := fx.clock.Add(30 * time.Second)
	value := deadline.Format(time.RFC3339Nano)
	g.ExpiresAt = &value
	r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/report.txt"})
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionAllow {
		t.Fatal(d, err)
	}
	fx.eng.opts.Now = func() time.Time { return deadline }
	if _, err := fx.eng.Observe(correlatedRequest(r, d), "fixture result"); err != nil {
		t.Fatal("historical observation lost", err)
	}
	all, err := fx.chain.Read()
	if err != nil || len(all) != 2 || Verify(all, fx.k.Public()) != nil {
		t.Fatal("historical chain invalid", err)
	}
	r.ToolCallID = "new-after-expiry"
	d, err = fx.eng.Decide(r)
	if err != nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "grant_expired" {
		t.Fatal("new action allowed", d, err)
	}
}
