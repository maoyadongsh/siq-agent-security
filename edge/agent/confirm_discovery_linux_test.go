//go:build linux

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestConfirmDiscoveryPersistsRestriction(t *testing.T) {
	parent := t.TempDir()
	if err := os.Chmod(parent, 0700); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(parent, "private")
	t.Setenv("SIQ_EDGE_STATE_DIR", dir)
	s, task := consentFixture(t)
	raw := s.DiscoveryPlan
	s.DiscoveryPlan = nil
	s.DiscoveryPlanSHA256 = ""
	s.Secret = "synthetic-secret"
	if s.Save() != nil {
		t.Fatal("state fixture")
	}
	plan := filepath.Join(t.TempDir(), "plan.json")
	if os.WriteFile(plan, raw, 0600) != nil {
		t.Fatal("plan fixture")
	}
	h := sha256.Sum256(raw)
	args := []string{"--plan", plan, "--tenant", "tenant-fixture", "--confirm-plan-sha256", hex.EncodeToString(h[:])}
	now, _ := time.Parse(time.RFC3339, "2026-09-25T01:01:00Z")
	if confirmDiscovery(args, now.Add(time.Hour), "arm64") != errDiscoveryConsent {
		t.Fatal("expired confirmation accepted")
	}
	if confirmDiscovery(args, now, "arm64") != nil {
		t.Fatal("confirmation failed")
	}
	loaded, err := LoadState()
	if err != nil || loaded.Secret != s.Secret || checkDiscoveryConsent(loaded, task) != nil {
		t.Fatal("state formatting broke consent or identity", err)
	}
	if loaded.DiscoveryPlanSHA256 == "" {
		t.Fatal("consent not persisted")
	}
}
