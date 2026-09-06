package skillmanifest

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// TestPythonHashSkillDirParity locks DEV04-C: verify_manifest.hash_skill_dir ≡ HashSkillDir.
func TestPythonHashSkillDirParity(t *testing.T) {
	skillDir, err := FindSkillDir()
	if err != nil {
		t.Skip(err)
	}
	py := filepath.Join(skillDir, "scripts", "verify_manifest.py")
	if _, err := os.Stat(py); err != nil {
		t.Skip("verify_manifest.py missing")
	}
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 not available")
	}

	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte("---\nname: parity\n---\n# parity\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(filepath.Join(dir, "scripts"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "scripts", "x.sh"), []byte("echo ok\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	// Must be ignored by both implementations.
	if err := os.WriteFile(filepath.Join(dir, "skill-manifest.json"), []byte(`{"noise":true}`), 0o644); err != nil {
		t.Fatal(err)
	}

	want, err := HashSkillDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	got := pythonContentHash(t, py, dir)
	if got != want {
		t.Fatalf("python content_hash %s != go %s", got, want)
	}

	// Real skill tree must also match (guards against install-path drift).
	wantSkill, err := HashSkillDir(skillDir)
	if err != nil {
		t.Fatal(err)
	}
	gotSkill := pythonContentHash(t, py, skillDir)
	if gotSkill != wantSkill {
		t.Fatalf("skill-dir python %s != go %s", gotSkill, wantSkill)
	}
}

func TestPythonHashSkillDirRejectsEscape(t *testing.T) {
	skillDir, err := FindSkillDir()
	if err != nil {
		t.Skip(err)
	}
	py := filepath.Join(skillDir, "scripts", "verify_manifest.py")
	if _, err := exec.LookPath("python3"); err != nil {
		t.Skip("python3 not available")
	}
	dir := t.TempDir()
	outside := t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "secret"), []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte("# x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "secret"), filepath.Join(dir, "leak")); err != nil {
		t.Fatal(err)
	}
	if _, err := HashSkillDir(dir); err == nil {
		t.Fatal("go HashSkillDir must refuse symlink escape")
	}
	cmd := exec.Command("python3", py, "--print-content-hash", dir)
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("python must refuse symlink escape, got %s", out)
	}
	if !bytes.Contains(out, []byte("incomplete")) && !bytes.Contains(out, []byte("symlink")) {
		t.Fatalf("unexpected python error: %s", out)
	}
}

func pythonContentHash(t *testing.T, py, dir string) string {
	t.Helper()
	cmd := exec.Command("python3", py, "--print-content-hash", dir)
	out, err := cmd.Output()
	if err != nil {
		if ee, ok := err.(*exec.ExitError); ok {
			t.Fatalf("python hash failed: %v\n%s", err, ee.Stderr)
		}
		t.Fatal(err)
	}
	return strings.TrimSpace(string(out))
}
