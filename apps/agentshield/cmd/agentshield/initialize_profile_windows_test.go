package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestFreshWindowsClientInitializationEnablesProfileWithoutGrants(t *testing.T) {
	t.Setenv(signing.SeedEnv, "")
	dir := filepath.Join(t.TempDir(), "state")
	if err := prepareWindowsClientInstallationIdentity(dir, 49221); err != nil {
		t.Fatal(err)
	}
	if err := stateformat.RequireWindowsProfile(dir); err != nil {
		t.Fatal(err)
	}
	st := &state.Store{Dir: dir}
	config, err := st.LoadConfig()
	if err != nil || config.Port != 49221 {
		t.Fatal("initial port was not preserved", err)
	}
	keyPath := filepath.Join(dir, "keys", "signing.seed")
	before, err := os.ReadFile(keyPath)
	if err != nil {
		t.Fatal(err)
	}
	marker, err := stateformat.ReadMarker(dir)
	if err != nil || marker.MinReader != 3 || marker.MinWriter != 3 {
		t.Fatal("fresh profile not activated", err)
	}
	if _, err := initializeLocalClient(dir, 49221); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(keyPath)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("retry replaced signing identity")
	}
	grants, err := os.ReadDir(filepath.Join(dir, "grants"))
	if err != nil || len(grants) != 0 {
		t.Fatal("storage initialization created business grants")
	}
}

func TestWindowsInitializationDoesNotUpgradeHistoricalStateImplicitly(t *testing.T) {
	t.Setenv(signing.SeedEnv, "")
	dir := t.TempDir()
	st, err := state.Open(dir)
	if err != nil {
		t.Fatal(err)
	}
	w, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := st.Initialize(w, 0); err != nil {
		t.Fatal(err)
	}
	if err := w.Release(); err != nil {
		t.Fatal(err)
	}
	markerPath := filepath.Join(dir, stateformat.MarkerName)
	before, err := os.ReadFile(markerPath)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := initializeLocalClient(dir, 0); err == nil {
		t.Fatal("historical profile was reported ready without explicit activation")
	}
	after, err := os.ReadFile(markerPath)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("existing marker upgraded implicitly")
	}
	if err := stateformat.RequireWindowsProfile(dir); err == nil {
		t.Fatal("old profile silently enabled")
	}
}

func TestWindowsInitializationRejectsEnvironmentIdentityBeforeWriting(t *testing.T) {
	t.Setenv(signing.SeedEnv, "fixture-override")
	dir := filepath.Join(t.TempDir(), "absent")
	if _, err := initializeLocalClient(dir, 0); err == nil {
		t.Fatal("environment identity accepted")
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatal("rejection created state", err)
	}
	if err := prepareWindowsProfileIdentity(dir); err == nil {
		t.Fatal("profile accepted environment identity")
	}
	if _, err := os.Lstat(dir); !os.IsNotExist(err) {
		t.Fatal("profile rejection created state", err)
	}
}
