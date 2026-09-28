package main

import (
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func TestTeardownConfirmationAndAbsentWriterSafety(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "absent")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	for _, args := range [][]string{nil, {"--confirm-teardown", "extra"}} {
		if err := cmdTeardown(args, io.Discard); err == nil {
			t.Fatal("invalid confirmation accepted")
		}
		if _, err := os.Lstat(dir); !os.IsNotExist(err) {
			t.Fatal("confirmation failure wrote state")
		}
	}
	st, source, _, _ := upgradeFixture(t)
	control := func(args ...string) (string, error) {
		if args[0] != "show" {
			t.Fatalf("mutated absent unit %v", args)
		}
		return "LoadState=not-found\nFragmentPath=\nDropInPaths=\nUnitFileState=\nActiveState=inactive\nMainPID=0\n", nil
	}
	writer, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	if err := teardownUserService(st, source, control); err == nil {
		t.Fatal("teardown reported success with active writer")
	}
	if err := writer.Release(); err != nil {
		t.Fatal(err)
	}
	if err := teardownUserService(st, source, control); err != nil {
		t.Fatal("absent repeat", err)
	}
	if err := teardownUserService(st, []byte("foreign unit"), control); err == nil {
		t.Fatal("foreign source accepted")
	}
}
