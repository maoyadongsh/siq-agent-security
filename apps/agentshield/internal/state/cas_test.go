package state

import (
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/grant"
)

func TestPutGrantCASRejectsStaleExpected(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	seq, err := st.PutGrantCAS(grant.Grant{GrantID: "cas1", Status: "pending"}, -1)
	if err != nil || seq != 0 {
		t.Fatalf("create: seq=%d err=%v", seq, err)
	}
	if _, err := st.PutGrantCAS(grant.Grant{GrantID: "cas1", Status: "approved"}, -1); !errors.Is(err, ErrRevisionConflict) {
		t.Fatalf("stale expected must conflict: %v", err)
	}
	seq, err = st.PutGrantCAS(grant.Grant{GrantID: "cas1", Status: "approved"}, 0)
	if err != nil || seq != 1 {
		t.Fatalf("cas approve: seq=%d err=%v", seq, err)
	}
	entries, err := os.ReadDir(filepath.Join(st.Dir, "grants"))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 2 {
		t.Fatalf("want 2 versions, got %d", len(entries))
	}
}

func TestPutGrantCASOnlyOneWinner(t *testing.T) {
	st, err := Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.PutGrantCAS(grant.Grant{GrantID: "race", Status: "pending"}, -1); err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for i := 0; i < 2; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			status := "approved-a"
			if i == 1 {
				status = "approved-b"
			}
			_, err := st.PutGrantCAS(grant.Grant{GrantID: "race", Status: status}, 0)
			errs <- err
		}(i)
	}
	wg.Wait()
	close(errs)
	ok, conflict := 0, 0
	for err := range errs {
		if err == nil {
			ok++
		} else if errors.Is(err, ErrRevisionConflict) {
			conflict++
		} else {
			t.Fatalf("unexpected: %v", err)
		}
	}
	if ok != 1 || conflict != 1 {
		t.Fatalf("want exactly one success and one conflict, got ok=%d conflict=%d", ok, conflict)
	}
	g, seq, err := st.GetGrantWithSeq("race")
	if err != nil || seq != 1 {
		t.Fatalf("head: seq=%d err=%v", seq, err)
	}
	if g.Status != "approved-a" && g.Status != "approved-b" {
		t.Fatalf("unexpected status %q", g.Status)
	}
}

func TestAcquireWriterBlocksSecondAndTakesOverDead(t *testing.T) {
	dir := t.TempDir()
	w1, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := AcquireWriter(dir); !errors.Is(err, ErrWriterBusy) {
		t.Fatalf("second acquire must be busy: %v", err)
	}
	if err := w1.Release(); err != nil {
		t.Fatal(err)
	}
	// Simulate a crashed holder: write a lock for a dead pid and take over.
	dead := filepath.Join(dir, LockFile)
	if err := os.WriteFile(dead, []byte("999999999\ndeadowner\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	w2, err := AcquireWriter(dir)
	if err != nil {
		t.Fatalf("stale lock must be quarantined and acquired: %v", err)
	}
	defer func() { _ = w2.Release() }()
	stale, _ := filepath.Glob(filepath.Join(dir, LockFile+".stale.*"))
	if len(stale) == 0 {
		t.Fatal("stale lock must be renamed aside, not deleted silently")
	}
}

func TestWriterReleaseRefusesForeignLock(t *testing.T) {
	dir := t.TempDir()
	w, err := AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	foreign := &Writer{Dir: dir, path: filepath.Join(dir, LockFile), owner: "other", pid: w.pid + 1}
	if err := foreign.Release(); err == nil {
		t.Fatal("must not release a lock owned by another writer")
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
}
