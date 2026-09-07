package receipt

import (
	"fmt"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/intent"
)

func revocableEngine(t *testing.T, enforcement, mode string) (*fixture, *intent.Store, intent.Binding) {
	t.Helper()
	fx := newFixture(t, mode, deployedGrant(t, "hermes", false), false)
	fx.clock = time.Now().UTC()
	store, err := intent.Open(t.TempDir(), fx.k)
	if err != nil {
		t.Fatal(err)
	}
	c := intent.Contract{SchemaVersion: "intent/v2", IntentID: "int-revocable", TaskID: "task-revocable", Principal: intent.Principal{Type: "user", ID: "fixture-user"}, Agent: intent.Agent{ID: "inst_1", Platform: "hermes"}, Purpose: "read fixture", AllowedTools: []string{"read_file"}, AllowedEffects: []string{"file.read"}, ResourceConstraints: []intent.ResourceConstraint{}, ParameterConstraints: []intent.ParameterConstraint{}, IssuedAt: "2026-01-01T00:00:00Z", ValidFrom: "2026-01-01T00:00:00Z", ExpiresAt: "2099-01-01T00:00:00Z", Authority: intent.Authority{Issuer: "local-admin", Revision: "r1", EvidenceIDs: []string{}}}
	issued, err := store.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	binding, err := store.Bind(intent.Binding{Platform: "hermes", SessionID: "sess-1", AgentID: "inst_1", IntentID: issued.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	fx.eng.opts.IntentEnforcement = enforcement
	fx.eng.opts.IntentLookup = ResolveStore(store)
	return fx, store, binding
}
func assertRevokedDecision(t *testing.T, d *Decision, err error, mode string) {
	t.Helper()
	if err != nil || d == nil {
		t.Fatal(d, err)
	}
	if d.Receipt.ReasonCode != "intent_binding_revoked" || d.Receipt.IntentBinding != "bound" || d.Receipt.IntentID != "int-revocable" || d.Receipt.Principal == nil || d.Receipt.Principal.ID != "fixture-user" {
		t.Fatalf("revoked binding lost denial metadata: %+v", d.Receipt)
	}
	if mode == "block" {
		if d.Action != ActionDeny {
			t.Fatal("revocation did not block")
		}
	} else if d.Action != ActionAllow || str(d.Receipt.AdvisoryAction) != ActionDeny {
		t.Fatal("advisory mode lost would-deny")
	}
}
func TestRevokedBindingCannotDowngradeEvenBeforeFirstDecision(t *testing.T) {
	for _, enforcement := range []string{"optional", "required"} {
		for _, mode := range []string{"block", "warn", "audit_only"} {
			t.Run(enforcement+"/"+mode, func(t *testing.T) {
				fx, store, b := revocableEngine(t, enforcement, mode)
				if _, err := store.RevokeBinding(b.BindingID, b.IntentDigest); err != nil {
					t.Fatal(err)
				}
				request := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
				d, err := fx.eng.Decide(request)
				assertRevokedDecision(t, d, err, mode)
				eng, err := New(fx.eng.opts)
				if err != nil {
					t.Fatal(err)
				}
				d, err = eng.Decide(request)
				assertRevokedDecision(t, d, err, mode)
			})
		}
	}
}
func TestRevocationPreservesTaintSequenceAndPastObservation(t *testing.T) {
	fx, store, b := revocableEngine(t, "optional", "block")
	request := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
	first, err := fx.eng.Decide(request)
	if err != nil || first.Action != ActionAllow {
		t.Fatal(first, err)
	}
	request.ActionID, request.DecisionReceiptID = first.Receipt.ActionID, first.Receipt.ReceiptID
	if _, err = fx.eng.Observe(request, "fixture sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"); err != nil {
		t.Fatal(err)
	}
	if _, err = store.RevokeBinding(b.BindingID, b.IntentDigest); err != nil {
		t.Fatal(err)
	}
	next := request
	next.ActionID, next.DecisionReceiptID = "", ""
	next.ToolCallID = "after-revoke"
	d, err := fx.eng.Decide(next)
	assertRevokedDecision(t, d, err, "block")
	if d.Receipt.TaskSeq != first.Receipt.TaskSeq+1 || d.Receipt.ParentActionID != first.Receipt.ActionID || !contains(d.Receipt.TaintLabels, taintSecret) {
		t.Fatal("revocation reset security state")
	}
	// Withdrawal does not falsify a completed pre-revocation execution or create
	// duplicate observations on retry. A denied action still cannot be observed.
	if _, err = fx.eng.Observe(request, "fixture sk-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"); err != nil {
		t.Fatal(err)
	}
	next.ActionID, next.DecisionReceiptID = d.Receipt.ActionID, d.Receipt.ReceiptID
	if _, err = fx.eng.Observe(next, "fake success"); err == nil {
		t.Fatal("revoked denial accepted observation")
	}
}
func TestBindingRevokeWhileDecideUsesExplicitSnapshotOrder(t *testing.T) {
	fx, store, b := revocableEngine(t, "optional", "block")
	lookup := ResolveStore(store)
	resolved, resume := make(chan struct{}), make(chan struct{})
	var once sync.Once
	fx.eng.opts.IntentLookup = func(platform, session, agent string) (*IntentContract, error) {
		c, err := lookup(platform, session, agent)
		once.Do(func() { close(resolved); <-resume })
		return c, err
	}
	result := make(chan *Decision, 1)
	request := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
	go func() {
		d, err := fx.eng.Decide(request)
		if err != nil {
			t.Error(err)
		}
		result <- d
	}()
	<-resolved
	if _, err := store.RevokeBinding(b.BindingID, b.IntentDigest); err != nil {
		t.Fatal(err)
	}
	close(resume)
	if d := <-result; d == nil || d.Action != ActionAllow {
		t.Fatal("pre-revocation snapshot unexpectedly changed")
	}
	var wg sync.WaitGroup
	for i := 0; i < 32; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			r := request
			r.ToolCallID = fmt.Sprintf("after-revoke-%d", i)
			d, err := fx.eng.Decide(r)
			if err != nil || d == nil || d.Action != ActionDeny || d.Receipt.ReasonCode != "intent_binding_revoked" {
				t.Errorf("post-revocation decision: %+v %v", d, err)
			}
		}(i)
	}
	wg.Wait()
}

func TestCurrentHoldAuthorityRejectsRevokedBinding(t *testing.T) {
	fx, store, b := revocableEngine(t, "optional", "block")
	r := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionAllow {
		t.Fatal(d, err)
	}
	// Exercise the shared authorization predicate. A read decision does not claim
	// that a bound arbitrary exec hold is reachable in the current Grant compiler.
	request := statusRequest(r, d)
	if !fx.eng.holdAuthorityCurrent(request, d.Receipt, fx.clock) {
		t.Fatal("normal binding is not current")
	}
	if _, err = store.RevokeBinding(b.BindingID, b.IntentDigest); err != nil {
		t.Fatal(err)
	}
	if fx.eng.holdAuthorityCurrent(request, d.Receipt, fx.clock) {
		t.Fatal("revoked binding remained approval-eligible")
	}
}
