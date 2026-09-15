package skillcontext

import (
	"bytes"
	"encoding/json"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

const (
	testInstance = "hi-" + "aaaaaaaabbbbbbbbccccccccdddddddd"
	testAgent    = "hri-aaaaaaaabbbbbbbbccccccccdddddddd"
	testSession  = "sess-1"
	testTask     = "task-1"
	testInstall  = "ins-test-1"
	testGrantID  = "grt-skill-1"
	testSkillID  = "marketplace:skill:report-gen@0a1b2c3d4e5f"
	testHash     = "1111111111111111111111111111111111111111111111111111111111111111"
	testClaimSig = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
)

var errMissing = errorsNew("missing")

type missingError struct{ s string }

func (e *missingError) Error() string { return e.s }
func errorsNew(s string) error        { return &missingError{s} }

type fixture struct {
	t          *testing.T
	store      *Store
	key        *signing.Key
	grants     map[string]*grant.Grant
	installs   map[string]*skillinstall.Record
	instances  map[string]runtimeidentity.Record
	bound      map[string]string // platform|agent|session -> grantID
	boundUntil map[string]time.Time
	now        time.Time
}

func instanceRecord() runtimeidentity.Record {
	r := runtimeidentity.Record{
		SchemaVersion: "local-runtime-identity/v1", IdentityID: "ri-" + strings.Repeat("1", 32),
		InstanceID: testInstance, AgentID: testAgent, Platform: "hermes",
	}
	r.GrantRef.GrantID = testGrantID
	return r
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	key, err := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	if err != nil {
		t.Fatal(err)
	}
	f := &fixture{
		t: t, key: key,
		grants:     map[string]*grant.Grant{},
		installs:   map[string]*skillinstall.Record{},
		instances:  map[string]runtimeidentity.Record{},
		bound:      map[string]string{},
		boundUntil: map[string]time.Time{},
		now:        time.Date(2026, 9, 14, 12, 0, 0, 0, time.UTC),
	}
	version := "1.2.0"
	f.grants[testGrantID] = &grant.Grant{
		GrantID: testGrantID, AdmissionID: "adm-1", Platform: "hermes",
		Status: "deployed", CreatedAt: f.now.Add(-time.Hour).Format(time.RFC3339),
		Subject: grant.Subject{Type: "agent_instance", ID: testAgent},
		Skill:   &grant.SkillRef{SkillID: testSkillID, ContentHash: testHash, Version: &version},
	}
	f.installs[testInstall] = &skillinstall.Record{
		SchemaVersion:  "local-skill-install-record/v1",
		InstallID:      testInstall,
		Plan:           skillinstall.Plan{PlanID: "plan-1", GrantID: testGrantID, Platform: "hermes", InstanceID: testInstance},
		ClaimSignature: testClaimSig,
		RecordedStatus: "installed_unverified",
	}
	f.instances[testInstance] = instanceRecord()
	boundKey := "hermes|" + testAgent + "|" + testSession
	f.bound[boundKey] = testGrantID
	f.boundUntil[boundKey] = f.now.Add(90 * time.Minute)
	st, err := Open(t.TempDir(), Deps{
		Key: key,
		Now: func() time.Time { return f.now },
		ReadGrant: func(id string) (*grant.Grant, error) {
			g := f.grants[id]
			if g == nil {
				return nil, errMissing
			}
			return g, nil
		},
		ReadInstall: func(id string) (*skillinstall.Record, error) {
			r := f.installs[id]
			if r == nil {
				return nil, errMissing
			}
			return r, nil
		},
		ReadInstance: func(instanceID string) (runtimeidentity.Record, error) {
			r, ok := f.instances[instanceID]
			if !ok {
				return runtimeidentity.Record{}, errMissing
			}
			return r, nil
		},
		SessionBound: func(platform, agentID, sessionID, grantID string) (time.Time, error) {
			key := platform + "|" + agentID + "|" + sessionID
			if f.bound[key] != grantID {
				return time.Time{}, errMissing
			}
			return f.boundUntil[key], nil
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	f.store = st
	return f
}

func (f *fixture) issue(t *testing.T, task string) *Context {
	t.Helper()
	c, err := f.store.Issue(IssueRequest{InstanceID: testInstance, SessionID: testSession, TaskID: task, InstallID: testInstall, TTL: time.Hour})
	if err != nil {
		t.Fatalf("issue: %v", err)
	}
	return c
}

func TestIssueBindsDerivedIdentity(t *testing.T) {
	f := newFixture(t)
	c := f.issue(t, testTask)
	if c.EvidenceLevel != EvidenceTask || c.Skill.SkillID != testSkillID || c.Skill.ContentHash != testHash || c.Skill.Version != "1.2.0" {
		t.Fatalf("skill identity must derive from the grant: %+v", c.Skill)
	}
	if c.Authority.GrantID != testGrantID {
		t.Fatalf("grant must derive from the install plan: %+v", c.Authority)
	}
	digest, err := GrantDigest(f.grants[testGrantID])
	if err != nil || c.Authority.GrantDigest != digest {
		t.Fatalf("grant digest must be issuer-computed: %v %q", err, c.Authority.GrantDigest)
	}
	if c.Install.ClaimSignature != testClaimSig {
		t.Fatalf("install binding must derive from the record: %+v", c.Install)
	}
	if c.Signature == "" || signing.VerifyWithSchema(c.SigningSchema, f.key.Public(), c.Unsigned(), c.Signature) != nil {
		t.Fatal("issued context must verify against the state key")
	}
	if err := c.Validate(); err != nil {
		t.Fatalf("issued context must validate: %v", err)
	}
}

func TestVerifyAcceptsInstallPipelineTerminalState(t *testing.T) {
	// The real install pipeline leaves the skill grant approved with an
	// import-reserved admission (never deployed). SEC issuance and per-decision
	// verification must treat that state as live when the install record matches.
	f := newFixture(t)
	g := f.grants[testGrantID]
	g.Status = "approved"
	g.AdmissionID = "adm-si-test"
	c := f.issue(t, testTask)
	v, err := f.store.Verify("hermes", testAgent, testSession, testTask)
	if err != nil || v == nil || v.Invalid || v.Grant == nil {
		t.Fatalf("approved+reserved grant with matching install must verify: %+v %v", v, err)
	}
	// Flipping the same grant out of the reserved terminal state invalidates.
	g.Status = "draft"
	v, _ = f.store.Verify("hermes", testAgent, testSession, testTask)
	if v == nil || !v.Invalid || v.ReasonCode != "skill_context_grant_changed" {
		t.Fatalf("non-live terminal state must invalidate: %+v", v)
	}
	_ = c
}

func TestIssueSessionLevelWithoutTask(t *testing.T) {
	f := newFixture(t)
	c := f.issue(t, "")
	if c.EvidenceLevel != EvidenceSession || c.Subject.TaskID != "" {
		t.Fatalf("session-level context: %+v", c)
	}
}

func TestIssueClampsExpiryToSignedSessionBinding(t *testing.T) {
	f := newFixture(t)
	key := "hermes|" + testAgent + "|" + testSession
	f.boundUntil[key] = f.now.Add(20 * time.Minute)
	c, err := f.store.Issue(IssueRequest{
		InstanceID: testInstance, SessionID: testSession, TaskID: testTask,
		InstallID: testInstall, TTL: time.Hour,
	})
	if err != nil {
		t.Fatal(err)
	}
	if c.ExpiresAt != f.boundUntil[key].Format(time.RFC3339Nano) {
		t.Fatalf("SEC expiry %q must be clamped to binding %q", c.ExpiresAt, f.boundUntil[key])
	}
}

func TestIssueNegativeMatrix(t *testing.T) {
	cases := map[string]func(f *fixture){
		"install_not_completed": func(f *fixture) { f.installs[testInstall].RecordedStatus = "staged" },
		"install_removed":       func(f *fixture) { delete(f.installs, testInstall) },
		"install_recovery":      func(f *fixture) { f.installs[testInstall].RecordedStatus = "recovery_required" },
		"install_wrong_instance": func(f *fixture) {
			f.installs[testInstall].Plan.InstanceID = "hi-" + strings.Repeat("9", 32)
		},
		"grant_not_deployed": func(f *fixture) { f.grants[testGrantID].Status = "approved" },
		"grant_not_skill":    func(f *fixture) { f.grants[testGrantID].Skill = nil },
		"grant_revoked":      func(f *fixture) { f.grants[testGrantID].Status = "revoked" },
		"instance_missing":   func(f *fixture) { delete(f.instances, testInstance) },
		"instance_grant_other": func(f *fixture) {
			r := f.instances[testInstance]
			r.GrantRef.GrantID = "grt-other"
			f.instances[testInstance] = r
		},
		"session_unbound": func(f *fixture) { delete(f.bound, "hermes|"+testAgent+"|"+testSession) },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t)
			mutate(f)
			if _, err := f.store.Issue(IssueRequest{InstanceID: testInstance, SessionID: testSession, TaskID: testTask, InstallID: testInstall, TTL: time.Hour}); err == nil {
				t.Fatalf("%s: issuance must fail", name)
			}
		})
	}
}

func TestIssueRejectsBadInput(t *testing.T) {
	f := newFixture(t)
	for name, req := range map[string]IssueRequest{
		"bad_instance":  {InstanceID: "bogus", SessionID: testSession, InstallID: testInstall, TTL: time.Hour},
		"empty_session": {InstanceID: testInstance, SessionID: "", InstallID: testInstall, TTL: time.Hour},
		"ttl_over":      {InstanceID: testInstance, SessionID: testSession, InstallID: testInstall, TTL: 25 * time.Hour},
		"ttl_zero":      {InstanceID: testInstance, SessionID: testSession, InstallID: testInstall},
	} {
		if _, err := f.store.Issue(req); err == nil {
			t.Fatalf("%s: must fail", name)
		}
	}
}

func TestVerifyPositiveTaskAndSession(t *testing.T) {
	f := newFixture(t)
	f.issue(t, testTask)
	v, err := f.store.Verify("hermes", testAgent, testSession, testTask)
	if err != nil || v == nil || v.Invalid || v.Grant == nil || v.Grant.GrantID != testGrantID {
		t.Fatalf("task-level verify: %+v %v", v, err)
	}
	// A request for another task is not covered by the task-bound context.
	v, err = f.store.Verify("hermes", testAgent, testSession, "task-2")
	if err != nil || v != nil {
		t.Fatalf("other task must not be covered: %+v %v", v, err)
	}
	f2 := newFixture(t)
	f2.issue(t, "")
	v, err = f2.store.Verify("hermes", testAgent, testSession, "task-2")
	if err != nil || v == nil || v.Invalid {
		t.Fatalf("session-level context covers any task in the session: %+v %v", v, err)
	}
}

func TestVerifySubjectCopyFails(t *testing.T) {
	f := newFixture(t)
	f.issue(t, testTask)
	for name, args := range map[string][4]string{
		"other_session":  {"hermes", testAgent, "sess-2", testTask},
		"other_agent":    {"hermes", "hri-" + strings.Repeat("9", 32), testSession, testTask},
		"other_platform": {"openclaw", testAgent, testSession, testTask},
	} {
		v, err := f.store.Verify(args[0], args[1], args[2], args[3])
		if err != nil || v != nil {
			t.Fatalf("%s: copied subject must not verify: %+v %v", name, v, err)
		}
	}
}

func TestVerifyInvalidationMatrix(t *testing.T) {
	cases := map[string]struct {
		mutate func(f *fixture)
		code   string
	}{
		"expired":          {func(f *fixture) { f.now = f.now.Add(2 * time.Hour) }, "skill_context_expired"},
		"grant_revised":    {func(f *fixture) { f.grants[testGrantID].CreatedAt = f.now.Format(time.RFC3339) }, "skill_context_grant_changed"},
		"grant_revoked":    {func(f *fixture) { f.grants[testGrantID].Status = "revoked" }, "skill_context_grant_changed"},
		"grant_removed":    {func(f *fixture) { delete(f.grants, testGrantID) }, "skill_context_grant_changed"},
		"install_removed":  {func(f *fixture) { delete(f.installs, testInstall) }, "skill_context_install_changed"},
		"install_replaced": {func(f *fixture) { f.installs[testInstall].ClaimSignature = strings.Repeat("b", 128) }, "skill_context_install_changed"},
		"instance_revoked": {func(f *fixture) { delete(f.instances, testInstance) }, "skill_context_instance_invalid"},
		"instance_grant_changed": {func(f *fixture) {
			r := f.instances[testInstance]
			r.GrantRef.GrantID = "grt-other"
			f.instances[testInstance] = r
		}, "skill_context_instance_invalid"},
		"session_revoked": {func(f *fixture) {
			delete(f.bound, "hermes|"+testAgent+"|"+testSession)
		}, "skill_context_session_unbound"},
		"session_expiry_shortened": {func(f *fixture) {
			f.boundUntil["hermes|"+testAgent+"|"+testSession] = f.now.Add(30 * time.Minute)
		}, "skill_context_session_unbound"},
	}
	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t)
			f.issue(t, testTask)
			tc.mutate(f)
			v, err := f.store.Verify("hermes", testAgent, testSession, testTask)
			if err != nil || v == nil || !v.Invalid {
				t.Fatalf("%s: must be invalid: %+v %v", name, v, err)
			}
			if v.ReasonCode != tc.code {
				t.Fatalf("%s: code %q want %q", name, v.ReasonCode, tc.code)
			}
		})
	}
}

