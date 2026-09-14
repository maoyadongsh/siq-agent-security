package statefs

import (
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func windowsPathSnapshot(t *testing.T, root string) map[string]string {
	t.Helper()
	out := map[string]string{}
	if err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		value := info.Mode().String()
		if info.Mode().IsRegular() {
			raw, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			value += string(raw)
		}
		out[rel] = value
		return nil
	}); err != nil {
		t.Fatal(err)
	}
	return out
}

func TestWindowsStatePathFileOperationsRejectBeforeEffects(t *testing.T) {
	parent := t.TempDir()
	target := filepath.Join(parent, "target")
	if err := os.Mkdir(target, 0700); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(target, "credential")
	if err := WriteFile(file, []byte("synthetic sentinel"), 0600); err != nil {
		t.Fatal(err)
	}
	if got, err := ReadFile(file); err != nil || string(got) != "synthetic sentinel" {
		t.Fatal("valid access failed")
	}
	// No marker: RequirePath must reject bad spellings before looking for one.
	before := windowsPathSnapshot(t, parent)
	for i, root := range []string{target + ".", target + " ", parent + `\bad.\..\target`, parent + `/bad /../target`} {
		bad := root + `\credential`
		ops := []struct {
			name string
			run  func() error
		}{
			{"read", func() error {
				b, e := ReadFile(bad)
				if len(b) != 0 {
					t.Error("read returned aliased bytes")
				}
				return e
			}},
			{"open", func() error {
				f, e := Open(bad)
				if f != nil {
					_ = f.Close()
				}
				return e
			}},
			{"write", func() error { return WriteFile(bad, []byte("replacement"), 0600) }},
			{"truncate", func() error {
				f, e := OpenFile(bad, os.O_WRONLY|os.O_TRUNC, 0600)
				if f != nil {
					_ = f.Close()
				}
				return e
			}},
			{"mkdir", func() error { return MkdirAll(root+`\new`, 0700) }},
			{"temp", func() error {
				f, e := CreateTemp(root, "temp-")
				if f != nil {
					_ = f.Close()
				}
				return e
			}},
			{"rename-source", func() error { return Rename(bad, filepath.Join(parent, "moved")) }},
			{"rename-target", func() error { return Rename(file, root+`\moved`) }},
			{"link-source", func() error { return Link(bad, filepath.Join(parent, "linked")) }},
			{"link-target", func() error { return Link(file, root+`\linked`) }},
			{"remove", func() error { return Remove(bad) }},
		}
		for _, op := range ops {
			if err := op.run(); !errors.Is(err, stateformat.ErrCorrupt) {
				t.Errorf("vector %d %s did not reject spelling", i, op.name)
			}
			if !reflect.DeepEqual(before, windowsPathSnapshot(t, parent)) {
				t.Fatalf("vector %d %s changed fixture", i, op.name)
			}
		}
	}
}
