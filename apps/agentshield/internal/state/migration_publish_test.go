package state

import (
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestMigrationPublicationReuseAndDrift(t *testing.T) {
	for _, mode := range []os.FileMode{0600, 0400} {
		t.Run(mode.String(), func(t *testing.T) {
			root := t.TempDir()
			path := filepath.Join(root, "checkpoint")
			if err := os.Mkdir(filepath.Join(root, stateformat.MigrationDir), 0700); err != nil {
				t.Fatal(err)
			}
			raw := []byte("immutable checkpoint\n")
			if err := migrationPublish(root, path, raw, mode); err != nil {
				t.Fatal(err)
			}
			original, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			if err := migrationPublish(root, path, raw, mode); err != nil {
				t.Fatalf("identical checkpoint refused: %v", err)
			}
			after, err := os.Stat(path)
			if err != nil || !os.SameFile(original, after) || original.Mode() != after.Mode() {
				t.Fatal("reuse changed checkpoint")
			}
			if err := migrationPublish(root, path, []byte("different"), mode); err == nil {
				t.Fatal("different checkpoint overwritten")
			}
			got, err := os.ReadFile(path)
			if err != nil || string(got) != string(raw) {
				t.Fatal("rejection mutated bytes")
			}
			// Change the actual read-only attribute on Windows, and the owner
			// write permission on POSIX. Neither drift may be silently accepted.
			changed := mode ^ 0200
			if err := os.Chmod(path, changed); err != nil {
				t.Fatal(err)
			}
			if err := migrationPublish(root, path, raw, mode); err == nil {
				t.Fatal("mode drift accepted")
			}
			if err := os.Chmod(path, 0600); err != nil {
				t.Fatal(err)
			}
		})
	}
}
