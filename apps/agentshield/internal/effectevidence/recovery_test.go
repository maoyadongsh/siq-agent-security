package effectevidence

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestRecoveryHistoryBindsPendingAndRetainsEveryOwner(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	now := time.Date(2026, 9, 8, 1, 0, 0, 0, time.UTC)
	p := PendingFile{SchemaVersion: "file-observation-pending/v1", ID: "p1", ActionID: "a1", ReceiptID: "r1", Scope: provenance.Scope{Platform: "hermes", SessionID: "s1", AgentID: "a1", TaskID: "t1"}, Source: Source{Type: "host_observer", SourceID: "observer", Independence: "host_independent"}, Before: FileSnapshot{ResourceRef: "filesystem:sha256:" + strings.Repeat("a", 64), CapturedAt: now.Add(-time.Minute).Format(time.RFC3339Nano)}, OwnerDigest: strings.Repeat("b", 64), ExpectedDigest: strings.Repeat("c", 64), MaxBytes: 1024, ExpiresAt: now.Add(time.Hour).Format(time.RFC3339Nano), SigningSchema: "local_canonical/v1"}
	p.Signature, _ = key.SignCanonical(p.unsigned())
	first, err := newRecovery(p, nil, strings.Repeat("d", 64), key, now)
	if err != nil {
		t.Fatal(err)
	}
	second, err := newRecovery(p, []FileRecovery{first}, strings.Repeat("e", 64), key, now.Add(time.Second))
	if err != nil {
		t.Fatal(err)
	}
	history := []FileRecovery{first, second}
	owners, err := RecoveryOwners(p, history, key.Public(), now.Add(time.Second))
	if err != nil || len(owners) != 3 || owners[0] != p.OwnerDigest || owners[2] != second.OwnerDigest {
		t.Fatal(owners, err)
	}
	for _, mutate := range []func(*FileRecovery){func(r *FileRecovery) { r.Sequence = 1 }, func(r *FileRecovery) { r.PreviousHash = strings.Repeat("0", 64) }, func(r *FileRecovery) { r.PendingDigest = strings.Repeat("f", 64) }, func(r *FileRecovery) { r.OwnerDigest = first.OwnerDigest }, func(r *FileRecovery) { r.RecoveredAt = now.Add(2 * time.Hour).Format(time.RFC3339Nano) }} {
		bad := second
		mutate(&bad)
		bad.Signature, _ = key.SignCanonical(bad.unsigned())
		if _, err := RecoveryOwners(p, []FileRecovery{first, bad}, key.Public(), now.Add(3*time.Hour)); err == nil {
			t.Fatal("invalid signed history accepted")
		}
	}
	altered := p
	altered.ExpectedDigest = strings.Repeat("f", 64)
	altered.Signature, _ = key.SignCanonical(altered.unsigned())
	if _, err := RecoveryOwners(altered, history, key.Public(), now.Add(time.Second)); err == nil {
		t.Fatal("history rebound to different signed snapshot")
	}
	history = nil
	for i := 1; i <= MaxRecoveries; i++ {
		r, e := newRecovery(p, history, fmt.Sprintf("%064x", i), key, now)
		if e != nil {
			t.Fatal(i, e)
		}
		history = append(history, r)
	}
	if _, err := newRecovery(p, history, strings.Repeat("f", 64), key, now); err != ErrCapacity {
		t.Fatal("recovery capacity not enforced", err)
	}
	dir := t.TempDir()
	store, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	unsigned := p
	unsigned.Signature = ""
	if _, err := store.SavePendingFile(unsigned); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for i := 0; i < 8; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			r, e := store.RecoverPendingFile(p.ID, p.OwnerDigest, first.OwnerDigest, now)
			if e != nil || r.Signature != first.Signature {
				t.Error("concurrent idempotency", e)
			}
		}()
	}
	wg.Wait()
	restarted, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	if owner, e := restarted.PendingFileOwner(p.ID, now); e != nil || owner != first.OwnerDigest {
		t.Fatal(owner, e)
	}
	if _, e := restarted.RecoverPendingFile(p.ID, p.OwnerDigest, second.OwnerDigest, now); e != ErrConflict {
		t.Fatal("stale owner accepted", e)
	}
	if _, e := restarted.RecoverPendingFile(p.ID, first.OwnerDigest, second.OwnerDigest, now.Add(time.Second)); e != nil {
		t.Fatal(e)
	}
	if _, e := restarted.PendingFileOwner(p.ID, now.Add(time.Hour)); e != ErrConflict {
		t.Fatal("deadline extended", e)
	}
	if _, e := restarted.RevokeObserver(first.OwnerDigest, now.Add(time.Second)); e != nil {
		t.Fatal(e)
	}
	if _, e := restarted.PendingFileOwner(p.ID, now.Add(time.Second)); e != ErrConflict {
		t.Fatal("historical revocation ignored", e)
	}
	if _, e := restarted.RecoverPendingFile(p.ID, second.OwnerDigest, strings.Repeat("f", 64), now.Add(time.Second)); e != ErrConflict {
		t.Fatal("revocation bypass", e)
	}
	// Even a structurally valid record with a changed signature fails closed.
	file := filepath.Join(dir, "effect-evidence-pending", p.ID+".recoveries", "000002.json")
	raw, e := os.ReadFile(file)
	if e != nil {
		t.Fatal(e)
	}
	raw = bytes.Replace(raw, []byte(second.Signature), []byte(strings.Repeat("0", 128)), 1)
	if e := os.WriteFile(file, raw, 0600); e != nil {
		t.Fatal(e)
	}
	if _, e := restarted.PendingFileOwner(p.ID, now.Add(time.Second)); e != ErrState {
		t.Fatal("tampered history accepted", e)
	}

}
