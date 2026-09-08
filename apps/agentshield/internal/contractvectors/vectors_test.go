// Package contractvectors_test checks the three template §91 contracts together.
package contractvectors_test

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
)

type unsignedDocument interface{ Unsigned() map[string]any }

func TestSharedAuthorityEffectCanonicalVectors(t *testing.T) {
	for _, c := range []struct {
		name     string
		seed     byte
		document unsignedDocument
	}{
		{"context-assertion", 7, &trustedcontext.Assertion{}},
		{"provenance-assertion", 3, &provenance.Assertion{}},
		{"effect-evidence", 7, &effectevidence.Evidence{}},
	} {
		t.Run(c.name, func(t *testing.T) {
			var vector struct {
				Canonical string `json:"canonical_unsigned"`
				Digest    string `json:"unsigned_sha256"`
			}
			var envelope struct {
				Signature string `json:"signature"`
			}
			raw, err := os.ReadFile("../../testdata/contracts/" + c.name + ".sample.json")
			if err != nil {
				t.Fatal(err)
			}
			if err = json.Unmarshal(raw, c.document); err != nil {
				t.Fatal(err)
			}
			if err = json.Unmarshal(raw, &envelope); err != nil {
				t.Fatal(err)
			}
			raw, err = os.ReadFile("../../testdata/contracts/" + c.name + ".vector.json")
			if err != nil {
				t.Fatal(err)
			}
			if err = json.Unmarshal(raw, &vector); err != nil {
				t.Fatal(err)
			}
			canonical, err := canon.Marshal(c.document.Unsigned())
			if err != nil {
				t.Fatal(err)
			}
			if string(canonical) != vector.Canonical {
				t.Fatal("canonical bytes differ from Python vector")
			}
			digest := sha256.Sum256(canonical)
			if hex.EncodeToString(digest[:]) != vector.Digest {
				t.Fatal("canonical digest differs")
			}
			key, err := signing.FromSeed(bytes.Repeat([]byte{c.seed}, 32))
			if err != nil {
				t.Fatal(err)
			}
			if !signing.VerifyCanonical(key.Public(), c.document.Unsigned(), envelope.Signature) {
				t.Fatal("signature verification failed")
			}
			signature, err := key.SignCanonical(c.document.Unsigned())
			if err != nil || signature != envelope.Signature {
				t.Fatal("deterministic signature differs", err)
			}
		})
	}
}
