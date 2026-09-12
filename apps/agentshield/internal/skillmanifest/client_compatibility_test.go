package skillmanifest

import (
	"bytes"
	"encoding/json"
	"os"
	"siq-agent-security/apps/agentshield/internal/signing"
	"strings"
	"testing"
)

func TestClientCompatibilityContractAndTampering(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	m, err := Build(Options{ClientCompatible: true, Version: "0.3.0", ContentHash: strings.Repeat("a", 64), Artifacts: []Artifact{{OS: "linux", Arch: "arm64", SHA256: strings.Repeat("b", 64), Bytes: 123, URL: "https://example.invalid/siq"}}, SignedBy: key.PublicBase64()})
	if err != nil {
		t.Fatal(err)
	}
	if err = Sign(m, key); err != nil {
		t.Fatal(err)
	}
	if err = VerifyWithPublicKey(m, key.Public()); err != nil {
		t.Fatal(err)
	}
	raw, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	raw = append(raw, '\n')
	path := "../../testdata/contracts/skill-manifest.v2.sample.json"
	if os.Getenv("SIQ_UPDATE_CLIENT_COMPAT_FIXTURE") == "1" {
		if err = os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	expected, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(raw, expected) {
		t.Fatal("v2 fixture drift")
	}
	m.ClientCompatibility.Migration = "automatic"
	if err = VerifyWithPublicKey(m, key.Public()); err == nil {
		t.Fatal("unsupported migration accepted")
	}
	m.ClientCompatibility = CurrentClientCompatibility()
	m.Binary.Artifacts[0].Bytes = 0
	if err = Sign(m, key); err != nil {
		t.Fatal(err)
	}
	if err = VerifyWithPublicKey(m, key.Public()); err == nil {
		t.Fatal("signed zero size accepted")
	}
	m.ManifestVersion = 1
	if err = VerifyWithPublicKey(m, key.Public()); err == nil {
		t.Fatal("v1 with new unsigned semantics accepted")
	}
	if err = CheckClientCompatibility(&Manifest{ManifestVersion: 1}); err == nil {
		t.Fatal("legacy manifest approved for upgrade")
	}
}
