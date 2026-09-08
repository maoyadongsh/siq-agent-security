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

	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestPendingFileImmutableRestartAndTamper(t *testing.T) {
	key, _ := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	dir := t.TempDir()
	store, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "private-file")
	if err := os.WriteFile(target, []byte("private file contents"), 0600); err != nil {
		t.Fatal(err)
	}
	snapshot, err := CaptureFile(target, 1024)
	if err != nil {
		t.Fatal(err)
	}
	pending := PendingFile{SchemaVersion: "file-observation-pending/v1", ID: "pending-1", ActionID: "action-1", ReceiptID: "receipt-1", Scope: provenance.Scope{Platform: "hermes", SessionID: "session-1", AgentID: "agent-1", TaskID: "task-1"}, Source: Source{Type: "host_observer", SourceID: "observer", Independence: "host_independent"}, Before: snapshot, OwnerDigest: strings.Repeat("a", 64), ExpectedDigest: strings.Repeat("b", 64), MaxBytes: 1024, ExpiresAt: time.Now().Add(time.Minute).UTC().Format(time.RFC3339Nano), SigningSchema: "local_canonical/v1"}
	first, err := store.SavePendingFile(pending)
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
			got, e := other.SavePendingFile(pending)
			if e != nil || got.Signature != first.Signature {
				t.Error("concurrent retry changed pending", e)
			}
		}()
	}
	wg.Wait()
	other, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	got, err := other.GetPendingFile(pending.ID)
	if err != nil || got != first {
		t.Fatal(got, err)
	}
	bad := pending
	bad.ExpectedDigest = strings.Repeat("c", 64)
	if _, err := other.SavePendingFile(bad); !errors.Is(err, ErrConflict) {
		t.Fatal("changed pending replaced", err)
	}
	file := filepath.Join(dir, "effect-evidence-pending", "pending-1.json")
	raw, err := os.ReadFile(file)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(raw, []byte(target)) || bytes.Contains(raw, []byte("private file contents")) {
		t.Fatal("pending leaked raw data")
	}
	raw = bytes.Replace(raw, []byte(pending.OwnerDigest), []byte(strings.Repeat("d", 64)), 1)
	if err := os.WriteFile(file, raw, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := other.GetPendingFile(pending.ID); !errors.Is(err, ErrState) {
		t.Fatal("tampered owner accepted", err)
	}
	if _, err := other.GetPendingFile("../escape"); !errors.Is(err, ErrInvalid) {
		t.Fatal(err)
	}
}
