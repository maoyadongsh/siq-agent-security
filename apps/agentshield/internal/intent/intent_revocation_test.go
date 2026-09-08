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

func TestGlobalRevocationFixedVectorAndTampering(t *testing.T) {
	s := testStore(t)
	r := IntentRevocation{SchemaVersion: "intent-revocation/v1", IntentID: "int-fixed-revoked", IntentDigest: strings.Repeat("ab", 32), RevokedAt: "2026-09-08T03:00:00.123456789Z", ReasonCode: "intent_revoked", SigningSchema: "local_canonical/v1"}
	var err error
	r.Signature, err = s.key.SignCanonical(intentRevocationMap(r))
	if err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile("../../testdata/contracts/intent-revocation.sample.json")
	if err != nil {
		t.Fatal(err)
	}
	var fixed IntentRevocation
	if err := json.Unmarshal(raw, &fixed); err != nil {
		t.Fatal(err)
	}
	if fixed != r {
		t.Fatal("cross-language fixed vector differs")
	}
	path, err := s.intentRevocationPath(r.IntentID)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if got, err := s.GetIntentRevocation(r.IntentID); err != nil || got != r {
		t.Fatal("fixed record rejected", err)
	}
	for _, field := range []string{"intent_digest", "revoked_at", "intent_id", "reason_code", "signing_schema", "schema_version", "signature"} {
		t.Run(field, func(t *testing.T) {
			var m map[string]any
			if err := json.Unmarshal(raw, &m); err != nil {
				t.Fatal(err)
			}
			switch field {
			case "intent_digest":
				m[field] = strings.Repeat("cd", 32)
			case "revoked_at":
				m[field] = "2026-09-08T03:00:00.123456788Z"
			case "signature":
				m[field] = strings.Repeat("0", 128)
			default:
				m[field] = "changed"
			}
			altered, err := json.Marshal(m)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, altered, 0600); err != nil {
				t.Fatal(err)
			}
			_, err = s.GetIntentRevocation(r.IntentID)
			assertCode(t, err, "intent_revocation_invalid")
		})
	}
}
