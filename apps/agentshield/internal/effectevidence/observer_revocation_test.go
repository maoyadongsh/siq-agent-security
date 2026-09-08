package effectevidence

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestObserverRevocationSurvivesRestartAndConcurrentRetries(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	dir := t.TempDir()
	s, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	owner := strings.Repeat("a", 64)
	revoked, err := s.ObserverRevoked(owner)
	if err != nil || revoked {
		t.Fatal(revoked, err)
	}
	first, err := s.RevokeObserver(owner, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			other, e := NewStore(dir, key)
			if e != nil {
				t.Error(e)
				return
			}
			r, e := other.RevokeObserver(owner, time.Now().Add(time.Minute))
			if e != nil || r != first {
				t.Error("revocation rewritten", e)
			}
		}()
	}
	wg.Wait()
	other, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	revoked, err = other.ObserverRevoked(owner)
	if err != nil || !revoked {
		t.Fatal("lost revocation", err)
	}
	path := filepath.Join(dir, "effect-observer-revocations", owner+".json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	raw = bytes.Replace(raw, []byte(first.RevokedAt), []byte("2026-01-01T00:00:00Z"), 1)
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := other.ObserverRevoked(owner); !errors.Is(err, ErrState) {
		t.Fatal("tampered tombstone accepted", err)
	}
}
