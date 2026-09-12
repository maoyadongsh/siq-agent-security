package clientrelease

import (
	"os"
	"runtime"
	"siq-agent-security/apps/agentshield/internal/skillmanifest"
	"testing"
)

func TestUpgradeCheckRequiresSignedCompatibilityAndExactCandidate(t *testing.T) {
	manifest, binary, m, key := fixture(t)
	check := func() error {
		_, err := checkUpgrade(manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public())
		return err
	}
	if check() == nil {
		t.Fatal("v1 approved for upgrade")
	}
	m.ManifestVersion = 2
	m.ClientCompatibility = skillmanifest.CurrentClientCompatibility()
	writeManifest(t, manifest, m, key)
	if err := check(); err != nil {
		t.Fatal(err)
	}
	if _, err := stage(t.TempDir(), manifest, binary, runtime.GOOS, runtime.GOARCH, key.Public()); err != nil {
		t.Fatal("v2 cannot stage", err)
	}
	m.ClientCompatibility.StateProfile = "future-format"
	writeManifest(t, manifest, m, key)
	if check() == nil {
		t.Fatal("unsupported signed state profile accepted")
	}
	m.ClientCompatibility = skillmanifest.CurrentClientCompatibility()
	writeManifest(t, manifest, m, key)
	if err := os.WriteFile(binary, []byte("tampered"), 0600); err != nil {
		t.Fatal(err)
	}
	if check() == nil {
		t.Fatal("candidate tamper accepted")
	}
}
