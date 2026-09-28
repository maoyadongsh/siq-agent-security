package skillimport

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

// Windows chmod(0700) does not manufacture the POSIX executable-bit change
// used by the separate physical-tamper test. This checks actual native facts.
func TestImportWindowsChmodPreservesSignedFacts(t *testing.T) {
	s, req := storeFixture(t)
	rec, _, _, err := s.Create(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	if len(rec.Files) != 1 || rec.Files[0].Path != "SKILL.md" || rec.Files[0].Executable {
		t.Fatal("unexpected native file metadata", rec)
	}
	path := filepath.Join(s.blob(req.ImportID), "payload", "SKILL.md")
	before, err := os.Stat(path)
	if err != nil || before.Mode().Perm()&0111 != 0 {
		t.Fatal("unexpected native mode", err)
	}
	if err := os.Chmod(path, 0700); err != nil {
		t.Fatal(err)
	}
	after, err := os.Stat(path)
	if err != nil || after.Mode() != before.Mode() || !os.SameFile(before, after) {
		t.Fatal("fixture unexpectedly changed file mode or identity", err)
	}
	loaded, _, err := s.Load(context.Background(), req.ImportID)
	if err != nil || loaded.ArtifactDigest != rec.ArtifactDigest || loaded.Signature != rec.Signature ||
		!signing.VerifyCanonical(s.key.Public(), unsigned(*loaded), loaded.Signature) {
		t.Fatal("unchanged native file facts did not preserve signed import", err)
	}
}
