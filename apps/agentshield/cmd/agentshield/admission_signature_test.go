package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/admission"
	"siq-agent-security/apps/agentshield/internal/signing"
)

func TestAdmissionExportDoesNotChangeSignedCardReference(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	k, err := signing.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	root, err := filepath.Abs(filepath.Join("..", "..", "internal", "admission", "testdata", "skills", "benign", "official-like"))
	if err != nil {
		t.Fatal(err)
	}
	out := t.TempDir()
	if err := cmdAdmit([]string{root, "--out", out}); err != nil {
		t.Fatal(err)
	}
	entries, err := filepath.Glob(filepath.Join(out, "adm-*.json"))
	if err != nil || len(entries) != 1 {
		t.Fatal("missing export", err)
	}
	raw, err := os.ReadFile(entries[0])
	if err != nil {
		t.Fatal(err)
	}
	var value admission.Admission
	if json.Unmarshal(raw, &value) != nil || !admission.Verify(k.Public(), value) {
		t.Fatal("export invalidated signature")
	}
	if value.SkillCardRef != nil {
		t.Fatal("post-signing path inserted")
	}
	if _, err := os.Stat(filepath.Join(out, value.AdmissionID+".skill-card.md")); err != nil {
		t.Fatal("card missing", err)
	}
	stored, err := os.ReadFile(filepath.Join(dir, "admissions", value.AdmissionID+".json"))
	if err != nil {
		t.Fatal(err)
	}
	if string(stored) != string(raw) {
		t.Fatal("stored and exported signed documents differ")
	}
}
