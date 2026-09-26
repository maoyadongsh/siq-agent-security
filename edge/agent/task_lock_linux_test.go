//go:build linux

package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestTaskLockExclusiveAndReusable(t *testing.T) {
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	release, err := acquireTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	if other, err := acquireTaskLock(); err == nil {
		other()
		t.Fatal("second owner accepted")
	}
	release()
	release, err = acquireTaskLock()
	if err != nil {
		t.Fatal(err)
	}
	release()
	if _, err := os.Stat(filepath.Join(dir, "tasks.lock")); err != nil {
		t.Fatal("lock inode removed")
	}
}

func TestTaskLockRejectsUnsafeFile(t *testing.T) {
	for _, kind := range []string{"symlink", "permissive", "directory"} {
		t.Run(kind, func(t *testing.T) {
			dir := t.TempDir()
			if err := os.Chmod(dir, 0700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("SIQ_EDGE_STATE_DIR", dir)
			path := filepath.Join(dir, "tasks.lock")
			switch kind {
			case "symlink":
				if err := os.Symlink(filepath.Join(dir, "target"), path); err != nil {
					t.Fatal(err)
				}
			case "directory":
				if err := os.Mkdir(path, 0700); err != nil {
					t.Fatal(err)
				}
			default:
				if err := os.WriteFile(path, []byte("preserve"), 0600); err != nil {
					t.Fatal(err)
				}
				if err := os.Chmod(path, 0666); err != nil {
					t.Fatal(err)
				}
			}
			if release, err := acquireTaskLock(); err == nil {
				release()
				t.Fatal("unsafe lock accepted")
			}
		})
	}
}
