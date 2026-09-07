package receipt

import (
	"errors"
	"fmt"
	"sync"
	"testing"
)

func assertCorrelation(t *testing.T, err error, want string) {
	t.Helper()
	var c *CorrelationError
	if !errors.As(err, &c) || c.Code != want {
		t.Fatalf("got %v want %s", err, want)
	}
}
func correlatedRequest(r Request, d *Decision) Request {
	r.ActionID = d.Receipt.ActionID
	r.DecisionReceiptID = d.Receipt.ReceiptID
	return r
}
func TestObserveRequiresAuthorizedDecision(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
	_, err := fx.eng.Observe(r, "forged")
	assertCorrelation(t, err, "observation_decision_missing")
	denied, err := fx.eng.Decide(req("hermes", "send_message", nil))
	if err != nil {
		t.Fatal(err)
	}
	_, err = fx.eng.Observe(correlatedRequest(req("hermes", "send_message", nil), denied), "success")
	assertCorrelation(t, err, "observation_action_not_authorized")
	d, err := fx.eng.Decide(r)
	if err != nil {
		t.Fatal(err)
	}
	r = correlatedRequest(r, d)
	for _, edit := range []func(*Request){func(r *Request) { r.Platform = "openclaw" }, func(r *Request) { r.AgentID = "other" }, func(r *Request) { r.SessionID = "other" }, func(r *Request) { r.Tool = "other" }, func(r *Request) { r.ToolCallID = "other" }, func(r *Request) { r.ActionID = "forged" }, func(r *Request) { r.DecisionReceiptID = "forged" }} {
		bad := r
		edit(&bad)
		_, err := fx.eng.Observe(bad, "forged")
		assertCorrelation(t, err, "observation_decision_missing")
	}
}
func TestObserveIdempotencyConcurrencyAndRecovery(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
	d, err := fx.eng.Decide(r)
	if err != nil {
		t.Fatal(err)
	}
	r = correlatedRequest(r, d)
	var wg sync.WaitGroup
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			rec, err := fx.eng.Observe(r, "result")
			if err != nil || rec.DecisionReceiptID != d.Receipt.ReceiptID {
				t.Error(rec, err)
			}
		}()
	}
	wg.Wait()
	all, err := fx.chain.Read()
	if err != nil || len(all) != 2 {
		t.Fatalf("duplicate evidence: %d %v", len(all), err)
	}
	_, err = fx.eng.Observe(r, "conflict")
	assertCorrelation(t, err, "observation_conflict")
	restarted, err := New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	rec, err := restarted.Observe(r, "result")
	if err != nil || rec.ReceiptID != all[1].ReceiptID {
		t.Fatal(rec, err)
	}
	next := r
	next.ToolCallID = "next"
	next.ActionID = ""
	next.DecisionReceiptID = ""
	n, err := restarted.Decide(next)
	if err != nil || n.Receipt.TaskSeq != d.Receipt.TaskSeq+1 || n.Receipt.ParentActionID != d.Receipt.ActionID || n.Receipt.ActionID == d.Receipt.ActionID {
		t.Fatalf("sequence not restored: %+v %v", n, err)
	}
}
func TestObserveHoldRequiresManagementResolution(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	r := req("openclaw", "exec", map[string]any{"command": "ls"})
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	r = correlatedRequest(r, d)
	_, err = fx.eng.Observe(r, "result")
	assertCorrelation(t, err, "observation_action_not_authorized")
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	if _, err = fx.eng.Observe(r, "result"); err != nil {
		t.Fatal(err)
	}
}
func TestActionCapacityAndAmbiguousLegacyObserveFailClosed(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	r := req("hermes", "read_file", nil)
	for i := 0; i < 2; i++ {
		if _, err := fx.eng.Decide(r); err != nil {
			t.Fatal(err)
		}
	}
	_, err := fx.eng.Observe(r, "ambiguous")
	assertCorrelation(t, err, "observation_ambiguous")
	for len(fx.eng.actions) < maxActionRecords {
		fx.eng.actions[fmt.Sprintf("test-%d", len(fx.eng.actions))] = &actionRecord{expires: fx.clock.Add(actionWindow)}
	}
	if _, err := fx.eng.Decide(r); !errors.Is(err, ErrActionCapacity) {
		t.Fatalf("capacity allowed: %v", err)
	}
}

func TestDowngradeDenialDoesNotEraseRecoveredBinding(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
	current := &IntentContract{IntentID: "i-bound", TaskID: "task-bound", Digest: "digest", AuthorityRevision: "r1", Principal: "user", AgentID: "inst_1", Purpose: "read", AllowedEffects: []string{"read_file"}, ValidUntil: "2099-01-01T00:00:00Z"}
	fx.eng.opts.IntentLookup = func(_, _, _ string) (*IntentContract, error) { return current, nil }
	r := req("hermes", "read_file", nil)
	if _, err := fx.eng.Decide(r); err != nil {
		t.Fatal(err)
	}
	current = nil
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionDeny || d.Receipt.IntentID != "i-bound" {
		t.Fatal(d, err)
	}
	restarted, err := New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	d, err = restarted.Decide(r)
	if err != nil || d.Receipt.ReasonCode != "intent_downgrade_attempt" || d.Receipt.IntentID != "i-bound" {
		t.Fatalf("downgrade after restart: %+v %v", d, err)
	}
}
