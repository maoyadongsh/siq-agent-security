package skillmanifest

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestBootstrapEmbedsConstant(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	pub, err := ReadEmbeddedPubkey(dir)
	if err != nil {
		t.Fatal(err)
	}
	if pub != ReleasePublicKeyB64 {
		t.Fatalf("bootstrap.sh pubkey %s != ReleasePublicKeyB64 %s", pub, ReleasePublicKeyB64)
	}
	ps1, err := os.ReadFile(filepath.Join(dir, "scripts", "bootstrap.ps1"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(ps1), ReleasePublicKeyB64) {
		t.Fatal("bootstrap.ps1 must embed the same public key")
	}
}

func TestPythonVerifierAcceptsSignedManifest(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	py := filepath.Join(dir, "scripts", "verify_manifest.py")
	if _, err := os.Stat(py); err != nil {
		t.Fatal(err)
	}
	k := testKey(t)
	m, err := Build(Options{ContentHash: strings.Repeat("cd", 32), Artifacts: fakeArtifacts()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(m, k); err != nil {
		t.Fatal(err)
	}
	tmp := filepath.Join(t.TempDir(), "skill-manifest.json")
	if err := WriteFile(tmp, m); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("python3", py, "--manifest", tmp, "--pubkey", k.PublicBase64())
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("python verifier rejected a Go-signed manifest: %v\n%s", err, out)
	}

	bad := m.Signature
	m.Signature = "ff" + bad[2:]
	if err := WriteFile(tmp, m); err != nil {
		t.Fatal(err)
	}
	cmd = exec.Command("python3", py, "--manifest", tmp, "--pubkey", k.PublicBase64())
	if out, err := cmd.CombinedOutput(); err == nil {
		t.Fatalf("python verifier must reject a tampered signature\n%s", out)
	}
}

func TestPythonVerifierAcceptsCommittedRelease(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Skip(err)
	}
	path := filepath.Join(dir, "skill-manifest.json")
	if _, err := os.Stat(path); err != nil {
		t.Skip("release manifest not generated yet")
	}
	py := filepath.Join(dir, "scripts", "verify_manifest.py")
	cmd := exec.Command("python3", py, "--manifest", path, "--pubkey", ReleasePublicKeyB64)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("committed skill-manifest.json failed bootstrap verifier: %v\n%s", err, out)
	}
}
