package state

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"strings"
	"testing"
)

func migrationFixture(t *testing.T) *Store {
	t.Helper()
	s, w := initializationStore(t)
	if _, e := s.Initialize(w, 49123); e != nil {
		t.Fatal(e)
	}
	if e := w.Release(); e != nil {
		t.Fatal(e)
	}
	writeMarker(t, s.Dir, StateFormatMarker{Schema: StateFormatSchema, FormatVersion: 1})
	for _, p := range []string{"grants/revoked/0.json", "grants/revoked/1.json", "receipts/fixture/2026-09-13.jsonl", "backups/old/nested/record", "keys/signing.seed"} {
		if e := os.MkdirAll(filepath.Dir(filepath.Join(s.Dir, p)), 0700); e != nil {
			t.Fatal(e)
		}
		if e := os.WriteFile(filepath.Join(s.Dir, p), []byte("historical revoked/expired fixture: "+p), 0600); e != nil {
			t.Fatal(e)
		}
	}
	return s
}
func TestMigrationFullBackupAndEveryCheckpointRecovery(t *testing.T) {
	// First enumerate actual fault boundaries, including every copied entry.
	s := migrationFixture(t)
	var points []string
	if _, e := s.migrateState("n01-test", func(p string) error { points = append(points, p); return nil }); e != nil {
		t.Fatal(e)
	}
	for _, point := range points {
		t.Run(point, func(t *testing.T) {
			s := migrationFixture(t)
			before, _ := snapshotMigration(s.Dir)
			injected := errors.New("injected interruption")
			_, e := s.migrateState("n01-test", func(p string) error {
				if p == point {
					return injected
				}
				return nil
			})
			if !errors.Is(e, injected) {
				t.Fatal(e)
			}
			if point != "done" {
				paths := treeSnapshot(t, s.Dir)
				if _, e := Open(s.Dir); e == nil {
					t.Fatal("ordinary access during migration")
				}
				if !reflect.DeepEqual(paths, treeSnapshot(t, s.Dir)) {
					t.Fatal("blocked access wrote data")
				}
			}
			if _, e := s.MigrateState("n01-test"); e != nil {
				t.Fatal("resume", e)
			}
			if e := RequireStateCompatibility(s.Dir); e != nil {
				t.Fatal(e)
			}
			for _, entry := range before {
				if entry.Directory || entry.Path == stateformat.MarkerName {
					continue
				}
				b, e := os.ReadFile(filepath.Join(s.Dir, entry.Path))
				if e != nil || stateformat.Hash(b) != entry.SHA256 {
					t.Fatal("history changed", entry.Path)
				}
			}
			planRaw, e := os.ReadFile(filepath.Join(s.Dir, stateformat.MigrationDir, "plan.json"))
			if e != nil {
				t.Fatal(e)
			}
			var p MigrationPlan
			if json.Unmarshal(planRaw, &p) != nil {
				t.Fatal("plan")
			}
			backup, e := snapshotMigrationTree(filepath.Join(s.Dir, stateformat.MigrationDir, "backup"), false)
			if e != nil || !reflect.DeepEqual(backup, p.Entries) {
				t.Fatal("incomplete backup", e)
			}
			stable := treeSnapshot(t, s.Dir)
			result, e := s.MigrateState("n01-test")
			if e != nil || result.Status != "up_to_date" || !reflect.DeepEqual(stable, treeSnapshot(t, s.Dir)) {
				t.Fatal("repeat mutation", e)
			}
		})
	}
}
func TestMigrationRejectsDriftAndUntrustedPlan(t *testing.T) {
	for _, kind := range []string{"source", "backup", "extra-backup-lock", "plan-path", "plan-instance", "symlink-backup"} {
		t.Run(kind, func(t *testing.T) {
			s := migrationFixture(t)
			_, e := s.migrateState("test", func(p string) error {
				if p == "backup" {
					return errors.New("stop")
				}
				return nil
			})
			if e == nil {
				t.Fatal("no interruption")
			}
			switch kind {
			case "source":
				os.WriteFile(filepath.Join(s.Dir, "grants/revoked/1.json"), []byte("newer revocation"), 0600)
			case "backup":
				os.WriteFile(filepath.Join(s.Dir, stateformat.MigrationDir, "backup/grants/revoked/1.json"), []byte("corruption"), 0600)
			case "extra-backup-lock":
				os.WriteFile(filepath.Join(s.Dir, stateformat.MigrationDir, "backup/serve.lock"), []byte("extra"), 0600)
			case "symlink-backup":
				p := filepath.Join(s.Dir, stateformat.MigrationDir, "backup/grants/revoked/1.json")
				os.Remove(p)
				if e := os.Symlink(filepath.Join(s.Dir, "config.json"), p); e != nil {
					t.Skip(e)
				}
			default:
				p := filepath.Join(s.Dir, stateformat.PlanName)
				b, _ := os.ReadFile(p)
				var plan MigrationPlan
				json.Unmarshal(b, &plan)
				if kind == "plan-path" {
					plan.Entries[0].Path = "../escape"
				} else {
					plan.Target.InstanceID = strings.Repeat("a", 64)
				}
				os.WriteFile(p, migrationJSON(plan), 0600)
			}
			before := treeSnapshot(t, s.Dir)
			if _, e := s.MigrateState("test"); e == nil {
				t.Fatal("invalid recovery accepted")
			}
			after := treeSnapshot(t, s.Dir)
			// Acquiring and releasing owned locks is allowed; no business file changes.
			for p, b := range before {
				if !strings.HasSuffix(p, "serve.lock") && after[p] != b {
					t.Fatal("modified rejected recovery", p)
				}
			}
			m, e := stateformat.ReadMarker(s.Dir)
			if e != nil || m.FormatVersion != 1 {
				t.Fatal("advanced marker", e)
			}
		})
	}
}
func TestMigrationExclusiveAndUnsupportedSource(t *testing.T) {
	s := migrationFixture(t)
	w, e := AcquireWriter(s.Dir)
	if e != nil {
		t.Fatal(e)
	}
	before := treeSnapshot(t, s.Dir)
	if _, e := s.MigrateState("test"); !errors.Is(e, ErrWriterBusy) {
		t.Fatal(e)
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
		t.Fatal("busy migration wrote")
	}
	w.Release()
	for _, format := range []int{0, 999} {
		writeMarker(t, s.Dir, StateFormatMarker{Schema: StateFormatSchema, FormatVersion: format})
		before := treeSnapshot(t, s.Dir)
		if _, e := s.MigrateState("test"); e == nil {
			t.Fatal(fmt.Sprint(format))
		}
		if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
			t.Fatal("unsupported format mutated")
		}
	}
}
func TestBoundInitializationRejectsLostOrCopiedIdentity(t *testing.T) {
	s, w := initializationStore(t)
	if _, e := s.Initialize(w, 49123); e != nil {
		t.Fatal(e)
	}
	w.Release()
	m, e := stateformat.ReadMarker(s.Dir)
	if e != nil || m.Schema != "state-format/v2" {
		t.Fatal(m, e)
	}
	p := filepath.Join(s.Dir, "local-instance.json")
	original, _ := os.ReadFile(p)
	os.Remove(p)
	before := treeSnapshot(t, s.Dir)
	if _, e := AcquireWriter(s.Dir); e == nil {
		t.Fatal("lost identity silently replaced")
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, s.Dir)) {
		t.Fatal("identity reset")
	}
	os.WriteFile(p, original, 0600)
	other := t.TempDir()
	for _, n := range []string{"local-instance.json", stateformat.MarkerName} {
		b, _ := os.ReadFile(filepath.Join(s.Dir, n))
		os.WriteFile(filepath.Join(other, n), b, 0600)
	}
	if e := stateformat.Check(other, true, false); !errors.Is(e, stateformat.ErrCorrupt) {
		t.Fatal("copied marker accepted", e)
	}
	m.MinWriter = 3
	os.WriteFile(filepath.Join(s.Dir, stateformat.MarkerName), migrationJSON(m), 0600)
	if e := stateformat.Check(s.Dir, false, false); e != nil {
		t.Fatal("compatible reader rejected", e)
	}
	if e := stateformat.Check(s.Dir, true, false); !errors.Is(e, stateformat.ErrFuture) {
		t.Fatal("future writer accepted", e)
	}
}

