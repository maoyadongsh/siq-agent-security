package admission

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWalkRespectsMaxDirsDuringEnumeration(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "# skill\n")
	for i := 0; i < 5; i++ {
		dir := filepath.Join(root, "d"+string(rune('a'+i)))
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
		mustWrite(t, filepath.Join(dir, "f.txt"), "x")
	}
	lim := DefaultLimits
	lim.MaxDirs = 2
	if hash, _, err := HashDir(root, lim); err == nil || hash != "" {
		t.Fatalf("dir budget must fail closed: hash=%q err=%v", hash, err)
	}
	w, err := walk(root, lim)
	if err != nil {
		t.Fatal(err)
	}
	if !w.overLimit || w.dirsSeen <= lim.MaxDirs {
		t.Fatalf("expected over_limit after MaxDirs+1, dirsSeen=%d", w.dirsSeen)
	}
}

func TestWalkCanceledBeforeAndDuringEnumeration(t *testing.T) {
	root := t.TempDir()
	mustWrite(t, filepath.Join(root, "SKILL.md"), "# skill\n")
	for i := 0; i < 40; i++ {
		mustWrite(t, filepath.Join(root, "f"+string(rune('a'+i%26))+string(rune('0'+i/26))+".txt"), "body")
	}

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, _, err := HashDirContext(ctx, root, DefaultLimits); !errors.Is(err, ErrCanceled) {
		t.Fatalf("pre-canceled scan must return ErrCanceled, got %v", err)
	}

	ctx, cancel = context.WithCancel(context.Background())
	done := make(chan error, 1)
	go func() {
		_, _, err := HashDirContext(ctx, root, DefaultLimits)
		done <- err
	}()
	time.Sleep(1 * time.Millisecond)
	cancel()
	select {
	case err := <-done:
		if err != nil && !errors.Is(err, ErrCanceled) {
			t.Fatalf("mid-scan cancel: %v", err)
		}
		// Tiny trees may finish before cancel; both complete success and cancel are acceptable
		// as long as cancel never hangs or panics. Prefer cancel when possible.
	case <-time.After(5 * time.Second):
		t.Fatal("canceled walk must not hang")
	}
}

func mustWrite(t *testing.T, path, body string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
}
