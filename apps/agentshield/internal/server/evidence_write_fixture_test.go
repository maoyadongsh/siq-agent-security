package server

import (
	"errors"
	"os"
	"testing"
)

func refuseEvidenceWrites(t *testing.T, root, path string) {
	t.Helper()
	restore := makeEvidenceDirectoryReadOnly(t, root, path)
	probe, err := os.CreateTemp(path, "write-denial-probe-")
	if err == nil {
		_ = probe.Close()
		restore()
		if err := os.Remove(probe.Name()); err != nil {
			t.Error(err)
		}
		t.Fatal("evidence failure fixture still permits file creation")
	}
	if !errors.Is(err, os.ErrPermission) {
		t.Fatalf("evidence failure fixture must deny file creation: %v", err)
	}
}
