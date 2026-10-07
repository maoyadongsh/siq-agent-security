package skillcontext

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/signing"
)

type invocationStoreFixture struct {
	*fixture
	s                                   *InvocationStore
	audits                              []string
	auditError, installError, loadError error
	loads                               map[string]InvocationRequest
	loadUntil                           time.Time
}

func (f *invocationStoreFixture) signGrant(g *grant.Grant) {
	f.t.Helper()
	g.SigningSchema = signing.SchemaLocalCanonicalV1
	b, _ := json.Marshal(g)
	var m map[string]any
	_ = json.Unmarshal(b, &m)
	delete(m, "signature")
	var err error
	g.Signature, err = f.key.SignCanonical(m)
	if err != nil {
		f.t.Fatal(err)
	}
}

func newInvocationStoreFixture(t *testing.T) *invocationStoreFixture {
	f := &invocationStoreFixture{fixture: newFixture(t), loads: map[string]InvocationRequest{}}
	base := *f.grants[testGrantID]
	base.GrantID, base.Skill = "grt-agent-baseline", nil
	f.grants[base.GrantID] = &base
	f.signGrant(&base)
	f.signGrant(f.grants[testGrantID])
	inst := f.instances[testInstance]
	inst.GrantRef.GrantID = base.GrantID
	f.instances[testInstance] = inst
	f.bound["hermes|"+testAgent+"|"+testSession] = base.GrantID
	f.loadUntil = f.now.Add(45 * time.Minute)
	deps := InvocationDeps{Deps: f.store.deps,
		ValidateInstalled: func(g *grant.Grant, ref InstallRef) error { return f.installError },
		ValidateLoad: func(subject Subject, install InstallRef, loader NativeLoadRef, parent *ParentRef) (time.Time, error) {
			r, ok := f.loads[loader.LoadID]
			if !ok || r.InstanceID != subject.InstanceID || r.SessionID != subject.SessionID || r.TaskID != subject.TaskID ||
				r.InstallID != install.InstallID || r.Loader != loader || !reflect.DeepEqual(r.Parent, parent) {
				return time.Time{}, errMissing
			}
			return f.loadUntil, f.loadError
		},
		Audit: func(event, id string) error {
			if f.auditError != nil {
				return f.auditError
			}
			f.audits = append(f.audits, event+":"+id)
			return nil
		},
	}
	var err error
	f.s, err = OpenInvocations(f.store.dir, deps)
	if err != nil {
		t.Fatal(err)
	}
	return f
}

func (f *invocationStoreFixture) request(n int, parent *InvocationContext) InvocationRequest {
	r := InvocationRequest{InstanceID: testInstance, SessionID: testSession, TaskID: testTask, InstallID: testInstall, TTL: time.Hour,
		Loader: NativeLoadRef{LoadID: fmt.Sprintf("nload-%032x", n), SkillFileSHA256: testHash, RuntimeArtifactSHA256: strings.Repeat("8", 64)}}
	if parent != nil {
		r.Parent = &ParentRef{ContextID: parent.ContextID, Signature: parent.Signature}
	}
	f.loads[r.Loader.LoadID] = r
	return r
}

func (f *invocationStoreFixture) issueV2(r InvocationRequest) *InvocationContext {
	f.t.Helper()
	c, err := f.s.Issue(r)
	if err != nil {
		f.t.Fatal(err)
	}
	return c
}

func TestInvocationStoreRestartReplayAndSnapshot(t *testing.T) {
	f := newInvocationStoreFixture(t)
	r := f.request(1, nil)
	c := f.issueV2(r)
	if c.AgentAuthority.GrantID != "grt-agent-baseline" || c.Authority.GrantID != testGrantID || c.ExpiresAt != f.loadUntil.Format(time.RFC3339Nano) {
		t.Fatal("issuance must derive distinct authorities and clamp the native lease")
	}
	restarted, err := OpenInvocations(f.s.dir, f.s.deps)
	if err != nil {
		t.Fatal(err)
	}
	f.s = restarted
	f.now = f.now.Add(time.Minute)
	again := f.issueV2(r)
	if !reflect.DeepEqual(c, again) || len(f.audits) != 1 {
		t.Fatal("restart replay must preserve original bytes and audit")
	}
	v, err := f.s.Verify(c.ContextID, c.Subject)
	if err != nil || len(v.SkillGrants) != 1 {
		t.Fatal(err)
	}
	v.AgentGrant.Status = "revoked"
	v.SkillGrants[0].Skill.ContentHash = strings.Repeat("f", 64)
	if _, err := f.s.Verify(c.ContextID, c.Subject); err != nil {
		t.Fatal("returned snapshots mutated trusted dependencies", err)
	}
	if _, err := f.store.Get(c.ContextID); err == nil {
		t.Fatal("v1 reader accepted v2 authority")
	}
}

