package skillmanifest

import (
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The official signature authenticates this immutable historical package only.
// A missing fixture is an error, never a reason to skip publisher verification.
func historicalReleaseDir(t *testing.T) string {
	t.Helper()
	source, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(source, "..", "..", "apps", "agentshield", "testdata", "releases", "siq-agent-security-v0.2.0")
	if _, err := os.Stat(filepath.Join(dir, "skill-manifest.json")); err != nil {
		t.Fatal(err)
	}
	return dir
}

// Test keys are embedded exclusively in a disposable copy of current source.
// Production trust roots and historical publisher artifacts are never changed.
func signedSourceCopy(t *testing.T) string {
	t.Helper()
	source, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	err = filepath.WalkDir(source, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		rel, err := filepath.Rel(source, path)
		if err != nil {
			return err
		}
		dest := filepath.Join(dir, rel)
		if entry.IsDir() {
			return os.MkdirAll(dest, 0o755)
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return &os.PathError{Op: "copy regular fixture", Path: path, Err: os.ErrInvalid}
		}
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		return os.WriteFile(dest, data, info.Mode().Perm())
	})
	if err != nil {
		t.Fatal(err)
	}
	key := testKey(t)
	if err := EmbedReleasePubkey(dir, key.PublicBase64()); err != nil {
		t.Fatal(err)
	}
	hash, err := HashSkillDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	manifest, err := Build(Options{ContentHash: hash, Artifacts: fakeArtifacts()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(manifest, key); err != nil {
		t.Fatal(err)
	}
	if err := WriteFile(filepath.Join(dir, "skill-manifest.json"), manifest); err != nil {
		t.Fatal(err)
	}
	return dir
}

func TestUnsignedSourceCannotBootstrap(t *testing.T) {
	source, err := FindSkillDir()
	if err != nil {
		t.Fatal(err)
	}
	// Remove the manifest in a temporary copy so this also works in a release checkout.
	dir := signedSourceCopy(t)
	if err := os.Remove(filepath.Join(dir, "skill-manifest.json")); err != nil {
		t.Fatal(err)
	}
	for _, pinned := range []string{"0", "1"} {
		t.Run("pinned="+pinned, func(t *testing.T) {
			stage := t.TempDir()
			bin := filepath.Join(t.TempDir(), "fake-bin.exe")
			if err := os.WriteFile(bin, []byte("must not execute"), 0o755); err != nil {
				t.Fatal(err)
			}
			cmd := exec.Command("sh", filepath.Join(dir, "scripts", "resolve_verified_bin.sh"))
			cmd.Env = append(os.Environ(), "SIQ_AGENT_SECURITY_BIN="+bin,
				"SIQ_AGENT_SECURITY_STAGE_DIR="+stage, "SIQ_AGENT_SECURITY_REQUIRE_PINNED="+pinned,
				"AGENTSHIELD_REQUIRE_PINNED="+pinned, "SIQ_AGENT_SECURITY_ALLOW_DOWNLOAD=0")
			output, err := cmd.CombinedOutput()
			if err == nil || !strings.Contains(string(output), "skill-manifest.json missing") {
				t.Fatalf("unsigned source accepted or wrong failure: %v: %s", err, output)
			}
			files, err := os.ReadDir(stage)
			if err != nil || len(files) != 0 {
				t.Fatalf("unsigned binary staged: %v, %d", err, len(files))
			}
		})
	}
	// Test-only signing must never mutate the source's embedded trust root.
	pub, err := ReadEmbeddedPubkey(source)
	if err != nil || pub != ReleasePublicKeyB64 {
		t.Fatalf("source trust changed: %v", err)
	}
}

func TestCurrentSourceSignedCopyVerification(t *testing.T) {
	dir := signedSourceCopy(t)
	key := testKey(t)
	path := filepath.Join(dir, "skill-manifest.json")
	m, err := LoadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := Verify(m); err == nil {
		t.Fatal("test-signed source must not pass official publisher trust")
	}
	cmd := exec.Command("python3", filepath.Join(dir, "scripts", "verify_manifest.py"), "--manifest", path, "--pubkey", key.PublicBase64(), "--skill-dir", dir)
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("current-source signed fixture: %v: %s", err, out)
	}
	// A real source change must invalidate its signed digest, even with a valid signature.
	if err := os.WriteFile(filepath.Join(dir, "SKILL.md"), []byte("changed after signing"), 0o644); err != nil {
		t.Fatal(err)
	}
	cmd = exec.Command("python3", filepath.Join(dir, "scripts", "verify_manifest.py"), "--manifest", path, "--pubkey", key.PublicBase64(), "--skill-dir", dir)
	if out, err := cmd.CombinedOutput(); err == nil || !strings.Contains(string(out), "content_hash mismatch") {
		t.Fatalf("changed source must fail digest check: %v: %s", err, out)
	}
}
