package signing

import (
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
)

func TestLocalDocSignatureVectorsV1(t *testing.T) {
	raw, err := os.ReadFile(localDocFixturePath(t))
	if err != nil {
		t.Fatal(err)
	}
	root, err := canon.Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	m := root.(map[string]any)
	if m["schema"] != "local_doc_signature_vectors/v1" {
		t.Fatalf("unexpected fixture schema %v", m["schema"])
	}
	cross := m["cross_contract_note"].(map[string]any)
	evidenceUTF8, _ := cross["evidence_utf8_canonical"].(string)
	if evidenceUTF8 == "" {
		t.Fatal("missing cross_contract_note.evidence_utf8_canonical")
	}
	var unicodeCanon string
	for _, item := range m["vectors"].([]any) {
		vec := item.(map[string]any)
		name := vec["name"].(string)
		schema := vec["signing_schema"].(string)
		doc := vec["document"].(map[string]any)
		wantCanon := vec["canonical_utf8"].(string)
		sigHex := vec["signature_hex"].(string)
		pubB64 := vec["public_key_b64"].(string)

		got, err := canon.Marshal(doc)
		if err != nil {
			t.Fatalf("%s: marshal: %v", name, err)
		}
		if string(got) != wantCanon {
			t.Fatalf("%s: canon mismatch\n got %s\nwant %s", name, got, wantCanon)
		}
		pub, err := base64.StdEncoding.DecodeString(pubB64)
		if err != nil {
			t.Fatal(err)
		}
		if err := VerifyWithSchema(schema, pub, doc, sigHex); err != nil {
			t.Fatalf("%s: verify: %v", name, err)
		}
		if err := VerifyWithSchema(SchemaEvidenceUTF8V1, pub, doc, sigHex); err == nil {
			t.Fatalf("%s: evidence schema must not verify via local router", name)
		}
		if name == "chinese_html_float_null" {
			unicodeCanon = wantCanon
		}
	}
	if unicodeCanon == "" || unicodeCanon == evidenceUTF8 {
		t.Fatal("local ASCII canon must differ from evidence UTF-8 for unicode vector")
	}
}

func TestSigningSchemaRouterRejectsUnknown(t *testing.T) {
	if _, err := NormalizeSigningSchema("local_canonical/v2"); !errors.Is(err, ErrUnknownSigningSchema) {
		t.Fatalf("v2 must be unknown until dual-read registers it: %v", err)
	}
	if _, err := NormalizeSigningSchema(SchemaEvidenceUTF8V1); !errors.Is(err, ErrSchemaNotSupportedHere) {
		t.Fatalf("evidence schema must not be accepted by local verifier: %v", err)
	}
	if _, err := NormalizeSigningSchema(SchemaReceiptHashChainV1); !errors.Is(err, ErrSchemaNotSupportedHere) {
		t.Fatalf("receipt hash-chain must not use VerifyCanonical router: %v", err)
	}
	if !SupportsLocalCanonical(SchemaLocalCanonicalV1) || SupportsLocalCanonical(SchemaEvidenceUTF8V1) {
		t.Fatal("SupportsLocalCanonical mismatch")
	}
	if err := VerifyWithSchema("local_canonical/v2", nil, map[string]any{"a": 1}, "00"); !errors.Is(err, ErrUnknownSigningSchema) {
		t.Fatalf("unknown schema must fail before crypto: %v", err)
	}
}

func localDocFixturePath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("caller")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "..", ".."))
	return filepath.Join(root, "packages", "contracts", "fixtures", "local_doc_signature_vectors_v1.json")
}
