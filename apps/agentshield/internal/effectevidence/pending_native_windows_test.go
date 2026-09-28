package effectevidence_test

import (
	"bytes"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

type windowsPendingState struct {
	store       *effectevidence.Store
	key         *signing.Key
	dir, target string
	pending     effectevidence.PendingFile
	now         time.Time
}

// The external test package can use the real state activation transaction
// without creating an effectevidence -> state -> effectevidence import cycle.
// No business Grant or real host instance is created by this component fixture.
func newWindowsPendingState(t *testing.T) windowsPendingState {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	_, initErr := st.Initialize(w, 47611)
	releaseErr := w.Release()
	if initErr != nil || releaseErr != nil {
		t.Fatal(initErr, releaseErr)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.ActivateWindowsProfile(true, "pending-component-test"); err != nil {
		t.Fatal(err)
	}
	store, err := effectevidence.NewStore(st.Dir, key)
	if err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "private-file")
	if err := os.WriteFile(target, []byte("synthetic private contents"), 0600); err != nil {
		t.Fatal(err)
	}
	before, err := effectevidence.CaptureFileForProfile(runtimeaction.FilesystemWindowsLocalDriveV1, target, 1024)
	if err != nil || before.SchemaVersion != "file-snapshot/v2" || before.IdentityDigest == "" || before.ParentIdentityDigest == "" {
		t.Fatal("native file identity unavailable", before, err)
	}
	now := time.Now().UTC()
	p := effectevidence.PendingFile{
		SchemaVersion: "file-observation-pending/v2", ID: "native-pending",
		IntentID: "int-component", IntentDigest: strings.Repeat("d", 64),
		ActionID: "action-component", ReceiptID: "receipt-component",
		Scope:  provenance.Scope{Platform: "workbuddy", SessionID: "session-component", AgentID: "agent-component", TaskID: "task-component"},
		Source: effectevidence.Source{Type: "host_observer", SourceID: "component-fixture", Independence: "host_independent"},
		Before: before, OwnerDigest: strings.Repeat("a", 64), ExpectedDigest: strings.Repeat("b", 64),
		MaxBytes: 1024, ExpiresAt: now.Add(time.Hour).Format(time.RFC3339Nano), SigningSchema: signing.SchemaLocalCanonicalV1,
	}
	return windowsPendingState{store: store, key: key, dir: st.Dir, target: target, pending: p, now: now}
}

func (f windowsPendingState) recordPath() string {
	return filepath.Join(f.dir, "effect-evidence-pending", f.pending.ID+".json")
}

func TestWindowsPendingRestartAndTamper(t *testing.T) {
	f := newWindowsPendingState(t)
	first, err := f.store.SavePendingFile(f.pending)
	if err != nil {
		t.Fatal(err)
	}
	original, err := os.ReadFile(f.recordPath())
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(original, []byte(f.target)) || bytes.Contains(original, []byte("synthetic private contents")) {
		t.Fatal("pending leaked raw path or contents")
	}
	if err := os.WriteFile(f.target, []byte("changed after begin"), 0600); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for range 8 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			other, err := effectevidence.NewStore(f.dir, f.key)
			if err != nil {
				t.Error(err)
				return
			}
			got, err := other.SavePendingFile(f.pending)
			if err != nil || got != first {
				t.Error("concurrent retry changed original pending", err)
			}
		}()
	}
	wg.Wait()
	other, err := effectevidence.NewStore(f.dir, f.key)
	if err != nil {
		t.Fatal(err)
	}
	got, err := other.GetPendingFile(first.ID)
	if err != nil || got != first {
		t.Fatal("restart replaced original snapshot", got, err)
	}
	after, err := os.ReadFile(f.recordPath())
	if err != nil || !bytes.Equal(original, after) {
		t.Fatal("idempotent retry rewrote signed pending", err)
	}
	changed := f.pending
	changed.ExpectedDigest = strings.Repeat("c", 64)
	if _, err := other.SavePendingFile(changed); !errors.Is(err, effectevidence.ErrConflict) {
		t.Fatal("changed pending reused", err)
	}
	tampered := bytes.Replace(original, []byte(first.OwnerDigest), []byte(strings.Repeat("e", 64)), 1)
	if bytes.Equal(original, tampered) {
		t.Fatal("tamper was not injected")
	}
	if err := os.WriteFile(f.recordPath(), tampered, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := other.GetPendingFile(first.ID); !errors.Is(err, effectevidence.ErrState) {
		t.Fatal("tampered owner accepted", err)
	}
	if _, err := other.GetPendingFile("../escape"); !errors.Is(err, effectevidence.ErrInvalid) {
		t.Fatal(err)
	}
}

