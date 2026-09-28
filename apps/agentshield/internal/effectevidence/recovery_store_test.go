package effectevidence_test

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/evidencetest"
	"siq-agent-security/apps/agentshield/internal/linktest"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func recoveryFixture(t *testing.T) (*effectevidence.Store, effectevidence.PendingFile, time.Time, string) {
	t.Helper()
	f := evidencetest.New(t)
	store := f.Store
	before, err := f.Capture(filepath.Join(t.TempDir(), "absent"), 1024)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()
	p, err := store.SavePendingFile(f.Pending(effectevidence.PendingFile{SchemaVersion: "file-observation-pending/v1", ID: "recovery-matrix", ActionID: "a1", ReceiptID: "r1", Scope: provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a1", TaskID: "t1"}, Source: effectevidence.Source{Type: "host_observer", SourceID: "host", Independence: "host_independent"}, Before: before, OwnerDigest: strings.Repeat("a", 64), ExpectedDigest: strings.Repeat("b", 64), MaxBytes: 1024, ExpiresAt: now.Add(time.Hour).Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1}))
	if err != nil {
		t.Fatal(err)
	}
	return store, p, now, filepath.Join(f.Dir, "effect-evidence-pending", p.ID+".recoveries")
}

func TestRecoveryConcurrentDifferentOwnersHaveOneWinner(t *testing.T) {
	s, p, now, dir := recoveryFixture(t)
	var wg sync.WaitGroup
	results := make(chan error, 8)
	start := make(chan struct{})
	for i := 1; i <= 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			_, err := s.RecoverPendingFile(p.ID, p.OwnerDigest, fmt.Sprintf("%064x", i), now)
			results <- err
		}(i)
	}
	close(start)
	wg.Wait()
	close(results)
	winners := 0
	for err := range results {
		if err == nil {
			winners++
		} else if err != effectevidence.ErrConflict {
			t.Fatal(err)
		}
	}
	if winners != 1 {
		t.Fatalf("wanted one durable winner, got %d", winners)
	}
	history, err := os.ReadDir(dir)
	if err != nil || len(history) != 1 {
		t.Fatal(history, err)
	}
	if owner, err := s.PendingFileOwner(p.ID, now); err != nil || owner == p.OwnerDigest {
		t.Fatal("durable history did not validate its new owner", owner, err)
	}
}

func TestRecoveryStoredCapacityAndFailureIsolation(t *testing.T) {
	s, p, now, _ := recoveryFixture(t)
	owner := p.OwnerDigest
	for i := 1; i <= effectevidence.MaxRecoveries; i++ {
		next := fmt.Sprintf("%064x", i)
		if _, err := s.RecoverPendingFile(p.ID, owner, next, now); err != nil {
			t.Fatal(i, err)
		}
		owner = next
	}
	if _, err := s.RecoverPendingFile(p.ID, owner, strings.Repeat("f", 64), now); err != effectevidence.ErrCapacity {
		t.Fatal(err)
	}
	if current, err := s.PendingFileOwner(p.ID, now); err != nil || current != owner {
		t.Fatal("failed append changed owner", current, err)
	}
	if r, err := s.RecoverPendingFile(p.ID, owner, owner, now); err != nil || r.Sequence != effectevidence.MaxRecoveries {
		t.Fatal("retry at capacity failed", err)
	}
}

func TestRecoveryMalformedStorageFailsClosed(t *testing.T) {
	for _, kind := range []string{"gap", "unknown-field", "symlink", "redirected-history", "oversized", "unpublished-temp"} {
		t.Run(kind, func(t *testing.T) {
			s, p, now, dir := recoveryFixture(t)
			owner := strings.Repeat("c", 64)
			if _, err := s.RecoverPendingFile(p.ID, p.OwnerDigest, owner, now); err != nil {
				t.Fatal(err)
			}
			path := filepath.Join(dir, "000001.json")
			raw, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			switch kind {
			case "redirected-history":
				if err := os.Rename(dir, dir+".owned"); err != nil {
					t.Fatal(err)
				}
				if err := linktest.Directory(dir+".owned", dir); err != nil {
					t.Fatal(err)
				}
				defer os.Remove(dir)
			case "gap":
				err = os.Rename(path, filepath.Join(dir, "000002.json"))
			case "unknown-field":
				err = os.WriteFile(path, append([]byte(`{"token":"not-allowed",`), raw[1:]...), 0600)
			case "symlink":
				target := filepath.Join(t.TempDir(), "record.json")
				if err = os.WriteFile(target, raw, 0600); err != nil {
					t.Fatal(err)
				}
				if err = os.Remove(path); err != nil {
					t.Fatal(err)
				}
				linktest.Symlink(t, target, path)
			case "oversized":
				err = os.WriteFile(path, bytes.Repeat([]byte(" "), 4097), 0600)
			case "unpublished-temp":
				err = os.WriteFile(filepath.Join(dir, ".recovery-crashed"), []byte(`{"partial":`), 0600)
			}
			if err != nil {
				t.Fatal(err)
			}
			current, err := s.PendingFileOwner(p.ID, now)
			if kind == "unpublished-temp" {
				if err != nil || current != owner {
					t.Fatal("unpublished temp affected valid owner", err)
				}
			} else if err != effectevidence.ErrState {
				t.Fatal("malformed history accepted", kind, err)
			}
		})
	}
}
