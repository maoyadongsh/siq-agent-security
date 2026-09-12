package main

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func upgradeFixture(t *testing.T) (*state.Store, []byte, []byte, state.UserServiceRecord) {
	t.Helper()
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if _, err = st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	key, err := signing.Load(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	source, target := []byte("source unit"), []byte("target unit")
	record, err := st.PrepareUserService(w, key, source)
	if err != nil {
		t.Fatal(err)
	}
	return st, source, target, record
}
func TestServiceUpgradeReloadFailureRecoveryAndReuse(t *testing.T) {
	st, source, target, record := upgradeFixture(t)
	active := "active"
	pid := "100"
	failReload := true
	stops, starts := 0, 0
	control := func(args ...string) (string, error) {
		switch args[0] {
		case "show":
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=success\n", filepath.Join(st.Dir, record.UnitName), active, pid), nil
		case "stop":
			stops++
			active = "inactive"
			pid = "0"
		case "start":
			if _, err := os.Stat(filepath.Join(st.Dir, "serve.lock")); !os.IsNotExist(err) {
				t.Fatal("started while writer held")
			}
			starts++
			active = "active"
			pid = "101"
		case "daemon-reload":
			if failReload {
				return "", errors.New("injected reload failure")
			}
		default:
			t.Fatalf("unexpected mutation %v", args)
		}
		return "", nil
	}
	var out bytes.Buffer
	err := upgradeUserService(st, source, target, "", &out, control, func() error { return nil }, func() error { return nil })
	if err == nil || stops != 1 || starts != 0 {
		t.Fatal("reload failure reported success", err)
	}
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	id := strings.TrimPrefix(lines[len(lines)-1], "切换事务：")
	if len(id) != 64 {
		t.Fatalf("missing recovery ID: %q", id)
	}
	failReload = false
	if err = upgradeUserService(st, source, []byte("different target"), id, io.Discard, control, func() error { return nil }, func() error { return nil }); err == nil {
		t.Fatal("recovery switched candidate")
	}
	if err = upgradeUserService(st, source, target, id, io.Discard, control, func() error { return nil }, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	if starts != 1 || stops != 1 {
		t.Fatal("recovery unexpectedly stopped again")
	}
	if err = upgradeUserService(st, source, target, id, io.Discard, control, func() error { return nil }, func() error { return nil }); err != nil {
		t.Fatal("ready target reuse", err)
	}
	if starts != 1 || stops != 1 {
		t.Fatal("reuse restarted service")
	}
}
func TestServiceUpgradeRejectsBeforeStopping(t *testing.T) {
	st, source, target, record := upgradeFixture(t)
	for _, foreign := range []bool{false, true} {
		path := filepath.Join(st.Dir, record.UnitName)
		if foreign {
			path += ".foreign"
		}
		control := func(args ...string) (string, error) {
			if args[0] != "show" {
				t.Fatal("stopped before candidate/ownership verified")
			}
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=active\nMainPID=123\nResult=success\n", path), nil
		}
		if err := upgradeUserService(st, source, target, "", io.Discard, control, func() error { return errors.New("candidate invalid") }, func() error { return nil }); err == nil {
			t.Fatal("invalid candidate accepted")
		}
	}
}
func TestServiceUpgradeRequiresConfirmation(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("Linux CLI")
	}
	dir := filepath.Join(t.TempDir(), "absent")
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	if cmdServiceUpgrade(nil, io.Discard) == nil {
		t.Fatal("unconfirmed upgrade accepted")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatal("confirmation rejection wrote state")
	}
}

func TestServiceUpgradeFailedTargetRecovery(t *testing.T) {
	st, source, target, record := upgradeFixture(t)
	active, pid, result := "active", "100", "success"
	failStart := true
	starts := 0
	control := func(args ...string) (string, error) {
		switch args[0] {
		case "show":
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=%s\n", filepath.Join(st.Dir, record.UnitName), active, pid, result), nil
		case "stop":
			active, pid = "inactive", "0"
		case "start":
			starts++
			if failStart {
				active, pid, result = "failed", "0", "exit-code"
				return "", errors.New("candidate startup failure")
			}
			active, pid, result = "active", "101", "success"
		case "daemon-reload":
		default:
			t.Fatalf("unexpected action %v", args)
		}
		return "", nil
	}
	var out bytes.Buffer
	if err := upgradeUserService(st, source, target, "", &out, control, func() error { return nil }, func() error { return nil }); err == nil {
		t.Fatal("failed target reported healthy")
	}
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	id := strings.TrimPrefix(lines[len(lines)-1], "切换事务：")
	if len(id) != 64 {
		t.Fatal("transaction id missing")
	}
	failStart = false
	if err := upgradeUserService(st, source, target, id, io.Discard, control, func() error { return nil }, func() error { return nil }); err != nil {
		t.Fatal("failed target cannot recover", err)
	}
	if starts != 2 {
		t.Fatal("target not retried")
	}
}

func TestFailedUpgradeRecoveryRejectsLiveWriterAndAmbiguousProcess(t *testing.T) {
	for _, scenario := range []string{"live-writer", "activating", "unknown-pid", "nonzero-pid"} {
		t.Run(scenario, func(t *testing.T) {
			st, source, target, record := upgradeFixture(t)
			key, err := signing.LoadExisting(st.Dir)
			if err != nil {
				t.Fatal(err)
			}
			w, err := state.AcquireWriter(st.Dir)
			if err != nil {
				t.Fatal(err)
			}
			id, err := st.PrepareServiceSwitch(w, key, source, target)
			if err != nil {
				w.Release()
				t.Fatal(err)
			}
			if scenario == "live-writer" {
				defer w.Release()
			} else {
				if err = w.Release(); err != nil {
					t.Fatal(err)
				}
			}
			active, pid := "failed", "0"
			switch scenario {
			case "activating":
				active = "activating"
			case "unknown-pid":
				pid = ""
			case "nonzero-pid":
				pid = "123"
			}
			control := func(args ...string) (string, error) {
				if args[0] != "show" {
					t.Fatal("recovery mutated an unsafe process state")
				}
				return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=exit-code\n", filepath.Join(st.Dir, record.UnitName), active, pid), nil
			}
			if err = upgradeUserService(st, source, target, id, io.Discard, control, func() error { return nil }, func() error { return nil }); err == nil {
				t.Fatal("unsafe recovery accepted")
			}
			if _, err = st.VerifyUserService(key, source); err != nil {
				t.Fatal("source changed after rejection", err)
			}
		})
	}
}
