package main

import (
	"errors"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/clientrelease"
	"siq-agent-security/apps/agentshield/internal/state"
	"testing"
)

func TestPrepareRollbackMissingBinary(t *testing.T) {
	st, _, _, _ := upgradeFixture(t)
	snapshot, err := clientrelease.SnapshotCurrent(st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	digest, err := clientrelease.Digest(snapshot)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "original")
	unit, err := renderUserUnit(path, st.Dir)
	if err != nil {
		t.Fatal(err)
	}
	plan := state.ServiceSwitch{SourceUnit: unit, BinaryBindings: &state.ServiceBinaryBindings{SourceSHA256: digest, TargetSHA256: digest}}
	calls := 0
	verify := func(_ string, candidate string) (string, error) {
		calls++
		actual, err := clientrelease.Digest(candidate)
		if err != nil {
			return "", err
		}
		if actual != digest {
			return "", errors.New("fixture integrity")
		}
		return "test", nil
	}
	if _, _, err := prepareRollbackBinary(st, plan, path, "fixture", false, verify); err == nil || calls != 0 {
		t.Fatal("restored without explicit flag")
	}
	wrong := filepath.Join(t.TempDir(), "unrelated")
	if _, _, err := prepareRollbackBinary(st, plan, wrong, "fixture", true, verify); err == nil || calls != 0 {
		t.Fatal("unrelated path allowed")
	}
	reject := func(string, string) (string, error) { return "", errors.New("untrusted release") }
	if _, _, err := prepareRollbackBinary(st, plan, path, "fixture", true, reject); err == nil {
		t.Fatal("untrusted snapshot restored")
	}
	if _, err := os.Lstat(path); !os.IsNotExist(err) {
		t.Fatal("verification failure wrote target")
	}
	got, version, err := prepareRollbackBinary(st, plan, path, "fixture", true, verify)
	if err != nil || got != path || version != "test" || calls != 2 {
		t.Fatal("restore failed", err, calls)
	}
	if err := os.WriteFile(path, []byte("unrelated content"), 0700); err != nil {
		t.Fatal(err)
	}
	if _, _, err := prepareRollbackBinary(st, plan, path, "fixture", true, verify); err == nil {
		t.Fatal("existing content overwritten")
	}
	raw, _ := os.ReadFile(path)
	if string(raw) != "unrelated content" {
		t.Fatal("user data changed")
	}
}
