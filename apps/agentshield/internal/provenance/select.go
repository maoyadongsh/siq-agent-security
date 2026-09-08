package provenance

import (
	"siq-agent-security/apps/agentshield/internal/signing"
	"time"
)

// Select proves an explicit JSON selection, not arbitrary model influence.
// The caller supplies the original object, never an asserted selected value.
func (s *Store) Select(parentID, pointer string, scope Scope, original any, now time.Time) (Assertion, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	parent, err := s.loadAssertion(parentID, scope)
	if err != nil {
		return Assertion{}, err
	}
	node, err := s.resolveNode(parent, scope, now, 1, newWalk())
	if err != nil {
		return Assertion{}, err
	}
	parent = node.assertion
	if err := ValidateReport(parent.Source); err != nil {
		return Assertion{}, err
	}
	issuer, err := s.getIssuer(parent.Issuer)
	if err != nil {
		return Assertion{}, err
	}
	if issuer.LocalKeyRef != "local-state" {
		return Assertion{}, failure("provenance_issuer_untrusted")
	}
	digest, err := ContentDigest(original)
	if err != nil {
		return Assertion{}, err
	}
	if digest != parent.ContentDigest {
		return Assertion{}, failure("provenance_content_mismatch")
	}
	value, ok := PointerValue(original, pointer)
	if !ok {
		return Assertion{}, failure("provenance_missing")
	}
	selectedDigest, err := ContentDigest(value)
	if err != nil {
		return Assertion{}, err
	}
	identity, _ := ContentDigest(map[string]any{"parent_id": parentID, "pointer": pointer, "scope": unsignedRecord(scope)})
	child := Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: "sel-" + identity[:40], Source: Source{Type: parent.Source.Type, SourceID: "selection:" + identity, Trust: parent.Source.Trust}, Scope: scope, ContentDigest: selectedDigest, Parents: []string{parentID}, Derivation: "transformed", IssuedAt: parent.IssuedAt, ExpiresAt: parent.ExpiresAt, Issuer: parent.Issuer, SigningSchema: signing.SchemaLocalCanonicalV1}
	if parent.Derivation == "unknown" {
		child.Derivation = "unknown"
	}
	child.Signature, err = s.key.SignCanonical(child.Unsigned())
	if err != nil {
		return Assertion{}, err
	}
	return s.importAssertion(child, now)
}
