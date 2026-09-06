package export

import (
	"bytes"
	"errors"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/ledger"
	"siq-agent-security/apps/agentshield/internal/receipt"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func sealedDemo(t *testing.T) (*signing.Key, Bundle) {
	t.Helper()
	key, err := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	r := receipt.Receipt{
		Platform: "hermes", SessionID: "s1", Tool: "read_file", Action: "allow",
		Reason: "granted", EnforcementMode: "block",
	}
	if err := chain.Append(&r); err != nil {
		t.Fatal(err)
	}
	recs, err := chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	b := Build(Input{
		Now:  "2026-09-06T00:00:00Z",
		Mode: "block",
		Key:  key,
		Snap: ledger.Snapshot{Receipts: recs},
	})
	if err := Seal(key, &b); err != nil {
		t.Fatal(err)
	}
	return key, b
}

func TestSealVerifyRoundTrip(t *testing.T) {
	key, b := sealedDemo(t)
	if b.Signature == "" || b.SigningSchema != signing.SchemaLocalCanonicalV1 {
		t.Fatalf("seal missing: schema=%q sig_len=%d", b.SigningSchema, len(b.Signature))
	}
	if b.DerivedFrom == nil || b.DerivedFrom.Kind != DerivedKind {
		t.Fatalf("derived_from: %+v", b.DerivedFrom)
	}
	if b.DerivedFrom.AttestationScope != AttestationShareProjectionOnly {
		t.Fatalf("scope: %q", b.DerivedFrom.AttestationScope)
	}
	if b.DerivedFrom.SourceCount != 1 || b.DerivedFrom.SourceTipHash == "" {
		t.Fatalf("source tip: %+v", b.DerivedFrom)
	}
	if err := Verify(key.Public(), b); err != nil {
		t.Fatal(err)
	}
}

func TestSealRejectsTamper(t *testing.T) {
	key, b := sealedDemo(t)
	b.Receipts[0].Reason = "tampered"
	if err := Verify(key.Public(), b); !errors.Is(err, ErrTampered) {
		t.Fatalf("want ErrTampered, got %v", err)
	}
}

func TestUnsignedFails(t *testing.T) {
	key, b := sealedDemo(t)
	b.Signature = ""
	if err := Verify(key.Public(), b); !errors.Is(err, ErrUnsigned) {
		t.Fatalf("want ErrUnsigned, got %v", err)
	}
}

func TestReceiptSignatureMustNotVerifyAsExport(t *testing.T) {
	key, err := signing.FromSeed(bytes.Repeat([]byte{9}, 32))
	if err != nil {
		t.Fatal(err)
	}
	chain, err := receipt.OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	r := receipt.Receipt{
		Platform: "hermes", SessionID: "s1", Tool: "read_file", Action: "allow",
		Reason: "granted", EnforcementMode: "block",
	}
	if err := chain.Append(&r); err != nil {
		t.Fatal(err)
	}
	recs, err := chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	b := Build(Input{
		Now:  "2026-09-06T00:00:00Z",
		Mode: "block",
		Key:  key,
		Snap: ledger.Snapshot{Receipts: recs},
	})
	// Cross-contract: paste the receipt hash-chain signature onto the export.
	b.DerivedFrom = deriveFrom(&b)
	b.SigningSchema = signing.SchemaLocalCanonicalV1
	b.Signature = recs[0].Sig
	if b.Signature == "" {
		t.Fatal("fixture receipt must be signed")
	}
	if err := Verify(key.Public(), b); err == nil {
		t.Fatal("receipt hash-chain sig must not verify as derived export seal")
	} else if !errors.Is(err, ErrTampered) {
		t.Fatalf("want ErrTampered, got %v", err)
	}
}

func TestSealedMarshalKeepsPrivacy(t *testing.T) {
	key, b := sealedDemo(t)
	raw, err := MarshalJSONBytes(b)
	if err != nil {
		t.Fatal(err)
	}
	s := string(raw)
	if !strings.Contains(s, `"derived_from"`) || !strings.Contains(s, DerivedKind) {
		t.Fatalf("derived_from missing in JSON: %s", s[:min(200, len(s))])
	}
	if !strings.Contains(s, `"signature"`) {
		t.Fatal("signature field required")
	}
	if ContainsForbidden(raw, "signing.seed", "params_excerpt") {
		t.Fatal("forbidden material")
	}
	_ = key
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}
