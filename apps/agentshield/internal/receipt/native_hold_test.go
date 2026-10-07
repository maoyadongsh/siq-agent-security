package receipt

import (
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

type nativeHoldFixture struct {
	*fixture
	original, retry       *NativeInvocationVerification
	originalErr, retryErr error
	required              bool
	r                     Request
	d                     *Decision
	reserve               HoldExecutionReserve
}

func newNativeHoldFixture(t *testing.T, noSkill bool) *nativeHoldFixture {
	t.Helper()
	base := baselineGrant(t, "hermes", "read_file")
	base.OpenClawToolPolicy = &grant.OpenClawToolPolicy{RequireApproval: []string{"read_file"}}
	skills := []*grant.Grant{}
	if !noSkill {
		skills = append(skills, skillGrant(t, "hermes", "leaf", "1", strings.Repeat("a", 64)), skillGrant(t, "hermes", "parent", "2", strings.Repeat("b", 64)))
	}
	fx, r, v := nativeEngineFixture(t, "block", base, skills...)
	f := &nativeHoldFixture{fixture: fx, original: v, required: true, r: r}
	b, _ := json.Marshal(v)
	f.retry = &NativeInvocationVerification{}
	if err := json.Unmarshal(b, f.retry); err != nil {
		t.Fatal(err)
	}
	f.retry.Evidence.CallID = "ncall-" + strings.Repeat("f", 32)
	f.retry.Evidence.CallSignature = strings.Repeat("f", 128)
	bind, err := trustedcontext.CallBinding(r.Platform, r.SessionID, r.AgentID, r.RuntimeTaskID, r.Tool, "retry-call", r.Params)
	if err != nil {
		t.Fatal(err)
	}
	f.retry.Evidence.RequestBinding = bind
	fx.eng.opts.NativeCalls = func(req Request) (bool, *NativeInvocationVerification, error) {
		if !f.required {
			return false, nil, nil
		}
		if req.ToolCallID == r.ToolCallID {
			return true, f.original, f.originalErr
		}
		if req.ToolCallID == "retry-call" {
			return true, f.retry, f.retryErr
		}
		return true, nil, nil
	}
	f.d, err = fx.eng.Decide(r)
	if err != nil || f.d.Action != ActionHold {
		t.Fatalf("native hold: %v %+v", err, f.d)
	}
	if _, err := fx.eng.ResolveHold(f.d.Receipt, true, "synthetic-reviewer"); err != nil {
		t.Fatal(err)
	}
	f.reserve = HoldExecutionReserve{SchemaVersion: "hold-execution-reserve/v1", Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID,
		TaskID: f.d.Receipt.TaskID, RuntimeTaskID: r.RuntimeTaskID, Tool: r.Tool, OriginalToolCallID: r.ToolCallID, RetryToolCallID: "retry-call",
		ActionID: f.d.Receipt.ActionID, DecisionReceiptID: f.d.Receipt.ReceiptID, Params: r.Params}
	return f
}

func (f *nativeHoldFixture) statusRequest(res *HoldExecutionStatus) HoldExecutionStatusRequest {
	r := f.reserve
	return HoldExecutionStatusRequest{SchemaVersion: "hold-execution-status-request/v1", Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID,
		TaskID: r.TaskID, RuntimeTaskID: r.RuntimeTaskID, Tool: r.Tool, RetryToolCallID: r.RetryToolCallID, ActionID: r.ActionID, DecisionReceiptID: r.DecisionReceiptID,
		ReservationReceiptID: res.ReservationReceiptID, Params: r.Params}
}

func TestNativeHoldReserveRecheckObserve(t *testing.T) {
	for _, noSkill := range []bool{false, true} {
		t.Run(map[bool]string{false: "skill", true: "no-skill"}[noSkill], func(t *testing.T) {
			f := newNativeHoldFixture(t, noSkill)
			res, err := f.eng.ReserveHoldExecution(f.reserve)
			if err != nil || res.Status != "reserved" {
				t.Fatal("reserve", err)
			}
			reservation := f.eng.actions[f.d.Receipt.ActionID].reservation
			if !reflect.DeepEqual(reservation.NativeInvocation, f.retry.Evidence) || reflect.DeepEqual(reservation.NativeInvocation, f.original.Evidence) {
				t.Fatal("reservation retained original call proof")
			}
			if !noSkill && reservation.SkillAttribution.CallBinding != f.retry.Evidence.RequestBinding {
				t.Fatal("retry attribution was not rebound")
			}
			query := f.statusRequest(res)
			if err := f.eng.RecheckReservedExecution(query); err != nil {
				t.Fatal(err)
			}
			if err := f.eng.RecheckReservedExecution(query); err == nil {
				t.Fatal("final native execution check succeeded twice")
			}
			if _, err := f.eng.ReserveHoldExecution(f.reserve); !errors.Is(err, ErrHoldExecutionConflict) {
				t.Fatal("reservation replay", err)
			}
			status, err := f.eng.ReadHoldExecutionStatus(query)
			if err != nil || status.Status != "uncertain" {
				t.Fatal("status read granted another execution", err)
			}
			r := f.r
			r.TaskID = f.d.Receipt.TaskID
			r.ToolCallID = "retry-call"
			r.ActionID = f.d.Receipt.ActionID
			r.DecisionReceiptID = res.ReservationReceiptID
			// Revocation after execution cannot erase a correctly correlated effect.
			f.originalErr = errors.New("revoked")
			f.retryErr = errors.New("revoked")
			observed, err := f.eng.Observe(r, "synthetic result")
			if err != nil || !reflect.DeepEqual(observed.NativeInvocation, reservation.NativeInvocation) {
				t.Fatal("observation lost retry authority evidence", err)
			}
			status, err = f.eng.ReadHoldExecutionStatus(query)
			if err != nil || status.Status != "completed" {
				t.Fatal(err)
			}
			rows, err := f.chain.Read()
			if err != nil || Verify(rows, f.k.Public()) != nil {
				t.Fatal("native lifecycle chain", err)
			}
		})
	}
}

func TestNativeHoldRejectsChangedOriginalAndRetry(t *testing.T) {
	for name, change := range map[string]func(*nativeHoldFixture){
		"original_missing":            func(f *nativeHoldFixture) { f.original = nil },
		"original_revoked":            func(f *nativeHoldFixture) { f.originalErr = errors.New("revoked") },
		"retry_missing":               func(f *nativeHoldFixture) { f.retry = nil },
		"retry_revoked":               func(f *nativeHoldFixture) { f.retryErr = errors.New("revoked") },
		"mode_downgrade":              func(f *nativeHoldFixture) { f.required = false },
		"different_session_signature": func(f *nativeHoldFixture) { f.retry.Evidence.SessionSignature = strings.Repeat("a", 128) },
		"parent_changed":              func(f *nativeHoldFixture) { f.retry.Evidence.Contexts[1].ContextSignature = strings.Repeat("a", 128) },
		"parent_dropped": func(f *nativeHoldFixture) {
			f.retry.Evidence.Contexts = f.retry.Evidence.Contexts[:1]
			f.retry.SkillGrants = f.retry.SkillGrants[:1]
		},
		"original_call_reused": func(f *nativeHoldFixture) { f.retry.Evidence.CallID = f.original.Evidence.CallID },
		"no_skill_downgrade": func(f *nativeHoldFixture) {
			f.retry.Evidence.NoSkill = true
			f.retry.Evidence.Contexts = []NativeContextRef{}
			f.retry.SkillGrants = nil
		},
		"baseline_changed": func(f *nativeHoldFixture) {
			f.retry.AgentGrant.DefaultEffect = "allow"
			f.retry.Evidence.AgentAuthority = nativeRefForTest(t, f.retry.AgentGrant)
		},
	} {
		t.Run(name, func(t *testing.T) {
			f := newNativeHoldFixture(t, false)
			change(f)
			if _, err := f.eng.ReserveHoldExecution(f.reserve); err == nil {
				t.Fatal("changed authority inherited original approval")
			}
			rows, err := f.chain.Read()
			if err != nil {
				t.Fatal(err)
			}
			for _, r := range rows {
				if r.RecordType == "hold_reservation" {
					t.Fatal("failed check still published reservation")
				}
			}
		})
	}
}

func TestNativeHoldRecheckFailsOnLateChangeAndRecovery(t *testing.T) {
	for _, kind := range []string{"original", "retry", "retry_reissued", "restart"} {
		t.Run(kind, func(t *testing.T) {
			f := newNativeHoldFixture(t, false)
			res, err := f.eng.ReserveHoldExecution(f.reserve)
			if err != nil {
				t.Fatal(err)
			}
			query := f.statusRequest(res)
			switch kind {
			case "original":
				f.originalErr = errors.New("revoked")
			case "retry":
				f.retryErr = errors.New("task ended")
			case "retry_reissued":
				f.retry.Evidence.CallSignature = strings.Repeat("a", 128)
			case "restart":
				f.eng, err = New(f.eng.opts)
				if err != nil {
					t.Fatal(err)
				}
			}
			if err := f.eng.RecheckReservedExecution(query); err == nil {
				t.Fatal("late change or recovery created execution permission")
			}
			status, err := f.eng.ReadHoldExecutionStatus(query)
			if err != nil || status.Status != "uncertain" {
				t.Fatal("uncertain side effect erased", err)
			}
			if _, err := f.eng.ReserveHoldExecution(f.reserve); !errors.Is(err, ErrHoldExecutionConflict) {
				t.Fatal("old approval was reusable", err)
			}
		})
	}
}

func TestNativeHoldConcurrentFinalCheckOneWinner(t *testing.T) {
	f := newNativeHoldFixture(t, false)
	res, err := f.eng.ReserveHoldExecution(f.reserve)
	if err != nil {
		t.Fatal(err)
	}
	q := f.statusRequest(res)
	results := make(chan error, 16)
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); results <- f.eng.RecheckReservedExecution(q) }()
	}
	wg.Wait()
	close(results)
	allowed := 0
	for err := range results {
		if err == nil {
			allowed++
		}
	}
	if allowed != 1 {
		t.Fatalf("got %d final execution checks", allowed)
	}
}

