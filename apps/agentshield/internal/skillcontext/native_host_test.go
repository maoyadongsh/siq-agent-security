package skillcontext

import (
	"fmt"
	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"strings"
	"testing"
	"time"
)

type hostFixture struct {
	*invocationStoreFixture
	host                  *NativeHostBridge
	subject               Subject
	runtimeErr, sourceErr error
}

func newHostFixture(t *testing.T) *hostFixture {
	f := &hostFixture{invocationStoreFixture: newInvocationStoreFixture(t), subject: Subject{Platform: "hermes", InstanceID: testInstance, AgentID: testAgent, SessionID: testSession, TaskID: testTask}}
	for _, g := range f.grants {
		g.DefaultEffect = "deny"
		g.HermesToolsetAllowlist = &[]string{"read_file"}
		g.Facts = []grant.Fact{{FactID: "read", Domain: "filesystem", Action: "fs.read", Resource: admission.Resource{Type: "path", Value: "/workspace"}, Effect: "allow", State: "declared", Authority: "skill_manifest", EvidenceIDs: []string{"fixture"}}}
		f.signGrant(g)
	}
	deps := NativeHostDeps{InvocationDeps: f.s.deps,
		VerifyRuntime: func(s Subject, artifact string) (time.Time, error) {
			if artifact != strings.Repeat("8", 64) || s.AgentID != testAgent {
				return time.Time{}, errMissing
			}
			return f.loadUntil, f.runtimeErr
		},
		ResolveSource: func(s Subject, source NativeSource) (InstallRef, error) {
			if s.AgentID != testAgent || source.SkillFile.SHA256 != testHash {
				return InstallRef{}, errMissing
			}
			return InstallRef{InstallID: testInstall, ClaimSignature: testClaimSig}, f.sourceErr
		}}
	var err error
	f.host, err = OpenNativeHost(f.store.dir, deps)
	if err != nil {
		t.Fatal(err)
	}
	if err = f.host.Begin(f.subject, strings.Repeat("8", 64)); err != nil {
		t.Fatal(err)
	}
	return f
}
func hostSource() NativeSource {
	file := NativeSourceFile{PathSHA256: strings.Repeat("3", 64), SHA256: testHash, Bytes: 12}
	return NativeSource{SchemaVersion: "native-skill-source/v1", SkillFile: file, ContentFile: file, TextSHA256: testHash, Decoding: "utf-8-sig-replace-universal-newlines/v1"}
}
func (f *hostFixture) prepare(id, load string, params map[string]any) string {
	f.t.Helper()
	b, err := CallBinding("hermes", f.subject.SessionID, testAgent, f.subject.TaskID, "read_file", id, params)
	if err != nil {
		f.t.Fatal(err)
	}
	if err = f.host.Prepare(f.subject, "read_file", id, b, load); err != nil {
		f.t.Fatal(err)
	}
	return b
}
func (f *hostFixture) bind(id, load string) (map[string]any, string) {
	f.t.Helper()
	p := map[string]any{"path": "/workspace/visible.txt"}
	b := f.prepare(id, load, p)
	if _, err := f.host.Bind(f.subject, "read_file", id, p); err != nil {
		f.t.Fatal(err)
	}
	return p, b
}
func TestNativeHostAutomaticContextAndEngine(t *testing.T) {
	f := newHostFixture(t)
	load := "nload-" + strings.Repeat("1", 32)
	ref, err := f.host.Load(f.subject, load, "", hostSource())
	if err != nil {
		t.Fatal(err)
	}
	ctx, err := f.host.Contexts().Verify(ref.ContextID, f.subject)
	if err != nil || ctx.Contexts[0].Authority.GrantID != testGrantID || ctx.Contexts[0].AgentAuthority.GrantID != "grt-agent-baseline" {
		t.Fatal("automatic authority failed", err)
	}
	pack, _ := rulepack.Builtin()
	chain, err := receipt.OpenChain(t.TempDir(), "local", f.key)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Version: "host-bridge-component", EnforcementMode: "block", Now: func() time.Time { return f.now },
		NativeCalls: func(r receipt.Request) (bool, *receipt.NativeInvocationVerification, error) {
			v, e := f.host.Calls().VerifyNativeForEngine(r)
			return true, v, e
		},
		IntentLookup: func(_, _, _ string) (*receipt.IntentContract, error) {
			return &receipt.IntentContract{IntentID: "fixture-intent", TaskID: "trusted-envelope", Principal: "synthetic-user", AgentID: testAgent, Purpose: "read fixture", AllowedEffects: []string{"file.read"}, ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "fixture", SelectedGrant: f.grants["grt-agent-baseline"]}, nil
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	for n, path := range []string{"/workspace/visible.txt", "/outside/denied.txt"} {
		id := fmt.Sprintf("call-%d", n)
		p := map[string]any{"path": path}
		b := f.prepare(id, load, p)
		if _, err = f.host.Bind(f.subject, "read_file", id, p); err != nil {
			t.Fatal(err)
		}
		d, e := engine.Decide(receipt.Request{Platform: "hermes", AgentID: testAgent, SessionID: testSession, RuntimeTaskID: testTask, Tool: "read_file", ToolCallID: id, Params: p})
		want := receipt.ActionAllow
		if n == 1 {
			want = receipt.ActionDeny
		}
		if e != nil || d.Action != want || d.Receipt.SchemaVersion != "runtime-receipt/v3" {
			t.Fatalf("real engine: %v %+v", e, d)
		}
		if err = f.host.Finish(f.subject, id, b); err != nil {
			t.Fatal(err)
		}
	}
	rows, err := chain.Read()
	if err != nil || receipt.Verify(rows, f.key.Public()) != nil {
		t.Fatal("signed chain invalid", err)
	}
}
func TestNativeHostSwitchCacheAndParentSnapshot(t *testing.T) {
	f := newHostFixture(t)
	src := hostSource()
	a := "nload-" + strings.Repeat("1", 32)
	b := "nload-" + strings.Repeat("2", 32)
	c := "nload-" + strings.Repeat("3", 32)
	first, err := f.host.Load(f.subject, a, "", src)
	if err != nil {
		t.Fatal(err)
	}
	original := *first
	first.Signature = "mutated caller copy"
	src2 := src
	src2.SkillFile.PathSHA256 = strings.Repeat("4", 64)
	src2.ContentFile = src2.SkillFile
	second, err := f.host.Load(f.subject, b, a, src2)
	if err != nil {
		t.Fatal(err)
	}
	src.CacheHit = true
	third, err := f.host.Load(f.subject, c, b, src)
	if err != nil {
		t.Fatal(err)
	}
	v, err := f.host.Contexts().Verify(third.ContextID, f.subject)
	if err != nil || len(v.Contexts) != 3 || v.Contexts[0].Parent.ContextID != second.ContextID || v.Contexts[1].Parent.ContextID != original.ContextID {
		t.Fatal("ancestor lost", err)
	}
	if _, err = f.host.Load(f.subject, c, "", src); err != nil {
		t.Fatal("cache reread failed", err)
	}
	f.bind("after-switch", c)
}
func TestNativeHostRefusesInvalidTransitions(t *testing.T) {
	for _, name := range []string{"missing_task", "wrong_binding", "wrong_tool", "selected_load", "repeat_bind", "repeat_call", "source_unverified", "source_changed", "unknown_cache", "wrong_parent", "runtime_dead", "end", "restart", "audit_failure"} {
		t.Run(name, func(t *testing.T) {
			f := newHostFixture(t)
			p := map[string]any{"path": "/workspace/visible.txt"}
			id := "one"
			load := "nload-" + strings.Repeat("1", 32)
			var err error
			switch name {
			case "missing_task":
				f.subject.TaskID = "unknown"
				err = f.host.Prepare(f.subject, "read_file", id, strings.Repeat("a", 64), "")
			case "wrong_binding":
				f.prepare(id, "", p)
				p["path"] = "/elsewhere"
				_, err = f.host.Bind(f.subject, "read_file", id, p)
			case "wrong_tool":
				f.prepare(id, "", p)
				_, err = f.host.Bind(f.subject, "write_file", id, p)
			case "selected_load":
				err = f.host.Prepare(f.subject, "read_file", id, strings.Repeat("a", 64), load)
			case "repeat_bind":
				f.bind(id, "")
				_, err = f.host.Bind(f.subject, "read_file", id, p)
			case "repeat_call":
				_, b := f.bind(id, "")
				if e := f.host.Finish(f.subject, id, b); e != nil {
					t.Fatal(e)
				}
				err = f.host.Prepare(f.subject, "read_file", id, b, "")
			case "source_unverified":
				f.sourceErr = errMissing
				_, err = f.host.Load(f.subject, load, "", hostSource())
			case "source_changed":
				src := hostSource()
				if _, e := f.host.Load(f.subject, load, "", src); e != nil {
					t.Fatal(e)
				}
				src.TextSHA256 = strings.Repeat("9", 64)
				_, err = f.host.Load(f.subject, load, "", src)
			case "unknown_cache":
				src := hostSource()
				src.CacheHit = true
				_, err = f.host.Load(f.subject, load, "", src)
			case "wrong_parent":
				_, err = f.host.Load(f.subject, load, "nload-"+strings.Repeat("2", 32), hostSource())
			case "runtime_dead":
				f.runtimeErr = errMissing
				err = f.host.Prepare(f.subject, "read_file", id, strings.Repeat("a", 64), "")
			case "end":
				if e := f.host.End(f.subject); e != nil {
					t.Fatal(e)
				}
				err = f.host.Begin(f.subject, strings.Repeat("8", 64))
			case "restart":
				f.bind(id, "")
				restarted, e := OpenNativeHost(f.store.dir, f.host.deps)
				if e != nil {
					t.Fatal(e)
				}
				_, err = restarted.Calls().VerifyCall(NativeCallRequest{Subject: f.subject, Tool: "read_file", ToolCallID: id, Params: p})
			case "audit_failure":
				f.auditError = errMissing
				err = f.host.Prepare(f.subject, "read_file", id, strings.Repeat("a", 64), "")
			}
			if err == nil {
				t.Fatal("invalid host transition accepted")
			}
			if name != "restart" {
				if _, _, e := f.host.live(f.subject); e == nil {
					t.Fatal("failed task stayed live")
				}
			}
		})
	}
}
func TestNativeHostEndPreservesLateObservation(t *testing.T) {
	f := newHostFixture(t)
	p, b := f.bind("in-flight", "")
	if err := f.host.End(f.subject); err != nil {
		t.Fatal(err)
	}
	if _, err := f.host.Calls().VerifyCall(NativeCallRequest{Subject: f.subject, Tool: "read_file", ToolCallID: "in-flight", Params: p}); err == nil {
		t.Fatal("ended task accepted")
	}
	if err := f.host.Finish(f.subject, "in-flight", b); err != nil {
		t.Fatal(err)
	}
	if err := f.host.Finish(f.subject, "in-flight", b); err == nil {
		t.Fatal("duplicate late finish accepted")
	}
}

func TestNativeHostEndDoesNotWaitForRuntimeVerifier(t *testing.T) {
	f := newHostFixture(t)
	entered, release := make(chan struct{}), make(chan struct{})
	f.host.deps.Audit = func(string, string) error { return nil }
	f.host.deps.VerifyRuntime = func(Subject, string) (time.Time, error) { close(entered); <-release; return f.loadUntil, nil }
	result := make(chan error, 1)
	go func() { result <- f.host.Prepare(f.subject, "read_file", "waiting", strings.Repeat("a", 64), "") }()
	select {
	case <-entered:
	case <-time.After(time.Second):
		t.Fatal("verifier not entered")
	}
	ended := make(chan error, 1)
	go func() { ended <- f.host.End(f.subject) }()
	select {
	case err := <-ended:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		close(release)
		t.Fatal("End waited for publisher")
	}
	close(release)
	select {
	case err := <-result:
		if err == nil {
			t.Fatal("cancelled publisher continued")
		}
	case <-time.After(time.Second):
		t.Fatal("publisher did not stop")
	}
}

func TestNativeHostGrantRevocationAndMissingPrepare(t *testing.T) {
	for _, name := range []string{"missing_prepare", "revoked_skill", "revoked_agent", "expired_host", "finished_call"} {
		t.Run(name, func(t *testing.T) {
			f := newHostFixture(t)
			id := "call"
			load := "nload-" + strings.Repeat("1", 32)
			if _, err := f.host.Load(f.subject, load, "", hostSource()); err != nil {
				t.Fatal(err)
			}
			p := map[string]any{"path": "/workspace/visible.txt"}
			if name == "missing_prepare" {
				if _, err := f.host.Bind(f.subject, "read_file", id, p); err == nil {
					t.Fatal("bind without host prepare")
				}
				return
			}
			_, b := f.bind(id, load)
			switch name {
			case "revoked_skill":
				g := f.grants[testGrantID]
				g.Status = "revoked"
				f.signGrant(g)
			case "revoked_agent":
				g := f.grants["grt-agent-baseline"]
				g.Status = "revoked"
				f.signGrant(g)
			case "expired_host":
				f.now = f.loadUntil.Add(time.Second)
			case "finished_call":
				if err := f.host.Finish(f.subject, id, b); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := f.host.Calls().VerifyCall(NativeCallRequest{Subject: f.subject, Tool: "read_file", ToolCallID: id, Params: p}); err == nil {
				t.Fatal("stale host authority accepted")
			}
		})
	}
}

func TestNativeHostDistinctSkillsCannotBorrowWriterGrant(t *testing.T) {
	f := newHostFixture(t)
	reader := f.grants[testGrantID]
	reader.Facts[0].Resource.Value = "/workspace/reader"
	f.signGrant(reader)
	writer := *reader
	writer.GrantID = "grt-skill-writer"
	skill := *reader.Skill
	skill.SkillID = "writer-skill"
	skill.ContentHash = strings.Repeat("2", 64)
	writer.Skill = &skill
	writer.Facts = append([]grant.Fact(nil), reader.Facts...)
	writer.Facts[0].Resource.Value = "/workspace/writer"
	f.grants[writer.GrantID] = &writer
	f.signGrant(&writer)
	install := *f.installs[testInstall]
	install.InstallID = "ins-writer"
	install.Plan.GrantID = writer.GrantID
	f.installs[install.InstallID] = &install
	sourceA := hostSource()
	sourceB := sourceA
	sourceB.SkillFile = NativeSourceFile{PathSHA256: strings.Repeat("4", 64), SHA256: strings.Repeat("2", 64), Bytes: 10}
	sourceB.ContentFile = sourceB.SkillFile
	sourceB.TextSHA256 = sourceB.SkillFile.SHA256
	f.host.deps.ResolveSource = func(_ Subject, source NativeSource) (InstallRef, error) {
		switch source.SkillFile {
		case sourceA.SkillFile:
			return InstallRef{InstallID: testInstall, ClaimSignature: testClaimSig}, nil
		case sourceB.SkillFile:
			return InstallRef{InstallID: install.InstallID, ClaimSignature: testClaimSig}, nil
		default:
			return InstallRef{}, errMissing
		}
	}
	a := "nload-" + strings.Repeat("1", 32)
	b := "nload-" + strings.Repeat("2", 32)
	if _, err := f.host.Load(f.subject, a, "", sourceA); err != nil {
		t.Fatal(err)
	}
	if _, err := f.host.Load(f.subject, b, a, sourceB); err != nil {
		t.Fatal(err)
	}
	pack, _ := rulepack.Builtin()
	chain, err := receipt.OpenChain(t.TempDir(), "local", f.key)
	if err != nil {
		t.Fatal(err)
	}
	engine, err := receipt.New(receipt.Options{Pack: pack, Chain: chain, Version: "host-multi-skill", EnforcementMode: "block", Now: func() time.Time { return f.now },
		NativeCalls: func(r receipt.Request) (bool, *receipt.NativeInvocationVerification, error) {
			v, e := f.host.Calls().VerifyNativeForEngine(r)
			return true, v, e
		},
		IntentLookup: func(_, _, _ string) (*receipt.IntentContract, error) {
			return &receipt.IntentContract{IntentID: "fixture-intent", TaskID: "trusted-envelope", Principal: "synthetic-user", AgentID: testAgent, Purpose: "read fixture", AllowedEffects: []string{"file.read"}, ValidUntil: "2099-01-01T00:00:00Z", AuthorityRevision: "fixture", SelectedGrant: f.grants["grt-agent-baseline"]}, nil
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	check := func(id string, want string) {
		t.Helper()
		p := map[string]any{"path": "/workspace/writer/file.txt"}
		binding := f.prepare(id, b, p)
		if _, e := f.host.Bind(f.subject, "read_file", id, p); e != nil {
			t.Fatal(e)
		}
		d, e := engine.Decide(receipt.Request{Platform: "hermes", AgentID: testAgent, SessionID: testSession, RuntimeTaskID: f.subject.TaskID, Tool: "read_file", ToolCallID: id, Params: p})
		if e != nil || d.Action != want {
			t.Fatalf("cross-skill result: %v %+v", e, d)
		}
		if e = f.host.Finish(f.subject, id, binding); e != nil {
			t.Fatal(e)
		}
	}
	check("borrow-writer", receipt.ActionDeny)
	if err = f.host.End(f.subject); err != nil {
		t.Fatal(err)
	}
	f.subject.TaskID = "independent-writer-task"
	if err = f.host.Begin(f.subject, strings.Repeat("8", 64)); err != nil {
		t.Fatal(err)
	}
	if _, err = f.host.Load(f.subject, b, "", sourceB); err != nil {
		t.Fatal(err)
	}
	check("writer-own-task", receipt.ActionAllow)
}

func TestNativeHostRestartCannotReauthorizeRecordedCall(t *testing.T) {
	f := newHostFixture(t)
	params, binding := f.bind("uncertain-old-call", "")
	// Even authenticated re-enrollment cannot turn the old immutable call into
	// a new execution; this remains true without a prior Finish observation.
	next, err := OpenNativeHost(f.store.dir, f.host.deps)
	if err != nil {
		t.Fatal(err)
	}
	if err = next.Begin(f.subject, strings.Repeat("8", 64)); err != nil {
		t.Fatal(err)
	}
	if err = next.Prepare(f.subject, "read_file", "uncertain-old-call", binding, ""); err != nil {
		t.Fatal(err)
	}
	if _, err = next.Bind(f.subject, "read_file", "uncertain-old-call", params); err == nil {
		t.Fatal("restart replayed an uncertain recorded call")
	}
}