func TestInvocationStoreEachLiveDependencyRechecked(t *testing.T) {
	for name, change := range map[string]func(*invocationStoreFixture){
		"agent_revoke": func(f *invocationStoreFixture) { f.grants["grt-agent-baseline"].Status = "revoked" },
		"agent_resigned_drift": func(f *invocationStoreFixture) {
			g := f.grants["grt-agent-baseline"]
			g.DefaultEffect = "allow"
			f.signGrant(g)
		},
		"skill_removed": func(f *invocationStoreFixture) { delete(f.grants, testGrantID) },
		"skill_resigned_drift": func(f *invocationStoreFixture) {
			g := f.grants[testGrantID]
			g.Skill.ContentHash = strings.Repeat("a", 64)
			f.signGrant(g)
		},
		"identity_revoked": func(f *invocationStoreFixture) { delete(f.instances, testInstance) },
		"identity_rebound": func(f *invocationStoreFixture) {
			r := f.instances[testInstance]
			r.GrantRef.GrantID = testGrantID
			f.instances[testInstance] = r
		},
		"session_revoked":       func(f *invocationStoreFixture) { delete(f.bound, "hermes|"+testAgent+"|"+testSession) },
		"install_removed":       func(f *invocationStoreFixture) { delete(f.installs, testInstall) },
		"install_claim_changed": func(f *invocationStoreFixture) { f.installs[testInstall].ClaimSignature = strings.Repeat("b", 128) },
		"install_instance_changed": func(f *invocationStoreFixture) {
			f.installs[testInstall].Plan.InstanceID = "hi-" + strings.Repeat("b", 32)
		},
		"install_bytes_drift": func(f *invocationStoreFixture) { f.installError = errMissing },
		"native_task_ended":   func(f *invocationStoreFixture) { f.loadError = errMissing },
		"native_load_removed": func(f *invocationStoreFixture) { clear(f.loads) },
		"lease_shortened":     func(f *invocationStoreFixture) { f.loadUntil = f.now.Add(time.Minute) },
		"lease_expired":       func(f *invocationStoreFixture) { f.now = f.loadUntil },
		"clock_before_issue":  func(f *invocationStoreFixture) { f.now = f.now.Add(-time.Second) },
	} {
		t.Run(name, func(t *testing.T) {
			f := newInvocationStoreFixture(t)
			r := f.request(1, nil)
			c := f.issueV2(r)
			change(f)
			if _, err := f.s.Verify(c.ContextID, c.Subject); err == nil {
				t.Fatal("stale authority accepted")
			}
			if _, err := f.s.Issue(r); err == nil {
				t.Fatal("replay revived stale authority")
			}
			if len(f.audits) != 1 {
				t.Fatal("failed replay emitted publication audit")
			}
		})
	}
}

func TestInvocationStoreParentRevocationAndDepth(t *testing.T) {
	f := newInvocationStoreFixture(t)
	r := f.request(1, nil)
	r.TTL = 10 * time.Minute
	root := f.issueV2(r)
	leaf := root
	for i := 2; i <= 8; i++ {
		leaf = f.issueV2(f.request(i, leaf))
	}
	if leaf.ExpiresAt != root.ExpiresAt {
		t.Fatal("child escaped parent lease")
	}
	v, err := f.s.Verify(leaf.ContextID, leaf.Subject)
	if err != nil || len(v.Contexts) != 8 || len(v.SkillGrants) != 8 {
		t.Fatal("full authority chain missing", err)
	}
	if _, err := f.s.Issue(f.request(9, leaf)); err == nil {
		t.Fatal("ninth ancestor accepted")
	}
	if _, err := f.s.Revoke(root.ContextID, strings.Repeat("0", 128)); err == nil {
		t.Fatal("wrong expected signature revoked context")
	}
	rev, err := f.s.Revoke(root.ContextID, root.Signature)
	if err != nil {
		t.Fatal(err)
	}
	f.now = f.now.Add(time.Second)
	duplicate, err := f.s.Revoke(root.ContextID, root.Signature)
	if err != nil || !reflect.DeepEqual(rev, duplicate) || len(f.audits) != 9 {
		t.Fatal("revocation was not immutable and idempotent", err)
	}
	if _, err := f.s.Verify(leaf.ContextID, leaf.Subject); err == nil {
		t.Fatal("ancestor revocation did not invalidate descendant")
	}
	if _, err := os.Stat(f.s.contextPath(root.ContextID)); err != nil {
		t.Fatal("revocation deleted original")
	}
}

