package runtimeidentity

import (
	"encoding/json"
	"os"
	"strings"
	"sync"
	"testing"
)

func TestSelfInspectionAndIdempotentRevocation(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	v, err := s.Self(token)
	if err != nil || v.IdentityID != r.IdentityID || v.GrantRef != r.GrantRef || v.RuntimeState != "unverified" || v.Status != "active" {
		t.Fatal("self identity mismatch", err)
	}
	encoded, _ := json.Marshal(v)
	for _, forbidden := range []string{token, r.CredentialHash, "credential", "signature", "actor_id"} {
		if strings.Contains(string(encoded), forbidden) {
			t.Fatal("self response leaked private material")
		}
	}
	first, err := s.RevokeSelf(token)
	if err != nil || first.ActorID != "runtime-self:"+r.IdentityID {
		t.Fatal("self revoke failed", err)
	}
	second, err := s.RevokeSelf(token)
	if err != nil || first != second {
		t.Fatal("retry changed signed revocation", err)
	}
	if _, err = s.Self(token); err == nil {
		t.Fatal("revoked identity inspected as active")
	}
	if _, err = s.Authenticate(token); err == nil {
		t.Fatal("revoked identity authenticated")
	}
}

func TestSelfRevocationSurvivesLostAuthorityAndInstance(t *testing.T) {
	s, req, g := fixture(t)
	r, token := create(t, s, req)
	g.Status = "revoked" // Deliberately invalidates the signed selected Grant.
	s.resolve = func(string) (string, error) { return "", ErrUnavailable }
	if _, err := s.Self(token); err == nil {
		t.Fatal("lost Grant accepted")
	}
	rev, err := s.RevokeSelf(token)
	if err != nil || rev.IdentityID != r.IdentityID {
		t.Fatal("cleanup required execution authority", err)
	}
}

func TestSelfCannotRevokeAnotherIdentityOrTrustCorruption(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	for _, candidate := range []string{"", strings.Repeat("a", 64), token[:36] + strings.Repeat("0", 64), "ri-" + strings.Repeat("f", 32) + token[35:]} {
		if _, err := s.RevokeSelf(candidate); err == nil {
			t.Fatal("forged credential revoked identity")
		}
	}
	if _, err := s.Self(token); err != nil {
		t.Fatal("invalid attempt affected real identity", err)
	}
	if err := os.WriteFile(s.recordPath(r.IdentityID), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.RevokeSelf(token); err == nil {
		t.Fatal("corrupt signed record accepted")
	}
	if _, err := os.Stat(s.revokedPath(r.IdentityID)); !os.IsNotExist(err) {
		t.Fatal("unverified revoke persisted")
	}
}

func TestSelfConcurrentCleanupPreservesOriginalAudit(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	var wg sync.WaitGroup
	results := make(chan Revocation, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			rev, err := s.RevokeSelf(token)
			if err != nil {
				t.Error(err)
				return
			}
			results <- rev
		}()
	}
	wg.Wait()
	close(results)
	var first Revocation
	for rev := range results {
		if first.IdentityID == "" {
			first = rev
		}
		if rev != first {
			t.Fatal("concurrent audit differs")
		}
	}
	if first.IdentityID != r.IdentityID {
		t.Fatal("missing audit")
	}
}

func TestSelfRevocationCorruptTombstoneNeverReportsSuccess(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	if err := os.WriteFile(s.revokedPath(r.IdentityID), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := s.RevokeSelf(token); err == nil {
		t.Fatal("corrupt revocation accepted")
	}
}

func TestSelfInspectionRequiresCurrentInstanceButCleanupDoesNot(t *testing.T) {
	s, req, _ := fixture(t)
	_, token := create(t, s, req)
	s.resolve = func(string) (string, error) { return "", ErrUnavailable }
	if _, err := s.Self(token); err == nil {
		t.Fatal("missing instance accepted by preflight")
	}
	if _, err := s.RevokeSelf(token); err != nil {
		t.Fatal("missing instance blocked cleanup", err)
	}
}

func TestSelfCleanupPreservesPriorManagementRevocation(t *testing.T) {
	s, req, _ := fixture(t)
	r, token := create(t, s, req)
	prior, err := s.Revoke(r.IdentityID, "original-human-operator")
	if err != nil {
		t.Fatal(err)
	}
	after, err := s.RevokeSelf(token)
	if err != nil || after != prior {
		t.Fatal("self cleanup rewrote original audit", err)
	}
}

func TestSelfLifecycleAlsoPreservesOpenClawPlatform(t *testing.T) {
	s, req := openClawFixture(t)
	_, token := create(t, s, req)
	v, err := s.Self(token)
	if err != nil || v.Platform != "openclaw" {
		t.Fatal("OpenClaw self identity rejected", err)
	}
	if _, err = s.RevokeSelf(token); err != nil {
		t.Fatal("OpenClaw self cleanup failed", err)
	}
	if _, err = s.Self(token); err == nil {
		t.Fatal("OpenClaw revoked identity accepted")
	}
}
