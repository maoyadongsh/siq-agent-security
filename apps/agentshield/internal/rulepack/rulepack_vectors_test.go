package rulepack

import (
	"bytes"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

type rulepackSigFixtureFile struct {
	Schema            string           `json:"schema"`
	SigningSchema     string           `json:"signing_schema"`
	PublicKeyB64      string           `json:"public_key_b64"`
	CrossContractNote map[string]any   `json:"cross_contract_note"`
	Vectors           []rulepackSigVec `json:"vectors"`
}

type rulepackSigVec struct {
	Name          string         `json:"name"`
	Document      map[string]any `json:"document"`
	CanonicalUTF8 string         `json:"canonical_utf8"`
	SignatureB64  string         `json:"signature_b64"`
}

func loadRulepackSigFixtures(t *testing.T) rulepackSigFixtureFile {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	path := filepath.Clean(filepath.Join(
		filepath.Dir(thisFile),
		"..", "..", "..", "..",
		"packages", "contracts", "fixtures", "rulepack_signature_vectors_v1.json",
	))
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var doc rulepackSigFixtureFile
	if err := dec.Decode(&doc); err != nil {
		t.Fatal(err)
	}
	if doc.Schema != "rulepack_signature_vectors/v1" {
		t.Fatalf("schema %q", doc.Schema)
	}
	if doc.SigningSchema != "local_canonical/v1" {
		t.Fatalf("signing_schema %q", doc.SigningSchema)
	}
	return doc
}

func TestRulepackSignatureVectorsV1(t *testing.T) {
	doc := loadRulepackSigFixtures(t)
	pubRaw, err := base64.StdEncoding.DecodeString(doc.PublicKeyB64)
	if err != nil || len(pubRaw) != ed25519.PublicKeySize {
		t.Fatalf("bad public key: %v", err)
	}
	pub := ed25519.PublicKey(pubRaw)
	cross := doc.CrossContractNote
	evidenceUTF8, _ := cross["evidence_utf8_canonical"].(string)
	if evidenceUTF8 == "" {
		t.Fatal("missing cross_contract_note.evidence_utf8_canonical")
	}

	for _, v := range doc.Vectors {
		v := v
		t.Run(v.Name, func(t *testing.T) {
			got, err := canon.Marshal(v.Document)
			if err != nil {
				t.Fatal(err)
			}
			if string(got) != v.CanonicalUTF8 {
				t.Fatalf("canon mismatch\n got %s\nwant %s", got, v.CanonicalUTF8)
			}
			sig, err := base64.StdEncoding.Strict().DecodeString(v.SignatureB64)
			if err != nil {
				t.Fatal(err)
			}
			if !ed25519.Verify(pub, got, sig) {
				t.Fatal("signature verify failed")
			}
			bad := append([]byte(nil), got...)
			bad[len(bad)/2] ^= 0x01
			if ed25519.Verify(pub, bad, sig) {
				t.Fatal("tampered accepted")
			}
			if v.Name == "chinese_html_confidence" {
				if string(got) == evidenceUTF8 {
					t.Fatal("local ASCII canon must differ from evidence UTF-8")
				}
				if bytes.Contains(got, []byte("安全")) {
					t.Fatal("ensure_ascii=True must escape non-ASCII")
				}
			}
		})
	}

	// Sidecar wire form: VerifySignature over on-disk JSON + .sig
	t.Run("sidecar_verify_signature", func(t *testing.T) {
		vec := doc.Vectors[0]
		dir := t.TempDir()
		path := filepath.Join(dir, "pack.json")
		raw, err := json.Marshal(vec.Document)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, raw, 0o600); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path+".sig", []byte(vec.SignatureB64+"\n"), 0o600); err != nil {
			t.Fatal(err)
		}
		if err := VerifySignature(pub, path, raw); err != nil {
			t.Fatal(err)
		}
	})
}
