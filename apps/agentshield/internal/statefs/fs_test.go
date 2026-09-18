package statefs_test

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/pending"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"testing"
)

func snapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	r := map[string]string{}
	e := filepath.WalkDir(root, func(p string, d os.DirEntry, e error) error {
		if e != nil {
			return e
		}
		i, e := os.Lstat(p)
		if e != nil {
			return e
		}
		v := i.Mode().String()
		if i.Mode().IsRegular() {
			b, e := os.ReadFile(p)
			if e != nil {
				return e
			}
			v += string(b)
		}
		r[p] = v
		return nil
	})
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func TestIndependentWritersAndReadersRejectChangedFormat(t *testing.T) {
	dir := t.TempDir()
	st, e := state.Open(dir)
	if e != nil {
		t.Fatal(e)
	}
	key, e := signing.Load(dir)
	if e != nil {
		t.Fatal(e)
	}
	chain, e := receipt.OpenChain(dir, "fixture", key)
	if e != nil {
		t.Fatal(e)
	}
	file := filepath.Join(dir, "config.json")
	os.WriteFile(file, []byte("preserve"), 0600)
	marker := []byte(`{"schema":"state-format/v1","program_version":"future","format_version":999,"published_at":"2026-09-13T09:00:00Z"}`)
	os.WriteFile(filepath.Join(dir, stateformat.MarkerName), marker, 0600)
	before := snapshot(t, dir)
	calls := []func() error{
		func() error { return pending.Append(dir, pending.Record{}) },
		func() error { return chain.Append(&receipt.Receipt{}) },
		func() error { _, e := receipt.OpenChain(dir, "another", key); return e },
		func() error { _, e := signing.Load(dir); return e },
		func() error { return st.SaveConfig(state.Config{}) },
		func() error { return statefs.WriteFile(file, []byte("overwrite"), 0600) },
		func() error {
			f, e := statefs.OpenFile(file, os.O_WRONLY|os.O_TRUNC, 0600)
			if f != nil {
				f.Close()
			}
			return e
		},
		func() error { return statefs.Remove(file) }, func() error { return statefs.RemoveAll(filepath.Join(dir, "grants")) },
		func() error { return statefs.Rename(file, file+".moved") }, func() error { return statefs.Link(file, file+".link") },
		func() error { return statefs.Chmod(file, 0777) }, func() error { return statefs.MkdirAll(filepath.Join(dir, "new/sub"), 0700) },
		func() error { _, e := statefs.ReadFile(file); return e }, func() error { _, e := statefs.ReadDir(dir); return e },
	}
	for i, call := range calls {
		if e := call(); !errors.Is(e, stateformat.ErrIncompatible) {
			t.Fatalf("entry %d: %v", i, e)
		}
	}
	if !reflect.DeepEqual(before, snapshot(t, dir)) {
		t.Fatal("incompatible state changed")
	}
}

func TestNestedMarkerCannotShadowOuterState(t *testing.T) {
	root := t.TempDir()
	child := filepath.Join(root, "nested")
	os.Mkdir(child, 0700)
	os.WriteFile(filepath.Join(root, stateformat.MarkerName), []byte(`{"schema":"state-format/v1","program_version":"future","format_version":999,"published_at":"2026-09-13T09:00:00Z"}`), 0600)
	os.WriteFile(filepath.Join(child, stateformat.MarkerName), []byte(`{"schema":"state-format/v1","program_version":"old","format_version":1,"published_at":"2026-09-13T09:00:00Z"}`), 0600)
	if e := statefs.WriteFile(filepath.Join(child, "data"), []byte("bad"), 0600); !errors.Is(e, stateformat.ErrIncompatible) {
		t.Fatal(e)
	}
	if _, e := os.Lstat(filepath.Join(child, "data")); !os.IsNotExist(e) {
		t.Fatal("nested marker bypass")
	}
}

func TestPrivatePublicationChecksBothCompatibilityBarriers(t *testing.T) {
	for _, side := range []string{"source", "target"} {
		t.Run(side, func(t *testing.T) {
			sourceRoot, targetRoot := t.TempDir(), t.TempDir()
			source, target := filepath.Join(sourceRoot, "scratch"), filepath.Join(targetRoot, "published")
			f, err := os.OpenFile(source, os.O_CREATE|os.O_EXCL|os.O_RDWR, 0600)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := f.WriteString("unchanged private payload"); err != nil {
				t.Fatal(err)
			}
			created, err := f.Stat()
			if err != nil {
				t.Fatal(err)
			}
			if err := f.Close(); err != nil {
				t.Fatal(err)
			}
			root := sourceRoot
			if side == "target" {
				root = targetRoot
			}
			if err := os.WriteFile(filepath.Join(root, stateformat.MarkerName), []byte(`{"schema":"state-format/v1","program_version":"future","format_version":999,"published_at":"2026-09-13T09:00:00Z"}`), 0600); err != nil {
				t.Fatal(err)
			}
			beforeSource, beforeTarget := snapshot(t, sourceRoot), snapshot(t, targetRoot)
			if moved, err := statefs.PublishPrivateNew(source, target, created); moved || !errors.Is(err, stateformat.ErrIncompatible) {
				t.Fatal("compatibility publication bypass", moved, err)
			}
			if !reflect.DeepEqual(beforeSource, snapshot(t, sourceRoot)) || !reflect.DeepEqual(beforeTarget, snapshot(t, targetRoot)) {
				t.Fatal("blocked publication changed state")
			}
		})
	}
}
