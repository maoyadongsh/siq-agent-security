package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

func TestSkillImportCLIFixesCandidateWithoutGrantOrInstallation(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	source := t.TempDir()
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("---\nname: cli-import\ndescription: Read a report.\n---\nRead a report.\n"), 0600); err != nil {
		t.Fatal(err)
	}
	id := "si-" + strings.Repeat("b", 32)
	args := []string{"--path", source, "--actor", "fixture-human", "--id", id}
	var out bytes.Buffer
	if err := cmdImportSkill(args, &out); err != nil {
		t.Fatal(err)
	}
	var first skillimport.Result
	if json.Unmarshal(out.Bytes(), &first) != nil || first.Installed || first.Reused || first.Import.ImportID != id {
		t.Fatal("invalid response")
	}
	if first.Admission.Verdict == "quarantine" {
		t.Fatal("benign fixture quarantined")
	}
	if _, err := os.Stat(filepath.Join(dir, "grants")); !os.IsNotExist(err) {
		t.Fatal("import created grants")
	}
	if err := os.WriteFile(filepath.Join(source, "SKILL.md"), []byte("changed source"), 0600); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err := cmdImportSkill(args, &out); err != nil {
		t.Fatal(err)
	}
	var retry skillimport.Result
	if json.Unmarshal(out.Bytes(), &retry) != nil || !retry.Reused || retry.Installed || retry.Import.ArtifactDigest != first.Import.ArtifactDigest {
		t.Fatal("retry did not preserve fixed copy")
	}
	writer, err := state.AcquireWriter(dir)
	if err != nil {
		t.Fatal(err)
	}
	defer writer.Release()
	out.Reset()
	if err := cmdImportSkill(args, &out); !errors.Is(err, state.ErrWriterBusy) {
		t.Fatal("CLI bypassed daemon writer lock", err)
	}
	if out.Len() != 0 {
		t.Fatal("failed operation emitted success")
	}
}

func TestSkillImportCLIRemoteFlagsAndBlockedURL(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	for _, args := range [][]string{
		{"--actor", "human"},
		{"--path", "/fixture", "--url", "https://download.example.com/a", "--actor", "human"},
		{"--path", "/fixture", "--archive-path", "repo/skill", "--actor", "human"},
		{"--path", "/fixture", "--sha256", strings.Repeat("0", 64), "--actor", "human"},
		{"--url", "https://download.example.com/a", "--kind", "local_dir", "--actor", "human"},
	} {
		var out bytes.Buffer
		if err := cmdImportSkill(args, &out); err == nil || out.Len() != 0 {
			t.Fatal("invalid flags accepted", args, err)
		}
	}
	var out bytes.Buffer
	err := cmdImportSkill([]string{"--url", "https://127.0.0.1/private?token=secret", "--archive-path", "repo/skill", "--actor", "human"}, &out)
	if !errors.Is(err, skillimport.ErrURLBlocked) || strings.Contains(err.Error(), "secret") || out.Len() != 0 {
		t.Fatal("unsafe URL accepted or exposed", err)
	}
}