func TestWindowsPendingRecoveryHasOneWinner(t *testing.T) {
	f := newWindowsPendingState(t)
	p, err := f.store.SavePendingFile(f.pending)
	if err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(f.recordPath())
	if err != nil {
		t.Fatal(err)
	}
	type result struct {
		owner string
		err   error
	}
	results := make(chan result, 8)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 1; i <= 8; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			other, err := effectevidence.NewStore(f.dir, f.key)
			owner := fmt.Sprintf("%064x", i)
			if err == nil {
				_, err = other.RecoverPendingFile(p.ID, p.OwnerDigest, owner, f.now)
			}
			results <- result{owner, err}
		}(i)
	}
	close(start)
	wg.Wait()
	close(results)
	winner := ""
	for r := range results {
		if r.err == nil {
			if winner != "" {
				t.Fatal("more than one durable recovery winner")
			}
			winner = r.owner
		} else if !errors.Is(r.err, effectevidence.ErrConflict) {
			t.Fatal(r.err)
		}
	}
	if winner == "" {
		t.Fatal("no recovery won")
	}
	owner, err := f.store.PendingFileOwner(p.ID, f.now)
	if err != nil || owner != winner {
		t.Fatal("winner not durable", owner, err)
	}
	got, err := f.store.GetPendingFile(p.ID)
	if err != nil || got != p {
		t.Fatal("recovery changed signed original or deadline", got, err)
	}
	after, err := os.ReadFile(f.recordPath())
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("recovery rewrote pending", err)
	}
	if _, err := f.store.PendingFileOwner(p.ID, f.now.Add(time.Hour)); !errors.Is(err, effectevidence.ErrConflict) {
		t.Fatal("recovery extended original deadline", err)
	}
}

func TestWindowsPendingRecoveryBoundaries(t *testing.T) {
	for _, kind := range []string{"capacity", "gap", "unknown-field", "hardlink-tamper", "oversized", "unpublished-temp"} {
		t.Run(kind, func(t *testing.T) {
			f := newWindowsPendingState(t)
			p, err := f.store.SavePendingFile(f.pending)
			if err != nil {
				t.Fatal(err)
			}
			owner := p.OwnerDigest
			limit := 1
			if kind == "capacity" {
				limit = effectevidence.MaxRecoveries
			}
			for i := 1; i <= limit; i++ {
				next := fmt.Sprintf("%064x", i)
				if _, err := f.store.RecoverPendingFile(p.ID, owner, next, f.now); err != nil {
					t.Fatal(err)
				}
				owner = next
			}
			if kind == "capacity" {
				if _, err := f.store.RecoverPendingFile(p.ID, owner, strings.Repeat("f", 64), f.now); !errors.Is(err, effectevidence.ErrCapacity) {
					t.Fatal("capacity bypassed", err)
				}
				if r, err := f.store.RecoverPendingFile(p.ID, owner, owner, f.now); err != nil || r.Sequence != effectevidence.MaxRecoveries {
					t.Fatal("retry at capacity changed history", err)
				}
			} else {
				dir := filepath.Join(f.dir, "effect-evidence-pending", p.ID+".recoveries")
				path := filepath.Join(dir, "000001.json")
				raw, err := os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				switch kind {
				case "gap":
					err = os.Rename(path, filepath.Join(dir, "000002.json"))
				case "unknown-field":
					err = os.WriteFile(path, append([]byte(`{"unexpected":true,`), raw[1:]...), 0600)
				case "hardlink-tamper":
					alias := filepath.Join(t.TempDir(), "alias.json")
					if err := os.Link(path, alias); err != nil {
						t.Fatal("hardlink fixture unavailable", err)
					}
					changed := bytes.Replace(raw, []byte(owner), []byte(strings.Repeat("f", 64)), 1)
					if bytes.Equal(raw, changed) {
						t.Fatal("owner tamper was not injected")
					}
					err = os.WriteFile(alias, changed, 0600)
				case "oversized":
					err = os.WriteFile(path, bytes.Repeat([]byte(" "), 4097), 0600)
				case "unpublished-temp":
					err = os.WriteFile(filepath.Join(dir, ".recovery-crashed"), []byte(`{"partial":`), 0600)
				}
				if err != nil {
					t.Fatal("fault injection failed", err)
				}
			}
			current, err := f.store.PendingFileOwner(p.ID, f.now)
			if kind == "capacity" || kind == "unpublished-temp" {
				if err != nil || current != owner {
					t.Fatal("failed/unpublished append changed owner", current, err)
				}
			} else if !errors.Is(err, effectevidence.ErrState) {
				t.Fatal("unsafe history accepted", kind, err)
			}
		})
	}
}