func TestInvocationStoreCannotOmitOrBorrowParent(t *testing.T) {
	for _, kind := range []string{"omit", "signature", "task", "baseline"} {
		t.Run(kind, func(t *testing.T) {
			f := newInvocationStoreFixture(t)
			root := f.issueV2(f.request(1, nil))
			r := f.request(2, root)
			switch kind {
			case "omit":
				r.Parent = nil
			case "signature":
				p := *r.Parent
				p.Signature = strings.Repeat("b", 128)
				r.Parent = &p
			case "task":
				r.TaskID = "other-task"
				f.loads[r.Loader.LoadID] = r
			case "baseline":
				g := f.grants["grt-agent-baseline"]
				g.DefaultEffect = "allow"
				f.signGrant(g)
			}
			if _, err := f.s.Issue(r); err == nil {
				t.Fatal("untrusted or mismatched parent accepted")
			}
		})
	}
}

func TestInvocationStoreAuditFailureDoesNotPublish(t *testing.T) {
	f := newInvocationStoreFixture(t)
	r := f.request(1, nil)
	f.auditError = errMissing
	if _, err := f.s.Issue(r); err == nil {
		t.Fatal("unaudited context published")
	}
	entries, _ := os.ReadDir(f.s.contextDir())
	if len(entries) != 0 {
		t.Fatal("failure left authority")
	}
	f.auditError = nil
	c := f.issueV2(r)
	f.auditError = errMissing
	if _, err := f.s.Revoke(c.ContextID, c.Signature); err == nil {
		t.Fatal("unaudited tombstone published")
	}
	if _, err := os.Stat(f.s.revokedPath(c.ContextID)); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("failed revoke changed authority")
	}
	if _, err := f.s.Verify(c.ContextID, c.Subject); err != nil {
		t.Fatal(err)
	}
}