func TestVerifyRevocation(t *testing.T) {
	f := newFixture(t)
	c := f.issue(t, testTask)
	if _, err := f.store.Revoke(c.ContextID); err != nil {
		t.Fatal(err)
	}
	v, err := f.store.Verify("hermes", testAgent, testSession, testTask)
	if err != nil || v == nil || !v.Invalid || v.ReasonCode != "skill_context_revoked" {
		t.Fatalf("revoked context must invalidate: %+v %v", v, err)
	}
	// The tombstone retains the file: double revoke conflicts.
	if _, err := f.store.Revoke(c.ContextID); err == nil {
		t.Fatal("double revoke must conflict")
	}
}

func TestVerifySurvivesRestart(t *testing.T) {
	f := newFixture(t)
	f.issue(t, testTask)
	reopened, err := Open(f.store.dir, f.store.deps)
	if err != nil {
		t.Fatal(err)
	}
	v, err := reopened.Verify("hermes", testAgent, testSession, testTask)
	if err != nil || v == nil || v.Invalid {
		t.Fatalf("restart must not restore or lose validity: %+v %v", v, err)
	}
	// Grant revoked while "down": the reopened store still refuses.
	delete(f.grants, testGrantID)
	v, _ = reopened.Verify("hermes", testAgent, testSession, testTask)
	if v == nil || !v.Invalid {
		t.Fatalf("restart must not restore revoked authority: %+v", v)
	}
}

