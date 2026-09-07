package receipt

import (
	"errors"
	"testing"
	"time"
)

func TestActionWindowUsesSignedTimestampBeforeAndAfterRestart(t *testing.T) {
	for _, restart := range []bool{false, true} {
		for _, offset := range []time.Duration{-time.Nanosecond, 0, time.Nanosecond} {
			name := "live/"
			if restart {
				name = "restarted/"
			}
			t.Run(name+offset.String(), func(t *testing.T) {
				fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
				fx.clock = fx.clock.Truncate(time.Second).Add(500 * time.Millisecond)
				fx.eng.opts.Now = func() time.Time { return fx.clock }
				r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/report"})
				d, err := fx.eng.Decide(r)
				if err != nil || d.Action != ActionAllow {
					t.Fatal(d, err)
				}
				issued, err := time.Parse(time.RFC3339, d.Receipt.IssuedAt)
				if err != nil {
					t.Fatal(err)
				}
				fx.clock = issued.Add(actionWindow).Add(offset)
				engine := fx.eng
				if restart {
					engine, err = New(fx.eng.opts)
					if err != nil {
						t.Fatal(err)
					}
				}
				_, err = engine.Observe(correlatedRequest(r, d), "result")
				if offset < 0 {
					if err != nil {
						t.Fatalf("inside signed window must allow: %v", err)
					}
				} else {
					assertCorrelation(t, err, "observation_decision_missing")
				}
			})
		}
	}
}

func TestExpiredActionAndRecentObservationDoNotEraseBoundTaint(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	fx.clock = fx.clock.Truncate(time.Second)
	current := &IntentContract{IntentID: "bound-expiry", TaskID: "task-expiry", Digest: "digest", AuthorityRevision: "r1",
		Principal: "fixture-user", AgentID: "inst_1", Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: "2099-01-01T00:00:00Z"}
	opts := fx.eng.opts
	opts.MaxSessions, opts.SessionIdleTTL = 1, time.Second
	opts.Now = func() time.Time { return fx.clock }
	opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) { return current, nil }
	engine, err := New(opts)
	if err != nil {
		t.Fatal(err)
	}
	r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/report"})
	d, err := engine.Decide(r)
	if err != nil || d.Action != ActionAllow {
		t.Fatal(d, err)
	}
	issued := fx.clock
	fx.clock = issued.Add(actionWindow - time.Minute)
	result := "fixture contact: alice@example.com"
	if _, err := engine.Observe(correlatedRequest(r, d), result); err != nil {
		t.Fatal(err)
	}
	fx.clock = issued.Add(actionWindow)
	current = nil // Missing authority must never turn a formerly bound session clean.
	for _, restart := range []bool{false, true} {
		if restart {
			engine, err = New(opts)
			if err != nil {
				t.Fatal(err)
			}
		}
		_, err := engine.Observe(correlatedRequest(r, d), result)
		assertCorrelation(t, err, "observation_decision_missing")
		denied, err := engine.Decide(r)
		if err != nil || denied.Action != ActionDeny || denied.Receipt.ReasonCode != "intent_downgrade_attempt" {
			t.Fatalf("expiry erased trusted binding: %v %v", denied, err)
		}
		if !contains(denied.Receipt.TaintLabels, taintPII) || engine.actions[d.Receipt.ActionID] != nil {
			t.Fatal("action cleanup must retain taint and remove only expired action correlation")
		}
		fresh := r
		fresh.SessionID = "other-session"
		if _, err := engine.Decide(fresh); !errors.Is(err, ErrSessionCapacity) {
			t.Fatalf("bound tainted session must still occupy capacity: %v", err)
		}
	}
}