func TestInvocationStoreMalformedRecordsFailClosed(t *testing.T) {
	for name, mutate := range map[string]func([]byte) []byte{
		"duplicate": func(b []byte) []byte {
			return bytes.Replace(b, []byte(`"schema_version":`), []byte(`"schema_version":"skill-execution-context/v2","schema_version":`), 1)
		},
		"alias": func(b []byte) []byte { return bytes.Replace(b, []byte(`"context_id"`), []byte(`"Context_ID"`), 1) },
		"null_parent": func(b []byte) []byte {
			return bytes.Replace(b, []byte(`"schema_version":`), []byte(`"parent":null,"schema_version":`), 1)
		},
		"unknown": func(b []byte) []byte {
			return bytes.Replace(b, []byte(`"schema_version":`), []byte(`"model_authorized":true,"schema_version":`), 1)
		},
		"extra_document": func(b []byte) []byte { return append(b, []byte(` {}`)...) },
		"oversize":       func(b []byte) []byte { return append(b, bytes.Repeat([]byte(" "), invocationRecordBytes)...) },
		"tampered":       func(b []byte) []byte { return bytes.Replace(b, []byte(testHash), []byte(strings.Repeat("f", 64)), 1) },
	} {
		t.Run(name, func(t *testing.T) {
			f := newInvocationStoreFixture(t)
			c := f.issueV2(f.request(1, nil))
			p := f.s.contextPath(c.ContextID)
			b, err := os.ReadFile(p)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(p, mutate(b), 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := f.s.Verify(c.ContextID, c.Subject); err == nil {
				t.Fatal("malformed signed record accepted")
			}
		})
	}
}

func TestInvocationStorePrivateObjectsAndTombstones(t *testing.T) {
	for _, kind := range []string{"symlink", "public_file", "corrupt_tombstone", "other_context_tombstone"} {
		t.Run(kind, func(t *testing.T) {
			if runtime.GOOS == "windows" && (kind == "symlink" || kind == "public_file") {
				t.Skip("POSIX object fixture")
			}
			f := newInvocationStoreFixture(t)
			c := f.issueV2(f.request(1, nil))
			p := f.s.contextPath(c.ContextID)
			switch kind {
			case "symlink":
				if err := os.Rename(p, p+".old"); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(p+".old", p); err != nil {
					t.Fatal(err)
				}
			case "public_file":
				if err := os.Chmod(p, 0644); err != nil {
					t.Fatal(err)
				}
			case "corrupt_tombstone":
				if err := os.WriteFile(f.s.revokedPath(c.ContextID), []byte(`{}`), 0600); err != nil {
					t.Fatal(err)
				}
			case "other_context_tombstone":
				other := f.issueV2(f.request(2, nil))
				rev, err := f.s.Revoke(other.ContextID, other.Signature)
				if err != nil {
					t.Fatal(err)
				}
				b, _ := json.Marshal(rev)
				if err := os.WriteFile(f.s.revokedPath(c.ContextID), b, 0600); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := f.s.Verify(c.ContextID, c.Subject); err == nil {
				t.Fatal("unsafe record accepted")
			}
		})
	}
}

func TestInvocationStoreConcurrentDuplicateAndCapacity(t *testing.T) {
	f := newInvocationStoreFixture(t)
	r := f.request(1, nil)
	results := make(chan *InvocationContext, 16)
	errs := make(chan error, 16)
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); c, err := f.s.Issue(r); results <- c; errs <- err }()
	}
	wg.Wait()
	close(results)
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	var original *InvocationContext
	for c := range results {
		if original == nil {
			original = c
		}
		if !reflect.DeepEqual(original, c) {
			t.Fatal("concurrent replay diverged")
		}
	}
	if len(f.audits) != 1 {
		t.Fatal("concurrent duplicate publication")
	}
	// Occupied slots consume the budget even if no longer live. No scan of
	// unrelated record contents is needed for a point lookup or parent chain.
	for i := 0; i < maxInvocations-2; i++ {
		p := filepath.Join(f.s.contextDir(), fmt.Sprintf("sec-%032x.json", i))
		if err := os.WriteFile(p, []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	f.issueV2(f.request(2, nil)) // last available slot
	if _, err := f.s.Issue(f.request(3, nil)); err == nil {
		t.Fatal("capacity overrun accepted")
	}
	if _, err := f.s.Issue(r); err != nil {
		t.Fatal("exact replay at capacity refused", err)
	}
}

func TestInvocationStoreChangedLoadCannotBeResigned(t *testing.T) {
	f := newInvocationStoreFixture(t)
	r := f.request(1, nil)
	c := f.issueV2(r)
	r.Loader.SkillFileSHA256 = strings.Repeat("b", 64)
	f.loads[r.Loader.LoadID] = r // even a newly attested fact cannot rewrite this ID
	if _, err := f.s.Issue(r); err == nil {
		t.Fatal("same load identity was re-signed with changed facts")
	}
	original, err := f.s.read(c.ContextID)
	if err != nil || original.Signature != c.Signature {
		t.Fatal("original changed", err)
	}
}

func TestInvocationStoreRequiresAllTrustedDependencies(t *testing.T) {
	f := newInvocationStoreFixture(t)
	for _, remove := range []func(*InvocationDeps){
		func(d *InvocationDeps) { d.Key = nil }, func(d *InvocationDeps) { d.ReadGrant = nil },
		func(d *InvocationDeps) { d.ReadInstall = nil }, func(d *InvocationDeps) { d.ReadInstance = nil },
		func(d *InvocationDeps) { d.SessionBound = nil }, func(d *InvocationDeps) { d.ValidateInstalled = nil },
		func(d *InvocationDeps) { d.ValidateLoad = nil }, func(d *InvocationDeps) { d.Audit = nil },
	} {
		d := f.s.deps
		remove(&d)
		if _, err := OpenInvocations(t.TempDir(), d); err == nil {
			t.Fatal("missing trusted dependency accepted")
		}
	}
}

func TestInvocationStoreIndependentSkillChainAndExactSubject(t *testing.T) {
	f := newInvocationStoreFixture(t)
	root := f.issueV2(f.request(1, nil))
	g := *f.grants[testGrantID]
	sk := *g.Skill
	sk.SkillID, sk.ContentHash = "marketplace:skill:writer", strings.Repeat("c", 64)
	g.GrantID, g.Skill = "grt-writer", &sk
	f.grants[g.GrantID] = &g
	f.signGrant(&g)
	install := *f.installs[testInstall]
	install.InstallID, install.Plan.GrantID = "ins-writer", g.GrantID
	f.installs[install.InstallID] = &install
	r := f.request(2, root)
	r.InstallID = install.InstallID
	f.loads[r.Loader.LoadID] = r
	leaf := f.issueV2(r)
	v, err := f.s.Verify(leaf.ContextID, leaf.Subject)
	if err != nil || len(v.SkillGrants) != 2 || v.SkillGrants[0].GrantID != g.GrantID || v.SkillGrants[1].GrantID != testGrantID || v.AgentGrant.GrantID != root.AgentAuthority.GrantID {
		t.Fatal("distinct Skill authorities lost or substituted the pinned baseline", err)
	}
	for _, change := range []func(*Subject){
		func(s *Subject) { s.Platform = "openclaw" }, func(s *Subject) { s.InstanceID = "hi-" + strings.Repeat("c", 32) },
		func(s *Subject) { s.AgentID = "hri-" + strings.Repeat("c", 32) }, func(s *Subject) { s.SessionID = "other" }, func(s *Subject) { s.TaskID = "other" },
	} {
		subject := leaf.Subject
		change(&subject)
		if _, err := f.s.Verify(leaf.ContextID, subject); err == nil {
			t.Fatal("context borrowed across a subject boundary")
		}
	}
}

func TestInvocationStorePublicationFailurePreservesConflictingObject(t *testing.T) {
	f := newInvocationStoreFixture(t)
	f.s.deps.Audit = func(event, id string) error {
		// Simulates failure between durable audit and exclusive publication.
		return os.WriteFile(f.s.contextPath(id), []byte("owned-conflicting-object"), 0600)
	}
	r := f.request(1, nil)
	if _, err := f.s.Issue(r); err == nil {
		t.Fatal("audit acknowledgement treated as publication")
	}
	subject := Subject{Platform: "hermes", InstanceID: testInstance, AgentID: testAgent, SessionID: testSession, TaskID: testTask}
	id := invocationID(subject, r.Loader.LoadID)
	b, err := os.ReadFile(f.s.contextPath(id))
	if err != nil || string(b) != "owned-conflicting-object" {
		t.Fatal("conflicting object overwritten", err)
	}
	if _, err := f.s.Verify(id, subject); err == nil {
		t.Fatal("failed publication authorized")
	}
}

func TestInvocationStoreProcessRecovery(t *testing.T) {
	const helperEnv = "SIQ_INVOCATION_TEST_STATE"
	if dir := os.Getenv(helperEnv); dir != "" {
		f := newInvocationStoreFixture(t)
		var err error
		f.s, err = OpenInvocations(dir, f.s.deps)
		if err != nil {
			t.Fatal(err)
		}
		f.issueV2(f.request(1, nil))
		os.Exit(0) // do not rely on orderly Store shutdown or any in-memory cache
	}
	f := newInvocationStoreFixture(t)
	cmd := exec.Command(os.Args[0], "-test.run=^TestInvocationStoreProcessRecovery$")
	cmd.Env = append(os.Environ(), helperEnv+"="+f.s.dir)
	if b, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("writer process: %v %s", err, b)
	}
	r := f.request(1, nil)
	subject := Subject{Platform: "hermes", InstanceID: testInstance, AgentID: testAgent, SessionID: testSession, TaskID: testTask}
	id := invocationID(subject, r.Loader.LoadID)
	v, err := f.s.Verify(id, subject)
	if err != nil || len(v.Contexts) != 1 {
		t.Fatal("independent process could not recover published authority", err)
	}
	if _, err := f.s.Revoke(id, v.Contexts[0].Signature); err != nil {
		t.Fatal(err)
	}
	if _, err := f.s.Verify(id, subject); err == nil {
		t.Fatal("recovered authority ignored revocation")
	}
}