func TestIssueRejectsDuplicateActive(t *testing.T) {
	f := newFixture(t)
	f.issue(t, testTask)
	if _, err := f.store.Issue(IssueRequest{InstanceID: testInstance, SessionID: testSession, TaskID: testTask, InstallID: testInstall, TTL: time.Hour}); err == nil {
		t.Fatal("duplicate active context for the subject must be rejected")
	}
}

func TestIssueRejectsOverlappingSessionAndTaskContexts(t *testing.T) {
	t.Run("session_blocks_task", func(t *testing.T) {
		f := newFixture(t)
		f.issue(t, "")
		if _, err := f.store.Issue(IssueRequest{
			InstanceID: testInstance, SessionID: testSession, TaskID: testTask,
			InstallID: testInstall, TTL: time.Hour,
		}); err == nil {
			t.Fatal("active session context must block a task context in the same session")
		}
	})
	t.Run("task_blocks_session", func(t *testing.T) {
		f := newFixture(t)
		f.issue(t, testTask)
		if _, err := f.store.Issue(IssueRequest{
			InstanceID: testInstance, SessionID: testSession,
			InstallID: testInstall, TTL: time.Hour,
		}); err == nil {
			t.Fatal("active task context must block a session context in the same session")
		}
	})
	t.Run("distinct_tasks_may_coexist", func(t *testing.T) {
		f := newFixture(t)
		f.issue(t, testTask)
		if _, err := f.store.Issue(IssueRequest{
			InstanceID: testInstance, SessionID: testSession, TaskID: "task-2",
			InstallID: testInstall, TTL: time.Hour,
		}); err != nil {
			t.Fatalf("distinct task contexts should coexist: %v", err)
		}
	})
}

