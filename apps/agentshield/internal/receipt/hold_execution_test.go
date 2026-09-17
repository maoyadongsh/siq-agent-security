package receipt

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func executionStatusRequest(req Request, d *Decision, status *HoldExecutionStatus, retryCallID string) HoldExecutionStatusRequest {
	return HoldExecutionStatusRequest{
		SchemaVersion: "hold-execution-status-request/v1", Platform: req.Platform,
		SessionID: req.SessionID, AgentID: req.AgentID, TaskID: d.Receipt.TaskID, RuntimeTaskID: d.Receipt.RuntimeTaskID, Tool: req.Tool,
		RetryToolCallID: retryCallID, ActionID: d.Receipt.ActionID,
		DecisionReceiptID: d.Receipt.ReceiptID, ReservationReceiptID: status.ReservationReceiptID,
		Params: req.Params,
	}
}

func TestHoldExecutionBindsSeparateRuntimeTask(t *testing.T) {
	g := deployedGrant(t, "openclaw", false)
	fx := newFixture(t, "block", nil, false)
	fx.eng.opts.IntentLookup = func(platform, sessionID, agentID string) (*IntentContract, error) {
		return &IntentContract{IntentID: "intent-runtime-hold", TaskID: "trusted-task", Principal: "user",
			AgentID: "inst_1", Purpose: "execute", AllowedTools: []string{"exec"}, AllowedEffects: []string{"*"},
			ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "rev-runtime", SelectedGrant: g}, nil
	}
	r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	r.RuntimeTaskID = "native-task"
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	base := HoldExecutionReserve{SchemaVersion: "hold-execution-reserve/v1", Platform: r.Platform,
		SessionID: r.SessionID, AgentID: r.AgentID, TaskID: d.Receipt.TaskID, RuntimeTaskID: r.RuntimeTaskID,
		Tool: r.Tool, OriginalToolCallID: r.ToolCallID, RetryToolCallID: "retry-runtime",
		ActionID: d.Receipt.ActionID, DecisionReceiptID: d.Receipt.ReceiptID, Params: r.Params}
	for name, mutate := range map[string]func(*HoldExecutionReserve){
		"missing runtime task": func(v *HoldExecutionReserve) { v.RuntimeTaskID = "" },
		"changed runtime task": func(v *HoldExecutionReserve) { v.RuntimeTaskID = "other-native-task" },
		"changed intent task":  func(v *HoldExecutionReserve) { v.TaskID = v.RuntimeTaskID },
	} {
		t.Run(name, func(t *testing.T) {
			changed := base
			mutate(&changed)
			if _, reserveErr := fx.eng.ReserveHoldExecution(changed); reserveErr == nil {
				t.Fatal("changed task boundary reserved")
			}
		})
	}
	status, err := fx.eng.ReserveHoldExecution(base)
	if err != nil || status.Status != "reserved" {
		t.Fatal(status, err)
	}
}

func TestHoldExecutionRequiresApprovalAndExactImmutableIdentity(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	r.TaskID = "task-1"
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	base := HoldExecutionReserve{
		SchemaVersion: "hold-execution-reserve/v1", Platform: r.Platform, SessionID: r.SessionID,
		AgentID: r.AgentID, TaskID: r.TaskID, Tool: r.Tool, OriginalToolCallID: r.ToolCallID,
		RetryToolCallID: "retry-1", ActionID: d.Receipt.ActionID, DecisionReceiptID: d.Receipt.ReceiptID,
		Params: r.Params,
	}
	if _, err = fx.eng.ReserveHoldExecution(base); err == nil {
		t.Fatal("pending hold reserved")
	}
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	mutations := []func(*HoldExecutionReserve){
		func(v *HoldExecutionReserve) { v.SchemaVersion = "other" },
		func(v *HoldExecutionReserve) { v.Platform = "hermes" },
		func(v *HoldExecutionReserve) { v.SessionID = "other" },
		func(v *HoldExecutionReserve) { v.AgentID = "other" },
		func(v *HoldExecutionReserve) { v.TaskID = "other" },
		func(v *HoldExecutionReserve) { v.Tool = "write_file" },
		func(v *HoldExecutionReserve) { v.OriginalToolCallID = "other" },
		func(v *HoldExecutionReserve) { v.RetryToolCallID = v.OriginalToolCallID },
		func(v *HoldExecutionReserve) { v.RetryToolCallID = string(make([]byte, 257)) },
		func(v *HoldExecutionReserve) { v.ActionID = "other" },
		func(v *HoldExecutionReserve) { v.DecisionReceiptID = "other" },
		func(v *HoldExecutionReserve) { v.Params = map[string]any{"command": "changed"} },
	}
	for i, mutate := range mutations {
		changed := base
		mutate(&changed)
		if _, err = fx.eng.ReserveHoldExecution(changed); err == nil {
			t.Fatalf("mutation %d reserved", i)
		}
	}
	status, err := fx.eng.ReserveHoldExecution(base)
	if err != nil || status.Status != "reserved" || status.ReasonCode != "hold_execution_reserved" {
		t.Fatal(status, err)
	}
	if _, err = fx.eng.ReserveHoldExecution(base); !errors.Is(err, ErrHoldExecutionConflict) {
		t.Fatal("duplicate reservation was not a conflict", err)
	}
	if _, err = fx.eng.Observe(correlatedRequest(r, d), "forged"); err == nil {
		t.Fatal("original hold receipt bypassed reservation")
	}
}

