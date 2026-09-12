package main

import (
	"errors"
	"fmt"
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

func TestTeardownResumesAfterRegistrationRemoval(t *testing.T) {
	st, source, _, record := upgradeFixture(t)
	path := filepath.Join(st.Dir, record.UnitName)
	fragment := filepath.Join(t.TempDir(), record.UnitName)
	if err := os.Symlink(path, fragment); err != nil {
		t.Skip("symlinks unavailable")
	}
	active, pid, loaded := "active", "200", true
	reloads := 0
	control := func(args ...string) (string, error) {
		switch args[0] {
		case "show":
			if !loaded {
				return "LoadState=not-found\nFragmentPath=\nDropInPaths=\nUnitFileState=\nActiveState=inactive\nMainPID=0\n", nil
			}
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=success\n", fragment, active, pid), nil
		case "stop":
			active, pid = "inactive", "0"
			return "", nil
		case "daemon-reload":
			reloads++
			if reloads == 2 {
				return "", errors.New("injected unregister reload failure")
			}
			if _, err := os.Lstat(fragment); os.IsNotExist(err) {
				loaded = false
			}
			return "", nil
		default:
			t.Fatalf("unexpected teardown action %v", args)
			return "", nil
		}
	}
	config, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	if err := teardownUserService(st, source, control); err == nil {
		t.Fatal("interrupted removal reported success")
	}
	if _, err := os.Lstat(fragment); !os.IsNotExist(err) {
		t.Fatal("failure did not reach removed registration")
	}
	if err := teardownUserService(st, source, control); err != nil {
		t.Fatal("reload recovery", err)
	}
	if loaded {
		t.Fatal("registration remained")
	}
	after, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil || string(after) != string(config) {
		t.Fatal("data changed")
	}
}
