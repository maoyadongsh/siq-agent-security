//go:build linux

// Linux-only native acceptance checks (CL-03-HERMES-NATIVE): /proc-based
// environment whitelist verification and FIFO (non-regular file) refusal.
// These rely on Linux-specific facilities and are reported as Linux
// aarch64 evidence only — they say nothing about macOS/Windows/AMD64.

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

// TestNativeFifoConfigRefusedLinux plants a FIFO named config.yaml. The
// connector must refuse non-regular files without blocking on the FIFO
// (openRegular uses O_NOFOLLOW|O_NONBLOCK on unix) and still collect the
// profile's real SOUL.md. The rpc timeout turns any hang into a failure.
func TestNativeFifoConfigRefusedLinux(t *testing.T) {
	home := t.TempDir()
	base := canonicalFixtureDir(t, t.TempDir())
	dir := filepath.Join(base, "profiles", "fifo")
	writeFixtureFile(t, filepath.Join(dir, "SOUL.md"), "synthetic soul", 0o600)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(filepath.Join(dir, "config.yaml"), 0o600); err != nil {
		t.Skipf("mkfifo unavailable: %v", err)
	}

	s := startNativeSession(t, home)
	c1, raw1 := s.collect(t, "fifo-01", []string{filepath.Join(base, "profiles") + "/*"}, []string{"config.yaml", "SOUL.md"}, 200, 1<<20)
	checkBatchShape(t, c1)
	checkReferenceIntegrity(t, c1)
	cand := indexCandidates(t, c1)[wantCandidateID(dir)]
	if cand == nil {
		t.Fatal("profile backed by a real SOUL.md must surface even when config.yaml is a FIFO")
	}
	evIDs := listOf(t, cand, "evidence_ids")
	if len(evIDs) != 1 || evIDs[0] != wantEvidenceID(dir, "SOUL.md") {
		t.Errorf("evidence_ids=%v, want only the SOUL.md evidence", evIDs)
	}
	if got := attributesOf(t, cand)["model"]; got != "" {
		t.Errorf("FIFO config.yaml supplied model fact %q", got)
	}
	if strings.Contains(raw1, "fifo") && strings.Contains(raw1, dir) {
		t.Error("absolute fixture path leaked into the response")
	}

	// A profile whose only candidate file is a FIFO must yield nothing.
	dir2 := filepath.Join(base, "profiles", "fifo-only")
	if err := os.MkdirAll(dir2, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := syscall.Mkfifo(filepath.Join(dir2, "config.yaml"), 0o600); err != nil {
		t.Skipf("mkfifo unavailable: %v", err)
	}
	c2, _ := s.collect(t, "fifo-02", []string{filepath.Join(base, "profiles") + "/*"}, []string{"config.yaml"}, 200, 1<<20)
	checkBatchShape(t, c2)
	for id := range indexCandidates(t, c2) {
		if id == wantCandidateID(dir2) {
			t.Error("fifo-only profile must not produce a candidate")
		}
	}
}
