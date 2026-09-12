package clientrelease

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func TestSnapshotSurvivesSourceRemovalAndRefusesDrift(t *testing.T) {
	dir := t.TempDir()
	source := filepath.Join(t.TempDir(), "source")
	raw := []byte("local source bytes; not a trusted release")
	if err := os.WriteFile(source, raw, 0700); err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	path, err := snapshot(dir, source, runtime.GOOS)
	if err != nil {
		t.Fatal(err)
	}
	hash := sha256.Sum256(raw)
	if filepath.Base(filepath.Dir(path)) != hex.EncodeToString(hash[:]) {
		t.Fatal("digest not reflected in storage")
	}
	if again, err := snapshot(dir, source, runtime.GOOS); err != nil || again != path {
		t.Fatal("non-idempotent snapshot", err)
	}
	if _, err = os.Stat(filepath.Join(dir, "client-releases")); !os.IsNotExist(err) {
		t.Fatal("local snapshot promoted to release")
	}
	if err = os.Remove(source); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(path)
	if err != nil || string(got) != string(raw) {
		t.Fatal("snapshot did not survive source removal")
	}
	if err = os.WriteFile(source, raw, 0700); err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte("unknown changes"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err = snapshot(dir, source, runtime.GOOS); err == nil {
		t.Fatal("snapshot drift overwritten")
	}
	got, _ = os.ReadFile(path)
	if string(got) != "unknown changes" {
		t.Fatal("unknown file modified")
	}
}
func TestSnapshotRejectsEmptyAndSymlinkSource(t *testing.T) {
	for _, kind := range []string{"empty", "symlink"} {
		t.Run(kind, func(t *testing.T) {
			source := filepath.Join(t.TempDir(), "source")
			if err := os.WriteFile(source, nil, 0700); err != nil {
				t.Fatal(err)
			}
			if kind == "symlink" {
				alias := source + ".link"
				if err := os.Symlink(source, alias); err != nil {
					t.Skip(err)
				}
				source = alias
			}
			if _, err := snapshot(t.TempDir(), source, runtime.GOOS); err == nil {
				t.Fatal("invalid snapshot source accepted")
			}
		})
	}
}
func TestSnapshotCurrentExecutable(t *testing.T) {
	dir := t.TempDir()
	path, err := SnapshotCurrent(dir)
	if err != nil {
		t.Fatal(err)
	}
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	original, err := os.ReadFile(executable)
	if err != nil {
		t.Fatal(err)
	}
	preserved, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if sha256.Sum256(original) != sha256.Sum256(preserved) {
		t.Fatal("current executable was not preserved")
	}
}
