package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func TestRollbackFailedCandidateToRecordedSource(t *testing.T) {
	st, source, target, record := upgradeFixture(t)
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	original, err := st.PrepareServiceSwitch(w, key, source, target)
	if err == nil {
		err = st.ApplyServiceSwitch(w, key, original)
	}
	w.Release()
	if err != nil {
		t.Fatal(err)
	}
	config, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	active, pid, result := "failed", "0", "exit-code"
	mutations := 0
	control := func(args ...string) (string, error) {
		if args[0] == "show" {
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=%s\n", filepath.Join(st.Dir, record.UnitName), active, pid, result), nil
		}
		mutations++
		switch args[0] {
		case "stop":
			active = "inactive"
		case "start":
			active, pid, result = "active", "200", "success"
		case "daemon-reload":
		default:
			t.Fatalf("unexpected mutation %v", args)
		}
		return "", nil
	}
	if err = rollbackUserService(st, original, []byte("different source"), "", io.Discard, control, func() error { return nil }, func() error { return nil }); err == nil || mutations != 0 {
		t.Fatal("unrelated rollback allowed")
	}
	if err = rollbackUserService(st, original, source, "", io.Discard, control, func() error { return nil }, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	if _, err = st.VerifyUserService(key, source); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(filepath.Join(st.Dir, "config.json"))
	if err != nil || string(after) != string(config) {
		t.Fatal("rollback changed configuration")
	}
	w, err = state.AcquireWriter(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	defer w.Release()
	if st.ApplyServiceSwitch(w, key, original) == nil {
		t.Fatal("old completed upgrade replayed after rollback")
	}
}