func TestUnmarkedMigrationPreservesPrivateReadonlyTree(t *testing.T) {
	s := migrationFixture(t)
	os.Remove(filepath.Join(s.Dir, stateformat.MarkerName))
	p := filepath.Join(s.Dir, "backups/old/nested")
	t.Cleanup(func() {
		_ = os.Chmod(p, 0700)
		_ = os.Chmod(filepath.Join(s.Dir, stateformat.MigrationDir, "backup/backups/old/nested"), 0700)
	})
	if e := os.Chmod(p, 0500); e != nil {
		t.Fatal(e)
	}
	original, err := os.Stat(p)
	if err != nil {
		t.Fatal(err)
	}
	// A pre-publication crash can leave an unpublished scratch file. It is retained.
	scratch := filepath.Join(s.Dir, stateformat.MigrationDir, "tmp")
	os.MkdirAll(scratch, 0700)
	os.WriteFile(filepath.Join(scratch, ".migration-orphan"), []byte("partial scratch"), 0600)
	if _, e := s.MigrateState("test"); e != nil {
		t.Fatal(e)
	}
	info, e := os.Stat(p)
	if e != nil || info.Mode() != original.Mode() {
		t.Fatal("source directory permissions changed", e)
	}
	if _, e := os.Stat(filepath.Join(scratch, ".migration-orphan")); e != nil {
		t.Fatal("unknown scratch deleted")
	}
}
func TestMigrationPlanContractFixture(t *testing.T) {
	raw, e := os.ReadFile("../../testdata/contracts/local-state-migration-plan.json")
	if e != nil {
		t.Fatal(e)
	}
	var p MigrationPlan
	if e = json.Unmarshal(raw, &p); e != nil {
		t.Fatal(e)
	}
	var want, got any
	json.Unmarshal(raw, &want)
	json.Unmarshal(migrationJSON(p), &got)
	if !reflect.DeepEqual(want, got) {
		t.Fatal("plan fixture drift")
	}
}