func TestHoldExecutionConcurrentReservationRecoveryAndCompletion(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	r := req("openclaw", "exec", map[string]any{"command": "printf once"})
	d, err := fx.eng.Decide(r)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	base := HoldExecutionReserve{SchemaVersion: "hold-execution-reserve/v1", Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, TaskID: r.TaskID, Tool: r.Tool, OriginalToolCallID: r.ToolCallID, RetryToolCallID: "retry-once", ActionID: d.Receipt.ActionID, DecisionReceiptID: d.Receipt.ReceiptID, Params: r.Params}
	var successes atomic.Int32
	marker := filepath.Join(t.TempDir(), "side-effect.txt")
	var statusMu sync.Mutex
	var status *HoldExecutionStatus
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			got, reserveErr := fx.eng.ReserveHoldExecution(base)
			if reserveErr == nil {
				successes.Add(1)
				file, openErr := os.OpenFile(marker, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
				if openErr != nil {
					t.Error(openErr)
				} else {
					if _, writeErr := file.WriteString("executed exactly once\n"); writeErr != nil {
						t.Error(writeErr)
					}
					if closeErr := file.Close(); closeErr != nil {
						t.Error(closeErr)
					}
				}
				statusMu.Lock()
				status = got
				statusMu.Unlock()
			} else if !errors.Is(reserveErr, ErrHoldExecutionConflict) {
				t.Error(reserveErr)
			}
		}()
	}
	wg.Wait()
	if successes.Load() != 1 || status == nil {
		t.Fatal("reservation count", successes.Load(), status)
	}
	content, err := os.ReadFile(marker)
	if err != nil || string(content) != "executed exactly once\n" {
		t.Fatal("real side effect was not exactly once", string(content), err)
	}
	query := executionStatusRequest(r, d, status, base.RetryToolCallID)
	got, err := fx.eng.ReadHoldExecutionStatus(query)
	if err != nil || got.Status != "uncertain" {
		t.Fatal(got, err)
	}
	before, _ := fx.chain.Read()
	for i := 0; i < 5; i++ {
		if _, err = fx.eng.ReadHoldExecutionStatus(query); err != nil {
			t.Fatal(err)
		}
	}
	after, _ := fx.chain.Read()
	if len(before) != len(after) {
		t.Fatal("status read appended records")
	}

	fx.eng, err = New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	got, err = fx.eng.ReadHoldExecutionStatus(query)
	if err != nil || got.Status != "uncertain" || got.ReasonCode != "hold_execution_uncertain" {
		t.Fatal(got, err)
	}
	if _, err = fx.eng.ReserveHoldExecution(base); !errors.Is(err, ErrHoldExecutionConflict) {
		t.Fatal("restart permitted blind re-execution", err)
	}
	second := r
	second.TaskID = "another-task"
	second.ToolCallID = "another-call"
	blocked, err := fx.eng.Decide(second)
	if err != nil || blocked.Action != ActionDeny || blocked.Receipt.ReasonCode != "hold_execution_uncertain" {
		t.Fatal("uncertain execution entered a fresh approval cycle", blocked, err)
	}
	retry := r
	retry.ToolCallID = base.RetryToolCallID
	retry.ActionID = d.Receipt.ActionID
	retry.DecisionReceiptID = status.ReservationReceiptID
	observed, err := fx.eng.Observe(retry, "completed result")
	if err != nil {
		t.Fatal(err)
	}
	again, err := fx.eng.Observe(retry, "completed result")
	if err != nil || again.ReceiptID != observed.ReceiptID {
		t.Fatal("result retry changed observation", again, err)
	}
	if _, err = fx.eng.Observe(retry, "different result"); err == nil {
		t.Fatal("conflicting result accepted")
	}
	got, err = fx.eng.ReadHoldExecutionStatus(query)
	if err != nil || got.Status != "completed" || got.ReasonCode != "hold_execution_completed" {
		t.Fatal(got, err)
	}
	all, err := fx.chain.Read()
	if err != nil || len(all) != 5 || all[2].RecordType != "hold_reservation" || all[4].DecisionReceiptID != all[2].ReceiptID || Verify(all, fx.k.Public()) != nil {
		t.Fatal("invalid retry chain", len(all), err)
	}
}

