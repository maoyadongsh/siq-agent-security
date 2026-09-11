package skillinstall

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func readyInstall(t *testing.T) (fixture, *Plan, ApplyRequest) {
	t.Helper()
	f := setup(t)
	p, _, err := f.store.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	return f, p, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true}
}
func TestInstallationApplyReadbackRetryAndNoAuthorityActivation(t *testing.T) {
	f, p, request := readyInstall(t)
	s := f.store
	result, err := s.Apply(nil, request)
	if err != nil || result.Status != "installed_unverified" || result.RuntimeVerified {
		t.Fatal(result, err)
	}
	target := filepath.Join(f.root, "skills", p.DirectoryName)
	expected, err := os.ReadFile(filepath.Join(f.source, "SKILL.md"))
	if err != nil {
		t.Fatal(err)
	}
	actual, err := os.ReadFile(filepath.Join(target, "SKILL.md"))
	if err != nil || string(actual) != string(expected) {
		t.Fatal("wrong installed content", err)
	}
	imported, _ := os.Stat(filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"))
	installed, _ := os.Stat(filepath.Join(target, "SKILL.md"))
	if os.SameFile(imported, installed) {
		t.Fatal("installation hardlinked immutable original")
	}
	later, _ := time.Parse(time.RFC3339Nano, p.ExpiresAt)
	s.now = func() time.Time { return later.Add(time.Hour) }
	retry, err := s.Apply(nil, request)
	if err != nil || retry.Signature != result.Signature {
		t.Fatal("retry renewed/reinstalled", err)
	}
	g, rev, err := s.authority.GetGrantWithSeq(p.GrantID)
	if err != nil || rev != p.GrantRevision || g.Status != "approved" {
		t.Fatal("installation activated grant", err)
	}
	if _, err := s.Recover(nil, result.InstallID, "human"); !errors.Is(err, ErrConflict) {
		t.Fatal("successful installation rolled back", err)
	}
	write(t, filepath.Join(target, "SKILL.md"), "user changed installed content")
	if _, err := s.ReadOperation(nil, result.InstallID); err == nil {
		t.Fatal("changed target accepted")
	}
	raw, _ := os.ReadFile(filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"))
	if string(raw) != string(expected) {
		t.Fatal("runtime change modified original import")
	}
}
func TestInstallationFailureRollbackAndUnknownOwnership(t *testing.T) {
	for _, mode := range []string{"revoke", "cancel", "case-alias", "foreign-file", "modified-file", "missing-owner", "spool-tamper", "before-result"} {
		t.Run(mode, func(t *testing.T) {
			f, p, request := readyInstall(t)
			s := f.store
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			target := filepath.Join(f.root, "skills", p.DirectoryName)
			s.boundary = func(phase string) error {
				if phase == "spooled" {
					if mode == "case-alias" {
						write(t, filepath.Join(f.root, "skills", strings.ToUpper(p.DirectoryName), "user.txt"), "keep")
					}
					if mode == "spool-tamper" {
						write(t, filepath.Join(f.root, ".siq-agent-security-installs", installID(p.PlanID), "f-0000"), "changed spool")
					}
				}
				if phase == "directory_created:" && mode == "missing-owner" {
					write(t, filepath.Join(target, "user.txt"), "user data before ownership")
					return errors.New("crash window")
				}
				if strings.HasPrefix(phase, "file_published:") {
					switch mode {
					case "revoke":
						f.revoke(t)
						return errors.New("interrupted after revoke")
					case "cancel":
						cancel()
					case "foreign-file":
						write(t, filepath.Join(target, "user.txt"), "keep")
						return errors.New("interrupted")
					case "modified-file":
						write(t, filepath.Join(target, strings.TrimPrefix(phase, "file_published:")), "user changed")
						return errors.New("interrupted")
					}
				}
				if phase == "before_result" && mode == "before-result" {
					return errors.New("interrupted")
				}
				return nil
			}
			result, err := s.Apply(ctx, request)
			if err == nil || result == nil {
				t.Fatal("failure accepted or unrecorded", result, err)
			}
			conflict := mode == "foreign-file" || mode == "modified-file" || mode == "missing-owner"
			if conflict {
				if result.Status != "recovery_required" {
					t.Fatal("unknown/modified contents removed", result)
				}
				if _, err := os.Stat(target); err != nil {
					t.Fatal("target removed", err)
				}
				if _, err := s.Recover(nil, result.InstallID, "recovery-human"); !errors.Is(err, ErrRecoveryRequired) {
					t.Fatal("unsafe recovery", err)
				}
			} else {
				if result.Status != "rolled_back" {
					t.Fatal("rollback failed", result, err)
				}
				if _, err := os.Stat(target); !os.IsNotExist(err) {
					t.Fatal("owned target retained", err)
				}
			}
			if mode == "foreign-file" {
				raw, _ := os.ReadFile(filepath.Join(target, "user.txt"))
				if string(raw) != "keep" {
					t.Fatal("user data removed")
				}
			}
			if mode == "case-alias" {
				raw, _ := os.ReadFile(filepath.Join(f.root, "skills", strings.ToUpper(p.DirectoryName), "user.txt"))
				if string(raw) != "keep" {
					t.Fatal("case alias overwritten")
				}
			}
		})
	}
}
func TestInstallationRecoveryReloadWithoutCurrentSourceOrAuthority(t *testing.T) {
	f, p, request := readyInstall(t)
	s := f.store
	target := filepath.Join(f.root, "skills", p.DirectoryName)
	s.boundary = func(phase string) error {
		if strings.HasPrefix(phase, "file_published:") {
			write(t, filepath.Join(target, "user.txt"), "user data")
			return errors.New("interrupted")
		}
		return nil
	}
	result, err := s.Apply(nil, request)
	if err == nil || result == nil || result.Status != "recovery_required" {
		t.Fatal(result, err)
	}
	// Simulate the user resolving the known conflict; the installer never removes it.
	if err := os.Remove(filepath.Join(target, "user.txt")); err != nil {
		t.Fatal(err)
	}
	f.revoke(t)
	write(t, filepath.Join(s.authority.Dir, "skill-imports", "blobs", f.importID, "payload", "SKILL.md"), "damaged original")
	reloaded, err := Open(s.authority, s.key, s.imports, s.resolve)
	if err != nil {
		t.Fatal(err)
	}
	reloaded.now = func() time.Time { return time.Now().Add(24 * time.Hour) }
	restored, err := reloaded.Recover(nil, result.InstallID, "recovery-human")
	if err != nil || restored.Status != "rolled_back" {
		t.Fatal(restored, err)
	}
	if _, err := os.Stat(target); !os.IsNotExist(err) {
		t.Fatal("target retained", err)
	}
	original, _, err := readBounded(context.Background(), s.operationPath(result.InstallID, "result"), 4<<20)
	if err != nil || !strings.Contains(string(original), "recovery_required") {
		t.Fatal("rewrote initial failure", err)
	}
	again, err := reloaded.Recover(nil, result.InstallID, "recovery-human")
	if err != nil || again.Signature != restored.Signature {
		t.Fatal("recovery not idempotent", err)
	}
}
func TestInstallationRequiresExactConfirmationAndPlan(t *testing.T) {
	f, _, request := readyInstall(t)
	for _, mode := range []string{"confirm", "signature", "actor", "expired"} {
		bad := request
		switch mode {
		case "confirm":
			bad.ConfirmInstall = false
		case "signature":
			bad.PlanSignature = strings.Repeat("0", 128)
		case "actor":
			bad.ActorID = "someone-else"
		case "expired":
			f.store.now = func() time.Time { return time.Now().Add(time.Hour) }
		}
		if _, err := f.store.Apply(nil, bad); err == nil {
			t.Fatal("invalid confirmation accepted", mode)
		}
	}
	if _, err := os.Stat(filepath.Join(f.root, "skills")); !os.IsNotExist(err) {
		t.Fatal("invalid confirmation wrote target")
	}
}

func TestInstallationNestedFilesAndEntrypointOrder(t *testing.T) {
	f := setupFiles(t, map[string]string{"references/report.txt": "synthetic report", "nested/SKILL.md": "Nested documentation.", "scripts/check.sh": "#!/bin/sh\nexit 93\n"})
	p, _, err := f.store.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	var order []string
	f.store.boundary = func(phase string) error {
		if strings.HasPrefix(phase, "file_published:") {
			order = append(order, strings.TrimPrefix(phase, "file_published:"))
		}
		return nil
	}
	result, err := f.store.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true})
	if err != nil {
		t.Fatal(err)
	}
	if len(order) != 5 || order[len(order)-1] != "SKILL.md" || order[len(order)-2] != "nested/SKILL.md" {
		t.Fatal("entrypoint publication order", order)
	}
	if _, err := f.store.ReadOperation(nil, result.InstallID); err != nil {
		t.Fatal("nested readback", err)
	}
	for _, path := range []string{"references/report.txt", "nested/SKILL.md", "scripts/check.sh"} {
		expected, _ := os.ReadFile(filepath.Join(f.source, filepath.FromSlash(path)))
		actual, err := os.ReadFile(filepath.Join(f.root, "skills", p.DirectoryName, filepath.FromSlash(path)))
		if err != nil || string(actual) != string(expected) {
			t.Fatal("nested content", path, err)
		}
	}
}
func TestInstallationReservedMetadataNameRejectedBeforeProfileWrite(t *testing.T) {
	f := setupFiles(t, map[string]string{"references/.siq-install-owner": "user payload"})
	p, _, err := f.store.Stage(nil, f.request)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.store.Apply(nil, ApplyRequest{"local-skill-install-apply/v1", p.PlanID, p.Signature, p.ActorID, true}); err == nil {
		t.Fatal("reserved payload accepted")
	}
	if _, err := os.Stat(filepath.Join(f.root, ".siq-agent-security-installs")); !os.IsNotExist(err) {
		t.Fatal("invalid payload wrote profile")
	}
}
func TestInstallationOperationCapacityBoundary(t *testing.T) {
	f, _, request := readyInstall(t)
	for i := 0; i < 63; i++ {
		write(t, f.store.operationPath(fmt.Sprintf("reserved-%d", i), "claim"), "reserved")
	}
	if _, err := f.store.Apply(nil, request); err != nil {
		t.Fatal("64th operation refused", err)
	}
	if err := f.store.operationCapacity(); !errors.Is(err, ErrLimit) {
		t.Fatal("65th operation allowed", err)
	}
	if _, err := f.store.Apply(nil, request); err != nil {
		t.Fatal("existing operation retry refused at capacity", err)
	}
}

func TestInstallationMarkerFailureCleansOnlyCurrentEmptyDirectory(t *testing.T) {
	f, _, request := readyInstall(t)
	f.store.boundary = func(phase string) error {
		if phase == "directory_created:" {
			return errors.New("marker unavailable")
		}
		return nil
	}
	result, err := f.store.Apply(nil, request)
	if err == nil || result == nil || result.Status != "rolled_back" {
		t.Fatal("live owned empty directory not cleaned", result, err)
	}
	if _, err := os.Stat(filepath.Join(f.root, "skills", "example")); !os.IsNotExist(err) {
		t.Fatal("empty directory retained", err)
	}
}
