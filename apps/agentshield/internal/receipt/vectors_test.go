package receipt

import (
	"bytes"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func receiptVectorsPath(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("no caller")
	}
	// apps/agentshield/internal/receipt → repo root
	root := filepath.Clean(filepath.Join(filepath.Dir(file), "..", "..", "..", ".."))
	return filepath.Join(root, "packages", "contracts", "fixtures", "receipt_signature_vectors_v1.json")
}

func TestReceiptSignatureVectors(t *testing.T) {
	raw, err := os.ReadFile(receiptVectorsPath(t))
	if err != nil {
		t.Fatal(err)
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var fix struct {
		Schema        string           `json:"schema"`
		SigningSchema string           `json:"signing_schema"`
		Genesis       string           `json:"genesis_prev_hash"`
		Cross         map[string]any   `json:"cross_contract_note"`
		Vectors       []map[string]any `json:"vectors"`
	}
	if err := dec.Decode(&fix); err != nil {
		t.Fatal(err)
	}
	if fix.Schema != "receipt_signature_vectors/v1" {
		t.Fatalf("schema %s", fix.Schema)
	}
	if fix.SigningSchema != signing.SchemaReceiptHashChainV1 {
		t.Fatalf("signing_schema %s", fix.SigningSchema)
	}
	if fix.Genesis != GenesisPrev {
		t.Fatalf("genesis %s", fix.Genesis)
	}
	if _, err := signing.NormalizeSigningSchema(fix.SigningSchema); !errors.Is(err, signing.ErrSchemaNotSupportedHere) {
		t.Fatalf("receipt schema must not route through VerifyWithSchema: %v", err)
	}

	byName := map[string]map[string]any{}
	for _, vec := range fix.Vectors {
		name, _ := vec["name"].(string)
		byName[name] = vec

		pubB64, _ := vec["public_key_b64"].(string)
		pub, err := base64.StdEncoding.DecodeString(pubB64)
		if err != nil || len(pub) != 32 {
			t.Fatalf("%s: bad pubkey", name)
		}
		doc, ok := vec["document"].(map[string]any)
		if !ok {
			t.Fatalf("%s: document missing", name)
		}
		wantCanon, _ := vec["canonical_utf8"].(string)
		wantHash, _ := vec["content_hash_hex"].(string)
		sigHex, _ := vec["signature_hex"].(string)

		gotCanon, err := canon.Marshal(doc)
		if err != nil {
			t.Fatalf("%s: canon: %v", name, err)
		}
		if string(gotCanon) != wantCanon {
			t.Fatalf("%s: canonical mismatch\n got %s\nwant %s", name, gotCanon, wantCanon)
		}
		sum := sha256.Sum256(gotCanon)
		gotHash := hex.EncodeToString(sum[:])
		if gotHash != wantHash {
			t.Fatalf("%s: content hash %s want %s", name, gotHash, wantHash)
		}
		if !VerifyHashSignature(pub, wantHash, sigHex) {
			t.Fatalf("%s: VerifyHashSignature failed", name)
		}
		// SignCanonical(body) must not verify as hash-chain sig.
		if signing.VerifyBytes(pub, gotCanon, sigHex) {
			t.Fatalf("%s: signature must not verify over canonical body bytes", name)
		}
	}

	crossWrong, _ := fix.Cross["sign_canonical_of_body_hex"].(string)
	gen := byName["genesis_chinese_html"]
	if crossWrong == "" || crossWrong == gen["signature_hex"] {
		t.Fatal("cross_contract_note must record distinct SignCanonical(body) hex")
	}

	link := byName["chained_second"]
	prevName, _ := link["prev_must_equal_hash_of"].(string)
	prev := byName[prevName]
	if link["document"].(map[string]any)["prev_hash"] != prev["content_hash_hex"] {
		t.Fatal("chained_second.prev_hash must equal genesis content_hash")
	}

	// Full Receipt struct path for schema-shaped vectors.
	for _, name := range []string{"genesis_chinese_html", "chained_second"} {
		vec := byName[name]
		docRaw, err := json.Marshal(vec["document"])
		if err != nil {
			t.Fatal(err)
		}
		var r Receipt
		if err := json.Unmarshal(docRaw, &r); err != nil {
			t.Fatalf("%s: unmarshal: %v", name, err)
		}
		h, err := ContentHash(r)
		if err != nil {
			t.Fatal(err)
		}
		if h != vec["content_hash_hex"] {
			t.Fatalf("%s: ContentHash %s want %s", name, h, vec["content_hash_hex"])
		}
	}
}
