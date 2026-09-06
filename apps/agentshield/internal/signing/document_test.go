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

func TestLocalDocEmbeddedSchemaVectorsV1(t *testing.T) {
	raw, err := os.ReadFile(embeddedSchemaFixturePath(t))
	if err != nil {
		t.Fatal(err)
	}
	root, err := canon.Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	m := root.(map[string]any)
	if m["schema"] != "local_doc_embedded_schema_vectors/v1" {
		t.Fatalf("unexpected fixture schema %v", m["schema"])
	}
	cross := m["cross_note"].(map[string]any)
	if cross["legacy_vs_embedded_must_differ"] != true {
		t.Fatal("cross_note must require legacy≠embedded")
	}
	if cross["legacy_canonical_utf8"] == cross["embedded_canonical_utf8"] {
		t.Fatal("embedding signing_schema must change canonical bytes")
	}

	for _, item := range m["vectors"].([]any) {
		vec := item.(map[string]any)
		name := vec["name"].(string)
		expect := vec["expect"].(string)
		doc := vec["document"].(map[string]any)
		sigHex := vec["signature_hex"].(string)
		pubB64 := vec["public_key_b64"].(string)
		pub, err := base64.StdEncoding.DecodeString(pubB64)
		if err != nil {
			t.Fatal(err)
		}

		switch expect {
		case "verify_ok":
			wantCanon := vec["canonical_utf8"].(string)
			got, err := canon.Marshal(doc)
			if err != nil {
				t.Fatalf("%s: marshal: %v", name, err)
			}
			if string(got) != wantCanon {
				t.Fatalf("%s: canon mismatch\n got %s\nwant %s", name, got, wantCanon)
			}
			schema, err := DocSigningSchema(doc)
			if err != nil {
				t.Fatalf("%s: schema: %v", name, err)
			}
			if doc["signing_schema"] == nil && schema != SchemaLocalCanonicalV1 {
				t.Fatalf("%s: legacy default want local_canonical/v1 got %s", name, schema)
			}
			if err := VerifyDocument(pub, doc, sigHex); err != nil {
				t.Fatalf("%s: verify: %v", name, err)
			}
		case "schema_not_supported":
			if err := VerifyDocument(pub, doc, sigHex); !errors.Is(err, ErrSchemaNotSupportedHere) {
				t.Fatalf("%s: want ErrSchemaNotSupportedHere, got %v", name, err)
			}
		case "unknown_schema":
			if err := VerifyDocument(pub, doc, sigHex); !errors.Is(err, ErrUnknownSigningSchema) {
				t.Fatalf("%s: want ErrUnknownSigningSchema, got %v", name, err)
			}
		case "verify_fail":
			if err := VerifyDocument(pub, doc, sigHex); err == nil {
				t.Fatalf("%s: legacy sig must not verify embedded body", name)
			} else if errors.Is(err, ErrUnknownSigningSchema) || errors.Is(err, ErrSchemaNotSupportedHere) {
				t.Fatalf("%s: expected crypto failure, got %v", name, err)
			}
		default:
			t.Fatalf("%s: unknown expect %q", name, expect)
		}
	}
}

func TestWithSigningSchemaRejectsUnsupported(t *testing.T) {
	doc := map[string]any{"a": 1}
	if _, err := WithSigningSchema(doc, SchemaEvidenceUTF8V1); !errors.Is(err, ErrSchemaNotSupportedHere) {
		t.Fatalf("got %v", err)
	}
	out, err := WithSigningSchema(doc, SchemaLocalCanonicalV1)
	if err != nil {
		t.Fatal(err)
	}
	if out["signing_schema"] != SchemaLocalCanonicalV1 {
		t.Fatalf("embedded field missing: %v", out)
	}
	if _, ok := doc["signing_schema"]; ok {
		t.Fatal("WithSigningSchema must not mutate input")
	}
}

func embeddedSchemaFixturePath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("caller")
	}
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "..", ".."))
	return filepath.Join(root, "packages", "contracts", "fixtures", "local_doc_embedded_schema_vectors_v1.json")
}
