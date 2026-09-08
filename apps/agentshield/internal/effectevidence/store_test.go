package effectevidence

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

func TestStoreAtomicIncidentRetryConflictAndRecovery(t *testing.T) {
	e, key, now := fixture(t)
	e.Signature = ""
	a := Action{ActionID: e.ActionID, DecisionReceiptID: e.DecisionReceiptID, TaskID: "task-1", IssuedAt: now, Authorized: false, Effects: []string{e.EffectType}, Resources: []runtimeaction.ResourceRef{{Domain: "filesystem", Digest: strings.Repeat("b", 64)}}}
	dir := t.TempDir()
	s, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	for i := 0; i < 16; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			other, err := NewStore(dir, key)
			if err != nil {
				t.Error(err)
				return
			}
			r, err := other.Submit(e, a, e.Source, now)
			if err != nil || r.FindingCode != "unauthorized_effect_observed" || r.Evidence.Result != "unexpected" {
				t.Error(r, err)
			}
		}()
	}
	wg.Wait()
	files, err := os.ReadDir(s.dir)
	if err != nil || len(files) != 1 {
		t.Fatal("non-atomic/duplicate records", files, err)
	}
	r, err := s.Get(e.EvidenceID, now)
	if err != nil {
		t.Fatal(err)
	}
	restarted, err := NewStore(dir, key)
	if err != nil {
		t.Fatal(err)
	}
	a.Authorized = true
	retry, err := restarted.Submit(e, a, e.Source, now)
	if err != nil || retry.Signature != r.Signature || retry.FindingCode != "unauthorized_effect_observed" {
		t.Fatal("retry changed historical incident", retry, err)
	}
	bad := e
	bad.Result = "unexpected"
	if _, err = s.Submit(bad, a, e.Source, now); !errors.Is(err, ErrConflict) {
		t.Fatal("normalized request hid conflict", err)
	}
	path := filepath.Join(s.dir, e.EvidenceID+".json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, []byte(strings.Replace(string(raw), "unauthorized_effect_observed", "effect_scope_mismatch", 1)), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = restarted.Get(e.EvidenceID, now); !errors.Is(err, ErrState) {
		t.Fatal("tampered incident accepted", err)
	}
}

func TestStoreRejectsUnsafeStateAndInput(t *testing.T) {
	e, key, now := fixture(t)
	e.Signature = ""
	a := Action{ActionID: e.ActionID, DecisionReceiptID: e.DecisionReceiptID, IssuedAt: now}
	s, err := NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"../escape", "/tmp/escape", ""} {
		if _, err = s.Get(id, now); !errors.Is(err, ErrInvalid) {
			t.Fatal(id, err)
		}
	}
	e.Source.SourceID = "forged"
	if _, err = s.Submit(e, a, Source{Type: "host_observer", SourceID: "real", Independence: "host_independent"}, now); !errors.Is(err, ErrObserver) {
		t.Fatal(err)
	}
	if err = os.Symlink(filepath.Join(t.TempDir(), "missing"), filepath.Join(s.dir, e.EvidenceID+".json")); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get(e.EvidenceID, now); !errors.Is(err, ErrState) {
		t.Fatal("symlink accepted", err)
	}
	if _, err = s.Submit(e, a, e.Source, now); !errors.Is(err, ErrState) {
		t.Fatal("symlink overwritten", err)
	}
}

func TestStoreCapacityAndInterruptedPublication(t *testing.T) {
	e, key, now := fixture(t)
	e.Signature = ""
	a := Action{ActionID: e.ActionID, DecisionReceiptID: e.DecisionReceiptID, IssuedAt: now}
	s, err := NewStore(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	// A crash before link leaves only a temporary file, never a readable record.
	if err = os.WriteFile(filepath.Join(s.dir, ".effect-interrupted"), []byte("partial"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err = s.Get(e.EvidenceID, now); !errors.Is(err, ErrNotFound) {
		t.Fatal(err)
	}
	// Capacity counts all directory entries conservatively, including orphans.
	for i := 1; i < MaxRecords-1; i++ {
		if err = os.WriteFile(filepath.Join(s.dir, fmt.Sprintf("reserved-%d", i)), nil, 0600); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = s.Submit(e, a, e.Source, now); err != nil {
		t.Fatal("last capacity slot rejected", err)
	}
	e.EvidenceID = "eff-over-capacity"
	if _, err = s.Submit(e, a, e.Source, now); !errors.Is(err, ErrCapacity) {
		t.Fatal("capacity exceeded", err)
	}
}