func TestConcurrentIssueAndVerify(t *testing.T) {
	f := newFixture(t)
	var wg sync.WaitGroup
	issues := make([]error, 8)
	for i := range issues {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_, issues[i] = f.store.Issue(IssueRequest{InstanceID: testInstance, SessionID: testSession, TaskID: testTask, InstallID: testInstall, TTL: time.Hour})
		}(i)
	}
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, _ = f.store.Verify("hermes", testAgent, testSession, testTask)
		}()
	}
	wg.Wait()
	succeeded := 0
	for _, err := range issues {
		if err == nil {
			succeeded++
		}
	}
	if succeeded != 1 {
		t.Fatalf("exactly one issuance may win, got %d", succeeded)
	}
}

func TestConcurrentVerifyDuringRevoke(t *testing.T) {
	f := newFixture(t)
	c := f.issue(t, testTask)
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := f.store.Verify("hermes", testAgent, testSession, testTask); err != nil {
				t.Errorf("verify must not error: %v", err)
			}
		}()
	}
	wg.Add(1)
	go func() {
		defer wg.Done()
		_, _ = f.store.Revoke(c.ContextID)
	}()
	wg.Wait()
	v, _ := f.store.Verify("hermes", testAgent, testSession, testTask)
	if v == nil || !v.Invalid || v.ReasonCode != "skill_context_revoked" {
		t.Fatalf("post-revoke verify must be invalid: %+v", v)
	}
}

