package skillcontext

import (
	"bytes"
	"encoding/json"
	"os"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

// vectorFixtures are deterministic: fixed key, ids and times keep the samples
// stable so the Python schema tests validate the exact same bytes.
func vectorFixtures(t *testing.T) (Context, Revocation) {
	t.Helper()
	c := Context{
		SchemaVersion: Schema,
		ContextID:     "sec-0123456789abcdef0123456789abcdef",
		IssuerID:      Issuer,
		Subject: Subject{
			Platform: "hermes", InstanceID: "hi-0123456789abcdef0123456789abcdef",
			AgentID: "hri-0123456789abcdef0123456789abcdef", SessionID: "s1", TaskID: "task-1",
		},
		Skill:         SkillRef{SkillID: "marketplace:skill:report-gen@0a1b2c3d4e5f", Version: "1.2.0", ContentHash: "1111111111111111111111111111111111111111111111111111111111111111"},
		Install:       InstallRef{InstallID: "ins-1", ClaimSignature: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
		Authority:     AuthorityRef{GrantID: "grt-1", GrantDigest: "2222222222222222222222222222222222222222222222222222222222222222"},
		EvidenceLevel: EvidenceTask,
		IssuedAt:      "2026-09-14T00:00:00Z",
		ExpiresAt:     "2026-09-14T01:00:00Z",
		SigningSchema: "local_canonical/v1",
	}
	r := Revocation{
		SchemaVersion: RevocationSchema,
		ContextID:     c.ContextID,
		IssuerID:      Issuer,
		RevokedAt:     "2026-09-14T02:00:00Z",
		SigningSchema: "local_canonical/v1",
	}
	return c, r
}

// TestSkillContextContractSamples pins the contract samples and regenerates
// them under AGENTSHIELD_UPDATE_SAMPLES=1.
func TestSkillContextContractSamples(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	c, r := vectorFixtures(t)
	if err := c.Validate(); err != nil {
		t.Fatal(err)
	}
	if err := r.Validate(); err != nil {
		t.Fatal(err)
	}
	c.Signature, err = key.SignCanonical(c.Unsigned())
	if err != nil {
		t.Fatal(err)
	}
	r.Signature, err = key.SignCanonical(r.Unsigned())
	if err != nil {
		t.Fatal(err)
	}
	for name, doc := range map[string]any{"skill-execution-context": c, "skill-execution-context-revocation": r} {
		raw, err := json.MarshalIndent(doc, "", "  ")
		if err != nil {
			t.Fatal(err)
		}
		path := "../../testdata/contracts/" + name + ".sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err := os.WriteFile(path, append(raw, '\n'), 0o644); err != nil {
				t.Fatal(err)
			}
		}
		want, err := os.ReadFile(path)
		if err != nil || !bytes.Equal(bytes.TrimSpace(want), raw) {
			t.Fatalf("%s sample differs (regenerate with AGENTSHIELD_UPDATE_SAMPLES=1)", name)
		}
	}
}
