package provenance

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

// Python-generated public fixture: seed 3 is deterministic test material only.
func TestProvenanceCrossLanguageFixedVector(t *testing.T) {
	var assertion Assertion
	var vector struct {
		Content   json.RawMessage `json:"content"`
		Canonical string          `json:"canonical_unsigned"`
		Digest    string          `json:"unsigned_sha256"`
	}
	for name, target := range map[string]any{
		"provenance-assertion.sample.json": &assertion,
		"provenance-assertion.vector.json": &vector,
	} {
		raw, err := os.ReadFile("../../testdata/contracts/" + name)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(raw, target); err != nil {
			t.Fatal(err)
		}
	}
	_, issuer, key, now := authorityFixture(t)
	if err := assertion.VerifyAuthority(issuer, key.Public(), assertion.Scope, now); err != nil {
		t.Fatal(err)
	}
	raw, err := canon.Marshal(assertion.Unsigned())
	if err != nil || string(raw) != vector.Canonical {
		t.Fatal("canonical bytes differ", err)
	}
	digest := sha256.Sum256(raw)
	if hex.EncodeToString(digest[:]) != vector.Digest {
		t.Fatal("unsigned digest differs")
	}
	content, err := canon.Decode(vector.Content)
	if err != nil {
		t.Fatal(err)
	}
	contentDigest, err := ContentDigest(content)
	if err != nil || contentDigest != assertion.ContentDigest {
		t.Fatal("content digest differs", err)
	}
	sig, err := key.SignCanonical(assertion.Unsigned())
	if err != nil || sig != assertion.Signature {
		t.Fatal("signature differs", err)
	}
	// Mutate every signed field without re-signing, including nested authority.
	for field := range assertion.Unsigned() {
		t.Run(field, func(t *testing.T) {
			bad := assertion.Unsigned()
			switch field {
			case "source":
				bad[field].(map[string]any)["source_id"] = "forged"
			case "scope":
				bad[field].(map[string]any)["task_id"] = "other"
			case "parents":
				bad[field] = []string{"other"}
			default:
				bad[field] = "changed"
			}
			bad["signature"] = assertion.Signature
			encoded, err := json.Marshal(bad)
			if err != nil {
				t.Fatal(err)
			}
			var changed Assertion
			if err := json.Unmarshal(encoded, &changed); err != nil {
				t.Fatal(err)
			}
			if changed.VerifyAuthority(issuer, key.Public(), assertion.Scope, now) == nil {
				t.Fatal("tampered field accepted")
			}
		})
	}
}
