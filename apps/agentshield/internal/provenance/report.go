package provenance

import (
	"siq-agent-security/apps/agentshield/internal/signing"
	"time"
)

// Report is the unprivileged issuance path. Neither issuer, scope authority nor
// the contents' truth may be supplied as a caller privilege assertion.
func (s *Store) Report(reportID string, source Source, scope Scope, content any, authorityExpires, now time.Time) (Assertion, error) {
	storeMu.Lock()
	defer storeMu.Unlock()
	if source.Trust == "" {
		source.Trust = "untrusted"
	}
	if err := ValidateReport(source); err != nil {
		return Assertion{}, err
	}
	if !identifier.MatchString(reportID) || !scope.valid() || !now.Before(authorityExpires) {
		return Assertion{}, failure("provenance_authority_invalid")
	}
	scopeDigest, _ := ContentDigest(unsignedRecord(scope))
	issuer := Issuer{IssuerID: "report-" + scopeDigest[:32], LocalKeyRef: "local-state", AllowedSourceTypes: []string{"MCP", "WEB", "TOOL", "AGENT", "UNKNOWN"}, MaxTrustLevel: "untrusted", Scope: scope, ExpiresAt: authorityExpires.UTC().Format(time.RFC3339)}
	if _, err := s.registerIssuer(issuer); err != nil {
		return Assertion{}, err
	}
	digest, err := ContentDigest(content)
	if err != nil {
		return Assertion{}, err
	}
	sourceDigest, err := ContentDigest(map[string]any{"type": source.Type, "source_id": source.SourceID})
	if err != nil {
		return Assertion{}, err
	}
	source.SourceID = "reported:" + sourceDigest
	idDigest, _ := ContentDigest(map[string]any{"report_id": reportID, "scope_digest": scopeDigest})
	id := "rep-" + idDigest[:40]
	// IssueAssertion remains the exclusive writer. Existing immutable identities
	// may only be reused after fresh issuer/graph verification.
	old, loadErr := s.loadAssertion(id, scope)
	if loadErr == nil {
		if old.Source != source || old.ContentDigest != digest || old.Issuer != issuer.IssuerID || old.Derivation != "direct" || len(old.Parents) != 0 {
			return Assertion{}, failure("provenance_immutable_conflict")
		}
		node, err := s.resolveNode(old, scope, now, 1, newWalk())
		return node.assertion, err
	}
	expires := now.Add(15 * time.Minute)
	if authorityExpires.Before(expires) {
		expires = authorityExpires
	}
	a := Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: id, Source: source, Scope: scope, ContentDigest: digest, Parents: []string{}, Derivation: "direct", IssuedAt: now.UTC().Format(time.RFC3339), ExpiresAt: expires.UTC().Format(time.RFC3339), Issuer: issuer.IssuerID}
	a.SigningSchema = signing.SchemaLocalCanonicalV1
	a.Signature, err = s.key.SignCanonical(a.Unsigned())
	if err != nil {
		return Assertion{}, err
	}
	return s.importAssertion(a, now)
}
