package clientrelease

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

func TestRestoreSnapshotExclusiveAndIntegrity(t *testing.T) {
	dir := t.TempDir()
	source := filepath.Join(t.TempDir(), "source")
	if err := os.WriteFile(source, []byte("original program"), 0700); err != nil {
		t.Fatal(err)
	}
	preserved, err := snapshot(dir, source, runtime.GOOS)
	if err != nil {
		t.Fatal(err)
	}
	digest, err := Digest(preserved)
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "restored")
	if err := RestoreSnapshot(dir, digest, target); err != nil {
		t.Fatal(err)
	}
	actual, err := Digest(target)
	if err != nil || actual != digest {
		t.Fatal("restored content mismatch", err)
	}
	info, err := os.Stat(target)
	if err != nil {
		t.Fatal(err)
	}
	if runtime.GOOS != "windows" && info.Mode().Perm() != 0700 {
		t.Fatal("restored mode")
	}
	if err := RestoreSnapshot(dir, digest, target); err == nil {
		t.Fatal("existing target accepted")
	}
	if err := os.WriteFile(target, []byte("user content"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := RestoreSnapshot(dir, digest, target); err == nil {
		t.Fatal("user target overwritten")
	}
	raw, err := os.ReadFile(target)
	if err != nil || string(raw) != "user content" {
		t.Fatal("user content changed")
	}
	link := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(target, link); err == nil {
		if err := RestoreSnapshot(dir, digest, link); err == nil {
			t.Fatal("symlink destination accepted")
		}
		if info, err := os.Lstat(link); err != nil || info.Mode()&os.ModeSymlink == 0 {
			t.Fatal("symlink changed")
		}
	}
	missingParent := filepath.Join(t.TempDir(), "not-created", "binary")
	if err := RestoreSnapshot(dir, digest, missingParent); err == nil {
		t.Fatal("created outside parent")
	}
	if err := os.WriteFile(preserved, []byte("corrupt"), 0700); err != nil {
		t.Fatal(err)
	}
	absent := filepath.Join(t.TempDir(), "absent")
	if err := RestoreSnapshot(dir, digest, absent); err == nil {
		t.Fatal("corrupt snapshot accepted")
	}
	if _, err := os.Lstat(absent); !os.IsNotExist(err) {
		t.Fatal("corrupt snapshot published")
	}
	for _, invalid := range []string{"../escape", strings.Repeat("A", 64), ""} {
		if _, err := SnapshotPath(dir, invalid); err == nil {
			t.Fatal("invalid digest accepted")
		}
	}
}
