package main

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/signing"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestLocalInventoryReusesRegisteredProjectScope(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("LOCALAPPDATA", filepath.Join(home, "AppData", "Local"))
	t.Setenv("HERMES_HOME", "")
	t.Setenv("WORKBUDDY_CONFIG_DIR", "")
	st, err := state.Open(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	project := t.TempDir()
	profile := filepath.Join(project, "agents", "hermes", "profiles", "analysis")
	if err := os.MkdirAll(profile, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(profile, "config.yaml"), []byte("model: fixture\n"), 0600); err != nil {
		t.Fatal(err)
	}
	key, err := signing.FromSeed(bytes.Repeat([]byte{7}, 32))
	if err != nil {
		t.Fatal(err)
	}
	before, err := runLocalInventory(st, key, "", "")
	if err != nil {
		t.Fatal(err)
	}
	id := hermeshome.Identifier(profile)
	for _, c := range before.Candidates {
		if c.Attributes["instance_id"] == id {
			t.Fatal("unregistered CLI profile visible")
		}
	}
	roots, rev, err := st.LoadDiscoveryRoots()
	if err != nil {
		t.Fatal(err)
	}
	roots.ProjectDirs = []string{project}
	if err := st.SaveDiscoveryRoots(roots, rev); err != nil {
		t.Fatal(err)
	}
	after, err := runLocalInventory(st, key, "", "")
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, c := range after.Candidates {
		if c.Attributes["instance_id"] == id {
			found = true
		}
	}
	if !found {
		t.Fatal("CLI ignored persisted project scope")
	}
}