func TestNativeHoldRecoveryRejectsContradictorySignedTrace(t *testing.T) {
	for _, kind := range []string{"old_call_in_reservation", "changed_resolution", "changed_observation", "missing_native_proof"} {
		t.Run(kind, func(t *testing.T) {
			f := newNativeHoldFixture(t, false)
			bad := f.d.Receipt
			bad.ReceiptID += "-contradiction"
			bad.DecisionReceiptID = f.d.Receipt.ReceiptID
			bad.Action = ActionAllow
			bad.IssuedAt = f.clock.Add(time.Millisecond).Format(time.RFC3339Nano)
			switch kind {
			case "old_call_in_reservation":
				bad.RecordType = "hold_reservation"
				bad.ToolCallID = &f.reserve.RetryToolCallID
			case "changed_resolution":
				bad.RecordType = "hold_resolution"
				bad.NativeInvocation = f.retry.Evidence
			case "missing_native_proof":
				bad.RecordType = "hold_resolution"
				bad.NativeInvocation = nil
			case "changed_observation":
				res, err := f.eng.ReserveHoldExecution(f.reserve)
				if err != nil {
					t.Fatal(err)
				}
				bad.RecordType = "observation"
				bad.DecisionReceiptID = res.ReservationReceiptID
				bad.ToolCallID = &f.reserve.RetryToolCallID
			}
			// Valid signature is insufficient if a producer wrote contradictory
			// native correlation. Never rewrite any existing row in this fixture.
			if err := f.chain.Append(&bad); err != nil {
				t.Fatal(err)
			}
			if _, err := New(f.eng.opts); err == nil {
				t.Fatal("signed but contradictory native trace recovered")
			}
		})
	}
}

