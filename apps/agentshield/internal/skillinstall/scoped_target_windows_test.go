package skillinstall

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

type workBuddyInstallFixture struct {
	fixture
	scope, scopeRoot string
	instance         Target
}

func workBuddyInstallSetup(t *testing.T, scope string, existingParents bool) workBuddyInstallFixture {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	_, initErr := st.Initialize(w, 47611)
	releaseErr := w.Release()
	if initErr != nil || releaseErr != nil {
		t.Fatal(initErr, releaseErr)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.Token(); err != nil {
		t.Fatal(err)
	}
	if _, err := st.ActivateWindowsProfile(true, "workbuddy-skill-component"); err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	imports, err := skillimport.Open(st.Dir, key, pack, "workbuddy-skill-component")
	if err != nil {
		t.Fatal(err)
	}
	config := t.TempDir()
	f := workBuddyInstallFixture{scope: scope, scopeRoot: config,
		instance: Target{InstanceID: hermeshome.Identifier(config), Platform: "workbuddy", Root: config, Display: "WorkBuddy fixture"}}
	if scope == "project" {
		f.scopeRoot = t.TempDir()
	}
	if existingParents {
		if err := os.MkdirAll(filepath.Join(f.scopeRoot, filepath.FromSlash(scopeSkills(scope))), 0700); err != nil {
			t.Fatal(err)
		}
	}
	resolver := func(ctx context.Context, instance, id string) (ScopedTarget, error) {
		if instance != f.instance.InstanceID {
			return ScopedTarget{}, ErrChanged
		}
		v, err := InspectScopedTarget(ctx, f.instance, scope, f.scopeRoot, "WorkBuddy target")
		if err != nil || v.Reference.TargetID != id {
			return ScopedTarget{}, ErrChanged
		}
		return v, nil
	}
	s, err := OpenWithTargets(st, key, imports, func(context.Context, string) (Target, error) { return Target{}, ErrChanged }, resolver)
	if err != nil {
		t.Fatal(err)
	}
	f.fixture = fixture{store: s, root: config}
	g, revision, importID := f.importApproved(t, "a", "first version")
	id, err := ScopedTargetID(f.instance.InstanceID, scope, f.scopeRoot)
	if err != nil {
		t.Fatal(err)
	}
	f.importID = importID
	f.request = Request{SchemaVersion: "local-skill-install-stage-create/v2", RequestID: "is-" + strings.Repeat("d", 32),
		GrantID: g.GrantID, ExpectedRevision: revision, InstanceID: f.instance.InstanceID, DirectoryName: "example", ActorID: "human", TargetID: id}
	return f
}

func (f workBuddyInstallFixture) importApproved(t *testing.T, nonce, body string) (grant.Grant, int, string) {
	t.Helper()
	source := t.TempDir()
	write(t, filepath.Join(source, "SKILL.md"), "---\nname: example\ndescription: Read a synthetic report.\nallowed-tools: read_file\n---\n"+body+"\n")
	write(t, filepath.Join(source, "reference.txt"), "synthetic reference\n")
	id := "si-" + strings.Repeat(nonce, 32)
	s := f.store
	if _, _, _, err := s.imports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: source, ActorID: "human"}); err != nil {
		t.Fatal(err)
	}
	_, derived, err := s.imports.PermissionAdmission(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.authority.PutImportAdmission(derived); err != nil {
		t.Fatal(err)
	}
	built, err := grant.BuildImported(derived.Admission, grant.Options{Key: s.key, Platform: "workbuddy", Subject: grant.Subject{Type: "agent_instance", ID: subjectForInstance(f.instance.InstanceID)}}, "human", "ip-"+strings.Repeat(nonce, 32))
	if err != nil {
		t.Fatal(err)
	}
	g, policy, err := grant.PrepareWindowsResources(built.Grant, grant.ResourceEdit{Tools: []string{"read_file"}, Network: []grant.NetworkPatch{}, Models: []string{},
		Filesystem: grant.FilesystemPatch{ReadOnly: []string{filepath.ToSlash(f.scopeRoot)}, ReadWrite: []string{}}}, true, s.key)
	if err != nil {
		t.Fatal("official Windows imported Skill preparation", err)
	}
	g, err = grant.Approve(g, grant.Approval{ActorType: "human", ActorID: "human", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, s.key)
	if err != nil {
		t.Fatal(err)
	}
	revision, err := s.authority.CommitGrant(state.GrantCommit{Grant: g, ExpectedRevision: -1, DesiredPolicy: policy, Audit: &state.AuditEvent{Event: "workbuddy_component_approve", Target: g.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	return g, revision, id
}

func (f workBuddyInstallFixture) install(t *testing.T) (*Plan, *Operation) {
	t.Helper()
	p, _, err := f.store.Stage(nil, f.request)
	if err != nil {
		t.Fatal("stage", err)
	}
	if p.SchemaVersion != planV2 || p.TargetRef.Scope != f.scope || p.RuntimeVerified || p.Installed {
		t.Fatal("wrong scoped preview")
	}
	op, err := f.store.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true})
	if err != nil || op == nil || op.Status != "installed_unverified" {
		t.Fatal("apply", op, err)
	}
	return p, op
}

func TestWorkBuddyV2InstallUpdateRemoveBothScopes(t *testing.T) {
	for _, scope := range []string{"user", "project"} {
		t.Run(scope, func(t *testing.T) {
			f := workBuddyInstallSetup(t, scope, false)
			s := f.store
			p, op := f.install(t)
			inspection, err := s.Inspect(nil, op.InstallID)
			if err != nil || inspection.TargetState != "matched" || inspection.SchemaVersion != "local-skill-install-inspection/v2" {
				t.Fatal("inspection", err)
			}
			active, err := s.Activate(nil, op.InstallID, ActivateRequest{"local-skill-install-activate/v1", op.Signature, p.GrantRevision, "human", true})
			if err != nil || active.RuntimeVerified {
				t.Fatal("activation", err)
			}
			ready, err := s.ReadReadiness(nil, op.InstallID)
			if err != nil || ready.SchemaVersion != "local-skill-install-runtime-readiness/v2" || ready.Status != "prepared" || s.ValidateRuntimeGrant(context.Background(), ready.Grant) != nil {
				t.Fatal("runtime binding", err)
			}
			next, revision, _ := f.importApproved(t, "e", "second version")
			update, _, err := s.StageUpdate(nil, op.InstallID, UpdateStageRequest{"local-skill-update-stage-create/v1", "up-" + strings.Repeat("e", 32), op.Signature, next.GrantID, revision, ready.StateRevision, ready.Binding.Signature, "human"})
			if err != nil {
				t.Fatal("update stage", err)
			}
			result, err := s.CommitUpdate(nil, UpdateCommitRequest{"local-skill-update-commit/v1", update.UpdateID, update.Signature, "human", true})
			if err != nil || result.Status != "updated_unverified" || result.SchemaVersion != "local-skill-update-view/v2" {
				t.Fatal("update commit", err)
			}
			ref := result.Claim.ReplacementPlan.TargetRef
			if ref.TargetID != p.TargetRef.TargetID || ref.ExistingParentRelativePath != scopeSkills(scope) || !replacementAnchorValid(*p, result.Claim.ReplacementPlan) {
				t.Fatal("update moved target instead of advancing the verified anchor")
			}
			path := filepath.Join(f.scopeRoot, filepath.FromSlash(scopeSkills(scope)), "example", "SKILL.md")
			if raw, err := os.ReadFile(path); err != nil || !strings.Contains(string(raw), "second version") {
				t.Fatal("replacement payload", err)
			}
			id := result.Installation.InstallID
			removed, err := s.Remove(nil, id, removalRequest(t, s, id))
			if err != nil || removed.Status != "removed" || removed.SchemaVersion != "local-skill-install-removal-view/v2" {
				t.Fatal("remove", err)
			}
			if _, err := os.Lstat(filepath.Dir(path)); !os.IsNotExist(err) {
				t.Fatal("owned Skill remained", err)
			}
			if history, err := s.ReadUpdate(nil, update.UpdateID); err != nil || history.Result.Signature != result.Result.Signature {
				t.Fatal("signed update history became unavailable after removal", err)
			}
		})
	}
}

// Match the daemon's installed-content deadline, not an unbounded fixture call.
func TestWorkBuddyV2RuntimeGrantWithinServerBudget(t *testing.T) {
	for _, scope := range []string{"user", "project"} {
		t.Run(scope, func(t *testing.T) {
			f := workBuddyInstallSetup(t, scope, false)
			p, op := f.install(t)
			if _, err := f.store.Activate(nil, op.InstallID, ActivateRequest{"local-skill-install-activate/v1", op.Signature, p.GrantRevision, "human", true}); err != nil {
				t.Fatal(err)
			}
			ready, err := f.store.ReadReadiness(nil, op.InstallID)
			if err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			started := time.Now()
			err = f.store.ValidateRuntimeGrant(ctx, ready.Grant)
			t.Logf("installed-content validation: %s", time.Since(started))
			if err != nil {
				t.Fatalf("daemon runtime budget rejected installed Skill: %v", err)
			}
		})
	}
}

func TestWorkBuddyV2ExistingParentsAndUnrecordedCreation(t *testing.T) {
	t.Run("existing-preview-anchor", func(t *testing.T) {
		f := workBuddyInstallSetup(t, "project", true)
		p, op := f.install(t)
		if p.TargetRef.ExistingParentRelativePath != ".codebuddy/skills" {
			t.Fatal("existing ancestor was not pinned")
		}
		_, pool, err := f.store.destination(context.Background(), *p)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := os.Lstat(parentFactPath(pool, 1)); !os.IsNotExist(err) {
			t.Fatal("adopted existing parent as newly created", err)
		}
		if _, err := f.store.ReadView(nil, op.InstallID); err != nil {
			t.Fatal(err)
		}
	})
	t.Run("crash-before-parent-fact", func(t *testing.T) {
		f := workBuddyInstallSetup(t, "project", false)
		p, _, err := f.store.Stage(nil, f.request)
		if err != nil {
			t.Fatal(err)
		}
		f.store.boundary = func(point string) error {
			if point == "parent_created:.codebuddy" {
				return errors.New("synthetic interruption")
			}
			return nil
		}
		op, err := f.store.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, "human", true})
		if err == nil || op == nil || op.Status != "recovery_required" {
			t.Fatal("unrecorded parent guessed owned", op, err)
		}
		f.store.boundary = func(string) error { return nil }
		if _, err := f.store.Recover(nil, op.InstallID, "human"); err == nil {
			t.Fatal("restart recovery adopted unrecorded directory")
		}
		if _, err := os.Lstat(filepath.Join(f.scopeRoot, ".codebuddy")); err != nil {
			t.Fatal("unknown parent removed", err)
		}
	})
}

