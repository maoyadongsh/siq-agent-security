package state

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDirectoryIdentity(t *testing.T) {
	dir := t.TempDir()
	st := &Store{Dir: dir}
	id, err := st.DirectoryID()
	if err != nil || len(id) != 64 {
		t.Fatalf("identity: %q %v", id, err)
	}
	again, err := (&Store{Dir: filepath.Join(dir, ".")}).DirectoryID()
	if err != nil || again != id {
		t.Fatal("equivalent directory changed identity")
	}
	other, err := (&Store{Dir: t.TempDir()}).DirectoryID()
	if err != nil || other == id {
		t.Fatal("different directory reused identity")
	}
	missing := filepath.Join(dir, "missing")
	if _, err := (&Store{Dir: missing}).DirectoryID(); err == nil {
		t.Fatal("missing directory accepted")
	}
	if _, err := os.Stat(missing); !os.IsNotExist(err) {
		t.Fatal("identity check created state")
	}
	alias := filepath.Join(t.TempDir(), "alias")
	if err := os.Symlink(dir, alias); err != nil {
		t.Skip("symlinks unavailable")
	}
	got, err := (&Store{Dir: alias}).DirectoryID()
	if err != nil || got != id {
		t.Fatal("symlink alias changed identity")
	}
}
