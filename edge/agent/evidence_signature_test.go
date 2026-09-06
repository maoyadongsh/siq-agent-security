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

type evidenceSigFixtureFile struct {
	Schema  string              `json:"schema"`
	Vectors []evidenceSigVector `json:"vectors"`
}

type evidenceSigVector struct {
	Name          string         `json:"name"`
	Kind          string         `json:"kind"`
	PublicKeyPEM  string         `json:"public_key_pem"`
	SeedB64       string         `json:"seed_b64"`
	Document      map[string]any `json:"document"`
	CanonicalUTF8 string         `json:"canonical_utf8"`
	SignatureHex  string         `json:"signature_hex"`
}

func loadEvidenceSigFixtures(t *testing.T) evidenceSigFixtureFile {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	path := filepath.Clean(filepath.Join(filepath.Dir(thisFile), "..", "..", "packages", "contracts", "fixtures", "evidence_signature_vectors_v1.json"))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var doc evidenceSigFixtureFile
	if err := dec.Decode(&doc); err != nil {
		t.Fatal(err)
	}
	if doc.Schema != "evidence_signature_vectors/v1" {
		t.Fatalf("schema %q", doc.Schema)
	}
	if len(doc.Vectors) == 0 {
		t.Fatal("empty evidence signature fixture set")
	}
	return doc
}

func TestEvidenceSignatureVectorsV1(t *testing.T) {
	doc := loadEvidenceSigFixtures(t)
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
			got2, err := CanonicalJSON(v.Document)
			if err != nil {
				t.Fatal(err)
			}
			if string(got2) != v.CanonicalUTF8 {
				t.Fatalf("CanonicalJSON mismatch\n got %s\nwant %s", got2, v.CanonicalUTF8)
			}
			signer, err := NewSignerFromSeed(v.SeedB64)
			if err != nil {
				t.Fatal(err)
			}
			sig, err := signer.Sign(got)
			if err != nil {
				t.Fatal(err)
			}
			if sig != v.SignatureHex {
				t.Fatalf("signature mismatch\n got %s\nwant %s", sig, v.SignatureHex)
			}
			if err := VerifySignature(v.PublicKeyPEM, got, v.SignatureHex); err != nil {
				t.Fatal(err)
			}
			bad := append([]byte(nil), got...)
			bad[len(bad)/2] ^= 0x01
			if err := VerifySignature(v.PublicKeyPEM, bad, v.SignatureHex); err == nil {
				t.Fatal("tampered payload accepted")
			}
		})
	}
}

func TestEvidenceCanonRejectsDefaultHTMLEscapeContract(t *testing.T) {
	doc := map[string]any{"msg": "<script>"}
	want := `{"msg":"<script>"}`
	got, err := CanonicalJSON(doc)
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != want {
		t.Fatalf("got %s", got)
	}
	raw, _ := json.Marshal(doc)
	if string(raw) == want {
		t.Fatal("expected encoding/json.Marshal to HTML-escape; fixture assumption broken")
	}
}

func TestEvidenceFloat100NativeMap(t *testing.T) {
	doc := map[string]any{"i": 100, "n": 100.0, "note": "x"}
	got, err := CanonicalJSON(doc)
	if err != nil {
		t.Fatal(err)
	}
	want := `{"i":100,"n":100.0,"note":"x"}`
	if string(got) != want {
		t.Fatalf("got %s want %s", got, want)
	}
}
