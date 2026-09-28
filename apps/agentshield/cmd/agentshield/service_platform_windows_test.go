package main

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// A Windows symlink privilege does not make POSIX service managers supported.
func TestWindowsRejectsPOSIXServiceRegistrationWithoutWrites(t *testing.T) {
	root := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", filepath.Join(root, "absent-state"))
	t.Setenv("HOME", root)
	t.Setenv("USERPROFILE", root)
	for _, tc := range []struct {
		name string
		call func() error
		want string
	}{
		{"launch-agent-register", func() error { return cmdLaunchAgentRegister(nil, io.Discard) }, "macOS configuration export required"},
		{"service-login-enable", func() error { return cmdServiceLogin([]string{"--enable", "--confirm-enable"}, io.Discard) }, "only available on Linux"},
		{"service-login-disable", func() error { return cmdServiceLogin([]string{"--disable"}, io.Discard) }, "only available on Linux"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if err := tc.call(); err == nil || !strings.Contains(err.Error(), tc.want) {
				t.Fatalf("unsupported service command not refused: %v", err)
			}
			entries, err := os.ReadDir(root)
			if err != nil || len(entries) != 0 {
				t.Fatal("unsupported command modified home or state", err)
			}
		})
	}
}
