package skillinstall

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/rulepack"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

type fixture struct {
	store                  *Store
	request                Request
	source, root, importID string
}

func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
}
func setup(t *testing.T) fixture { return setupFiles(t, nil) }
func setupFiles(t *testing.T, extra map[string]string) fixture {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	pack, err := rulepack.Builtin()
	if err != nil {
		t.Fatal(err)
	}
	imports, err := skillimport.Open(st.Dir, key, pack, "fixture")
	if err != nil {
		t.Fatal(err)
	}
	source, root := t.TempDir(), t.TempDir()
	write(t, filepath.Join(source, "SKILL.md"), "---\nname: example\ndescription: Read a synthetic report.\nallowed-tools: read_file\n---\nRead a synthetic report.\n")
	write(t, filepath.Join(source, "skill-manifest.json"), `{"fixture":"independent"}`)
	for relative, content := range extra {
		path := filepath.Join(source, filepath.FromSlash(relative))
		write(t, path, content)
		if strings.HasPrefix(relative, "scripts/") {
			if err := os.Chmod(path, 0700); err != nil {
				t.Fatal(err)
			}
		}
	}
	id := "si-" + strings.Repeat("a", 32)
	if _, _, _, err := imports.Create(nil, skillimport.CreateRequest{SchemaVersion: "local-skill-import-create/v1", ImportID: id, SourceKind: "local_dir", Path: source, ActorID: "human"}); err != nil {
		t.Fatal(err)
	}
	_, derived, err := imports.PermissionAdmission(nil, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := st.PutImportAdmission(derived); err != nil {
		t.Fatal(err)
	}
	instance := "hi-" + strings.Repeat("b", 32)
	built, err := grant.BuildImported(derived.Admission, grant.Options{Key: key, Platform: "hermes", Subject: grant.Subject{Type: "agent_instance", ID: "hri-" + strings.Repeat("b", 32)}}, "human", "ip-"+strings.Repeat("c", 32))
	if err != nil {
		t.Fatal(err)
	}
	approved, err := grant.Approve(built.Grant, grant.Approval{ActorType: "human", ActorID: "human", ApprovedAt: time.Now().UTC().Format(time.RFC3339Nano)}, key)
	if err != nil {
		t.Fatal(err)
	}
	rev, err := st.CommitGrant(state.GrantCommit{Grant: approved, ExpectedRevision: -1, DesiredPolicy: built.DesiredPolicy, Audit: &state.AuditEvent{Event: "fixture_approve", Target: approved.GrantID}})
	if err != nil {
		t.Fatal(err)
	}
	s, err := Open(st, key, imports, func(context.Context, string) (Target, error) {
		return Target{InstanceID: instance, Platform: "hermes", Root: root, Display: "Hermes work"}, nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return fixture{s, Request{"local-skill-install-stage-create/v1", "is-" + strings.Repeat("d", 32), approved.GrantID, rev, instance, "example", "human"}, source, root, id}
}
func (f fixture) revoke(t *testing.T) {
	t.Helper()
	g, rev, err := f.store.authority.GetGrantWithSeq(f.request.GrantID)
	if err != nil {
		t.Fatal(err)
	}
	changed, err := grant.Revoke(*g, f.store.key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.store.authority.CommitGrant(state.GrantCommit{Grant: changed, ExpectedRevision: rev, Audit: &state.AuditEvent{Event: "fixture_revoke", Target: g.GrantID}}); err != nil {
		t.Fatal(err)
	}
}
func TestStageIndependentCopyRetryAndExpiry(t *testing.T) {
	f := setup(t)
	s := f.store
	now := time.Now().UTC()
	s.now = func() time.Time { return now }
	p, reused, err := s.Stage(nil, f.request)
	if err != nil || reused {
		t.Fatal(reused, err)
	}
	if p.Installed || p.RuntimeVerified || p.FileCount != 2 {
		t.Fatal("staging claimed installation")
	}
	if _, err := os.Lstat(filepath.Join(f.root, "skills")); !os.IsNotExist(err) {
		t.Fatal("target modified", err)
	}
	original := filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md")
	staged := filepath.Join(s.stage(p.PlanID), "payload", "SKILL.md")
	a, err := os.Stat(original)
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.Stat(staged)
	if err != nil {
		t.Fatal(err)
	}
	if os.SameFile(a, b) {
		t.Fatal("staged file hardlinked to original")
	}
	write(t, filepath.Join(f.source, "SKILL.md"), "original source subsequently changed")
	now = now.Add(4 * time.Minute)
	again, reused, err := s.Stage(nil, f.request)
	if err != nil || !reused || again.Signature != p.Signature || again.ExpiresAt != p.ExpiresAt {
		t.Fatal("retry changed plan", err)
	}
	now = now.Add(time.Minute)
	if _, _, err := s.Stage(nil, f.request); !errors.Is(err, ErrExpired) {
		t.Fatal("expired plan refreshed", err)
	}
	f.request.RequestID = "is-" + strings.Repeat("e", 32)
	if _, _, err := s.Stage(nil, f.request); err != nil {
		t.Fatal("explicit fresh request", err)
	}
	g, _, _ := s.authority.GetGrantWithSeq(f.request.GrantID)
	if g.Status != "approved" {
		t.Fatal("stage activated grant")
	}
}
func TestStageAuthorityAndTargetFailures(t *testing.T) {
	for _, mode := range []string{"revision", "revoked", "pending", "expired", "instance", "name", "existing", "case-alias", "symlink", "copy-revocation", "copy-target", "copy-failure", "cancel"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t)
			s := f.store
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			switch mode {
			case "pending", "expired":
				g, revision, err := s.authority.GetGrantWithSeq(f.request.GrantID)
				if err != nil {
					t.Fatal(err)
				}
				if mode == "pending" {
					g.Status = "pending_approval"
					g.ApprovedBy = nil
				} else {
					deadline := time.Now().Add(-time.Minute).UTC().Format(time.RFC3339Nano)
					g.ExpiresAt = &deadline
				}
				doc, err := document(*g, false)
				if err != nil {
					t.Fatal(err)
				}
				g.Signature, err = s.key.SignCanonical(doc)
				if err != nil {
					t.Fatal(err)
				}
				f.request.ExpectedRevision, err = s.authority.CommitGrant(state.GrantCommit{Grant: *g, ExpectedRevision: revision, Audit: &state.AuditEvent{Event: "fixture_changed", Target: g.GrantID}})
				if err != nil {
					t.Fatal(err)
				}
			case "revision":
				f.request.ExpectedRevision++
			case "revoked":
				f.revoke(t)
			case "instance":
				f.request.InstanceID = "hi-" + strings.Repeat("e", 32)
			case "name":
				f.request.DirectoryName = "con"
			case "existing":
				write(t, filepath.Join(f.root, "skills", "example", "user.txt"), "preserve")
			case "case-alias":
				write(t, filepath.Join(f.root, "skills", "EXAMPLE", "user.txt"), "preserve")
			case "symlink":
				if err := os.Symlink(t.TempDir(), filepath.Join(f.root, "skills")); err != nil {
					t.Skip(err)
				}
			case "copy-revocation":
				s.boundary = func(string) error { f.revoke(t); return nil }
			case "copy-target":
				s.boundary = func(string) error {
					write(t, filepath.Join(f.root, "skills", "example", "user.txt"), "preserve")
					return nil
				}
			case "copy-failure":
				s.boundary = func(string) error { return errors.New("injected") }
			case "cancel":
				s.boundary = func(string) error { cancel(); return nil }
			}
			if _, _, err := s.Stage(ctx, f.request); err == nil {
				t.Fatal("unsafe stage accepted")
			}
			plans, _ := os.ReadDir(filepath.Join(s.dir, "plans"))
			stages, _ := os.ReadDir(filepath.Join(s.dir, "stages"))
			if len(plans) != 0 || len(stages) != 0 {
				t.Fatal("failed stage published or leaked owned payload")
			}
			if mode == "existing" || mode == "copy-target" {
				raw, err := os.ReadFile(filepath.Join(f.root, "skills", "example", "user.txt"))
				if err != nil || string(raw) != "preserve" {
					t.Fatal("user path changed")
				}
			}
		})
	}
}
func TestLoadRechecksAuthorityPayloadAndSignedPlan(t *testing.T) {
	for _, mode := range []string{"staged", "original", "plan", "duplicate", "unsigned-count", "signed-count", "revoke", "target", "target-root", "clock-rollback"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t)
			s := f.store
			p, _, err := s.Stage(nil, f.request)
			if err != nil {
				t.Fatal(err)
			}
			switch mode {
			case "staged":
				write(t, filepath.Join(s.stage(p.PlanID), "payload", "skill-manifest.json"), "changed")
			case "original":
				write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "skill-manifest.json"), "changed")
			case "plan":
				write(t, s.record(p.PlanID), "{}")
			case "duplicate":
				raw, _ := os.ReadFile(s.record(p.PlanID))
				write(t, s.record(p.PlanID), `{"installed":false,`+string(raw[1:]))
			case "unsigned-count", "signed-count":
				p.TotalBytes++
				doc, _ := document(*p, false)
				if mode == "signed-count" {
					p.Signature, _ = s.key.SignCanonical(doc)
				}
				doc, _ = document(*p, true)
				raw, _ := canon.Marshal(doc)
				write(t, s.record(p.PlanID), string(raw))
			case "revoke":
				f.revoke(t)
			case "target":
				write(t, filepath.Join(f.root, "skills", "example", "user.txt"), "preserve")
			case "target-root":
				newRoot := t.TempDir()
				s.resolve = func(context.Context, string) (Target, error) {
					return Target{f.request.InstanceID, "hermes", newRoot, "Hermes work"}, nil
				}
			case "clock-rollback":
				created, _ := time.Parse(time.RFC3339Nano, p.CreatedAt)
				s.now = func() time.Time { return created.Add(-time.Nanosecond) }
			}
			if _, err := s.Load(nil, p.PlanID); err == nil {
				t.Fatal("changed plan accepted")
			}
			if mode == "target-root" {
				if _, _, err := s.Stage(nil, f.request); !errors.Is(err, ErrConflict) {
					t.Fatal("same request silently retargeted", err)
				}
			}
		})
	}
}
func TestOrphanPreservedAndCapacityBounded(t *testing.T) {
	f := setup(t)
	s := f.store
	p, err := s.inspect(context.Background(), f.request)
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(s.stage(p.PlanID), "orphan"), "preserve")
	if _, _, err := s.Stage(nil, f.request); !errors.Is(err, ErrConflict) {
		t.Fatal(err)
	}
	if raw, err := os.ReadFile(filepath.Join(s.stage(p.PlanID), "orphan")); err != nil || string(raw) != "preserve" {
		t.Fatal("orphan adopted/deleted")
	}
	for i := 1; i < maxStages; i++ {
		if err := os.Mkdir(filepath.Join(s.dir, "stages", fmt.Sprintf("orphan-%d", i)), 0700); err != nil {
			t.Fatal(err)
		}
	}
	if _, _, err := s.Stage(nil, f.request); !errors.Is(err, ErrLimit) {
		t.Fatal("capacity ignored", err)
	}
}