func TestNativeHoldSeparateProcessCannotRecheck(t *testing.T) {
	const env = "SIQ_NATIVE_HOLD_TEST_RECOVERY"
	type recovery struct {
		State string
		Query HoldExecutionStatusRequest
		Now   time.Time
	}
	if path := os.Getenv(env); path != "" {
		b, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		var input recovery
		if err := json.Unmarshal(b, &input); err != nil {
			t.Fatal(err)
		}
		fx := newFixture(t, "block", nil, false)
		fx.clock = input.Now
		chain, err := OpenChain(input.State, "local", fx.k)
		if err != nil {
			t.Fatal(err)
		}
		opts := fx.eng.opts
		opts.Chain = chain
		engine, err := New(opts)
		if err != nil {
			t.Fatal(err)
		}
		if err := engine.RecheckReservedExecution(input.Query); err == nil {
			t.Fatal("new process reauthorized a recovered reservation")
		}
		status, err := engine.ReadHoldExecutionStatus(input.Query)
		if err != nil || status.Status != "uncertain" {
			t.Fatal("new process lost uncertainty", err)
		}
		return
	}
	f := newNativeHoldFixture(t, false)
	res, err := f.eng.ReserveHoldExecution(f.reserve)
	if err != nil {
		t.Fatal(err)
	}
	input := recovery{State: filepath.Dir(filepath.Dir(f.chain.dir)), Query: f.statusRequest(res), Now: f.clock.Add(time.Second)}
	b, err := json.Marshal(input)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "request.json")
	if err := os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestNativeHoldSeparateProcessCannotRecheck$")
	cmd.Env = append(os.Environ(), env+"="+path)
	if output, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("new process: %v %s", err, output)
	}
}
