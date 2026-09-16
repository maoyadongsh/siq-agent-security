package state

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func writeMarker(t *testing.T, dir string, m StateFormatMarker) {
	t.Helper()
	if m.ProgramVersion == "" {
		m.ProgramVersion = "test"
	}
	if m.PublishedAt == "" {
		m.PublishedAt = "2026-09-13T09:00:00Z"
	}
	raw, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(filepath.Join(dir, StateFormatMarkerName), raw, 0600); err != nil {
		t.Fatal(err)
	}
}
func treeSnapshot(t *testing.T, dir string) map[string]string {
	t.Helper()
	snapshot := map[string]string{}
	err := filepath.WalkDir(dir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := os.Lstat(path)
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(dir, path)
		value := info.Mode().String()
		if info.Mode().IsRegular() {
			raw, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			value += string(raw)
		}
		if info.Mode()&os.ModeSymlink != 0 {
			target, err := os.Readlink(path)
			if err != nil {
				return err
			}
			value += target
		}
		snapshot[rel] = value
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return snapshot
}
func TestCompatibilityStrictMarkerAndZeroWrites(t *testing.T) {
	good := `{"schema":"state-format/v1","program_version":"test","format_version":1,"published_at":"2026-09-13T09:00:00Z"}`
	cases := map[string]string{
		"future":       strings.Replace(good, `"format_version":1`, `"format_version":999`, 1),
		"explicit-old": strings.Replace(good, `"format_version":1`, `"format_version":0`, 1),
		"negative":     strings.Replace(good, `"format_version":1`, `"format_version":-1`, 1),
		"trailing":     good + ` {}`, "duplicate": strings.Replace(good, `"format_version":1`, `"format_version":999,"format_version":1`, 1),
		"missing": strings.Replace(good, `"format_version":1,`, "", 1), "null": strings.Replace(good, `"format_version":1`, `"format_version":null`, 1),
		"float": strings.Replace(good, `"format_version":1`, `"format_version":1.5`, 1), "unknown": strings.Replace(good, `"format_version":1`, `"x":1,"format_version":1`, 1),
		"case-alias": strings.Replace(good, `"format_version":1`, `"FORMAT_VERSION":1`, 1), "empty": "", "oversized": strings.Repeat(" ", StateFormatMarkerBudget+1),
		"case-alias-override": strings.Replace(good, `"format_version":1`, `"format_version":999,"FORMAT_VERSION":1`, 1),
		"bad-time":            strings.Replace(good, "2026-09-13T09:00:00Z", "bad", 1), "bad-utf8": strings.Replace(good, "test", string([]byte{0xff}), 1),
	}
	for name, raw := range cases {
		t.Run(name, func(t *testing.T) {
			dir := t.TempDir()
			if err := os.WriteFile(filepath.Join(dir, StateFormatMarkerName), []byte(raw), 0600); err != nil {
				t.Fatal(err)
			}
			before := treeSnapshot(t, dir)
			_, err := CheckStateCompatibility(dir)
			if !errors.Is(err, ErrIncompatibleState) {
				t.Fatalf("accepted: %v", err)
			}
			if _, err = Open(dir); !errors.Is(err, ErrIncompatibleState) {
				t.Fatalf("Open: %v", err)
			}
			if w, err := AcquireWriter(dir); err == nil {
				_ = w.Release()
				t.Fatal("writer accepted")
			}
			for _, scope := range []string{"service-control", "adapter-write", "client-releases", "client-snapshots"} {
				if w, err := AcquireScopedWriter(dir, scope); err == nil {
					_ = w.Release()
					t.Fatalf("%s writer accepted", scope)
				}
			}
			if !reflect.DeepEqual(before, treeSnapshot(t, dir)) {
				t.Fatal("rejection mutated content, mode or paths")
			}
		})
	}
	dir := t.TempDir()
	_ = os.WriteFile(filepath.Join(dir, StateFormatMarkerName), []byte(good+strings.Repeat(" ", StateFormatMarkerBudget-len(good))), 0600)
	if _, err := CheckStateCompatibility(dir); err != nil {
		t.Fatalf("exact budget: %v", err)
	}
}

func TestCompatibilityWriterRootIsNeverInferredFromBasename(t *testing.T) {
	parent := t.TempDir()
	dir := filepath.Join(parent, "service-control")
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	writeMarker(t, dir, StateFormatMarker{Schema: StateFormatSchema, FormatVersion: 999})
	before := treeSnapshot(t, parent)
	if w, err := AcquireWriter(dir); !errors.Is(err, ErrFutureState) {
		if w != nil {
			_ = w.Release()
		}
		t.Fatalf("state root was confused with a maintenance directory: %v", err)
	}
	for _, scope := range []string{"..", "../outside", "/tmp", "unknown", ""} {
		if w, err := AcquireScopedWriter(parent, scope); err == nil {
			_ = w.Release()
			t.Fatalf("unrecognized scope accepted: %q", scope)
		}
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, parent)) {
		t.Fatal("rejected writer modified state")
	}
}
func TestCompatibilityUnmarkedRecognition(t *testing.T) {
	t.Run("fresh", func(t *testing.T) {
		dir := filepath.Join(t.TempDir(), "new")
		got, err := CheckStateCompatibility(dir)
		if err != nil || got.Status != CompatStatusEmpty {
			t.Fatal(got, err)
		}
		if _, err = os.Stat(dir); !errors.Is(err, os.ErrNotExist) {
			t.Fatal("created path")
		}
	})
	t.Run("unknown", func(t *testing.T) {
		dir := t.TempDir()
		_ = os.WriteFile(filepath.Join(dir, "unrelated"), []byte("user data"), 0600)
		before := treeSnapshot(t, dir)
		if _, err := Open(dir); !errors.Is(err, ErrMissingMarker) {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(before, treeSnapshot(t, dir)) {
			t.Fatal("unknown directory changed")
		}
	})
	t.Run("scaffold", func(t *testing.T) {
		st, err := Open(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}
		before := treeSnapshot(t, st.Dir)
		w, err := AcquireWriter(st.Dir)
		if err != nil {
			t.Fatal(err)
		}
		if err = st.EnforceStateCompatibility(w, "test"); err != nil {
			t.Fatal(err)
		}
		if err = w.Release(); err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(before, treeSnapshot(t, st.Dir)) {
			t.Fatal("implicitly migrated legacy")
		}
	})
	t.Run("config", func(t *testing.T) {
		dir := t.TempDir()
		_ = os.WriteFile(filepath.Join(dir, "config.json"), []byte(`{"port":47611}`), 0600)
		got, err := CheckStateCompatibility(dir)
		if err != nil || got.Status != CompatStatusLegacy {
			t.Fatal(got, err)
		}
	})
	t.Run("unknown-migration", func(t *testing.T) {
		st, err := Open(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}
		_ = os.WriteFile(filepath.Join(st.Dir, "logs", "migration-plan.json"), []byte(`{"to_format":1,"committed":999}`), 0600)
		before := treeSnapshot(t, st.Dir)
		if _, err := Open(st.Dir); !errors.Is(err, ErrCorruptState) {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(before, treeSnapshot(t, st.Dir)) {
			t.Fatal("migration resumed")
		}
	})
}
func TestCompatibilityRejectsSymlinks(t *testing.T) {
	target := t.TempDir()
	link := filepath.Join(t.TempDir(), "alias")
	if err := os.Symlink(target, link); err != nil {
		t.Skip("symlink unavailable")
	}
	for _, path := range []string{link, filepath.Join(link, "new")} {
		if _, err := Open(path); !errors.Is(err, ErrCorruptState) {
			t.Fatalf("symlink accepted: %v", err)
		}
	}
	if _, err := os.Lstat(filepath.Join(link, "new")); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("rejected alias child created state")
	}
	dir := t.TempDir()
	outside := filepath.Join(target, "marker")
	_ = os.WriteFile(outside, []byte("do not read"), 0600)
	_ = os.Symlink(outside, filepath.Join(dir, StateFormatMarkerName))
	before := treeSnapshot(t, dir)
	if _, err := Open(dir); !errors.Is(err, ErrCorruptState) {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, dir)) {
		t.Fatal("symlink changed")
	}
}
func TestCompatibilityInitializeAndRepeatPreservesHistory(t *testing.T) {
	dir := t.TempDir()
	w, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	st, err := Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	got, err := CheckStateCompatibility(dir)
	if err != nil || got.Status != CompatStatusOK {
		t.Fatal(got, err)
	}
	_ = os.WriteFile(filepath.Join(dir, "grants", "revoked.0.json"), []byte(`{"status":"revoked"}`), 0600)
	before := treeSnapshot(t, dir)
	if _, err = st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, dir)) {
		t.Fatal("repeat init changed metadata/history")
	}
	writeMarker(t, dir, StateFormatMarker{Schema: StateFormatSchema, FormatVersion: 999})
	before = treeSnapshot(t, dir)
	if _, err = st.Initialize(w, 0); !errors.Is(err, ErrFutureState) {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, dir)) {
		t.Fatal("already-open store init wrote future state")
	}
}
func TestCompatibilityEnforceRequiresOwnedWriter(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err = st.EnforceStateCompatibility(nil, ""); !errors.Is(err, ErrWriterBusy) {
		t.Fatal(err)
	}
	w, err := AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if err = w.Release(); err != nil {
		t.Fatal(err)
	}
	if err = st.EnforceStateCompatibility(w, ""); !errors.Is(err, ErrWriterBusy) {
		t.Fatal(err)
	}
}

