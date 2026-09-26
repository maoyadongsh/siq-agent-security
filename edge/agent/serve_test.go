package main

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestServeLoopsIndependentAndCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	heartbeats := make(chan struct{}, 10)
	started := make(chan struct{})
	stopped := make(chan error, 1)
	go func() {
		stopped <- serveLoops(ctx, func(context.Context) error {
			heartbeats <- struct{}{}
			return nil
		}, func(ctx context.Context) error { close(started); <-ctx.Done(); return ctx.Err() }, time.Millisecond, 10*time.Millisecond)
	}()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("task did not start")
	}
	for i := 0; i < 2; i++ {
		select {
		case <-heartbeats:
		case <-time.After(time.Second):
			t.Fatal("task blocked heartbeat")
		}
	}
	cancel()
	select {
	case err := <-stopped:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		t.Fatal("failed to drain")
	}
}

func TestServeRetriesAndResets(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	calls := 0
	err := serveLoops(ctx, func(ctx context.Context) error { <-ctx.Done(); return ctx.Err() }, func(context.Context) error {
		calls++
		if calls == 4 {
			cancel()
			return nil
		}
		if calls == 2 {
			return nil
		}
		return errors.New("temporary")
	}, time.Millisecond, 4*time.Millisecond)
	if err != nil || calls != 4 {
		t.Fatalf("err=%v calls=%d", err, calls)
	}
}

func TestServeHelpDoesNotLoadState(t *testing.T) {
	t.Setenv("SIQ_EDGE_STATE_DIR", t.TempDir()+"/missing")
	if err := cmdServe(context.Background(), []string{"--help"}); err != nil {
		t.Fatal(err)
	}
	if err := cmdServe(context.Background(), []string{"unexpected"}); err == nil {
		t.Fatal("accepted arguments")
	}
}