func TestWorkBuddyV2ParentReplacementAndMissingFactDeny(t *testing.T) {
	for _, change := range []string{"parent-replaced", "fact-missing"} {
		t.Run(change, func(t *testing.T) {
			f := workBuddyInstallSetup(t, "project", false)
			p, op := f.install(t)
			_, pool, err := f.store.destination(context.Background(), *p)
			if err != nil {
				t.Fatal(err)
			}
			if change == "fact-missing" {
				if err := os.Remove(parentFactPath(pool, 1)); err != nil {
					t.Fatal(err)
				}
			} else {
				path := filepath.Join(f.scopeRoot, ".codebuddy")
				if err := os.Rename(path, filepath.Join(f.scopeRoot, "preserved-original")); err != nil {
					t.Fatal(err)
				}
				if err := os.Mkdir(path, 0700); err != nil {
					t.Fatal(err)
				}
				write(t, filepath.Join(path, "sentinel.txt"), "untouched")
			}
			if _, err := f.store.ReadView(nil, op.InstallID); err == nil {
				t.Fatal("changed parent chain accepted")
			}
			if _, err := f.store.Activate(nil, op.InstallID, ActivateRequest{"local-skill-install-activate/v1", op.Signature, p.GrantRevision, "human", true}); err == nil {
				t.Fatal("changed installation activated")
			}
			if change == "parent-replaced" {
				if raw, err := os.ReadFile(filepath.Join(f.scopeRoot, ".codebuddy", "sentinel.txt")); err != nil || string(raw) != "untouched" {
					t.Fatal("replacement directory changed", err)
				}
			}
		})
	}
}

