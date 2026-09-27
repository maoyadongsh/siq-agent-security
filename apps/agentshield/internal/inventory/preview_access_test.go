package inventory

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

func previewStatus(t *testing.T, opts Options, path string) string {
	t.Helper()
	for _, root := range Preview(opts) {
		if root.Path == redactHome(path, opts.Home) {
			return root.Status
		}
	}
	t.Fatal("expected root absent from preview")
	return ""
}

func TestPreviewReadAccessAndRecovery(t *testing.T) {
	if runtime.GOOS == "windows" || os.Geteuid() == 0 {
		t.Skip("requires unprivileged POSIX permissions")
	}
	home := t.TempDir()
	dir := filepath.Join(home, "skills")
	config := filepath.Join(home, ".openclaw", "openclaw.json")
	for _, path := range []string{dir, filepath.Dir(config)} {
		if err := os.MkdirAll(path, 0700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(config, []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	opts := Options{Home: home, SkillDirs: []string{dir}}
	for _, path := range []string{dir, config} {
		if previewStatus(t, opts, path) != "available" {
			t.Fatal("readable root rejected")
		}
		info, _ := os.Stat(path)
		if err := os.Chmod(path, 0); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(path, info.Mode()) })
		if previewStatus(t, opts, path) != "unreadable" {
			t.Fatal("unreadable root advertised as available")
		}
		if path == dir {
			if _, err := NormalizeDirectory(home, dir); err == nil {
				t.Fatal("unreadable manual directory accepted")
			}
		}
		if err := os.Chmod(path, info.Mode()); err != nil {
			t.Fatal(err)
		}
		if previewStatus(t, opts, path) != "available" {
			t.Fatal("recovered root still unavailable")
		}
	}
	if got, err := NormalizeDirectory(home, dir); err != nil || got != dir {
		t.Fatal("empty recovered directory rejected", err)
	}
	if err := os.Remove(config); err != nil {
		t.Fatal(err)
	}
	if previewStatus(t, opts, config) != "missing" {
		t.Fatal("missing optional config treated as failure")
	}
}

func TestPreviewAccessRefusesChangedObject(t *testing.T) {
	for _, directory := range []bool{true, false} {
		name := "file"
		if directory {
			name = "directory"
		}
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "root")
			create := func() {
				t.Helper()
				var err error
				if directory {
					err = os.Mkdir(path, 0700)
				} else {
					err = os.WriteFile(path, []byte("unchanged fixture contents"), 0600)
				}
				if err != nil {
					t.Fatal(err)
				}
			}
			create()
			before, err := inspectScanRoot(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := readableRoot(path, before); err != nil {
				t.Fatal("unchanged object refused", err)
			}
			// A prior SameFile call must not accidentally force a lazy path-based
			// FileInfo to cache the identity and hide the Windows regression.
			before, err = inspectScanRoot(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.Rename(path, path+"-old"); err != nil {
				t.Fatal(err)
			}
			create()
			if err := readableRoot(path, before); err == nil {
				t.Fatal("changed object identity accepted")
			}
			if err := verifyScanRootName(path, before); err == nil {
				t.Fatal("replaced root name accepted")
			}
			after, err := inspectScanRoot(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := readableRoot(path, after); err != nil {
				t.Fatal("fresh preview refused", err)
			}
		})
	}
}

func TestPreviewAccessRefusesSymlink(t *testing.T) {
	home := t.TempDir()
	dir := filepath.Join(home, "skills")
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(home, "link")
	if err := os.Symlink(dir, link); err != nil {
		t.Skip("symlinks unavailable")
	}
	if _, err := NormalizeDirectory(home, link); err == nil {
		t.Fatal("manual symlink accepted")
	}
	if _, err := inspectScanRoot(link); err == nil {
		t.Fatal("symlink identity accepted")
	}
	if previewStatus(t, Options{Home: home, SkillDirs: []string{link}}, link) != "unreadable" {
		t.Fatal("symlink advertised as readable")
	}
}
