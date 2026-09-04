package skillmanifest

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func testKey(t *testing.T) *signing.Key {
	t.Helper()
	k, err := signing.FromSeed(bytes.Repeat([]byte{11}, 32))
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func fakeArtifacts() []Artifact {
	h := strings.Repeat("ab", 32)
	return []Artifact{
		{OS: "linux", Arch: "amd64", SHA256: h, URL: "https://example.invalid/agentshield-linux-amd64", Bytes: 1},
		{OS: "linux", Arch: "arm64", SHA256: h, URL: "https://example.invalid/agentshield-linux-arm64", Bytes: 1},
		{OS: "darwin", Arch: "arm64", SHA256: h, URL: "https://example.invalid/agentshield-darwin-arm64", Bytes: 1},
		{OS: "windows", Arch: "amd64", SHA256: h, URL: "https://example.invalid/agentshield-windows-amd64.exe", Bytes: 1},
	}
}

func TestSignAndVerify(t *testing.T) {
	k := testKey(t)
	m, err := Build(Options{ContentHash: strings.Repeat("cd", 32), Artifacts: fakeArtifacts(), SignedBy: k.PublicBase64()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(m, k); err != nil {
		t.Fatal(err)
	}
	if len(m.Signature) != 128 {
		t.Fatalf("signature length %d", len(m.Signature))
	}
	if err := Verify(m); err != nil {
		t.Fatal(err)
	}
	m.Signature = "00" + m.Signature[2:]
	if err := Verify(m); err == nil {
		t.Fatal("tampered signature must fail")
	}
}

func TestVerifyRejectsWrongKey(t *testing.T) {
	k := testKey(t)
	m, err := Build(Options{ContentHash: strings.Repeat("cd", 32), Artifacts: fakeArtifacts()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(m, k); err != nil {
		t.Fatal(err)
	}
	other, err := signing.FromSeed(bytes.Repeat([]byte{12}, 32))
	if err != nil {
		t.Fatal(err)
	}
	m.SignedBy = other.PublicBase64()
	if err := Verify(m); err == nil {
		t.Fatal("signature under a different signed_by must fail")
	}
}

func TestDefaultMatrixHonesty(t *testing.T) {
	rows := DefaultMatrix()
	if err := ValidateMatrix(rows); err != nil {
		t.Fatal(err)
	}
	var sawTrae, sawHermesLinux bool
	for _, r := range rows {
		if r.Status == "supported" {
			t.Fatalf("%s/%s must not claim supported without evidence", r.Platform, r.OS)
		}
		if r.Platform == "trae" {
			sawTrae = true
			if r.Status != "audit_only" || len(r.Tiers) != 1 || r.Tiers[0] != "L0" {
				t.Fatalf("trae row %+v", r)
			}
		}
		if r.Platform == "hermes" && r.OS == "linux" {
			sawHermesLinux = true
		}
		if r.OS != "linux" {
			for _, tier := range r.Tiers {
				if tier == "L3" && len(r.Requires) == 0 {
					t.Fatalf("L3 on %s/%s missing requires", r.Platform, r.OS)
				}
			}
		}
	}
	if !sawTrae || !sawHermesLinux {
		t.Fatal("matrix must include trae and hermes/linux")
	}
}

func TestValidateMatrixRejectsLies(t *testing.T) {
	if err := ValidateMatrix([]Row{{Platform: "trae", OS: "linux", Tiers: []string{"L0", "L2"}, Status: "audit_only"}}); err == nil {
		t.Fatal("audit_only + L2 must be rejected")
	}
	if err := ValidateMatrix([]Row{{Platform: "hermes", OS: "linux", Tiers: []string{"L0"}, Status: "supported"}}); err == nil {
		t.Fatal("supported without evidence must be rejected")
	}
	if err := ValidateMatrix([]Row{{Platform: "hermes", OS: "darwin", Tiers: []string{"L0", "L3"}, Status: "experimental"}}); err == nil {
		t.Fatal("darwin L3 without requires must be rejected")
	}
}

func TestHashDirExcludesManifest(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte("---\nname: x\n---\n# x\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	h1, err := HashSkillDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "skill-manifest.json"), []byte(`{"noise":true}`), 0o644); err != nil {
		t.Fatal(err)
	}
	h2, err := HashSkillDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if h1 != h2 {
		t.Fatal("content_hash must ignore skill-manifest.json")
	}
	if err := os.WriteFile(filepath.Join(dir, "scripts", "x.sh"), []byte("echo\n"), 0o644); err == nil {
		t.Fatal("expected missing scripts dir")
	}
	if err := os.Mkdir(filepath.Join(dir, "scripts"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "scripts", "x.sh"), []byte("echo\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	h3, err := HashSkillDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if h3 == h1 {
		t.Fatal("adding a skill file must change content_hash")
	}
}

func TestSampleManifestMatchesBuilder(t *testing.T) {
	k := testKey(t)
	m, err := Build(Options{ContentHash: strings.Repeat("cd", 32), Artifacts: fakeArtifacts()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(m, k); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join("..", "..", "testdata", "contracts", "skill-manifest.sample.json")
	if os.Getenv("WRITE_SKILL_MANIFEST_SAMPLE") == "1" {
		if err := WriteFile(path, m); err != nil {
			t.Fatal(err)
		}
		t.Log("wrote", path)
		return
	}
	got, err := LoadFile(path)
	if err != nil {
		t.Fatalf("committed sample missing (%v); generate with the test key seed 0x0b*32", err)
	}
	if err := Verify(got); err != nil {
		t.Fatal(err)
	}
	wantJSON, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	gotJSON, err := json.Marshal(got)
	if err != nil {
		t.Fatal(err)
	}
	if string(wantJSON) != string(gotJSON) {
		t.Fatalf("sample drifted from builder output\nwant %s\ngot  %s", wantJSON, gotJSON)
	}
}

func TestCommittedReleaseManifest(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Skip(err)
	}
	path := filepath.Join(dir, "skill-manifest.json")
	if _, err := os.Stat(path); err != nil {
		t.Skip("release manifest not generated yet")
	}
	m, err := LoadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(m); err != nil {
		t.Fatal(err)
	}
	if m.SignedBy != ReleasePublicKeyB64 {
		t.Fatalf("signed_by %s != ReleasePublicKeyB64", m.SignedBy)
	}
	embedded, err := ReadEmbeddedPubkey(dir)
	if err != nil {
		t.Fatal(err)
	}
	if embedded != ReleasePublicKeyB64 {
		t.Fatalf("bootstrap pubkey %s != constant", embedded)
	}
	want, err := HashSkillDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if m.Skill.ContentHash != want {
		t.Fatalf("content_hash stale: manifest %s dir %s (re-run release-manifest)", m.Skill.ContentHash, want)
	}
	if m.Skill.Description != SkillDescription {
		t.Fatalf("description %q", m.Skill.Description)
	}
	if err := ValidateMatrix(m.SupportMatrix); err != nil {
		t.Fatal(err)
	}
	if len(m.Binary.Artifacts) != len(Targets) {
		t.Fatalf("expected %d artifacts, got %d", len(Targets), len(m.Binary.Artifacts))
	}
	for _, a := range m.Binary.Artifacts {
		if len(a.SHA256) != 64 {
			t.Fatalf("artifact %s/%s missing sha256", a.OS, a.Arch)
		}
		if a.URL == "" || strings.Contains(a.URL, "example.invalid") {
			t.Fatalf("release URL must be the unpublished GitHub path, got %s", a.URL)
		}
		if a.Bytes <= 0 {
			t.Fatalf("artifact %s/%s missing bytes", a.OS, a.Arch)
		}
	}
}

func TestParsePublicKeyRejectsJunk(t *testing.T) {
	if _, err := ParsePublicKey("not-base64"); err == nil {
		t.Fatal("expected error")
	}
	if _, err := ParsePublicKey("YQ=="); err == nil {
		t.Fatal("short key must fail")
	}
}

func TestHashFile(t *testing.T) {
	p := filepath.Join(t.TempDir(), "b")
	if err := os.WriteFile(p, []byte("abc"), 0o644); err != nil {
		t.Fatal(err)
	}
	sum, n, err := HashFile(p)
	if err != nil {
		t.Fatal(err)
	}
	if n != 3 {
		t.Fatalf("bytes=%d", n)
	}
	want := sha256.Sum256([]byte("abc"))
	if sum != hex.EncodeToString(want[:]) {
		t.Fatalf("got %s", sum)
	}
}

func TestKeyFromEnvFailClosed(t *testing.T) {
	t.Setenv(SeedEnv, "")
	if _, err := KeyFromEnv(); err == nil {
		t.Fatal("empty env must fail closed")
	}
}

func TestSampleJSONIsObject(t *testing.T) {
	raw, err := json.Marshal(DefaultMatrix())
	if err != nil {
		t.Fatal(err)
	}
	if !json.Valid(raw) {
		t.Fatal("matrix json invalid")
	}
}
