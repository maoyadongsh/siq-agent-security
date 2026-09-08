package intent

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
)

func TestGlobalIntentRevocationAffectsAllBindingsAndSurvivesRestart(t *testing.T) {
	s, first := boundForRevocation(t)
	second, err := s.Bind(Binding{Platform: first.Platform, SessionID: "second-session", AgentID: first.AgentID, IntentID: first.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	path, _ := s.path(first.IntentID)
	original, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	_, err = s.RevokeIntent(first.IntentID, strings.Repeat("0", 64))
	assertCode(t, err, "intent_revoke_conflict")
	for _, b := range []Binding{first, second} {
		if _, _, err := s.ResolveBinding(b.Platform, b.SessionID, b.AgentID); err != nil {
			t.Fatal(err)
		}
	}
	var wg sync.WaitGroup
	signatures := make(chan string, 8)
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, err := s.RevokeIntent(first.IntentID, first.IntentDigest)
			if err != nil {
				t.Error(err)
				return
			}
			signatures <- r.Signature
		}()
	}
	wg.Wait()
	close(signatures)
	signature := ""
	for got := range signatures {
		if signature != "" && signature != got {
			t.Fatal("retry changed revocation")
		}
		signature = got
	}
	if signature == "" {
		t.Fatal("no revocation published")
	}
	reopened, err := Open(filepath.Dir(s.dir), s.key)
	if err != nil {
		t.Fatal(err)
	}
	for _, b := range []Binding{first, second} {
		c, binding, err := reopened.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
		assertCode(t, err, "intent_revoked")
		if c == nil || binding == nil || c.Digest != b.IntentDigest {
			t.Fatal("revocation lost signed denial metadata")
		}
	}
	_, err = reopened.Bind(Binding{Platform: first.Platform, SessionID: "new-session", AgentID: first.AgentID, IntentID: first.IntentID})
	assertCode(t, err, "intent_revoked")
	current, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(current, original) {
		t.Fatal("original contract modified", err)
	}
	if _, err = reopened.Get(first.IntentID); err != nil {
		t.Fatal("historical contract unavailable", err)
	}
	revokedPath, _ := reopened.intentRevocationPath(first.IntentID)
	raw, err := os.ReadFile(revokedPath)
	if err != nil {
		t.Fatal(err)
	}
	raw = bytes.Replace(raw, []byte(first.IntentDigest), []byte(strings.Repeat("f", 64)), 1)
	if err = os.WriteFile(revokedPath, raw, 0600); err != nil {
		t.Fatal(err)
	}
	_, _, err = reopened.ResolveBinding(first.Platform, first.SessionID, first.AgentID)
	assertCode(t, err, "intent_revocation_invalid")
}