func TestTamperedContextFileRejected(t *testing.T) {
	f := newFixture(t)
	c := f.issue(t, testTask)
	raw, err := os.ReadFile(f.store.contextPath(c.ContextID))
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	doc["skill"].(map[string]any)["skill_id"] = "marketplace:skill:other@ffffffffffff"
	rewritten, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(f.store.contextPath(c.ContextID), rewritten, 0o600); err != nil {
		t.Fatal(err)
	}
	v, err := f.store.Verify("hermes", testAgent, testSession, testTask)
	if err == nil && v != nil && !v.Invalid {
		t.Fatalf("tampered context must not verify: %+v", v)
	}
}

func TestClaimMatching(t *testing.T) {
	f := newFixture(t)
	f.issue(t, testTask)
	v := f.store.VerifyForEngine("hermes", testAgent, testSession, testTask, (*receipt.SkillClaim)(nil))
	if v == nil || v.Invalid {
		t.Fatalf("nil claim must not downgrade a covered subject: %+v", v)
	}
	v = f.store.VerifyForEngine("hermes", testAgent, testSession, testTask, &receipt.SkillClaim{SkillID: testSkillID, Version: "1.2.0", ContentHash: testHash})
	if v == nil || v.Invalid || v.Grant == nil {
		t.Fatalf("matching claim: %+v", v)
	}
	v = f.store.VerifyForEngine("hermes", testAgent, testSession, testTask, &receipt.SkillClaim{SkillID: "marketplace:skill:other@ffffffffffff", ContentHash: testHash})
	if v == nil || !v.Invalid || v.ReasonCode != "skill_context_mismatch" {
		t.Fatalf("conflicting claim must invalidate: %+v", v)
	}
	v = f.store.VerifyForEngine("hermes", testAgent, "sess-2", testTask, (*receipt.SkillClaim)(nil))
	if v != nil {
		t.Fatalf("other session must not be covered: %+v", v)
	}
}

func TestContextValidateBounds(t *testing.T) {
	f := newFixture(t)
	c := f.issue(t, testTask)
	for name, mutate := range map[string]func(map[string]any){
		"bad_level": func(m map[string]any) { m["evidence_level"] = "host_attested" },
		"bad_digest": func(m map[string]any) {
			m["authority"].(map[string]any)["grant_digest"] = "zz" + strings.Repeat("0", 62)
		},
		"issuer_forged": func(m map[string]any) { m["issuer_id"] = "runtime" },
		"bad_skill":     func(m map[string]any) { m["skill"].(map[string]any)["skill_id"] = "bad id" },
	} {
		base := c.Unsigned()
		raw, err := json.Marshal(base)
		if err != nil {
			t.Fatal(err)
		}
		var isolated map[string]any
		if err := json.Unmarshal(raw, &isolated); err != nil {
			t.Fatal(err)
		}
		mutate(isolated)
		var c2 Context
		mutated, err := json.Marshal(isolated)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(mutated, &c2); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if err := c2.Validate(); err == nil {
			t.Fatalf("%s: must not validate", name)
		}
	}
}
