package clientrelease

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/skillmanifest"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func fixture(t *testing.T) (string, string, *skillmanifest.Manifest, *signing.Key) {
	t.Helper()
	dir := t.TempDir()
	binary := filepath.Join(dir, "candidate")
	raw := []byte("candidate is never executed")
	hash := sha256.Sum256(raw)
	if err := os.WriteFile(binary, raw, 0600); err != nil {
		t.Fatal(err)
	}
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	m := &skillmanifest.Manifest{ManifestVersion: 1, Binary: skillmanifest.Binary{Name: "siq-agent-security", Version: "test", Artifacts: []skillmanifest.Artifact{{OS: runtime.GOOS, Arch: runtime.GOARCH, SHA256: hex.EncodeToString(hash[:]), Bytes: int64(len(raw))}}}, SignedBy: key.PublicBase64()}
	path := filepath.Join(dir, "manifest.json")
	writeManifest(t, path, m, key)
	return path, binary, m, key
}
func writeManifest(t *testing.T, path string, m *skillmanifest.Manifest, key *signing.Key) {
	t.Helper()
	if err := skillmanifest.Sign(m, key); err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
}
func TestStageRetryRecoveryAndActiveDaemon(t *testing.T) {
	manifest, binary, _, key := fixture(t)
	dir := t.TempDir()
	w, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	run := func() (string, error) {
		return stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public())
	}
	path, err := run()
	if err != nil {
		t.Fatal(err)
	}
	if again, err := run(); err != nil || again != path {
		t.Fatal("retry", err)
	}
	if err = os.Remove(path); err != nil {
		t.Fatal(err)
	}
	if _, err = run(); err != nil {
		t.Fatal("recovery", err)
	}
	if runtime.GOOS != "windows" {
		info, _ := os.Stat(path)
		if info.Mode().Perm() != 0700 {
			t.Fatal("not private executable")
		}
	}
	if err = os.WriteFile(path, []byte("user changes"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, err = run(); err == nil {
		t.Fatal("drift overwritten")
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "user changes" {
		t.Fatal("unknown bytes changed")
	}
}
func TestStageTrustAndPins(t *testing.T) {
	for _, kind := range []string{"trust", "duplicate", "platform", "digest", "size", "symlink"} {
		t.Run(kind, func(t *testing.T) {
			manifest, binary, m, key := fixture(t)
			dir := filepath.Join(t.TempDir(), "state")
			switch kind {
			case "duplicate":
				m.Binary.Artifacts = append(m.Binary.Artifacts, m.Binary.Artifacts[0])
			case "platform":
				m.Binary.Artifacts[0].OS = "other"
			case "digest":
				m.Binary.Artifacts[0].SHA256 = hex.EncodeToString(make([]byte, 32))
			case "size":
				m.Binary.Artifacts[0].Bytes++
			case "symlink":
				alias := binary + ".link"
				if err := os.Symlink(binary, alias); err != nil {
					t.Skip(err)
				}
				binary = alias
			}
			writeManifest(t, manifest, m, key)
			var err error
			if kind == "trust" {
				_, err = Stage(dir, manifest, binary)
			} else {
				_, err = stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public())
			}
			if err == nil {
				t.Fatal("invalid candidate accepted")
			}
			if kind == "trust" {
				if _, err = os.Stat(dir); !os.IsNotExist(err) {
					t.Fatal("untrusted manifest created state")
				}
			}
		})
	}
}
