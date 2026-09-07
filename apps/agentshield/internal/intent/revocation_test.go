package intent

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func boundForRevocation(t *testing.T) (*Store, Binding) {
	t.Helper()
	s := testStore(t)
	c, err := s.Issue(testContract())
	if err != nil {
		t.Fatal(err)
	}
	b, err := s.Bind(Binding{Platform: "hermes", SessionID: "revocation-session", AgentID: "a-1", IntentID: c.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	return s, b
}
func TestBindingRevocationImmutableIdempotentAndRecovered(t *testing.T) {
	s, b := boundForRevocation(t)
	path, _ := s.bindingPath(b.BindingID)
	original, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = s.RevokeBinding(b.BindingID, strings.Repeat("0", 64))
	assertCode(t, err, "intent_binding_revoke_conflict")
	var wg sync.WaitGroup
	results := make(chan BindingRevocation, 16)
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, err := s.RevokeBinding(b.BindingID, b.IntentDigest)
			if err != nil {
				t.Error(err)
				return
			}
			results <- r
		}()
	}
	wg.Wait()
	close(results)
	var expected BindingRevocation
	for r := range results {
		if expected.Signature == "" {
			expected = r
		}
		if r != expected {
			t.Fatal("retry produced a different revocation")
		}
	}
	if expected.Signature == "" {
		t.Fatal("no revocation")
	}
	after, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(original, after) {
		t.Fatal("binding rewritten")
	}
	_, err = s.Bind(b)
	assertCode(t, err, "intent_binding_revoked")
	reopened, err := Open(filepath.Dir(s.dir), s.key)
	if err != nil {
		t.Fatal(err)
	}
	c, got, err := reopened.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
	assertCode(t, err, "intent_binding_revoked")
	if c == nil || got == nil || got.Signature != b.Signature || c.Digest != b.IntentDigest {
		t.Fatal("revoked authority lost verified metadata")
	}
	if err = os.Remove(path); err != nil {
		t.Fatal(err)
	}
	_, _, err = reopened.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
	assertCode(t, err, "intent_binding_revoked")
	c, got, err = reopened.ResolveBinding(b.Platform, "other-session", b.AgentID)
	if err != nil || c != nil || got != nil {
		t.Fatal("revocation crossed session identity")
	}
}
func TestBindingRevocationTamperingFailsClosed(t *testing.T) {
	for _, kind := range []string{"signature", "binding-digest", "unknown-field", "truncated", "symlink", "oversized"} {
		t.Run(kind, func(t *testing.T) {
			s, b := boundForRevocation(t)
			r, err := s.RevokeBinding(b.BindingID, b.IntentDigest)
			if err != nil {
				t.Fatal(err)
			}
			p, _ := s.revocationPath(b.BindingID)
			switch kind {
			case "signature":
				r.Signature = strings.Repeat("0", 128)
			case "binding-digest":
				r.BindingDigest = strings.Repeat("0", 64)
				r.Signature, _ = s.key.SignCanonical(revocationMap(r))
			}
			raw, _ := json.Marshal(r)
			switch kind {
			case "unknown-field":
				raw = append(raw[:len(raw)-1], []byte(`,"extra":true}`)...)
			case "truncated":
				raw = []byte("{")
			case "oversized":
				raw = []byte(strings.Repeat(" ", maxRecordBytes+1))
			case "symlink":
				original := filepath.Join(t.TempDir(), "record.json")
				if err = os.Rename(p, original); err != nil {
					t.Fatal(err)
				}
				if err = os.Symlink(original, p); err != nil {
					t.Skipf("symlink unavailable: %v", err)
				}
			}
			if kind != "symlink" {
				if err = os.WriteFile(p, raw, 0600); err != nil {
					t.Fatal(err)
				}
			}
			_, _, err = s.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
			assertCode(t, err, "intent_binding_revocation_invalid")
			_, err = s.RevokeBinding(b.BindingID, b.IntentDigest)
			assertCode(t, err, "intent_binding_revocation_invalid")
		})
	}
}
func TestBindingRevocationInputAndCapacity(t *testing.T) {
	s, b := boundForRevocation(t)
	for _, value := range []string{"", strings.Repeat("A", 64), "not-a-digest"} {
		_, err := s.RevokeBinding(b.BindingID, value)
		assertCode(t, err, "intent_invalid_revoke_request")
	}
	if _, err := s.RevokeBinding("../escape", b.IntentDigest); err == nil {
		t.Fatal("path traversal accepted")
	}
	for i := 0; i < maxRecords; i++ {
		id := bindingID("fixture", string(rune(i+1)), "other")
		p, _ := s.revocationPath(id)
		if err := os.WriteFile(p, []byte("{}"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	_, err := s.RevokeBinding(b.BindingID, b.IntentDigest)
	assertCode(t, err, "intent_state_capacity")
}
func TestConcurrentBindingResolutionAndRevocation(t *testing.T) {
	s, b := boundForRevocation(t)
	start := make(chan struct{})
	done := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			for j := 0; j < 20; j++ {
				_, _, err := s.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
				if err != nil {
					assertCode(t, err, "intent_binding_revoked")
				}
			}
			<-done
			for j := 0; j < 10; j++ {
				_, _, err := s.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
				assertCode(t, err, "intent_binding_revoked")
			}
		}()
	}
	close(start)
	if _, err := s.RevokeBinding(b.BindingID, b.IntentDigest); err != nil {
		t.Fatal(err)
	}
	close(done)
	wg.Wait()
}
