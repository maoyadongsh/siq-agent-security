//go:build !windows

package runtimeidentity

import (
	"os"
	"testing"
)

func assertPrivateIdentityFile(t *testing.T, path string) {
	t.Helper()
	info, err := os.Stat(path)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatal("private file", err)
	}
}
func broadenIdentityFile(t *testing.T, root, path string) {
	t.Helper()
	if err := os.Chmod(path, 0644); err != nil {
		t.Fatal(err)
	}
}
