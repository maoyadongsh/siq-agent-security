package adapterinstall

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestNativePreviewContextCancellation(t *testing.T) {
	cli, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"canceled", "deadline"} {
		t.Run(mode, func(t *testing.T) {
			stage, err := newNativeStage(cli)
			if err != nil {
				t.Fatal(err)
			}
			defer stage.close()
			ready := filepath.Join(stage.dir, "helper-ready")
			late := filepath.Join(stage.dir, "must-not-finish")
			stage.env = append(stage.env, "SIQ_TEST_NATIVE_CONTEXT_READY="+ready, "SIQ_TEST_NATIVE_CONTEXT_LATE="+late)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "deadline" {
				ctx, cancel = context.WithTimeout(context.Background(), 2*time.Second)
				defer cancel()
			}
			stage.ctx = ctx
			type result struct {
				raw []byte
				err error
			}
			done := make(chan result, 1)
			go func() {
				raw, err := stage.command("profile", "-test.run=^TestNativePreviewContextHelper$")
				done <- result{raw, err}
			}()
			until := time.Now().Add(time.Second)
			for {
				if _, err := os.Stat(ready); err == nil {
					break
				}
				if time.Now().After(until) {
					cancel()
					<-done
					t.Fatal("helper did not start")
				}
				time.Sleep(5 * time.Millisecond)
			}
			if mode == "canceled" {
				cancel()
			}
			select {
			case got := <-done:
				want := context.Canceled
				if mode == "deadline" {
					want = context.DeadlineExceeded
				}
				if len(got.raw) != 0 || !errors.Is(got.err, ErrNativeCLI) || !errors.Is(got.err, want) {
					t.Fatalf("usable or unclassified canceled output: %d %v", len(got.raw), got.err)
				}
			case <-time.After(4 * time.Second):
				cancel()
				<-done
				t.Fatal("request budget did not reach the native command")
			}
			if _, err := os.Stat(late); !os.IsNotExist(err) {
				t.Fatal("canceled helper completed a later effect")
			}
		})
	}
}

func TestNativePreviewContextHelper(t *testing.T) {
	ready := os.Getenv("SIQ_TEST_NATIVE_CONTEXT_READY")
	if ready == "" {
		return
	}
	if err := os.WriteFile(ready, []byte("started"), 0600); err != nil {
		os.Exit(2)
	}
	_, _ = os.Stdout.Write([]byte(`{"partial":"must never become a plan"}`))
	time.Sleep(30 * time.Second)
	_ = os.WriteFile(os.Getenv("SIQ_TEST_NATIVE_CONTEXT_LATE"), []byte("unexpected"), 0600)
	os.Exit(0)
}

func TestPrepareContextDoesNotEscapeIntoApply(t *testing.T) {
	o := testOpts(t, Hermes)
	ctx, cancel := context.WithCancel(context.Background())
	plan, err := PrepareContext(ctx, o, "install")
	if err != nil {
		t.Fatal(err)
	}
	if plan.prepareCtx != nil {
		t.Fatal("returned plan retained the request context")
	}
	cancel()
	for range 2 {
		if _, err := Apply(plan); err != nil {
			t.Fatalf("independent confirmed apply/replay: %v", err)
		}
	}
	if plan, err := PrepareContext(ctx, o, "uninstall"); plan != nil || !errors.Is(err, context.Canceled) {
		t.Fatal("canceled request produced a plan", err)
	}
}
