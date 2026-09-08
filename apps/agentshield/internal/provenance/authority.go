package provenance

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"regexp"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

var identifier = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)
var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (s Scope) valid() bool {
	for _, v := range []string{s.Platform, s.SessionID, s.AgentID, s.TaskID} {
		if v == "" || len(v) > 256 {
			return false
		}
	}
	return true
}
func (i Issuer) Validate() error {
	if !identifier.MatchString(i.IssuerID) || !i.Scope.valid() || (i.PublicKey == "") == (i.LocalKeyRef == "") {
		return failure("provenance_issuer_untrusted")
	}
	if i.LocalKeyRef != "" && i.LocalKeyRef != "local-state" {
		return failure("provenance_issuer_untrusted")
	}
	if i.PublicKey != "" {
		b, err := base64.StdEncoding.Strict().DecodeString(i.PublicKey)
		if err != nil || len(b) != ed25519.PublicKeySize {
			return failure("provenance_issuer_untrusted")
		}
	}
	c := Constraint{ParameterPath: "/value", AllowedSourceTypes: i.AllowedSourceTypes, MinimumTrust: i.MaxTrustLevel}
	if c.Validate() != nil {
		return failure("provenance_issuer_untrusted")
	}
	if _, err := time.Parse(time.RFC3339, i.ExpiresAt); err != nil {
		return failure("provenance_issuer_untrusted")
	}
	if i.RevokedAt != "" {
		if _, err := time.Parse(time.RFC3339, i.RevokedAt); err != nil {
			return failure("provenance_issuer_untrusted")
		}
	}
	return nil
}
func (a Assertion) Validate() error {
	if a.SchemaVersion != "provenance-assertion/v1" || !identifier.MatchString(a.ProvenanceID) || !identifier.MatchString(a.Issuer) || !a.Scope.valid() || !digestPattern.MatchString(a.ContentDigest) || a.SigningSchema != signing.SchemaLocalCanonicalV1 {
		return failure("provenance_authority_invalid")
	}
	if !sourceTypes[a.Source.Type] || a.Source.SourceID == "" || len(a.Source.SourceID) > 256 {
		return failure("provenance_authority_invalid")
	}
	if _, ok := trustRanks[a.Source.Trust]; !ok {
		return failure("provenance_authority_invalid")
	}
	if a.Parents == nil || len(a.Parents) > 32 {
		return failure("provenance_authority_invalid")
	}
	seen := map[string]bool{}
	for _, p := range a.Parents {
		if !identifier.MatchString(p) || p == a.ProvenanceID || seen[p] {
			return failure("provenance_authority_invalid")
		}
		seen[p] = true
	}
	switch a.Derivation {
	case "direct":
		if len(a.Parents) != 0 {
			return failure("provenance_authority_invalid")
		}
	case "transformed", "aggregated":
		if len(a.Parents) == 0 {
			return failure("provenance_authority_invalid")
		}
	case "unknown":
	default:
		return failure("provenance_authority_invalid")
	}
	issued, err := time.Parse(time.RFC3339, a.IssuedAt)
	expires, endErr := time.Parse(time.RFC3339, a.ExpiresAt)
	if err != nil || endErr != nil || !issued.Before(expires) {
		return failure("provenance_authority_invalid")
	}
	return nil
}

func (a Assertion) Unsigned() map[string]any {
	raw, _ := json.Marshal(a)
	var m map[string]any
	_ = json.Unmarshal(raw, &m)
	delete(m, "signature")
	return m
}

// VerifyAuthority authenticates one node against an already trusted registry
// entry. It does not validate its parents or prove the asserted data true.
func (a Assertion) VerifyAuthority(i Issuer, localPublic ed25519.PublicKey, scope Scope, now time.Time) error {
	if err := a.Validate(); err != nil {
		return err
	}
	if err := i.Validate(); err != nil {
		return err
	}
	if i.IssuerID != a.Issuer || i.RevokedAt != "" {
		return failure("provenance_issuer_untrusted")
	}
	if a.Scope != scope || i.Scope != scope {
		return failure("provenance_scope_mismatch")
	}
	issued, _ := time.Parse(time.RFC3339, a.IssuedAt)
	expires, _ := time.Parse(time.RFC3339, a.ExpiresAt)
	issuerExpires, _ := time.Parse(time.RFC3339, i.ExpiresAt)
	if now.Before(issued) {
		return failure("provenance_authority_invalid")
	}
	if !now.Before(expires) || !now.Before(issuerExpires) || expires.After(issuerExpires) {
		return failure("provenance_expired")
	}
	allowed := false
	for _, s := range i.AllowedSourceTypes {
		if s == a.Source.Type {
			allowed = true
		}
	}
	if !allowed || trustRanks[a.Source.Trust] > trustRanks[i.MaxTrustLevel] {
		return failure("provenance_issuer_untrusted")
	}
	public := localPublic
	if i.PublicKey != "" {
		raw, _ := base64.StdEncoding.Strict().DecodeString(i.PublicKey)
		public = ed25519.PublicKey(raw)
	}
	if len(public) != ed25519.PublicKeySize || signing.VerifyWithSchema(a.SigningSchema, public, a.Unsigned(), a.Signature) != nil {
		return failure("provenance_signature_invalid")
	}
	return nil
}
