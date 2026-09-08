package provenance

import (
	"os"
	"sync"
	"testing"
	"time"
)

func TestIssuerStoreRestartRevocationAndImmutability(t *testing.T) {
	a, i, key, now := authorityFixture(t)
	dir := t.TempDir()
	s, err := Open(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	original, err := os.ReadFile(s.recordPath("provenance-issuers", i.IssuerID))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal("retry", err)
	}
	changed := i
	changed.MaxTrustLevel = "untrusted"
	if _, err := s.RegisterIssuer(changed); err == nil {
		t.Fatal("overwrote immutable issuer")
	}
	s, err = Open(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	registered, err := s.GetIssuer(i.IssuerID)
	if err != nil || a.VerifyAuthority(registered, key.Public(), a.Scope, now) != nil {
		t.Fatal("restart lost authority", err)
	}
	revoked, err := s.RevokeIssuer(i.IssuerID, now)
	if err != nil {
		t.Fatal(err)
	}
	retry, err := s.RevokeIssuer(i.IssuerID, now.Add(time.Hour))
	if err != nil || retry.RevokedAt != revoked.RevokedAt {
		t.Fatal("revocation retry changed record", err)
	}
	if _, err := s.RegisterIssuer(i); err == nil {
		t.Fatal("revocation cleared by re-registration")
	}
	s, err = Open(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	registered, err = s.GetIssuer(i.IssuerID)
	if err != nil || a.VerifyAuthority(registered, key.Public(), a.Scope, now) == nil {
		t.Fatal("restart forgot revocation", err)
	}
	after, err := os.ReadFile(s.recordPath("provenance-issuers", i.IssuerID))
	if err != nil || string(after) != string(original) {
		t.Fatal("revocation mutated issuer", err)
	}
	if err := os.WriteFile(s.recordPath("provenance-issuer-revocations", i.IssuerID), []byte(`{}`), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.GetIssuer(i.IssuerID); err == nil {
		t.Fatal("corrupt revocation ignored")
	}
}
func TestIssuerConcurrentRegistrationAndReads(t *testing.T) {
	_, i, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for n := 0; n < 16; n++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := s.RegisterIssuer(i); err != nil {
				t.Error(err)
			}
			if _, err := s.GetIssuer(i.IssuerID); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	for n := 0; n < 16; n++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			if _, err := s.RevokeIssuer(i.IssuerID, now); err != nil {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	got, err := s.GetIssuer(i.IssuerID)
	if err != nil || got.RevokedAt == "" {
		t.Fatal(got, err)
	}
}
func TestIssuerMalformedAndSymlinkRecordsRejected(t *testing.T) {
	_, i, key, _ := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := s.RegisterIssuer(i); err != nil {
		t.Fatal(err)
	}
	p := s.recordPath("provenance-issuers", i.IssuerID)
	raw, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, append(raw, []byte(" {}")...), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.GetIssuer(i.IssuerID); err == nil {
		t.Fatal("trailing record accepted")
	}
	if _, err := s.GetIssuer("../escape"); err == nil {
		t.Fatal("path traversal accepted")
	}
	target := s.recordPath("provenance-issuers", "target")
	if err := os.WriteFile(target, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(p); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, p); err != nil {
		t.Skip("symlink unavailable", err)
	}
	if _, err := s.GetIssuer(i.IssuerID); err == nil {
		t.Fatal("followed symlink record")
	}
}
