//go:build !windows

package server

import (
	"os"
	"testing"
)

func makeEvidenceDirectoryReadOnly(t *testing.T, _, path string) func() {
	t.Helper()
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(path, 0500); err != nil {
		t.Fatal(err)
	}
	restore := func() {
		if err := os.Chmod(path, info.Mode().Perm()); err != nil {
			t.Error(err)
		}
	}
	t.Cleanup(restore)
	return restore
}
