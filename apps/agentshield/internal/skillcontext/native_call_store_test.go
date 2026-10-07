package skillcontext

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"
)

type callFixture struct {
	*invocationStoreFixture
	calls                       *NativeCallStore
	facts                       map[string]NativeCallRequest
	hostSessionErr, hostCallErr error
}

func newCallFixture(t *testing.T) *callFixture {
	f := &callFixture{invocationStoreFixture: newInvocationStoreFixture(t), facts: map[string]NativeCallRequest{}}
	var err error
	f.calls, err = OpenNativeCalls(f.s, CallDeps{
		ValidateSession: func(s NativeSession) (time.Time, error) {
			if s.RuntimeArtifactSHA256 != strings.Repeat("8", 64) {
				return time.Time{}, errMissing
			}
			return f.loadUntil, f.hostSessionErr
		},
		ValidateCall: func(c NativeCall) (time.Time, error) {
			r, ok := f.facts[c.CallID]
			binding, err := nativeRequestBinding(r)
			if !ok || err != nil || r.Subject != c.Subject || r.Tool != c.Tool || r.ToolCallID != c.ToolCallID || binding != c.RequestBinding ||
				r.NoSkill != c.NoSkill || !reflect.DeepEqual(r.Context, c.Context) {
				return time.Time{}, errMissing
			}
			return f.loadUntil, f.hostCallErr
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func (f *callFixture) register() *NativeSession {
	f.t.Helper()
	s, err := f.calls.RegisterSession(NativeSessionRequest{InstanceID: testInstance, SessionID: testSession, RuntimeArtifactSHA256: strings.Repeat("8", 64), TTL: time.Hour})
	if err != nil {
		f.t.Fatal(err)
	}
	return s
}

func (f *callFixture) callRequest(id string, c *InvocationContext) NativeCallRequest {
	r := NativeCallRequest{Subject: Subject{Platform: "hermes", InstanceID: testInstance, AgentID: testAgent, SessionID: testSession, TaskID: testTask},
		Tool: "read_file", ToolCallID: id, Params: map[string]any{"path": "/workspace/synthetic.txt", "sensitive_test_marker": "never-persist-this"}, TTL: time.Minute, NoSkill: c == nil}
	if c != nil {
		r.Context = &ParentRef{ContextID: c.ContextID, Signature: c.Signature}
	}
	f.facts[nativeCallID(r.Subject, id)] = r
	return r
}

func (f *callFixture) bind(r NativeCallRequest) *NativeCall {
	f.t.Helper()
	c, err := f.calls.BindCall(r)
	if err != nil {
		f.t.Fatal(err)
	}
	return c
}

func TestNativeCallsSignedPersistenceNoSkillAndSkill(t *testing.T) {
	for _, withSkill := range []bool{false, true} {
		t.Run(map[bool]string{false: "no_skill", true: "skill"}[withSkill], func(t *testing.T) {
			f := newCallFixture(t)
			session := f.register()
			var ctx *InvocationContext
			if withSkill {
				ctx = f.issueV2(f.request(1, nil))
			}
			r := f.callRequest("call-1", ctx)
			call := f.bind(r)
			if call.Validate() != nil || session.Validate() != nil {
				t.Fatal("invalid signed output")
			}
			b, err := os.ReadFile(f.calls.callPath(r.Subject, r.ToolCallID))
			if err != nil {
				t.Fatal(err)
			}
			if strings.Contains(string(b), "never-persist-this") || strings.Contains(string(b), "/workspace/") {
				t.Fatal("raw parameters persisted")
			}
			reopened, err := OpenNativeCalls(f.s, f.calls.deps)
			if err != nil {
				t.Fatal(err)
			}
			f.calls = reopened
			f.now = f.now.Add(10 * time.Second)
			if got := f.bind(r); !reflect.DeepEqual(got, call) {
				t.Fatal("replay extended or rewrote call")
			}
			if got := f.register(); !reflect.DeepEqual(got, session) {
				t.Fatal("session replay extended lease")
			}
			// The runtime request must not select authority by its claim fields.
			r.NoSkill = !r.NoSkill
			r.Context = nil
			v, err := f.calls.VerifyCall(r)
			if err != nil || v.Call.NoSkill == withSkill || (v.Invocation != nil) != withSkill || v.AgentGrant.GrantID != session.AgentAuthority.GrantID {
				t.Fatal("call authority selected by client claim", err)
			}
		})
	}
}

func TestNativeCallsExactFinalInvocationAndNoDowngrade(t *testing.T) {
	for name, change := range map[string]func(*NativeCallRequest){
		"tool":       func(r *NativeCallRequest) { r.Tool = "write_file" },
		"call":       func(r *NativeCallRequest) { r.ToolCallID = "other" },
		"parameters": func(r *NativeCallRequest) { r.Params = map[string]any{"path": "/secrets"} },
		"session":    func(r *NativeCallRequest) { r.Subject.SessionID = "other" },
		"task":       func(r *NativeCallRequest) { r.Subject.TaskID = "other" },
		"agent":      func(r *NativeCallRequest) { r.Subject.AgentID = "hri-" + strings.Repeat("c", 32) },
		"instance":   func(r *NativeCallRequest) { r.Subject.InstanceID = "hi-" + strings.Repeat("c", 32) },
		"platform":   func(r *NativeCallRequest) { r.Subject.Platform = "openclaw" },
		"empty_task": func(r *NativeCallRequest) { r.Subject.TaskID = "" },
	} {
		t.Run(name, func(t *testing.T) {
			f := newCallFixture(t)
			f.register()
			ctx := f.issueV2(f.request(1, nil))
			r := f.callRequest("call-1", ctx)
			f.bind(r)
			change(&r)
			if _, err := f.calls.VerifyCall(r); err == nil {
				t.Fatal("changed final invocation borrowed authority")
			}
		})
	}
	f := newCallFixture(t)
	f.register()
	r := f.callRequest("missing", nil)
	if _, err := f.calls.VerifyCall(r); err == nil {
		t.Fatal("missing call fell back to agent authority")
	}
	ctx := f.issueV2(f.request(1, nil))
	r = f.callRequest("skill", ctx)
	r.Context = nil
	r.NoSkill = true
	if _, err := f.calls.BindCall(r); err == nil {
		t.Fatal("model selected no-skill for a loaded Skill")
	}
	r = f.callRequest("unknown", nil)
	r.NoSkill = false
	if _, err := f.calls.BindCall(r); err == nil {
		t.Fatal("unknown lineage treated as empty")
	}
}

func TestNativeCallsCannotRewriteOneNativeCall(t *testing.T) {
	for _, kind := range []string{"tool", "params", "context"} {
		t.Run(kind, func(t *testing.T) {
			f := newCallFixture(t)
			f.register()
			ctx := f.issueV2(f.request(1, nil))
			r := f.callRequest("call-1", ctx)
			original := f.bind(r)
			switch kind {
			case "tool":
				r.Tool = "write_file"
			case "params":
				r.Params = map[string]any{"path": "other"}
			case "context":
				r.Context = nil
				r.NoSkill = true
			}
			f.facts[nativeCallID(r.Subject, r.ToolCallID)] = r
			if _, err := f.calls.BindCall(r); err == nil {
				t.Fatal("same native ID re-signed with different authority")
			}
			b, _ := os.ReadFile(f.calls.callPath(r.Subject, r.ToolCallID))
			var c NativeCall
			if json.Unmarshal(b, &c) != nil || c.Signature != original.Signature {
				t.Fatal("original overwritten")
			}
		})
	}
}

func TestNativeCallsEveryLiveBoundary(t *testing.T) {
	for name, change := range map[string]func(*callFixture, *InvocationContext){
		"host_session": func(f *callFixture, c *InvocationContext) { f.hostSessionErr = errMissing },
		"host_call":    func(f *callFixture, c *InvocationContext) { f.hostCallErr = errMissing },
		"call_expiry":  func(f *callFixture, c *InvocationContext) { f.now = f.now.Add(time.Minute) },
		"session_deleted": func(f *callFixture, c *InvocationContext) {
			if err := os.Remove(f.calls.sessionPath(c.Subject)); err != nil {
				f.t.Fatal(err)
			}
		},
		"baseline_changed": func(f *callFixture, c *InvocationContext) {
			g := f.grants["grt-agent-baseline"]
			g.DefaultEffect = "allow"
			f.signGrant(g)
		},
		"skill_revoked": func(f *callFixture, c *InvocationContext) {
			if _, err := f.s.Revoke(c.ContextID, c.Signature); err != nil {
				f.t.Fatal(err)
			}
		},
		"install_drift": func(f *callFixture, c *InvocationContext) { f.installError = errMissing },
		"task_ended":    func(f *callFixture, c *InvocationContext) { f.loadError = errMissing },
		"call_record_missing": func(f *callFixture, c *InvocationContext) {
			if err := os.Remove(f.calls.callPath(c.Subject, "call-1")); err != nil {
				f.t.Fatal(err)
			}
		},
	} {
		t.Run(name, func(t *testing.T) {
			f := newCallFixture(t)
			f.register()
			ctx := f.issueV2(f.request(1, nil))
			r := f.callRequest("call-1", ctx)
			f.bind(r)
			change(f, ctx)
			if _, err := f.calls.VerifyCall(r); err == nil {
				t.Fatal("stale call authority accepted")
			}
		})
	}
}

func TestNativeCallsAuditFailureAndConcurrency(t *testing.T) {
	f := newCallFixture(t)
	f.auditError = errMissing
	if _, err := f.calls.RegisterSession(NativeSessionRequest{InstanceID: testInstance, SessionID: testSession, RuntimeArtifactSHA256: strings.Repeat("8", 64), TTL: time.Hour}); err == nil {
		t.Fatal("unaudited registration")
	}
	f.auditError = nil
	f.register()
	r := f.callRequest("call-1", nil)
	f.auditError = errMissing
	if _, err := f.calls.BindCall(r); err == nil {
		t.Fatal("unaudited call")
	}
	entries, _ := os.ReadDir(f.calls.callDir())
	if len(entries) != 0 {
		t.Fatal("failed audit left call authority")
	}
	f.auditError = nil
	var wg sync.WaitGroup
	errs := make(chan error, 16)
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); _, err := f.calls.BindCall(r); errs <- err }()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	if len(f.audits) != 2 {
		t.Fatal("duplicate call publication")
	}
}

func TestNativeCallsRejectOtherRuntimeAndUnboundedParams(t *testing.T) {
	f := newCallFixture(t)
	f.register()
	load := f.request(1, nil)
	load.Loader.RuntimeArtifactSHA256 = strings.Repeat("f", 64)
	f.loads[load.Loader.LoadID] = load
	ctx := f.issueV2(load)
	if _, err := f.calls.BindCall(f.callRequest("foreign-runtime", ctx)); err == nil {
		t.Fatal("context from another runtime artifact accepted")
	}
	r := f.callRequest("large", nil)
	r.Params = map[string]any{"large": strings.Repeat("x", 1<<20)}
	if _, err := f.calls.BindCall(r); err == nil {
		t.Fatal("unbounded params accepted")
	}
	r.Params = map[string]any{}
	r.Params["cycle"] = r.Params
	if _, err := f.calls.BindCall(r); err == nil {
		t.Fatal("cyclic params accepted")
	}
	if _, err := OpenNativeCalls(f.s, CallDeps{}); err == nil {
		t.Fatal("missing trusted host accepted")
	}
}

func TestNativeCallsCapacityAndExactReplay(t *testing.T) {
	f := newCallFixture(t)
	f.register()
	for i := 0; i < maxNativeSessions-2; i++ {
		if err := os.WriteFile(filepath.Join(f.calls.sessionDir(), fmt.Sprintf("nsess-%032x.json", i)), []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	register := func(session string) (*NativeSession, error) {
		key := "hermes|" + testAgent + "|" + session
		f.bound[key] = "grt-agent-baseline"
		f.boundUntil[key] = f.loadUntil
		return f.calls.RegisterSession(NativeSessionRequest{InstanceID: testInstance, SessionID: session, RuntimeArtifactSHA256: strings.Repeat("8", 64), TTL: time.Hour})
	}
	if _, err := register("last-session"); err != nil {
		t.Fatal(err)
	}
	if _, err := register("excess-session"); err == nil {
		t.Fatal("session capacity exceeded")
	}
	f.register() // original registration remains usable at capacity
	for i := 0; i < maxNativeCalls-1; i++ {
		if err := os.WriteFile(filepath.Join(f.calls.callDir(), fmt.Sprintf("ncall-%032x.json", i)), []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	r := f.callRequest("last", nil)
	f.bind(r)
	if _, err := f.calls.BindCall(f.callRequest("excess", nil)); err == nil {
		t.Fatal("call capacity exceeded")
	}
	f.bind(r)
}

func TestNativeCallsCorruptSignedRecordsFailClosed(t *testing.T) {
	for _, target := range []string{"session", "call"} {
		for name, mutate := range map[string]func([]byte) []byte{
			"duplicate": func(b []byte) []byte {
				return bytes.Replace(b, []byte(`"issuer_id":`), []byte(`"issuer_id":"local-admin","issuer_id":`), 1)
			},
			"alias": func(b []byte) []byte { return bytes.Replace(b, []byte(`"issuer_id":`), []byte(`"Issuer_ID":`), 1) },
			"extra": func(b []byte) []byte { return append(b, []byte(` {}`)...) },
			"unknown": func(b []byte) []byte {
				return bytes.Replace(b, []byte(`"issuer_id":`), []byte(`"model_authorized":true,"issuer_id":`), 1)
			},
		} {
			t.Run(target+"/"+name, func(t *testing.T) {
				f := newCallFixture(t)
				f.register()
				r := f.callRequest("call-1", nil)
				f.bind(r)
				p := f.calls.callPath(r.Subject, r.ToolCallID)
				if target == "session" {
					p = f.calls.sessionPath(r.Subject)
				}
				b, err := os.ReadFile(p)
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(p, mutate(b), 0600); err != nil {
					t.Fatal(err)
				}
				if _, err := f.calls.VerifyCall(r); err == nil {
					t.Fatal("ambiguous signed record accepted")
				}
			})
		}
	}
}

func TestNativeCallsConcurrentIndependentCalls(t *testing.T) {
	f := newCallFixture(t)
	f.register()
	root := f.issueV2(f.request(1, nil))
	child := f.issueV2(f.request(2, root))
	requests := []NativeCallRequest{f.callRequest("root-call", root), f.callRequest("child-call", child)}
	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for _, r := range requests {
		wg.Add(1)
		go func(r NativeCallRequest) { defer wg.Done(); _, err := f.calls.BindCall(r); errs <- err }(r)
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	for i, r := range requests {
		v, err := f.calls.VerifyCall(r)
		if err != nil || len(v.Invocation.Contexts) != i+1 {
			t.Fatal("parallel calls exchanged lineage", err)
		}
	}
}

func TestNativeCallStoreContractSamples(t *testing.T) {
	f := newCallFixture(t)
	session := f.register()
	plain := f.bind(f.callRequest("call-plain", nil))
	ctx := f.issueV2(f.request(1, nil))
	skill := f.bind(f.callRequest("call-skill", ctx))
	for name, doc := range map[string]any{
		"native-skill-managed-session-v1.sample.json": session,
		"native-skill-call-no-skill-v1.sample.json":   plain,
		"native-skill-call-with-skill-v1.sample.json": skill,
	} {
		b, err := json.MarshalIndent(doc, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		b = append(b, '\n')
		p := filepath.Join("../../testdata/contracts", name)
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(p, b, 0644); err != nil {
				t.Fatal(err)
			}
		}
		want, err := os.ReadFile(p)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(b, want) {
			t.Fatalf("%s differs; regenerate only this test with AGENTSHIELD_UPDATE_SAMPLES=1", name)
		}
	}
}
