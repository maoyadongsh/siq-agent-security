package skillcontext

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// This exercises SEC's version boundary with its trusted storage readers.
// Native target verification is exercised by the skillinstall Windows tests;
// this fixture does not claim that a host chose the installed Skill itself.
func workBuddyV2ContextFixture(t *testing.T, scope string) *fixture {
	t.Helper()
	f := newFixture(t)
	name, root := "local-skill-install-plan.v2.sample.json", "C:/SIQ-Contract-Fixture/Project"
	if scope == "user" {
		name, root = "local-skill-install-plan.v2.user.sample.json", "C:/SIQ-Contract-Fixture/WorkBuddy"
	}
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", name))
	if err != nil {
		t.Fatal(err)
	}
	var p skillinstall.Plan
	if err := json.Unmarshal(raw, &p); err != nil {
		t.Fatal(err)
	}
	p.InstanceID, p.GrantID = testInstance, testGrantID
	p.TargetRef.TargetID, err = skillinstall.ScopedTargetID(testInstance, scope, root)
	if err != nil {
		t.Fatal(err)
	}
	record := f.installs[testInstall]
	record.SchemaVersion, record.Plan = "local-skill-install-record/v2", p
	f.grants[testGrantID].Platform = "workbuddy"
	instance := f.instances[testInstance]
	instance.Platform = "workbuddy"
	f.instances[testInstance] = instance
	key := "workbuddy|" + testAgent + "|" + testSession
	f.bound[key], f.boundUntil[key] = testGrantID, f.now.Add(time.Hour)
	return f
}

func TestWorkBuddyV2InstallSupportsControlledSessionSEC(t *testing.T) {
	for _, scope := range []string{"user", "project"} {
		t.Run(scope, func(t *testing.T) {
			f := workBuddyV2ContextFixture(t, scope)
			c := f.issue(t, "")
			if c.SchemaVersion != Schema || c.EvidenceLevel != EvidenceSession || c.Subject.TaskID != "" || c.Install.ClaimSignature != testClaimSig {
				t.Fatal("installation scope changed controlled-session evidence")
			}
			v, err := f.store.Verify("workbuddy", testAgent, testSession, "")
			if err != nil || v == nil || v.Invalid || v.Grant == nil {
				t.Fatal(v, err)
			}
			f.installs[testInstall].ClaimSignature = strings.Repeat("b", 128)
			v, err = f.store.Verify("workbuddy", testAgent, testSession, "")
			if err != nil || v == nil || !v.Invalid || v.ReasonCode != "skill_context_install_changed" {
				t.Fatal("replacement claim reused prior SEC", v, err)
			}
		})
	}
}

func TestWorkBuddyV2InstallSECRejectsMixedOrMissingTarget(t *testing.T) {
	for _, change := range []string{"v1-record", "v1-plan", "missing-target", "changed-scope", "other-platform"} {
		t.Run(change, func(t *testing.T) {
			f := workBuddyV2ContextFixture(t, "project")
			r := f.installs[testInstall]
			switch change {
			case "v1-record":
				r.SchemaVersion = "local-skill-install-record/v1"
			case "v1-plan":
				r.Plan.SchemaVersion = "local-skill-install-plan/v1"
			case "missing-target":
				r.Plan.TargetRef = nil
			case "changed-scope":
				r.Plan.TargetRef.Scope = "user"
			case "other-platform":
				r.Plan.Platform = "hermes"
			}
			if _, err := f.store.Issue(IssueRequest{InstanceID: testInstance, SessionID: testSession, InstallID: testInstall, TTL: time.Hour}); err == nil {
				t.Fatal("invalid v2 record created execution authority")
			}
		})
	}
}
