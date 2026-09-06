package signing

import (
	"errors"
	"fmt"
)

// Signing schema identifiers select the canonicalization + verify contract.
// Changing bytes or field sets requires a new schema id, dual-read consumers,
// then writer switch (DEV09 / signing-inventory-v1.md).
const (
	SchemaLocalCanonicalV1   = "local_canonical/v1"    // admission, grant, rulepack .sig (SignCanonical)
	SchemaTaskEnvelopeV1     = "task_envelope/v1"      // same ASCII canon as local; Edge task path
	SchemaEvidenceUTF8V1     = "evidence_utf8/v1"      // NOT verifiable via VerifyCanonical
	SchemaReceiptHashChainV1 = "receipt_hash_chain/v1" // body = local canon → sha256 hex; sig = Ed25519(hex ASCII)
)

// ErrUnknownSigningSchema means the schema id is not registered.
var ErrUnknownSigningSchema = errors.New("signing: unknown signing schema")

// ErrSchemaNotSupportedHere means the schema is known but this verifier cannot
// apply it (e.g. evidence UTF-8 must not use local ASCII VerifyCanonical).
var ErrSchemaNotSupportedHere = errors.New("signing: signing schema not supported by this verifier")

// NormalizeSigningSchema returns the canonical schema id or an error.
func NormalizeSigningSchema(schema string) (string, error) {
	switch schema {
	case SchemaLocalCanonicalV1, SchemaTaskEnvelopeV1:
		return schema, nil
	case SchemaEvidenceUTF8V1:
		return "", fmt.Errorf("%w: %s (use evidence UTF-8 verifier)", ErrSchemaNotSupportedHere, schema)
	case SchemaReceiptHashChainV1:
		return "", fmt.Errorf("%w: %s (use receipt.ContentHash + VerifyBytes over hash hex)", ErrSchemaNotSupportedHere, schema)
	case "":
		return "", fmt.Errorf("%w: empty", ErrUnknownSigningSchema)
	default:
		return "", fmt.Errorf("%w: %q", ErrUnknownSigningSchema, schema)
	}
}

// SupportsLocalCanonical is true when VerifyCanonical / SignCanonical apply.
func SupportsLocalCanonical(schema string) bool {
	s, err := NormalizeSigningSchema(schema)
	return err == nil && (s == SchemaLocalCanonicalV1 || s == SchemaTaskEnvelopeV1)
}
