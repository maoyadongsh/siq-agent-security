//go:build linux

// Linux-only native checks (CL-03-OPENCLAW-NATIVE-CLOSEOUT): /proc-based
// environment whitelist verification and FIFO (non-regular file) refusal of
// openclaw.json. These rely on Linux-specific facilities and are reported as
// Linux aarch64 evidence only — they say nothing about macOS/Windows/AMD64.

package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"syscall"
	"testing"
)

// TestNativeChildEnvWhitelistLinux reads the child's initial environment from
// /proc and asserts it is exactly the minimal whitelist — no real user config,
// no SIQ credentials, no proxy variables leak into the connector process.
func TestNativeChildEnvWhitelistLinux(t *testing.T) {
	home := t.TempDir()
	s := startNativeSession(t, home)

	data, err := os.ReadFile(fmt.Sprintf("/proc/%d/environ", s.cmd.Process.Pid))
	if err != nil {
		t.Fatalf("read child environ: %v", err)
	}
	got := map[string]bool{}
	for _, kv := range strings.Split(string(data), "\x00") {
		if kv == "" {
			continue
		}
		k := kv
		if i := strings.IndexByte(kv, '='); i >= 0 {
			k = kv[:i]
		}
		got[k] = true
	}
	want := map[string]bool{
		"HOME":                     true,
		"SIQ_CONNECTOR_NAME":       true,
		"SIQ_CONNECTOR_VERSION":    true,
		"SIQ_CONNECTOR_TIMEOUT_MS": true,
	}
	for k := range got {
		if !want[k] {
			t.Errorf("child environment carries non-whitelisted variable %q", k)
		}
	}
	for k := range want {
		if !got[k] {
			t.Errorf("child environment missing expected variable %q", k)
		}
	}
	// Explicit guard: no proxy or SIQ runtime/credential families, ever.
	for k := range got {
		lower := strings.ToLower(k)
		if strings.Contains(lower, "proxy") || strings.HasPrefix(k, "SIQ_AS_") || strings.Contains(lower, "token") {
			t.Errorf("child environment leaks sensitive variable family %q", k)
		}
	}

	// The process is alive and answering on this exact environment.
	resp, _ := s.rpc(t, "env-01", "describe", nil)
	rpcOK(t, resp)
}

// TestNativeFifoConfigRefusedLinux plants a FIFO named openclaw.json. The
// connector must refuse the non-regular file without blocking on the FIFO
// (openRegular uses O_NOFOLLOW|O_NONBLOCK on unix), fail with the fixed
// unavailability category, and never leak the path. The rpc timeout turns any
// hang into a failure.
func TestNativeFifoConfigRefusedLinux(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	root := filepath.Join(base, "fifo-root")
	if err := os.MkdirAll(root, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(filepath.Join(root, "openclaw.json"), 0o600); err != nil {
		t.Skipf("mkfifo unavailable: %v", err)
	}

	s := startNativeSession(t, home)
	errObj := s.collectErr(t, "fifo-01", []string{root}, 1<<20)
	msg := strOf(t, errObj, "message")
	if msg != "openclaw_config_unavailable" {
		t.Errorf("fifo config: message=%q, want openclaw_config_unavailable", msg)
	}
	if strings.Contains(msg, root) {
		t.Errorf("fifo refusal leaks the fixture path: %q", msg)
	}

	// The process survived and still serves.
	resp, _ := s.rpc(t, "fifo-02", "health", nil)
	rpcOK(t, resp)
}
