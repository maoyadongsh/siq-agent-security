package intent

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
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

func TestGlobalRevocationCapacityBoundaryAndRetry(t *testing.T) {
	s, b := boundForRevocation(t)
	c := testContract()
	c.IntentID = "int-capacity-second"
	second, err := s.Issue(c)
	if err != nil {
		t.Fatal(err)
	}
	// Prepublish valid signed records to exercise the directory budget without
	// repeatedly scanning the growing directory during fixture preparation.
	for i := 0; i < maxRecords-1; i++ {
		r := IntentRevocation{SchemaVersion: "intent-revocation/v1", IntentID: fmt.Sprintf("int-capacity-%04d", i), IntentDigest: strings.Repeat("a", 64), RevokedAt: "2026-09-08T03:00:00Z", ReasonCode: "intent_revoked", SigningSchema: "local_canonical/v1"}
		r.Signature, err = s.key.SignCanonical(intentRevocationMap(r))
		if err != nil {
			t.Fatal(err)
		}
		raw, err := json.Marshal(r)
		if err != nil {
			t.Fatal(err)
		}
		path, err := s.intentRevocationPath(r.IntentID)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, raw, 0600); err != nil {
			t.Fatal(err)
		}
	}
	first, err := s.RevokeIntent(b.IntentID, b.IntentDigest)
	if err != nil {
		t.Fatal("exact capacity must permit publication", err)
	}
	retry, err := s.RevokeIntent(b.IntentID, b.IntentDigest)
	if err != nil || retry != first {
		t.Fatal("full capacity broke idempotent retry", err)
	}
	_, err = s.RevokeIntent(second.IntentID, second.Digest)
	assertCode(t, err, "intent_state_capacity")
	path, _ := s.intentRevocationPath(second.IntentID)
	if _, err := os.Stat(path); !errors.Is(err, os.ErrNotExist) {
		t.Fatal("rejected revocation published a record", err)
	}
	ids, err := recordIDs(s.intentRevocationDir())
	if err != nil || len(ids) != maxRecords {
		t.Fatal("capacity changed", err)
	}
}

func TestConcurrentGlobalRevocationResolution(t *testing.T) {
	s, first := boundForRevocation(t)
	second, err := s.Bind(Binding{Platform: first.Platform, SessionID: "concurrent-second", AgentID: first.AgentID, IntentID: first.IntentID})
	if err != nil {
		t.Fatal(err)
	}
	start, revoked := make(chan struct{}), make(chan struct{})
	failures := make(chan error, 16)
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		b := []Binding{first, second}[i%2]
		wg.Add(1)
		go func() {
			defer wg.Done()
			<-start
			for j := 0; j < 10; j++ {
				_, _, err := s.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
				var v *Violation
				if err != nil && (!errors.As(err, &v) || v.Code != "intent_revoked") {
					failures <- fmt.Errorf("concurrent resolve: %w", err)
					return
				}
			}
			<-revoked // publication has returned before every following lookup
			for j := 0; j < 10; j++ {
				c, binding, err := s.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
				var v *Violation
				if !errors.As(err, &v) || v.Code != "intent_revoked" || c == nil || binding == nil || c.Digest != b.IntentDigest {
					failures <- fmt.Errorf("post-revocation resolution lost rejection or metadata: %v", err)
					return
				}
			}
		}()
	}
	close(start)
	_, revokeErr := s.RevokeIntent(first.IntentID, first.IntentDigest)
	close(revoked)
	wg.Wait()
	close(failures)
	if revokeErr != nil {
		t.Fatal(revokeErr)
	}
	for err := range failures {
		t.Error(err)
	}
}