func TestStageContractSamples(t *testing.T) {
	f := setup(t)
	p, _, err := f.store.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	// DTO fixtures normalize state-specific authority identity, analysis clock and
	// absolute target digest. Actual live binding is exercised in the tests above.
	p.Source.AnalysisSHA256 = strings.Repeat("2", 64)
	p.GrantID = "grt-si-" + strings.Repeat("3", 64)
	p.GrantSignature = strings.Repeat("4", 128)
	p.GrantPermissionDigest = strings.Repeat("5", 64)
	p.TargetLocatorDigest = strings.Repeat("6", 64)
	p.CreatedAt = "2026-09-11T03:00:00Z"
	p.ExpiresAt = "2026-09-11T03:05:00Z"
	p.PlanID, err = p.identity()
	if err != nil {
		t.Fatal(err)
	}
	doc, err := document(*p, false)
	if err != nil {
		t.Fatal(err)
	}
	p.Signature, err = f.store.key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	for name, value := range map[string]any{"local-skill-install-stage-create.v1": p.request(), "local-skill-install-plan.v1": p} {
		raw, err := json.MarshalIndent(value, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		raw = append(raw, '\n')
		path := "../../testdata/contracts/" + name + ".sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(raw, expected) {
			t.Fatal("contract sample differs", name, err)
		}
	}
}