func TestMigrationRecoversMissingMarkerOnlyAfterPreparedBackup(t *testing.T) {
	for _, point := range []string{"plan", "before-marker"} {
		t.Run(point, func(t *testing.T) {
			s := migrationFixture(t)
			_, e := s.migrateState("test", func(p string) error {
				if p == point {
					return errors.New("interrupted")
				}
				return nil
			})
			if e == nil {
				t.Fatal("no interruption")
			}
			os.Remove(filepath.Join(s.Dir, stateformat.MarkerName))
			_, e = s.MigrateState("test")
			if point == "plan" && e == nil {
				t.Fatal("unbacked missing marker accepted")
			}
			if point == "before-marker" && e != nil {
				t.Fatal("prepared target not recovered", e)
			}
		})
	}
}

func TestInitializeHistoricalStateDoesNotSkipMigration(t *testing.T) {
	for _, name := range []string{"keys/signing.seed", "grants/legacy.json"} {
		t.Run(name, func(t *testing.T) {
			s, w := initializationStore(t)
			path := filepath.Join(s.Dir, name)
			history := []byte("pre-client historical bytes")
			if e := os.WriteFile(path, history, 0600); e != nil {
				t.Fatal(e)
			}
			if _, e := s.Initialize(w, 49123); e != nil {
				t.Fatal(e)
			}
			w.Release()
			marker, e := stateformat.ReadMarker(s.Dir)
			if e != nil || marker.Schema != "state-format/v1" || marker.FormatVersion != 1 {
				t.Fatal("history silently migrated", marker, e)
			}
			if _, e = s.MigrateState("test"); e != nil {
				t.Fatal(e)
			}
			b, e := os.ReadFile(filepath.Join(s.Dir, stateformat.MigrationDir, "backup", name))
			if e != nil || string(b) != string(history) {
				t.Fatal("history not backed up")
			}
		})
	}
}
