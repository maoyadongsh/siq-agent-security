package stateformat

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/acltest"
	"siq-agent-security/apps/agentshield/internal/privatefs"
)

func windowsProfileCostFixture(t testing.TB) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "state")
	if err := privatefs.MkdirAll(filepath.Join(dir, WindowsProfileDir)); err != nil {
		t.Fatal(err)
	}
	id, err := DirectoryID(dir)
	if err != nil {
		t.Fatal(err)
	}
	source := Marker{Schema: "state-format/v2", ProgramVersion: "cost-test", FormatVersion: 2, PublishedAt: "2026-09-18T00:00:00Z", MinReader: 2, MinWriter: 2, DirectoryID: id, InstanceID: strings.Repeat("a", 64)}
	target := source
	target.MinReader = 3
	target.MinWriter = 3
	sourceRaw, _ := json.Marshal(source)
	targetRaw, _ := json.Marshal(target)
	plan := EncodeWindowsProfilePlan(WindowsProfilePlan{Schema: WindowsProfilePlanSchema, Profile: WindowsResourceProfile, SourceMarker: string(sourceRaw), TargetMarker: string(targetRaw), MigrationHash: "absent"})
	prepared, _ := json.Marshal(map[string]string{"plan_sha256": Hash(plan)})
	done, _ := json.Marshal(WindowsProfileDone{Schema: "state-windows-profile-done/v1", Plan: Hash(plan), Marker: Hash(targetRaw)})
	instance, _ := json.Marshal(map[string]string{"schema_version": "local-client-instance/v1", "instance_id": source.InstanceID})
	for name, raw := range map[string][]byte{MarkerName: targetRaw, "local-instance.json": instance, filepath.Join(WindowsProfileDir, "plan.json"): plan, filepath.Join(WindowsProfileDir, "prepared.json"): prepared, filepath.Join(WindowsProfileDir, "done.json"): done} {
		f, err := privatefs.CreateNew(filepath.Join(dir, name))
		if err != nil {
			t.Fatal(err)
		}
		if _, err = f.Write(raw); err != nil {
			t.Fatal(err)
		}
		if err = f.Close(); err != nil {
			t.Fatal(err)
		}
	}
	if err := Check(dir, true, false); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestWindowsProfileCheckAlwaysReadsCurrentObjects(t *testing.T) {
	for _, name := range []string{"plan.json", "prepared.json", "done.json"} {
		t.Run(name, func(t *testing.T) {
			dir := windowsProfileCostFixture(t)
			path := filepath.Join(dir, WindowsProfileDir, name)
			restore := acltest.BroadenRead(t, dir, path)
			if err := Check(dir, true, false); err == nil {
				t.Fatal("stale successful ACL reused")
			}
			restore()
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte("{}"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := Check(dir, true, false); err == nil {
				t.Fatal("stale successful proof reused")
			}
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			if err := Check(dir, true, false); err != nil {
				t.Fatal("valid recovery unavailable", err)
			}
			if err := os.Link(path, path+"-alias"); err != nil {
				t.Fatal(err)
			}
			if err := Check(dir, true, false); err == nil {
				t.Fatal("hard-link substituted proof accepted")
			}
		})
	}
	dir := windowsProfileCostFixture(t)
	if err := privatefs.MkdirAll(filepath.Join(dir, "logs")); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(filepath.Join(dir, WindowsProfileDir, "plan.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, PlanName), raw, 0600); err != nil {
		t.Fatal(err)
	}
	if err := Check(dir, true, false); !errors.Is(err, ErrMigration) {
		t.Fatal("active N01 barrier skipped", err)
	}
}

func TestWindowsProfileCheckRejectsDifferentInitialMarker(t *testing.T) {
	dir := windowsProfileCostFixture(t)
	m, err := ReadMarker(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := checkWindowsProfile(dir, m); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"version", "instance", "directory", "missing"} {
		t.Run(field, func(t *testing.T) {
			initial := m
			switch field {
			case "version":
				initial.MinReader, initial.MinWriter = 2, 2
			case "instance":
				initial.InstanceID = strings.Repeat("b", 64)
			case "directory":
				initial.DirectoryID = strings.Repeat("b", 64)
			case "missing":
				initial = Marker{}
			}
			if err := checkWindowsProfile(dir, initial); !errors.Is(err, ErrCorrupt) {
				t.Fatal("different initial compatibility marker accepted", err)
			}
		})
	}
}

func TestWindowsProfileBindingKeepsPathRecoveryMessage(t *testing.T) {
	dir := windowsProfileCostFixture(t)
	for _, path := range []string{strings.ToUpper(dir), dir + "-moved"} {
		if path == dir+"-moved" {
			if err := os.Rename(dir, path); err != nil {
				t.Fatal(err)
			}
			defer os.Rename(path, dir)
		}
		err := Check(path, true, false)
		if path == strings.ToUpper(dir) {
			// EvalSymlinks may canonicalize the case on this volume. Preserve
			// the existing DirectoryID policy instead of inventing a new one.
			marker, readErr := ReadMarker(path)
			if readErr != nil {
				t.Fatal(readErr)
			}
			if ValidateBinding(path, marker) == nil {
				if err != nil {
					t.Fatal("canonical case alias was rejected", err)
				}
				continue
			}
		}
		if !errors.Is(err, ErrBinding) || errors.Is(err, ErrWindowsProfileMigration) {
			t.Fatal("directory spelling changed binding error category", err)
		}
		if got := RecoveryMessageFor(err); !strings.Contains(got, "初始化时的规范路径") {
			t.Fatal("directory spelling lost recovery guidance", got)
		}
	}
}

// Retain the pre-optimization checked-I/O sequence only as a local benchmark
// reference; it is never a production fallback or acceptance shortcut.
func referenceWindowsProfileCheck(dir string) error {
	if err := CheckParents(dir); err != nil {
		return err
	}
	if err := checkMigration(dir); err != nil {
		return err
	}
	m, err := ReadMarker(dir)
	if err != nil {
		return err
	}
	if err := ValidateBinding(dir, m); err != nil {
		return err
	}
	raw, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "plan.json"), WindowsProfileBudget)
	if err != nil {
		return err
	}
	p, err := DecodeWindowsProfilePlan(raw)
	if err != nil {
		return err
	}
	target, _ := Decode([]byte(p.TargetMarker))
	if err := ValidateBinding(dir, target); err != nil {
		return err
	}
	history, err := WindowsProfileHistory(dir, []byte(p.SourceMarker))
	if err != nil || history != p.MigrationHash {
		return ErrCorrupt
	}
	if err := privatefs.CheckDir(dir); err != nil {
		return err
	}
	archive, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "plan.json"), WindowsProfileBudget)
	if err != nil || !bytes.Equal(archive, raw) {
		return ErrMigration
	}
	prepared, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "prepared.json"), Budget)
	var proof struct {
		Plan string `json:"plan_sha256"`
	}
	if err != nil || DecodeObject(prepared, []string{"plan_sha256"}, &proof) != nil || proof.Plan != Hash(raw) {
		return ErrMigration
	}
	done, err := readWindowsProfileMetadata(filepath.Join(dir, WindowsProfileDir, "done.json"), Budget)
	var finished WindowsProfileDone
	if err != nil || DecodeObject(done, []string{"schema", "plan_sha256", "marker_sha256"}, &finished) != nil || finished.Schema != "state-windows-profile-done/v1" || finished.Plan != Hash(raw) || finished.Marker != Hash([]byte(p.TargetMarker)) {
		return ErrCorrupt
	}
	live, err := readWindowsProfileMetadata(filepath.Join(dir, MarkerName), Budget)
	if err != nil || string(live) != p.TargetMarker {
		return ErrCorrupt
	}
	return nil
}

func BenchmarkWindowsProfileMetadataCheck(b *testing.B) {
	dir := windowsProfileCostFixture(b)
	for name, check := range map[string]func(string) error{"before": referenceWindowsProfileCheck, "after": func(dir string) error { return Check(dir, true, false) }} {
		b.Run(name, func(b *testing.B) {
			b.ResetTimer()
			for i := 0; i < b.N; i++ {
				if err := check(dir); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}