func TestWorkBuddyV2RecoveryUsesSignedParentFactsAfterReload(t *testing.T) {
	f := workBuddyInstallSetup(t, "project", false)
	s := f.store
	p, _, err := s.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(f.scopeRoot, ".codebuddy", "skills", p.DirectoryName)
	s.boundary = func(point string) error {
		if strings.HasPrefix(point, "file_published:") {
			write(t, filepath.Join(target, "user.txt"), "keep user content")
			return errors.New("synthetic interruption")
		}
		return nil
	}
	op, err := s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, "human", true})
	if err == nil || op == nil || op.Status != "recovery_required" {
		t.Fatal(op, err)
	}
	if raw, err := os.ReadFile(filepath.Join(target, "user.txt")); err != nil || string(raw) != "keep user content" {
		t.Fatal("unknown object was removed", err)
	}
	// Only the test's owner resolves its known conflict before explicit recovery.
	if err := os.Remove(filepath.Join(target, "user.txt")); err != nil {
		t.Fatal(err)
	}
	f.revoke(t)
	reloaded, err := OpenWithTargets(s.authority, s.key, s.imports, s.resolve, s.resolveV2)
	if err != nil {
		t.Fatal(err)
	}
	reloaded.now = func() time.Time { return time.Now().Add(24 * time.Hour) }
	result, err := reloaded.Recover(nil, op.InstallID, "human")
	if err != nil || result.Status != "rolled_back" {
		t.Fatal(result, err)
	}
	if _, err := os.Lstat(target); !os.IsNotExist(err) {
		t.Fatal("owned partial target remained", err)
	}
	again, err := reloaded.Recover(nil, op.InstallID, "human")
	if err != nil || again.Signature != result.Signature {
		t.Fatal("recovery repeated a mutation", err)
	}
	if _, _, err := reloaded.destination(context.Background(), *p); err != nil {
		t.Fatal("recovery lost parent facts", err)
	}
}

