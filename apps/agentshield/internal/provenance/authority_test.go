package provenance

import (
	"bytes"
	"siq-agent-security/apps/agentshield/internal/signing"
	"testing"
	"time"
)

func authorityFixture(t *testing.T) (Assertion, Issuer, *signing.Key, time.Time) {
	t.Helper()
	key, err := signing.FromSeed(bytes.Repeat([]byte{3}, 32))
	if err != nil {
		t.Fatal(err)
	}
	scope := Scope{Platform: "hermes", SessionID: "s1", AgentID: "a1", TaskID: "t1"}
	digest, _ := ContentDigest("recipient@example.test")
	a := Assertion{SchemaVersion: "provenance-assertion/v1", ProvenanceID: "prov-1", Source: Source{Type: "USER", SourceID: "approved-form", Trust: "authoritative"}, Scope: scope, ContentDigest: digest, Parents: []string{}, Derivation: "direct", IssuedAt: "2026-09-08T00:00:00Z", ExpiresAt: "2026-09-08T01:00:00Z", Issuer: "issuer-1", SigningSchema: signing.SchemaLocalCanonicalV1}
	a.Signature, err = key.SignCanonical(a.Unsigned())
	if err != nil {
		t.Fatal(err)
	}
	i := Issuer{IssuerID: "issuer-1", LocalKeyRef: "local-state", AllowedSourceTypes: []string{"USER"}, MaxTrustLevel: "authoritative", Scope: scope, ExpiresAt: "2026-09-08T02:00:00Z"}
	return a, i, key, time.Date(2026, 9, 8, 0, 30, 0, 0, time.UTC)
}
func TestAuthorityVerifiesLocalAndExternalIssuers(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	if err := a.VerifyAuthority(i, key.Public(), a.Scope, now); err != nil {
		t.Fatal(err)
	}
	i.PublicKey, i.LocalKeyRef = key.PublicBase64(), ""
	if err := a.VerifyAuthority(i, nil, a.Scope, now); err != nil {
		t.Fatal("external registry key unsupported", err)
	}
	i.LocalKeyRef = "local-state"
	if a.VerifyAuthority(i, key.Public(), a.Scope, now) == nil {
		t.Fatal("ambiguous key authority accepted")
	}
}
func TestAuthorityRejectsForgeryScopeExpiryAndRevocation(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	for name, edit := range map[string]func(*Assertion, *Issuer){
		"signature":         func(a *Assertion, _ *Issuer) { a.Signature = string(bytes.Repeat([]byte{'0'}, 128)) },
		"content":           func(a *Assertion, _ *Issuer) { a.ContentDigest = string(bytes.Repeat([]byte{'b'}, 64)) },
		"source_laundering": func(a *Assertion, _ *Issuer) { a.Source.SourceID = "forged" },
		"scope_session":     func(a *Assertion, _ *Issuer) { a.Scope.SessionID = "s2" },
		"scope_task":        func(a *Assertion, _ *Issuer) { a.Scope.TaskID = "t2" },
		"registry_scope":    func(_ *Assertion, i *Issuer) { i.Scope.AgentID = "a2" },
		"issuer_revoked":    func(_ *Assertion, i *Issuer) { i.RevokedAt = "2026-09-08T00:10:00Z" },
		"issuer_ceiling":    func(_ *Assertion, i *Issuer) { i.MaxTrustLevel = "untrusted" },
		"issuer_source":     func(_ *Assertion, i *Issuer) { i.AllowedSourceTypes = []string{"MCP"} },
		"expiry":            func(a *Assertion, _ *Issuer) { a.ExpiresAt = "2026-09-08T00:30:00Z" },
		"future":            func(a *Assertion, _ *Issuer) { a.IssuedAt = "2026-09-08T00:31:00Z" },
		"issuer_expiry":     func(_ *Assertion, i *Issuer) { i.ExpiresAt = "2026-09-08T00:45:00Z" },
		"self_parent":       func(a *Assertion, _ *Issuer) { a.Derivation = "transformed"; a.Parents = []string{a.ProvenanceID} },
		"unknown_key":       func(_ *Assertion, i *Issuer) { i.LocalKeyRef = "caller-key" },
	} {
		t.Run(name, func(t *testing.T) {
			bad, issuer := a, i
			edit(&bad, &issuer)
			if bad.VerifyAuthority(issuer, key.Public(), a.Scope, now) == nil {
				t.Fatal("invalid node gained authority")
			}
		})
	}
	if a.VerifyAuthority(i, key.Public(), a.Scope, now.Add(30*time.Minute)) == nil {
		t.Fatal("expiry boundary accepted")
	}
}
