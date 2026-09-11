package runtimecheck

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

const testInstance = "hi-0123456789abcdef0123456789abcdef"

type managerFixture struct {
	m       *Manager
	engine  *receipt.Engine
	changed atomic.Bool
}

func newManagerFixture(t *testing.T) *managerFixture {
	t.Helper()
	store, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	pack, _ := rulepack.Builtin()
	intents, err := intent.Open(store.Dir, key, store.GetGrantWithSeq)
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(store.Dir, "local", key)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Grants: store.ActiveGrant, IntentLookup: receipt.ResolveStore(intents), IntentEnforcement: "required", EnforcementMode: "block"})
	if err != nil {
		t.Fatal(err)
	}
	fx := &managerFixture{engine: engine}
	fx.m, err = New(Options{Store: store, Intents: intents, Key: key, Pack: pack, Chain: chain, Endpoint: "http://127.0.0.1:47611", Snapshot: func(id string) (adapterinstall.RuntimeTarget, error) {
		if id != testInstance {
			return adapterinstall.RuntimeTarget{}, errors.New("runtime_check_instance_unavailable")
		}
		value := "a"
		if fx.changed.Load() {
			value = "b"
		}
		return adapterinstall.RuntimeTarget{InstanceID: id, Home: store.Dir, ProfilePath: store.Dir, NativeCLI: filepath.Join(store.Dir, "missing-native"), Digest: strings.Repeat(value, 64)}, nil
	}})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := fx.m.Close(ctx); err != nil {
			t.Error(err)
		}
	})
	return fx
}
func startFixture(t *testing.T, fx *managerFixture) (Plan, Result) {
	t.Helper()
	plan, err := fx.m.Preview(testInstance, "admin")
	if err != nil {
		t.Fatal(err)
	}
	out, err := fx.m.Start(plan.ID, plan.Digest, "admin", "operator")
	if err != nil {
		t.Fatal(err)
	}
	return plan, out
}
func awaitResult(t *testing.T, m *Manager, id string) Result {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		out, err := m.Get(id)
		if err != nil {
			t.Fatal(err)
		}
		if terminal(out.Status) {
			return out
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatal("runtime check did not finish")
	return Result{}
}
func (fx *managerFixture) runProbes(r *run, nonce string, p probes, emitObservation bool) error {
	input := Attach{SchemaVersion: "local-runtime-check-attach/v1", ID: r.record.Result.ID, InstanceID: testInstance, AgentID: agentID(r.record.Result.ID), SessionID: "synthetic-native-session"}
	if _, err := fx.m.Attach(input, nonce); err != nil {
		return err
	}
	for _, probe := range []struct{ id, tool, path, action string }{{"rc-first", "read_file", p.first, "allow"}, {"rc-denied", "write_file", p.forbidden, "deny"}, {"rc-last", "read_file", p.last, "allow"}} {
		request := receipt.Request{Platform: "hermes", AgentID: input.AgentID, SessionID: input.SessionID, Tool: probe.tool, ToolCallID: probe.id, Params: map[string]any{"path": probe.path}}
		d, err := fx.engine.Decide(request)
		if err != nil {
			return err
		}
		if d.Action != probe.action {
			return errors.New("wrong probe decision")
		}
		if d.Action == "allow" && emitObservation {
			request.ActionID, request.DecisionReceiptID = d.Receipt.ActionID, d.Receipt.ReceiptID
			if _, err := fx.engine.Observe(request, p.proof); err != nil {
				return err
			}
		}
	}
	return nil
}

func TestCheckTemporaryAuthorityAndVerifiedCleanup(t *testing.T) {
	fx := newManagerFixture(t)
	fx.m.launchHost = func(_ context.Context, r *run, _ adapterinstall.RuntimeTarget, nonce string, p probes) error {
		return fx.runProbes(r, nonce, p, true)
	}
	plan, started := startFixture(t, fx)
	if started.Status != "preparing" {
		t.Fatal(started)
	}
	out := awaitResult(t, fx.m, plan.ID)
	if out.Status != "passed" || out.Cleanup != "complete" || len(out.ReceiptIDs) != 5 {
		t.Fatal(out)
	}
	grants, err := fx.m.o.Store.ListGrants()
	if err != nil || len(grants) != 1 || grants[0].Status != "revoked" || grants[0].ExpiresAt == nil {
		t.Fatal(grants, err)
	}
	if _, err := os.Stat(fx.m.materials(plan.ID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("materials retained")
	}
	bindings, err := fx.m.o.Intents.ListBindings()
	if err != nil || len(bindings) != 1 {
		t.Fatal(err)
	}
	if _, err := fx.m.o.Intents.GetBindingRevocation(bindings[0].BindingID); err != nil {
		t.Fatal("binding not revoked", err)
	}
	if _, err := fx.m.o.Intents.GetIntentRevocation(bindings[0].IntentID); err != nil {
		t.Fatal("intent not revoked", err)
	}
	events, err := fx.m.o.Store.TailAudit(100)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, event := range events {
		seen[event.Event] = true
	}
	for _, name := range []string{"runtime_check_start", "runtime_check_grant_approve", "runtime_check_grant_revoke", "runtime_check_finish"} {
		if !seen[name] {
			t.Fatal("missing audit", name)
		}
	}
	fx.changed.Store(true)
	out, err = fx.m.Get(plan.ID)
	if err != nil || out.Status != "invalidated" {
		t.Fatal(out, err)
	}
	fx.changed.Store(false)
	out, err = fx.m.Get(plan.ID)
	if err != nil || out.Status != "invalidated" {
		t.Fatal("invalidation resurrected", out, err)
	}
}

func TestPlanRequiresSameAdminSnapshotAndSingleUse(t *testing.T) {
	fx := newManagerFixture(t)
	plan, err := fx.m.Preview(testInstance, "admin")
	if err != nil {
		t.Fatal(err)
	}
	grants, err := fx.m.o.Store.ListGrants()
	if err != nil || len(grants) != 0 {
		t.Fatal("preview created authority")
	}
	if _, err := fx.m.Start(plan.ID, plan.Digest, "another-admin", "operator"); err != ErrCredential {
		t.Fatal(err)
	}
	if _, err := fx.m.Start(plan.ID, "changed", "admin", "operator"); err != ErrCredential {
		t.Fatal(err)
	}
	if _, err := fx.m.Start(plan.ID, plan.Digest, "admin", " "); err == nil {
		t.Fatal("empty actor")
	}
	fx.changed.Store(true)
	if _, err := fx.m.Start(plan.ID, plan.Digest, "admin", "operator"); err == nil {
		t.Fatal("drift accepted")
	}
	fx.changed.Store(false)
	fx.m.launchHost = func(context.Context, *run, adapterinstall.RuntimeTarget, string, probes) error {
		return errors.New("runtime_check_test_failure")
	}
	if _, err := fx.m.Start(plan.ID, plan.Digest, "admin", "operator"); err != nil {
		t.Fatal(err)
	}
	if _, err := fx.m.Start(plan.ID, plan.Digest, "admin", "operator"); err != ErrNotFound {
		t.Fatal("replayed start", err)
	}
	out := awaitResult(t, fx.m, plan.ID)
	if out.Status != "failed" || out.Cleanup != "complete" {
		t.Fatal(out)
	}
}

func TestLaunchAttachmentRejectsSubstitutionExpiryAndReplay(t *testing.T) {
	fx := newManagerFixture(t)
	fx.m.launchHost = func(_ context.Context, r *run, _ adapterinstall.RuntimeTarget, nonce string, _ probes) error {
		base := Attach{SchemaVersion: "local-runtime-check-attach/v1", ID: r.record.Result.ID, InstanceID: testInstance, AgentID: agentID(r.record.Result.ID), SessionID: "native"}
		for _, mutate := range []func(*Attach){func(a *Attach) { a.InstanceID = "hi-" + strings.Repeat("f", 32) }, func(a *Attach) { a.AgentID = "other" }, func(a *Attach) { a.SessionID = "" }, func(a *Attach) { a.SchemaVersion = "wrong" }} {
			bad := base
			mutate(&bad)
			if _, err := fx.m.Attach(bad, nonce); err == nil {
				t.Error("invalid attachment accepted")
			}
		}
		if _, err := fx.m.Attach(base, strings.Repeat("0", 64)); err == nil {
			t.Error("wrong credential accepted")
		}
		if fx.m.HasDecisionCredential(nonce) {
			t.Error("unattached check has decision authority")
		}
		for range 2 {
			if _, err := fx.m.Attach(base, nonce); err != nil {
				t.Error("same session retry", err)
			}
		}
		if !fx.m.HasDecisionCredential(nonce) || !fx.m.AuthorizeDecision(nonce, "hermes", base.AgentID, "native") {
			t.Error("attached check cannot authenticate")
		}
		for _, tuple := range [][3]string{{"hermes", base.AgentID, "other-session"}, {"hermes", "other-agent", "native"}, {"openclaw", base.AgentID, "native"}} {
			if fx.m.AuthorizeDecision(nonce, tuple[0], tuple[1], tuple[2]) {
				t.Error("launch credential borrowed another tuple")
			}
		}
		if fx.m.HasDecisionCredential(strings.Repeat("0", 64)) {
			t.Error("global or forged credential accepted")
		}
		bad := base
		bad.SessionID = "other-session"
		if _, err := fx.m.Attach(bad, nonce); err != ErrConflict {
			t.Error("session replaced", err)
		}
		fx.m.mu.Lock()
		r.record.Result.ExpiresAt = time.Now().Add(-time.Second).Format(time.RFC3339Nano)
		fx.m.mu.Unlock()
		if _, err := fx.m.Attach(base, nonce); err == nil {
			t.Error("expired ticket accepted")
		}
		if fx.m.HasDecisionCredential(nonce) || fx.m.AuthorizeDecision(nonce, "hermes", base.AgentID, "native") {
			t.Error("expired check credential retained authority")
		}
		return errors.New("runtime_check_test_end")
	}
	plan, _ := startFixture(t, fx)
	out := awaitResult(t, fx.m, plan.ID)
	if out.Cleanup != "complete" {
		t.Fatal(out)
	}
	if _, err := fx.m.Attach(Attach{ID: plan.ID}, strings.Repeat("0", 64)); err != ErrCredential {
		t.Fatal(err)
	}
}

func TestCancelStopsLaunchAndRevokesAuthority(t *testing.T) {
	fx := newManagerFixture(t)
	entered := make(chan struct{})
	fx.m.launchHost = func(ctx context.Context, _ *run, _ adapterinstall.RuntimeTarget, _ string, _ probes) error {
		close(entered)
		<-ctx.Done()
		return errors.New("runtime_check_cancelled")
	}
	plan, _ := startFixture(t, fx)
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		t.Fatal("launch not reached")
	}
	other, err := fx.m.Preview(testInstance, "admin")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = fx.m.Start(other.ID, other.Digest, "admin", "operator"); err != ErrConflict {
		t.Fatal("parallel launch accepted", err)
	}
	if _, err = fx.m.Cancel(plan.ID); err != nil {
		t.Fatal(err)
	}
	out := awaitResult(t, fx.m, plan.ID)
	if out.Status != "cancelled" || out.Cleanup != "complete" {
		t.Fatal(out)
	}
}

func TestExitSuccessCannotReplaceObservationsOrSideEffectCheck(t *testing.T) {
	for _, test := range []string{"no_hooks", "missing_observation", "forbidden_write"} {
		t.Run(test, func(t *testing.T) {
			fx := newManagerFixture(t)
			fx.m.launchHost = func(_ context.Context, r *run, _ adapterinstall.RuntimeTarget, nonce string, p probes) error {
				if test == "no_hooks" {
					return nil
				}
				if err := fx.runProbes(r, nonce, p, test != "missing_observation"); err != nil {
					return err
				}
				if test == "forbidden_write" {
					return os.WriteFile(p.forbidden, []byte("unexpected effect"), 0600)
				}
				return nil
			}
			plan, _ := startFixture(t, fx)
			out := awaitResult(t, fx.m, plan.ID)
			if out.Status != "failed" || out.Cleanup != "complete" {
				t.Fatal(out)
			}
		})
	}
}
