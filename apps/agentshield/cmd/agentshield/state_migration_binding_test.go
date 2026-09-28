package main

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/apps/agentshield/internal/product"
	"siq-agent-security/apps/agentshield/internal/stateformat"
)

func TestMigrationInvocationBindsExactDirectoryExecutableAndBytes(t *testing.T) {
	dir, other := t.TempDir(), t.TempDir()
	exe := filepath.Join(t.TempDir(), "candidate.exe")
	if err := os.WriteFile(exe, []byte("synthetic candidate A"), 0600); err != nil {
		t.Fatal(err)
	}
	first, err := inspectMigrationExecutable(dir, exe)
	if err != nil {
		t.Fatal(err)
	}
	changed, err := inspectMigrationExecutable(other, exe)
	if err != nil || changed.Binding == first.Binding {
		t.Fatal("directory not bound", err)
	}
	copyPath := exe + ".copy"
	if err := os.WriteFile(copyPath, []byte("synthetic candidate A"), 0600); err != nil {
		t.Fatal(err)
	}
	changed, err = inspectMigrationExecutable(dir, copyPath)
	if err != nil || changed.Binding == first.Binding {
		t.Fatal("fixed path not bound", err)
	}
	if err := os.WriteFile(exe, []byte("synthetic candidate B"), 0600); err != nil {
		t.Fatal(err)
	}
	changed, err = inspectMigrationExecutable(dir, exe)
	if err != nil || changed.Binding == first.Binding {
		t.Fatal("bytes not bound", err)
	}
}

func TestMigrationCommandPreviewAndChangedBinding(t *testing.T) {
	dir := t.TempDir()
	initializePreProfileFixture(t, dir)
	t.Setenv(product.EnvStateDir, dir)
	marker := filepath.Join(dir, stateformat.MarkerName)
	before, err := os.ReadFile(marker)
	if err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	if err := cmdStateMigrate([]string{"--preview"}, &out); err != nil {
		t.Fatal(err)
	}
	var view migrationCommandPreview
	if err := json.Unmarshal(out.Bytes(), &view); err != nil || view.InvocationBinding == "" || view.ExecutablePath == "" {
		t.Fatal("missing invocation", err)
	}
	if err := cmdStateMigrate([]string{"--confirm", "--binding", "changed"}, io.Discard); err == nil {
		t.Fatal("changed invocation accepted")
	}
	after, err := os.ReadFile(marker)
	if err != nil || !bytes.Equal(before, after) {
		t.Fatal("refused invocation changed state")
	}
	if _, err := os.Lstat(filepath.Join(dir, stateformat.MigrationDir)); !os.IsNotExist(err) {
		t.Fatal("refused invocation created journal")
	}
	if err := cmdStateMigrate([]string{"--confirm", "--binding", view.InvocationBinding}, io.Discard); err != nil {
		t.Fatal(err)
	}
}
