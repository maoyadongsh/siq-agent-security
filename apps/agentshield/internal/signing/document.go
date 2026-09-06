package signing

import (
	"crypto/ed25519"
	"fmt"
)

// DocSigningSchema returns the schema used to verify a signed local document.
// Legacy bodies omit the field and default to local_canonical/v1. When the
// field is present it is part of the signed payload (DEV09-E); unsupported or
// unknown ids fail closed before crypto.
func DocSigningSchema(doc map[string]any) (string, error) {
	v, ok := doc["signing_schema"]
	if !ok || v == nil {
		return SchemaLocalCanonicalV1, nil
	}
	s, ok := v.(string)
	if !ok {
		return "", fmt.Errorf("%w: signing_schema must be string", ErrUnknownSigningSchema)
	}
	return NormalizeSigningSchema(s)
}

// VerifyDocument dual-reads: missing signing_schema → local_canonical/v1;
// embedded schema must Normalize and VerifyWithSchema over the full body
// (including the field). Does not strip the field before hashing.
func VerifyDocument(pub ed25519.PublicKey, doc map[string]any, sigHex string) error {
	schema, err := DocSigningSchema(doc)
	if err != nil {
		return err
	}
	return VerifyWithSchema(schema, pub, doc, sigHex)
}

// WithSigningSchema returns a shallow copy of doc with signing_schema set.
// Callers that opt into the embedded contract must sign the returned map
// (writer switch is separate from dual-read consumers).
func WithSigningSchema(doc map[string]any, schema string) (map[string]any, error) {
	norm, err := NormalizeSigningSchema(schema)
	if err != nil {
		return nil, err
	}
	out := make(map[string]any, len(doc)+1)
	for k, v := range doc {
		out[k] = v
	}
	out["signing_schema"] = norm
	return out, nil
}
