package adapterinstall

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWindowsHermesNativeCommandTimeoutFailsClosed(t *testing.T) {
	cli, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	stage, err := newNativeStage(cli)
	if err != nil {
		t.Fatal(err)
	}
	defer stage.close()
	marker := filepath.Join(stage.dir, "owned-helper-started")
	stage.env = append(stage.env, "SIQ_TEST_NATIVE_TIMEOUT_MARKER="+marker)
	started := time.Now()
	raw, err := stage.command("profile", "-test.run=^TestWindowsHermesNativeTimeoutHelper$")
	if !errors.Is(err, ErrNativeCLI) || len(raw) != 0 {
		t.Fatalf("timeout returned usable output: bytes=%d err=%v", len(raw), err)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("helper did not start: %v", err)
	}
	if time.Since(started) > time.Minute {
		t.Fatal("native timeout was not bounded")
	}
}

func TestWindowsHermesNativeTimeoutHelper(t *testing.T) {
	marker := os.Getenv("SIQ_TEST_NATIVE_TIMEOUT_MARKER")
	if marker == "" {
		return
	}
	if err := os.WriteFile(marker, []byte("started"), 0600); err != nil {
		os.Exit(3)
	}
	os.Stdout.Write([]byte(`{"partial":"must not be applied"}`))
	time.Sleep(2 * time.Minute)
	os.Exit(0)
}
