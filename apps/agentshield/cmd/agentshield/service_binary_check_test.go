package main

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"strings"
	"testing"
)

func TestBoundUpgradeAndRollbackContentIdentity(t *testing.T) {
	st, source, target, record := upgradeFixture(t)
	oldPath, newPath := filepath.Join(t.TempDir(), "old"), filepath.Join(t.TempDir(), "new")
	write := func(path, content string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(content), 0700); err != nil {
			t.Fatal(err)
		}
	}
	write(oldPath, "old program")
	write(newPath, "new program")
	oldHash, err := clientrelease.Digest(oldPath)
	if err != nil {
		t.Fatal(err)
	}
	newHash, err := clientrelease.Digest(newPath)
	if err != nil {
		t.Fatal(err)
	}
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: oldHash, TargetSHA256: newHash}, sourcePath: oldPath, targetPath: newPath}
	active, pid, mutations := "active", "100", 0
	control := func(args ...string) (string, error) {
		if args[0] == "show" {
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=success\n", filepath.Join(st.Dir, record.UnitName), active, pid), nil
		}
		mutations++
		switch args[0] {
		case "stop":
			active, pid = "inactive", "0"
		case "start":
			active, pid = "active", "200"
		case "daemon-reload":
		default:
			t.Fatalf("unexpected mutation: %v", args)
		}
		return "", nil
	}
	noop := func() error { return nil }
	for _, path := range []string{oldPath, newPath} {
		write(path, "replacement")
		if err := upgradeUserService(st, source, target, "", io.Discard, control, noop, noop, check); err == nil || mutations != 0 {
			t.Fatal("changed binary reached stop", err)
		}
		write(oldPath, "old program")
		write(newPath, "new program")
	}
	var output bytes.Buffer
	if err := upgradeUserService(st, source, target, "", &output, control, noop, noop, check); err != nil {
		t.Fatal(err)
	}
	journalID := func() string {
		for _, line := range strings.Split(output.String(), "\n") {
			if strings.HasPrefix(line, "切换事务：") {
				return strings.TrimPrefix(line, "切换事务：")
			}
		}
		t.Fatal("missing journal")
		return ""
	}
	id := journalID()
	key, err := signing.LoadExisting(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	plan, err := st.ReadServiceSwitch(key, id)
	if err != nil {
		t.Fatal(err)
	}
	if plan.BinaryBindings == nil || *plan.BinaryBindings != check.bindings {
		t.Fatal("upgrade did not persist binary identity")
	}
	before := mutations
	wrong := *check
	wrong.bindings.TargetSHA256 = oldHash
	if err := upgradeUserService(st, source, target, id, io.Discard, control, noop, noop, &wrong); err == nil || mutations != before {
		t.Fatal("recovery changed signed bindings")
	}
	reverse := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: newHash, TargetSHA256: oldHash}, targetPath: oldPath}
	write(oldPath, "another build at same path")
	if err := rollbackUserService(st, id, source, "", io.Discard, control, noop, noop, reverse); err == nil || mutations != before {
		t.Fatal("rollback accepted replaced historical binary")
	}
	write(oldPath, "old program")
	write(newPath, "damaged current build")
	output.Reset()
	if err := rollbackUserService(st, id, source, "", &output, control, noop, noop, reverse); err != nil {
		t.Fatal(err)
	}
	plan, err = st.ReadServiceSwitch(key, journalID())
	if err != nil {
		t.Fatal(err)
	}
	if plan.BinaryBindings == nil || *plan.BinaryBindings != reverse.bindings {
		t.Fatal("rollback lost reverse identity")
	}
}

func TestBoundUpgradeRejectsDriftAfterStop(t *testing.T) {
	st, source, target, record := upgradeFixture(t)
	path := filepath.Join(t.TempDir(), "program")
	if err := os.WriteFile(path, []byte("program"), 0700); err != nil {
		t.Fatal(err)
	}
	digest, err := clientrelease.Digest(path)
	if err != nil {
		t.Fatal(err)
	}
	check := &serviceBinaryCheck{bindings: state.ServiceBinaryBindings{SourceSHA256: digest, TargetSHA256: digest}, sourcePath: path, targetPath: path}
	stopped := false
	control := func(args ...string) (string, error) {
		if args[0] == "show" {
			active, pid := "active", "100"
			if stopped {
				active, pid = "inactive", "0"
			}
			return fmt.Sprintf("LoadState=loaded\nFragmentPath=%s\nDropInPaths=\nUnitFileState=linked-runtime\nActiveState=%s\nMainPID=%s\nResult=success\n", filepath.Join(st.Dir, record.UnitName), active, pid), nil
		}
		if args[0] != "stop" {
			t.Fatalf("drift reached %s", args[0])
		}
		stopped = true
		return "", os.WriteFile(path, []byte("changed after stop"), 0700)
	}
	noop := func() error { return nil }
	if err := upgradeUserService(st, source, target, "", io.Discard, control, noop, noop, check); err == nil || !stopped {
		t.Fatal("post-stop drift accepted")
	}
	if err := st.CheckServiceSwitchPending(); err != nil {
		t.Fatal("drift created pending transaction")
	}
}