func TestHoldExecutionStatusRejectsTamperingAndChangedAuthority(t *testing.T) {
	g := deployedGrant(t, "openclaw", false)
	fx := newFixture(t, "block", g, false)
	r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	d, err := fx.eng.Decide(r)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	retry, status := reserveForRetry(t, fx, r, d, "status-tamper-retry")
	_ = retry
	query := executionStatusRequest(r, d, status, "status-tamper-retry")
	for i, mutate := range []func(*HoldExecutionStatusRequest){
		func(v *HoldExecutionStatusRequest) { v.SchemaVersion = "other" },
		func(v *HoldExecutionStatusRequest) { v.Platform = "hermes" },
		func(v *HoldExecutionStatusRequest) { v.SessionID = "other" },
		func(v *HoldExecutionStatusRequest) { v.AgentID = "other" },
		func(v *HoldExecutionStatusRequest) { v.TaskID = "other" },
		func(v *HoldExecutionStatusRequest) { v.Tool = "other" },
		func(v *HoldExecutionStatusRequest) { v.RetryToolCallID = "other" },
		func(v *HoldExecutionStatusRequest) { v.ActionID = "other" },
		func(v *HoldExecutionStatusRequest) { v.DecisionReceiptID = "other" },
		func(v *HoldExecutionStatusRequest) { v.ReservationReceiptID = "other" },
		func(v *HoldExecutionStatusRequest) { v.Params = map[string]any{"command": "changed"} },
	} {
		changed := query
		mutate(&changed)
		if _, err = fx.eng.ReadHoldExecutionStatus(changed); err == nil {
			t.Fatalf("status mutation %d accepted", i)
		}
	}
	g.Status = "revoked"
	got, err := fx.eng.ReadHoldExecutionStatus(query)
	if err != nil || got.Status != "uncertain" || got.ReasonCode != "hold_execution_uncertain" {
		t.Fatal(got, err)
	}
}