func TestStageRequestBoundaryAndCopyConfinement(t *testing.T) {
	f := setup(t)
	for _, name := range []string{"a", strings.Repeat("a", 64), "com10", "my-skill"} {
		r := f.request
		r.DirectoryName = name
		if !validRequest(r) {
			t.Fatal("valid name refused", name)
		}
	}
	for _, name := range []string{"", strings.Repeat("a", 65), "../escape", "a/b", "a\\b", "CON", "con", "com1", "lpt9", "aux", "nul", "-a", "a-", "UPPER", "a.b"} {
		r := f.request
		r.DirectoryName = name
		if validRequest(r) {
			t.Fatal("invalid name accepted", name)
		}
	}
	target := t.TempDir()
	if _, err := f.store.imports.CopyForInstallation(nil, f.importID, target); !errors.Is(err, skillimport.ErrInvalid) {
		t.Fatal("copy escaped private staging", err)
	}
	if entries, _ := os.ReadDir(target); len(entries) != 0 {
		t.Fatal("external target modified")
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	stageSlot <- struct{}{}
	_, _, err := f.store.Stage(ctx, f.request)
	<-stageSlot
	if !errors.Is(err, context.Canceled) {
		t.Fatal("canceled request waited for slot", err)
	}
}

func TestStageCapacityLastSlotAndPublicationFailure(t *testing.T) {
	t.Run("last-slot", func(t *testing.T) {
		f := setup(t)
		for i := 0; i < maxStages-1; i++ {
			if err := os.Mkdir(filepath.Join(f.store.dir, "stages", fmt.Sprintf("orphan-%d", i)), 0700); err != nil {
				t.Fatal(err)
			}
		}
		if _, _, err := f.store.Stage(nil, f.request); err != nil {
			t.Fatal("last allowed slot refused", err)
		}
		f.request.RequestID = "is-" + strings.Repeat("e", 32)
		if _, _, err := f.store.Stage(nil, f.request); !errors.Is(err, ErrLimit) {
			t.Fatal("extra slot accepted", err)
		}
	})
	t.Run("publish-failure", func(t *testing.T) {
		f := setup(t)
		plans := filepath.Join(f.store.dir, "plans")
		f.store.boundary = func(string) error {
			if err := os.Remove(plans); err != nil {
				return err
			}
			return os.WriteFile(plans, []byte("unavailable"), 0600)
		}
		if _, _, err := f.store.Stage(nil, f.request); err == nil {
			t.Fatal("unpublished stage accepted")
		}
		entries, err := os.ReadDir(filepath.Join(f.store.dir, "stages"))
		if err != nil || len(entries) != 0 {
			t.Fatal("failed publication retained owned stage", err)
		}
	})
}
