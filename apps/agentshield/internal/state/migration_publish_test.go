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
			original := migrationTestFileIdentity(t, path)
			if original.Mode()&0200 != mode&0200 {
				t.Fatal("publication changed requested read-only attribute")
			}
			entries, err := os.ReadDir(filepath.Join(root, stateformat.MigrationDir, "tmp"))
			if err != nil || len(entries) != 0 {
				t.Fatal("owned scratch not cleaned")
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

func TestMigrationScratchCleanupRefusesReplacement(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "scratch")
	if err := os.WriteFile(path, []byte("owned"), 0600); err != nil {
		t.Fatal(err)
	}
	original := migrationTestFileIdentity(t, path)
	if err := os.Rename(path, path+".original"); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("foreign"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := migrationRemoveScratch(path, original); err == nil {
		t.Fatal("foreign scratch removed")
	}
	got, err := os.ReadFile(path)
	if err != nil || string(got) != "foreign" {
		t.Fatal("foreign scratch changed")
	}
}

func migrationTestFileIdentity(t *testing.T, path string) os.FileInfo {
	t.Helper()
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	// Match production's File.Stat: Windows path Stat lazily resolves file IDs
	// in SameFile and cannot represent the identity before a path replacement.
	info, err := f.Stat()
	if err != nil {
		t.Fatal(err)
	}
	return info
}
