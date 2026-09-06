package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/edge/agent/canon"
)

type evidenceEmbedFixtureFile struct {
	Schema            string                   `json:"schema"`
	PublicKeyPEM      string                   `json:"public_key_pem"`
	SeedB64           string                   `json:"seed_b64"`
	CrossContractNote map[string]string        `json:"cross_contract_note"`
	Vectors           []evidenceEmbedVector    `json:"vectors"`
}

type evidenceEmbedVector struct {
	Name          string         `json:"name"`
	Expect        string         `json:"expect"`
	Document      map[string]any `json:"document"`
	CanonicalUTF8 string         `json:"canonical_utf8"`
	SignatureHex  string         `json:"signature_hex"`
}

func loadEvidenceEmbedFixtures(t *testing.T) evidenceEmbedFixtureFile {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	path := filepath.Clean(filepath.Join(filepath.Dir(thisFile), "..", "..", "packages", "contracts", "fixtures", "evidence_embedded_schema_vectors_v1.json"))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var doc evidenceEmbedFixtureFile
	if err := dec.Decode(&doc); err != nil {
		t.Fatal(err)
	}
	if doc.Schema != "evidence_embedded_schema_vectors/v1" {
		t.Fatalf("schema %q", doc.Schema)
	}
	return doc
}

func TestEvidenceEmbeddedSchemaVectorsV1(t *testing.T) {
	doc := loadEvidenceEmbedFixtures(t)
	if doc.CrossContractNote["legacy_canonical_utf8"] == doc.CrossContractNote["embedded_canonical_utf8"] {
		t.Fatal("legacy and embedded canon must differ")
	}
	signer, err := NewSignerFromSeed(doc.SeedB64)
	if err != nil {
		t.Fatal(err)
	}
	for _, v := range doc.Vectors {
		v := v
		t.Run(v.Name, func(t *testing.T) {
			got, err := canon.MarshalUTF8(v.Document)
			if err != nil {
				t.Fatal(err)
			}
			if string(got) != v.CanonicalUTF8 {
				t.Fatalf("canon mismatch\n got %s\nwant %s", got, v.CanonicalUTF8)
			}
			sig, err := signer.Sign(got)
			if err != nil {
				t.Fatal(err)
			}
			if sig != v.SignatureHex {
				t.Fatalf("signature mismatch\n got %s\nwant %s", sig, v.SignatureHex)
			}
			switch v.Expect {
			case "accept":
				if err := VerifySignature(doc.PublicKeyPEM, got, v.SignatureHex); err != nil {
					t.Fatal(err)
				}
				schema, _ := v.Document["signing_schema"].(string)
				if schema != "" && schema != EvidenceSigningSchemaV1 {
					t.Fatalf("accept vector unexpected schema %q", schema)
				}
			case "reject_schema":
				// Producer signed the bytes; Edge SealEvidence never emits these.
				// Control-plane normalize_evidence_signing_schema rejects them.
				schema := v.Document["signing_schema"]
				if schema == nil || schema == "" || schema == EvidenceSigningSchemaV1 {
					t.Fatalf("reject_schema vector needs non-evidence schema, got %#v", schema)
				}
			default:
				t.Fatalf("unknown expect %q", v.Expect)
			}
		})
	}
}
