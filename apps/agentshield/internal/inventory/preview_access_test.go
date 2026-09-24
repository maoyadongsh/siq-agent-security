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

func TestPreviewAccessRefusesSymlinkAndChangedObject(t *testing.T) {
	home := t.TempDir()
	dir := filepath.Join(home, "skills")
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	before, err := os.Stat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Rename(dir, dir+"-old"); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := readableRoot(dir, before); err == nil {
		t.Fatal("changed directory identity accepted")
	}
	link := filepath.Join(home, "link")
	if err := os.Symlink(dir, link); err != nil {
		t.Skip("symlinks unavailable")
	}
	if _, err := NormalizeDirectory(home, link); err == nil {
		t.Fatal("manual symlink accepted")
	}
	if previewStatus(t, Options{Home: home, SkillDirs: []string{link}}, link) != "unreadable" {
		t.Fatal("symlink advertised as readable")
	}
}
