package skillcontext

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
)

type signedNativeHoldFixture struct {
	f               *callFixture
	engine          *receipt.Engine
	opts            receipt.Options
	chain           *receipt.Chain
	context, parent *InvocationContext
	request         receipt.Request
	decision        *receipt.Decision
	reserve         receipt.HoldExecutionReserve
}

func newSignedNativeHold(t *testing.T, noSkill bool) *signedNativeHoldFixture {
	t.Helper()
	f := newCallFixture(t)
	for _, g := range f.grants {
		g.DefaultEffect = "deny"
		g.HermesToolsetAllowlist = &[]string{"read_file"}
		g.Facts = []grant.Fact{{FactID: "fixture-read", Domain: "filesystem", Action: "fs.read", Resource: admission.Resource{Type: "path", Value: "/workspace"}, Effect: "allow", State: "declared", Authority: "skill_manifest", EvidenceIDs: []string{"synthetic"}}}
		if g.Skill == nil {
			g.OpenClawToolPolicy = &grant.OpenClawToolPolicy{RequireApproval: []string{"read_file"}}
		}
		f.signGrant(g)
	}
	f.register()
	out := &signedNativeHoldFixture{f: f}
	if !noSkill {
		out.parent = f.issueV2(f.request(1, nil))
		// Same Agent, a separately installed and signed second Skill Grant.
		g := *f.grants[testGrantID]
		skill := *g.Skill
		skill.SkillID = "marketplace:skill:second"
		skill.ContentHash = strings.Repeat("c", 64)
		g.GrantID, g.Skill = "grt-second-skill", &skill
		f.grants[g.GrantID] = &g
		f.signGrant(&g)
		install := *f.installs[testInstall]
		install.InstallID, install.Plan.GrantID = "ins-second", g.GrantID
		f.installs[install.InstallID] = &install
		load := f.request(2, out.parent)
		load.InstallID = install.InstallID
		f.loads[load.Loader.LoadID] = load
		out.context = f.issueV2(load)
	}
	r := f.callRequest("original", out.context)
	f.bind(r)
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	out.chain, err = receipt.OpenChain(t.TempDir(), "local", f.key)
	if err != nil {
		t.Fatal(err)
	}
	out.opts = receipt.Options{Pack: pack, Chain: out.chain, Version: "native-hold-component-fixture", EnforcementMode: "block", HoldChannel: "console", HoldTimeoutMS: 120000,
		Now: func() time.Time { return f.now }, NativeCalls: func(req receipt.Request) (bool, *receipt.NativeInvocationVerification, error) {
			v, e := f.calls.VerifyNativeForEngine(req)
			return true, v, e
		},
		IntentLookup: func(_, _, _ string) (*receipt.IntentContract, error) {
			return &receipt.IntentContract{IntentID: "fixture-intent", TaskID: "trusted-envelope", Principal: "synthetic-user", AgentID: testAgent,
				Purpose: "read synthetic fixture after approval", AllowedEffects: []string{"file.read"}, ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "fixture-revision", SelectedGrant: f.grants["grt-agent-baseline"]}, nil
		},
	}
	out.engine, err = receipt.New(out.opts)
	if err != nil {
		t.Fatal(err)
	}
	out.request = receipt.Request{Platform: r.Subject.Platform, SessionID: r.Subject.SessionID, AgentID: r.Subject.AgentID, RuntimeTaskID: r.Subject.TaskID, Tool: r.Tool, ToolCallID: r.ToolCallID, Params: r.Params}
	out.decision, err = out.engine.Decide(out.request)
	if err != nil || out.decision.Action != receipt.ActionHold {
		t.Fatalf("signed hold: %v %+v", err, out.decision)
	}
	if _, err := out.engine.ResolveHold(out.decision.Receipt, true, "synthetic-reviewer"); err != nil {
		t.Fatal(err)
	}
	d := out.decision.Receipt
	out.reserve = receipt.HoldExecutionReserve{SchemaVersion: "hold-execution-reserve/v1", Platform: r.Subject.Platform, SessionID: r.Subject.SessionID, AgentID: r.Subject.AgentID,
		TaskID: d.TaskID, RuntimeTaskID: r.Subject.TaskID, Tool: r.Tool, OriginalToolCallID: r.ToolCallID, RetryToolCallID: "retry", ActionID: d.ActionID, DecisionReceiptID: d.ReceiptID, Params: r.Params}
	return out
}

func (f *signedNativeHoldFixture) query(status *receipt.HoldExecutionStatus) receipt.HoldExecutionStatusRequest {
	r := f.reserve
	return receipt.HoldExecutionStatusRequest{SchemaVersion: "hold-execution-status-request/v1", Platform: r.Platform, SessionID: r.SessionID, AgentID: r.AgentID, TaskID: r.TaskID, RuntimeTaskID: r.RuntimeTaskID,
		Tool: r.Tool, RetryToolCallID: r.RetryToolCallID, ActionID: r.ActionID, DecisionReceiptID: r.DecisionReceiptID, ReservationReceiptID: status.ReservationReceiptID, Params: r.Params}
}