func TestHoldExecutionAdministratorReconciliationIsSignedAndCannotReuseReservation(t *testing.T) {
	for _, outcome := range []string{HoldExecutionOccurred, HoldExecutionNotOccurred} {
		t.Run(outcome, func(t *testing.T) {
			fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
			r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
			d, err := fx.eng.Decide(r)
			if err != nil {
				t.Fatal(err)
			}
			if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
				t.Fatal(err)
			}
			retry, status := reserveForRetry(t, fx, r, d, "reconcile-retry")
			query := executionStatusRequest(r, d, status, "reconcile-retry")
			fx.clock = fx.clock.Add(6 * time.Minute)
			if got, readErr := fx.eng.ReadHoldExecutionStatus(query); readErr != nil || got.Status != "uncertain" {
				t.Fatal("reservation uncertainty was hidden by approval expiry", got, readErr)
			}
			reservation := fx.eng.actions[d.Receipt.ActionID].reservation
			base := HoldExecutionReconcile{SchemaVersion: "hold-execution-reconcile/v1", ActionID: d.Receipt.ActionID,
				DecisionReceiptID: d.Receipt.ReceiptID, ReservationReceiptID: reservation.ReceiptID,
				ReservationHash: reservation.Hash, Outcome: outcome, ActorID: "fixture-admin"}
			for i, mutate := range []func(*HoldExecutionReconcile){
				func(v *HoldExecutionReconcile) { v.SchemaVersion = "other" },
				func(v *HoldExecutionReconcile) { v.ActionID = "other" },
				func(v *HoldExecutionReconcile) { v.DecisionReceiptID = "other" },
				func(v *HoldExecutionReconcile) { v.ReservationReceiptID = "other" },
				func(v *HoldExecutionReconcile) { v.ReservationHash = strings.Repeat("A", 64) },
				func(v *HoldExecutionReconcile) { v.Outcome = "retry" },
				func(v *HoldExecutionReconcile) { v.ActorID = "\n" },
			} {
				changed := base
				mutate(&changed)
				if _, err = fx.eng.ReconcileHoldExecution(changed); err == nil {
					t.Fatalf("reconciliation mutation %d accepted", i)
				}
			}
			resolved, err := fx.eng.ReconcileHoldExecution(base)
			if err != nil || resolved.ReconciliationReceiptID == "" {
				t.Fatal(resolved, err)
			}
			wantStatus := "completed"
			if outcome == HoldExecutionNotOccurred {
				wantStatus = "cancelled"
			}
			if resolved.Status != wantStatus {
				t.Fatal(resolved)
			}
			again, err := fx.eng.ReconcileHoldExecution(base)
			if err != nil || again.ReconciliationReceiptID != resolved.ReconciliationReceiptID {
				t.Fatal("identical reconciliation was not idempotent", again, err)
			}
			opposite := base
			if outcome == HoldExecutionOccurred {
				opposite.Outcome = HoldExecutionNotOccurred
			} else {
				opposite.Outcome = HoldExecutionOccurred
			}
			if _, err = fx.eng.ReconcileHoldExecution(opposite); !errors.Is(err, ErrHoldReconciliationConflict) {
				t.Fatal("opposite finding did not conflict", err)
			}
			if _, err = fx.eng.ReserveHoldExecution(HoldExecutionReserve{
				SchemaVersion: "hold-execution-reserve/v1", Platform: r.Platform, SessionID: r.SessionID,
				AgentID: r.AgentID, TaskID: r.TaskID, Tool: r.Tool, OriginalToolCallID: r.ToolCallID,
				RetryToolCallID: "another-retry", ActionID: d.Receipt.ActionID,
				DecisionReceiptID: d.Receipt.ReceiptID, Params: r.Params,
			}); !errors.Is(err, ErrHoldExecutionConflict) {
				t.Fatal("old reservation became reusable", err)
			}
			if outcome == HoldExecutionNotOccurred {
				if _, err = fx.eng.Observe(retry, "late result"); err == nil {
					t.Fatal("late result contradicted signed not-occurred finding")
				}
			}
			all, err := fx.chain.Read()
			if err != nil || len(all) != 4 || all[3].RecordType != "hold_reconciliation" || all[3].DecisionReceiptID != reservation.ReceiptID || Verify(all, fx.k.Public()) != nil {
				t.Fatal("invalid reconciliation chain", len(all), err)
			}
			fx.eng, err = New(fx.eng.opts)
			if err != nil {
				t.Fatal(err)
			}
			got, err := fx.eng.ReadHoldExecutionStatus(query)
			if err != nil || got.Status != wantStatus || got.ReconciliationReceiptID != resolved.ReconciliationReceiptID {
				t.Fatal("reconciled state did not survive restart", got, err)
			}
			fresh := r
			fresh.TaskID, fresh.ToolCallID = "fresh-task", "fresh-call"
			decision, err := fx.eng.Decide(fresh)
			if err != nil || decision.Action != ActionHold {
				t.Fatal("reconciled effect remained permanently blocked", decision, err)
			}
		})
	}
}

