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
	if !strings.Contains(string(ps1), "$ReleasePubKeyB64 = '"+ReleasePublicKeyB64+"'") {
		t.Fatal("bootstrap.ps1 must keep $ReleasePubKeyB64 = '<pubkey>' (regexp $ must not eat the variable)")
	}
}

func TestEmbedReleasePubkeyKeepsPS1Variable(t *testing.T) {
	dir := t.TempDir()
	scripts := filepath.Join(dir, "scripts")
	if err := os.MkdirAll(scripts, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(scripts, "resolve_verified_bin.sh"), []byte("RELEASE_PUBKEY_B64='old'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(scripts, "bootstrap.sh"), []byte("# delegates to resolve\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(scripts, "bootstrap.ps1"), []byte("$ReleasePubKeyB64 = 'old'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	k := testKey(t)
	pub := k.PublicBase64()
	if err := EmbedReleasePubkey(dir, pub); err != nil {
		t.Fatal(err)
	}
	ps1, err := os.ReadFile(filepath.Join(scripts, "bootstrap.ps1"))
	if err != nil {
		t.Fatal(err)
	}
	want := "$ReleasePubKeyB64 = '" + pub + "'"
	if !strings.Contains(string(ps1), want) {
		t.Fatalf("ps1 rewrite ate the variable:\n%s", ps1)
	}
	got, err := ReadEmbeddedPubkey(dir)
	if err != nil {
		t.Fatal(err)
	}
	if got != pub {
		t.Fatalf("resolve pubkey %s != %s", got, pub)
	}
}

func TestAdapterAndBootstrapShareVerifiedResolve(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	resolve := filepath.Join(dir, "scripts", "resolve_verified_bin.sh")
	adapter, err := os.ReadFile(filepath.Join(dir, "scripts", "adapter.sh"))
	if err != nil {
		t.Fatal(err)
	}
	bootstrap, err := os.ReadFile(filepath.Join(dir, "scripts", "bootstrap.sh"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(resolve); err != nil {
		t.Fatal("resolve_verified_bin.sh missing")
	}
	if !strings.Contains(string(adapter), "resolve_verified_bin.sh") {
		t.Fatal("adapter.sh must call shared resolve_verified_bin.sh before exec")
	}
	if !strings.Contains(string(bootstrap), "resolve_verified_bin.sh") {
		t.Fatal("bootstrap.sh must call shared resolve_verified_bin.sh")
	}
	// Pinned mode must refuse a wrong binary hash (same contract for adapter path).
	tmpBin := filepath.Join(t.TempDir(), "fake-bin")
	if err := os.WriteFile(tmpBin, []byte("not-a-release-binary"), 0o755); err != nil {
		t.Fatal(err)
	}
	stage := t.TempDir()
	cmd := exec.Command("sh", resolve)
	cmd.Env = append(os.Environ(),
		"SIQ_AGENT_SECURITY_BIN="+tmpBin,
		"SIQ_AGENT_SECURITY_REQUIRE_PINNED=1",
		"AGENTSHIELD_REQUIRE_PINNED=1",
		"SIQ_AGENT_SECURITY_STAGE_DIR="+stage,
	)
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("pinned resolve must reject mismatched binary\n%s", out)
	}
	if !strings.Contains(string(out), "verification failed") && !strings.Contains(string(out), "sha256") && !strings.Contains(string(out), "does not match") && !strings.Contains(string(out), "staging failed") {
		t.Fatalf("expected hash/verify failure, got:\n%s", out)
	}
}

func TestResolveStagesVerifiedBinary(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Skip(err)
	}
	resolve := filepath.Join(dir, "scripts", "resolve_verified_bin.sh")
	repoBin := filepath.Join(dir, "..", "..", "apps", "agentshield", "siq-agent-security")
	if _, err := os.Stat(repoBin); err != nil {
		t.Skip("repo binary missing")
	}
	stage := t.TempDir()
	cmd := exec.Command("sh", resolve)
	cmd.Env = append(os.Environ(),
		"SIQ_AGENT_SECURITY_BIN="+repoBin,
		"SIQ_AGENT_SECURITY_STAGE_DIR="+stage,
		// allow-local: local build may not match release artifact pins
	)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("resolve failed: %v\n%s", err, out)
	}
	staged := strings.TrimSpace(string(out))
	// CombinedOutput mixes stderr; take last non-empty line as path.
	lines := strings.Split(staged, "\n")
	path := ""
	for i := len(lines) - 1; i >= 0; i-- {
		l := strings.TrimSpace(lines[i])
		if l != "" && !strings.Contains(l, "siq-agent-security-verify") {
			path = l
			break
		}
	}
	if path == "" || !strings.HasPrefix(path, stage) {
		t.Fatalf("expected staged path under %s, got %q\nfull:\n%s", stage, path, out)
	}
	if st, err := os.Stat(path); err != nil || st.Mode()&0o111 == 0 {
		t.Fatalf("staged binary missing or not executable: %v", err)
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
	m.Signature = "00" + bad[2:]
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
	cmd := exec.Command("python3", py, "--manifest", path, "--pubkey", ReleasePublicKeyB64, "--skill-dir", dir)
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("committed skill-manifest.json failed bootstrap verifier: %v\n%s", err, out)
	}
}

func TestPythonVerifierRejectsContentHashMismatch(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Skip(err)
	}
	py := filepath.Join(dir, "scripts", "verify_manifest.py")
	path := filepath.Join(dir, "skill-manifest.json")
	if _, err := os.Stat(path); err != nil {
		t.Skip("release manifest not generated yet")
	}
	tmp := t.TempDir()
	if err := os.WriteFile(filepath.Join(tmp, "SKILL.md"), []byte("---\nname: tampered\n---\n# tampered\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(tmp, "skill-manifest.json"), raw, 0o600); err != nil {
		t.Fatal(err)
	}
	cmd := exec.Command("python3", py, "--manifest", filepath.Join(tmp, "skill-manifest.json"),
		"--pubkey", ReleasePublicKeyB64, "--skill-dir", tmp)
	out, err := cmd.CombinedOutput()
	if err == nil {
		t.Fatalf("content_hash mismatch must fail\n%s", out)
	}
	if !strings.Contains(string(out), "content_hash mismatch") {
		t.Fatalf("expected content_hash mismatch, got:\n%s", out)
	}
}