func TestSignedNativeHoldLifecycleAndSamples(t *testing.T) {
	for _, noSkill := range []bool{false, true} {
		name := "with-skill"
		if noSkill {
			name = "no-skill"
		}
		t.Run(name, func(t *testing.T) {
			f := newSignedNativeHold(t, noSkill)
			if _, err := f.engine.ReserveHoldExecution(f.reserve); err == nil {
				t.Fatal("unattested retry accepted")
			}
			f.f.bind(f.f.callRequest("retry", f.context))
			status, err := f.engine.ReserveHoldExecution(f.reserve)
			if err != nil {
				t.Fatal(err)
			}
			q := f.query(status)
			if err := f.engine.RecheckReservedExecution(q); err != nil {
				t.Fatal(err)
			}
			if err := f.engine.RecheckReservedExecution(q); err == nil {
				t.Fatal("native final check repeated")
			}
			r := f.request
			r.TaskID = f.decision.Receipt.TaskID
			r.ToolCallID = "retry"
			r.ActionID = q.ActionID
			r.DecisionReceiptID = q.ReservationReceiptID
			obs, err := f.engine.Observe(r, "synthetic approved result")
			if err != nil {
				t.Fatal(err)
			}
			rows, err := f.chain.Read()
			if err != nil || receipt.Verify(rows, f.f.key.Public()) != nil {
				t.Fatal(err)
			}
			if len(rows) != 4 || rows[0].RecordType != "decision" || rows[1].RecordType != "hold_resolution" || rows[2].RecordType != "hold_reservation" || rows[3].RecordType != "observation" {
				t.Fatal("lifecycle chain incomplete")
			}
			if reflect.DeepEqual(rows[0].NativeInvocation, rows[2].NativeInvocation) || !reflect.DeepEqual(obs.NativeInvocation, rows[2].NativeInvocation) {
				t.Fatal("retry proof correlation failed")
			}
			// Persist the actual product-generated chain as a public synthetic vector.
			p := filepath.Join("../../testdata/contracts", "native-hold-"+name+"-v3.sample.json")
			b, err := json.MarshalIndent(rows, "", "  ")
			if err != nil {
				t.Fatal(err)
			}
			b = append(b, '\n')
			if os.Getenv("AGENTSHIELD_UPDATE_NATIVE_HOLDS") == "1" {
				if err := os.WriteFile(p, b, 0644); err != nil {
					t.Fatal(err)
				}
			}
			want, err := os.ReadFile(p)
			if err != nil || string(want) != string(b) {
				t.Fatal("lifecycle vector drift; regenerate this test explicitly", err)
			}
			fresh, err := receipt.New(f.opts)
			if err != nil {
				t.Fatal(err)
			}
			projection, err := fresh.ReadHoldExecutionStatus(q)
			if err != nil || projection.Status != "completed" {
				t.Fatal("completed chain recovery", err)
			}
		})
	}
}

func TestSignedNativeHoldLiveAuthorityChanges(t *testing.T) {
	for _, kind := range []string{"parent_revoked", "task_ended", "original_expired", "restart_before_approval_execution", "retry_missing_after_reserve"} {
		t.Run(kind, func(t *testing.T) {
			f := newSignedNativeHold(t, false)
			f.f.bind(f.f.callRequest("retry", f.context))
			var status *receipt.HoldExecutionStatus
			var err error
			if kind == "restart_before_approval_execution" || kind == "retry_missing_after_reserve" {
				status, err = f.engine.ReserveHoldExecution(f.reserve)
				if err != nil {
					t.Fatal(err)
				}
			}
			switch kind {
			case "parent_revoked":
				if _, err := f.f.s.Revoke(f.parent.ContextID, f.parent.Signature); err != nil {
					t.Fatal(err)
				}
			case "task_ended":
				f.f.loadError = errMissing
			case "original_expired":
				f.f.now = f.f.now.Add(time.Minute)
			case "restart_before_approval_execution":
				f.engine, err = receipt.New(f.opts)
				if err != nil {
					t.Fatal(err)
				}
			case "retry_missing_after_reserve":
				delete(f.f.facts, nativeCallID(f.context.Subject, "retry"))
			}
			if status == nil {
				if _, err := f.engine.ReserveHoldExecution(f.reserve); err == nil {
					t.Fatal("stale signed authority resumed")
				}
			} else {
				q := f.query(status)
				if err := f.engine.RecheckReservedExecution(q); err == nil {
					t.Fatal("recovered/unknown retry reauthorized")
				}
				read, err := f.engine.ReadHoldExecutionStatus(q)
				if err != nil || read.Status != "uncertain" {
					t.Fatal("lost uncertain execution fact", err)
				}
			}
		})
	}
}
