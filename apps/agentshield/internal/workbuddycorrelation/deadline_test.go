package workbuddycorrelation

import (
	"context"
	"errors"
	"os"
	"siq-agent-security/apps/agentshield/internal/statefs"
	"sync"
	"testing"
	"time"
)

func TestCorrelationWaitUsesOriginalDeadlineAndPreservesLock(t *testing.T) {
	cfg, req := fixture(t)
	owner, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	defer owner.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 40*time.Millisecond)
	defer cancel()
	start := time.Now()
	if tx, err := LockWithinDeadline(ctx, cfg, req); tx != nil || !errors.Is(err, ErrUnavailable) {
		t.Fatal("deadline did not fail closed", err)
	}
	if time.Since(start) > time.Second {
		t.Fatal("deadline renewed")
	}
	if _, err := os.Stat(owner.lockPath); err != nil {
		t.Fatal("waiting removed another invocation's lock", err)
	}
	owner.Close()
	if tx, err := LockWithinDeadline(ctx, cfg, req); tx != nil || err == nil {
		t.Fatal("expired context acquired free lock")
	}
	if tx, err := LockWithinDeadline(context.Background(), cfg, req); tx != nil || err == nil {
		t.Fatal("unbounded wait allowed")
	}
}

func TestCorrelationWaitAcquiresOnlyAfterOwnerReleases(t *testing.T) {
	cfg, req := fixture(t)
	owner, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	defer owner.Close()
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	type result struct {
		tx  *Transaction
		err error
	}
	done := make(chan result, 1)
	go func() { tx, err := LockWithinDeadline(ctx, cfg, req); done <- result{tx, err} }()
	select {
	case r := <-done:
		if r.tx != nil {
			r.tx.Close()
		}
		t.Fatalf("contended wait returned before release: %v", r.err)
	case <-time.After(30 * time.Millisecond):
	}
	owner.Close()
	r := <-done
	if r.err != nil || r.tx == nil {
		t.Fatal("wait failed after release", r.err)
	}
	r.tx.Close()
}

func TestCorrelationConcurrentLockTransitions(t *testing.T) {
	cfg, req := fixture(t)
	var group sync.WaitGroup
	start := make(chan struct{})
	for i := 0; i < 10; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			<-start
			for j := 0; j < 20; j++ {
				ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
				tx, err := LockWithinDeadline(ctx, cfg, req)
				cancel()
				if err != nil {
					t.Errorf("lock transition: %v", err)
					return
				}
				tx.Close()
			}
		}()
	}
	close(start)
	group.Wait()
}

func TestCorrelationReleasePreservesReplacementLock(t *testing.T) {
	cfg, req := fixture(t)
	owner, err := Lock(cfg, req)
	if err != nil {
		t.Fatal(err)
	}
	name := owner.lockPath
	if err := os.Rename(name, name+".original"); err != nil {
		t.Fatal(err)
	}
	f, err := statefs.CreatePrivate(name)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = f.WriteString("replacement"); err != nil {
		t.Fatal(err)
	}
	if err = f.Close(); err != nil {
		t.Fatal(err)
	}
	owner.Close()
	raw, err := statefs.ReadPrivateFile(name, 100)
	if err != nil || string(raw) != "replacement" {
		t.Fatal("release removed another lock")
	}
	if tx, err := Lock(cfg, req); tx != nil || !errors.Is(err, ErrBusy) {
		t.Fatal("replacement no longer excludes callers")
	}
}