func TestUncertainReservationSurvivesActionWindowAndRestart(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
		t.Fatal(err)
	}
	_, status := reserveForRetry(t, fx, r, d, "expired-window-retry")
	query := executionStatusRequest(r, d, status, "expired-window-retry")
	reservation := fx.eng.actions[d.Receipt.ActionID].reservation

	fx.clock = fx.clock.Add(actionWindow + time.Second)
	for _, restart := range []bool{false, true} {
		if restart {
			fx.eng, err = New(fx.eng.opts)
			if err != nil {
				t.Fatal("unresolved reservation was not restored", err)
			}
		}
		got, readErr := fx.eng.ReadHoldExecutionStatus(query)
		if readErr != nil || got.Status != "uncertain" || got.ReasonCode != "hold_execution_uncertain" {
			t.Fatal("action expiry hid uncertain execution", got, readErr)
		}
		items := fx.eng.Confirmations().Items
		if len(items) != 1 || items[0].Status != "uncertain" || items[0].ReservationReceiptID != reservation.ReceiptID {
			t.Fatal("expired uncertain execution disappeared from reconciliation UI", items)
		}
		fresh := r
		fresh.TaskID, fresh.ToolCallID = "fresh-after-window", "fresh-call-after-window"
		blocked, decideErr := fx.eng.Decide(fresh)
		if decideErr != nil || blocked.Action != ActionDeny || blocked.Receipt.ReasonCode != "hold_execution_uncertain" {
			t.Fatal("expired uncertain execution entered a new approval cycle", blocked, decideErr)
		}
	}

	resolved, err := fx.eng.ReconcileHoldExecution(HoldExecutionReconcile{
		SchemaVersion: "hold-execution-reconcile/v1", ActionID: d.Receipt.ActionID,
		DecisionReceiptID: d.Receipt.ReceiptID, ReservationReceiptID: reservation.ReceiptID,
		ReservationHash: reservation.Hash, Outcome: HoldExecutionNotOccurred, ActorID: "fixture-admin",
	})
	if err != nil || resolved.Status != "cancelled" {
		t.Fatal("administrator could not settle old uncertainty", resolved, err)
	}
}

func TestHoldExecutionRecoveryRejectsSignedIdentityDrift(t *testing.T) {
	t.Run("reservation", func(t *testing.T) {
		fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
		r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
		d, err := fx.eng.Decide(r)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
			t.Fatal(err)
		}
		forged := d.Receipt
		forged.RecordType, forged.ReceiptID, forged.DecisionReceiptID = "hold_reservation", d.Receipt.ReceiptID+"-forged", d.Receipt.ReceiptID
		forged.IssuedAt = fx.clock.Add(time.Millisecond).Format(time.RFC3339Nano)
		retryID := "forged-retry"
		forged.ToolCallID, forged.Action, forged.ParamsDigest = &retryID, ActionAllow, strings.Repeat("f", 64)
		forged.Hold, forged.AdvisoryAction, forged.DecisionLatencyMS = nil, nil, nil
		forged.Hash, forged.Sig = "", ""
		if err = fx.chain.Append(&forged); err != nil {
			t.Fatal(err)
		}
		if _, err = New(fx.eng.opts); err == nil {
			t.Fatal("signed reservation with changed parameters restored")
		}
	})
	t.Run("reconciliation", func(t *testing.T) {
		fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
		r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
		d, err := fx.eng.Decide(r)
		if err != nil {
			t.Fatal(err)
		}
		if _, err = fx.eng.ResolveHold(d.Receipt, true, "admin"); err != nil {
			t.Fatal(err)
		}
		_, _ = reserveForRetry(t, fx, r, d, "recovery-retry")
		reservation := fx.eng.actions[d.Receipt.ActionID].reservation
		forged := *reservation
		forged.RecordType, forged.ReceiptID, forged.DecisionReceiptID = "hold_reconciliation", reservation.ReceiptID+"-forged", reservation.ReceiptID
		forged.IssuedAt, forged.Tool, forged.Action = fx.clock.Add(time.Millisecond).Format(time.RFC3339Nano), "changed-tool", ActionDeny
		forged.Hash, forged.Sig = "", ""
		if err = fx.chain.Append(&forged); err != nil {
			t.Fatal(err)
		}
		if _, err = New(fx.eng.opts); err == nil {
			t.Fatal("signed reconciliation with changed tool restored")
		}
	})
}
