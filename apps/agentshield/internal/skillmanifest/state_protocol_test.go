package skillmanifest

import (
	"bytes"
	"encoding/json"
	"os"
	"siq-agent-security/apps/agentshield/internal/signing"
	"strings"
	"testing"
)

func TestStateProtocolReleaseContract(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	m, e := Build(Options{ClientCompatible: true, Version: "0.3.0-state-protocol", ContentHash: strings.Repeat("a", 64), Artifacts: []Artifact{{OS: "linux", Arch: "arm64", SHA256: strings.Repeat("b", 64), Bytes: 123, URL: "https://example.invalid/siq"}}, SignedBy: key.PublicBase64()})
	if e != nil {
		t.Fatal(e)
	}
	if m.ManifestVersion != 3 || m.StateCompatibility == nil {
		t.Fatal("missing state protocol")
	}
	if e = Sign(m, key); e != nil {
		t.Fatal(e)
	}
	if e = VerifyWithPublicKey(m, key.Public()); e != nil {
		t.Fatal(e)
	}
	raw, _ := json.MarshalIndent(m, "", "  ")
	raw = append(raw, '\n')
	path := "../../testdata/contracts/skill-manifest.v3.reader3.sample.json"
	if os.Getenv("SIQ_UPDATE_STATE_PROTO_FIXTURES") == "1" {
		if e = os.WriteFile(path, raw, 0600); e != nil {
			t.Fatal(e)
		}
	}
	expected, e := os.ReadFile(path)
	if e != nil || !bytes.Equal(raw, expected) {
		t.Fatal("v3 fixture drift", e)
	}
	// Keep the actual older signed fixture intact and readable; increasing the
	// current builder capability must not rewrite a historical signature.
	legacy, e := os.ReadFile("../../testdata/contracts/skill-manifest.v3.sample.json")
	var old Manifest
	if e != nil || json.Unmarshal(legacy, &old) != nil || VerifyWithPublicKey(&old, key.Public()) != nil {
		t.Fatal("legacy v3 manifest no longer verifies", e)
	}
	m.StateCompatibility.MaxFormat++
	if e = VerifyWithPublicKey(m, key.Public()); e == nil {
		t.Fatal("unsigned capability change accepted")
	}
	m.StateCompatibility = CurrentStateCompatibility()
	m.StateCompatibility.WriterVersion = 0
	Sign(m, key)
	if e = VerifyWithPublicKey(m, key.Public()); e == nil {
		t.Fatal("invalid signed capability accepted")
	}
}
