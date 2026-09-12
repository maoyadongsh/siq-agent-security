package clientrelease

import (
	"os"
	"path/filepath"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/skillmanifest"
	"strings"
	"testing"
)

func TestRetainedManifestTrustCompatibilityAndAmbiguity(t *testing.T) {
	manifest, binary, m, key := fixture(t)
	dir := t.TempDir()
	// Legacy manifests are retained but cannot authorize client rollback.
	if _, err := stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public()); err != nil {
		t.Fatal(err)
	}
	digest, err := Digest(binary)
	if err != nil {
		t.Fatal(err)
	}
	lookup := func() (string, error) {
		return retainedManifest(dir, digest, binary, runtime.GOOS, runtime.GOARCH, key.Public())
	}
	if _, err := lookup(); err == nil {
		t.Fatal("legacy manifest selected")
	}
	m.ManifestVersion = 2
	m.ClientCompatibility = skillmanifest.CurrentClientCompatibility()
	writeManifest(t, manifest, m, key)
	if _, err := stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public()); err != nil {
		t.Fatal(err)
	}
	selected, err := lookup()
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Dir(selected) != filepath.Join(dir, "client-releases", digest) {
		t.Fatal("wrong retained location")
	}
	// Product lookup must reject the fixture issuer even at the expected path.
	if _, err := RetainedManifest(dir, digest, binary); err == nil {
		t.Fatal("fixture key accepted by product")
	}
	m.Binary.Version = "different-release-name"
	writeManifest(t, manifest, m, key)
	if _, err := stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public()); err != nil {
		t.Fatal(err)
	}
	if _, err := lookup(); err == nil || !strings.Contains(err.Error(), "多个清单") {
		t.Fatal("ambiguous release selected", err)
	}
}

func TestRetainedManifestDriftAndBudget(t *testing.T) {
	for _, kind := range []string{"drift", "budget", "symlink", "binary"} {
		t.Run(kind, func(t *testing.T) {
			manifest, binary, m, key := fixture(t)
			m.ManifestVersion = 2
			m.ClientCompatibility = skillmanifest.CurrentClientCompatibility()
			writeManifest(t, manifest, m, key)
			dir := t.TempDir()
			if _, err := stage(dir, manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public()); err != nil {
				t.Fatal(err)
			}
			digest, err := Digest(binary)
			if err != nil {
				t.Fatal(err)
			}
			lookup := func() (string, error) {
				return retainedManifest(dir, digest, binary, runtime.GOOS, runtime.GOARCH, key.Public())
			}
			selected, err := lookup()
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "drift":
				if err := os.WriteFile(selected, []byte("changed"), 0600); err != nil {
					t.Fatal(err)
				}
			case "budget":
				for i := 0; i < 33; i++ {
					if err := os.WriteFile(filepath.Join(filepath.Dir(selected), strings.Repeat("x", i+1)), nil, 0600); err != nil {
						t.Fatal(err)
					}
				}
			case "symlink":
				if err := os.Remove(selected); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(manifest, selected); err != nil {
					t.Skip("symlink unavailable")
				}
			case "binary":
				if err := os.WriteFile(binary, []byte("changed program"), 0700); err != nil {
					t.Fatal(err)
				}
			}
			if _, err := lookup(); err == nil {
				t.Fatal("invalid retained material accepted")
			}
		})
	}
}
