package export

import (
	"encoding/json"
	"errors"
	"fmt"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/signing"
)

const (
	// DerivedKind identifies share-export provenance (not a raw evidence/receipt doc).
	DerivedKind = "agentshield.export.derived/v1"
	// AttestationShareProjectionOnly is honest about what the seal covers.
	AttestationShareProjectionOnly = "share_projection_only"
)

// ErrUnsigned means the bundle has no usable derived signature.
var ErrUnsigned = errors.New("export: unsigned derived bundle")

// ErrTampered means the derived signature does not match the projection body.
var ErrTampered = errors.New("export: derived signature verification failed")

// Seal attaches derived_from provenance and an independent local_canonical/v1
// signature over the redacted bundle. Call after Build; requires Key identity.
// Receipt/admission signatures must not be copied onto Signature.
func Seal(key *signing.Key, b *Bundle) error {
	if key == nil {
		return errors.New("export: seal requires signing key")
	}
	if b == nil {
		return errors.New("export: nil bundle")
	}
	if b.Format == "" {
		b.Format = Format
	}
	if b.PrivacyProfile == "" {
		b.PrivacyProfile = PrivacyProfileID
	}
	if b.Identity.PublicKeyBase64 == "" {
		b.Identity.PublicKeyBase64 = key.PublicBase64()
	}
	b.DerivedFrom = deriveFrom(b)
	b.SigningSchema = signing.SchemaLocalCanonicalV1
	b.Signature = ""
	m, err := bundleMap(*b)
	if err != nil {
		return err
	}
	m, err = signing.WithSigningSchema(m, signing.SchemaLocalCanonicalV1)
	if err != nil {
		return err
	}
	sig, err := key.SignCanonical(m)
	if err != nil {
		return err
	}
	b.Signature = sig
	b.SigningSchema = signing.SchemaLocalCanonicalV1
	return nil
}

func deriveFrom(b *Bundle) *DerivedFrom {
	d := &DerivedFrom{
		Kind:             DerivedKind,
		AttestationScope: AttestationShareProjectionOnly,
		SourceCount:      len(b.Receipts),
	}
	if n := len(b.Receipts); n > 0 {
		tip := b.Receipts[n-1]
		d.SourceTipHash = tip.Hash
		d.SourceSeq = tip.Seq
	}
	return d
}

// Verify checks the independent derived seal. An empty signature is unsigned.
// Passing a receipt/hash-chain signature as Signature must fail.
func Verify(pub []byte, b Bundle) error {
	if b.Signature == "" {
		return ErrUnsigned
	}
	m, err := bundleMap(b)
	if err != nil {
		return err
	}
	if err := signing.VerifyDocument(pub, m, b.Signature); err != nil {
		return fmt.Errorf("%w: %v", ErrTampered, err)
	}
	if b.DerivedFrom == nil || b.DerivedFrom.Kind != DerivedKind {
		return fmt.Errorf("%w: missing or wrong derived_from.kind", ErrTampered)
	}
	if b.DerivedFrom.AttestationScope != AttestationShareProjectionOnly {
		return fmt.Errorf("%w: unexpected attestation_scope", ErrTampered)
	}
	return nil
}

func bundleMap(b Bundle) (map[string]any, error) {
	raw, err := json.Marshal(b)
	if err != nil {
		return nil, err
	}
	dec, err := canon.Decode(raw)
	if err != nil {
		return nil, err
	}
	m, ok := dec.(map[string]any)
	if !ok {
		return nil, errors.New("export: canonical body must be object")
	}
	delete(m, "signature")
	return m, nil
}
