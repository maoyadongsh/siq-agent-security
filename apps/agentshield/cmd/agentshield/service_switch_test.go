package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestServeRefusesIncompleteServiceSwitchBeforeIdentityCreation(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	initializePreProfileFixture(t, dir)
	if err := os.WriteFile(filepath.Join(dir, "service-switch.pending.json"), []byte("invalid pending"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := cmdServe(nil); err == nil || !strings.Contains(err.Error(), "switch pending") {
		t.Fatal("pending switch accepted", err)
	}
	if _, err := os.Stat(filepath.Join(dir, "keys", "signing.seed")); !os.IsNotExist(err) {
		t.Fatal("serve created identity before refusal")
	}
	if _, err := os.Stat(filepath.Join(dir, "serve.lock")); !os.IsNotExist(err) {
		t.Fatal("serve retained writer")
	}
}