func TestCompatibilityGoSchemaFixture(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "contracts", "local-state-format.json"))
	if err != nil {
		t.Fatal(err)
	}
	marker, err := decodeStateMarker(raw)
	if err != nil {
		t.Fatal(err)
	}
	out, err := json.Marshal(marker)
	if err != nil {
		t.Fatal(err)
	}
	var expected, actual any
	if json.Unmarshal(raw, &expected) != nil || json.Unmarshal(out, &actual) != nil || !reflect.DeepEqual(expected, actual) {
		t.Fatal("schema sample not round-trippable")
	}
}
func TestCompatibilityExistingStoreRejectsWrites(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	writeMarker(t, st.Dir, StateFormatMarker{Schema: StateFormatSchema, FormatVersion: 999})
	before := treeSnapshot(t, st.Dir)
	calls := []func() error{
		func() error { return st.SaveConfig(Config{}) }, func() error { _, err := st.Token(); return err },
		func() error { return st.PutAdmission(nil) }, func() error { return st.PutEvidence("fixture", map[string]any{}) },
		func() error { return st.PutDesiredPolicy(nil) }, func() error { return st.AppendAudit(AuditEvent{}) },
		func() error { return st.PutVersioned("grants", "review", map[string]any{}) },
		func() error { _, err := st.PutVersionedCAS("grants", "review", -1, map[string]any{}); return err },
		func() error { _, err := st.CommitGrant(GrantCommit{}); return err },
		func() error { _, err := st.RecoverGrantCommits(w); return err },
	}
	for i, call := range calls {
		if err := call(); !errors.Is(err, ErrIncompatibleState) {
			t.Fatalf("write %d did not reject future format: %v", i, err)
		}
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, st.Dir)) {
		t.Fatal("held store mutated incompatible state")
	}
}

func TestCompatibilityCoreDirectorySymlinkNoPartialOpen(t *testing.T) {
	dir := t.TempDir()
	outside := t.TempDir()
	if err := os.Symlink(outside, filepath.Join(dir, "logs")); err != nil {
		t.Skip("symlink unavailable")
	}
	writeMarker(t, dir, StateFormatMarker{Schema: StateFormatSchema, FormatVersion: CurrentFormatVersion})
	before := treeSnapshot(t, dir)
	external := treeSnapshot(t, outside)
	if _, err := Open(dir); !errors.Is(err, ErrCorruptState) {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(before, treeSnapshot(t, dir)) || !reflect.DeepEqual(external, treeSnapshot(t, outside)) {
		t.Fatal("symlink created state outside root or partial scaffold")
	}
}