func replaceWorkBuddyTestRoot(t *testing.T, f workBuddyInstallFixture) {
	t.Helper()
	// Both names are siblings under this test's own TempDir container.
	preserved := f.scopeRoot + "-preserved"
	if filepath.Dir(preserved) != filepath.Dir(f.scopeRoot) {
		t.Fatal("fixture boundary")
	}
	if err := os.Rename(f.scopeRoot, preserved); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(f.scopeRoot, 0700); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{".codebuddy", ".siq-agent-security-installs"} {
		if _, err := os.Lstat(filepath.Join(preserved, name)); os.IsNotExist(err) {
			continue
		}
		if err := os.Rename(filepath.Join(preserved, name), filepath.Join(f.scopeRoot, name)); err != nil {
			t.Fatal(err)
		}
	}
	write(t, filepath.Join(f.scopeRoot, "new-root-sentinel.txt"), "untouched")
}

func TestWorkBuddyV2RechecksRootBeforeNextPublishOrDelete(t *testing.T) {
	for _, point := range []string{"directory_created:", "file_published:reference.txt", "removal_file_removed:SKILL.md", "removal_owner_removed:"} {
		t.Run(point, func(t *testing.T) {
			f := workBuddyInstallSetup(t, "project", false)
			s := f.store
			var p *Plan
			var op *Operation
			var err error
			removal := strings.HasPrefix(point, "removal_")
			if removal {
				p, op = f.install(t)
			} else {
				p, _, err = s.Stage(nil, f.request)
				if err != nil {
					t.Fatal(err)
				}
			}
			swapped := false
			s.boundary = func(at string) error {
				if at == point && !swapped {
					replaceWorkBuddyTestRoot(t, f)
					swapped = true
				}
				return nil
			}
			if removal {
				_, err = s.Remove(nil, op.InstallID, removalRequest(t, s, op.InstallID))
			} else {
				_, err = s.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, "human", true})
			}
			if !swapped || err == nil {
				t.Fatal("replaced root was accepted", swapped, err)
			}
			target := filepath.Join(f.scopeRoot, ".codebuddy", "skills", "example")
			switch point {
			case "directory_created:":
				if _, err := os.Lstat(filepath.Join(target, ownerName)); !os.IsNotExist(err) {
					t.Fatal("owner written into replaced root", err)
				}
			case "file_published:reference.txt":
				if _, err := os.Lstat(filepath.Join(target, "SKILL.md")); !os.IsNotExist(err) {
					t.Fatal("subsequent Skill publication into replaced root", err)
				}
			case "removal_file_removed:SKILL.md":
				if _, err := os.Lstat(filepath.Join(target, "reference.txt")); err != nil {
					t.Fatal("subsequent deletion from replaced root", err)
				}
			case "removal_owner_removed:":
				if _, err := os.Lstat(target); err != nil {
					t.Fatal("directory deleted from replaced root", err)
				}
			}
			if raw, err := os.ReadFile(filepath.Join(f.scopeRoot, "new-root-sentinel.txt")); err != nil || string(raw) != "untouched" {
				t.Fatal("unknown root sentinel changed", err)
			}
		})
	}
}
