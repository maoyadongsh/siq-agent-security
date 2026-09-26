package main

import (
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestSoulOnlyScopeDoesNotDeriveConfigFactsOrCursor(t *testing.T) {
	dir := t.TempDir()
	if os.WriteFile(filepath.Join(dir, "SOUL.md"), []byte("synthetic role"), 0600) != nil {
		t.Fatal("fixture")
	}
	config := filepath.Join(dir, "config.yaml")
	if os.WriteFile(config, []byte("model:\n  default: forbidden-model\nplatform_toolsets:\n  - name: forbidden-tool\n"), 0600) != nil {
		t.Fatal("fixture")
	}
	plan := protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{dir}, Include: []string{"SOUL.md"}}, Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20}}
	first, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Candidates) != 1 || first.Candidates[0].Attributes["model"] != "" || len(first.PermissionFacts) != 0 {
		t.Fatal("excluded config influenced facts")
	}
	if os.WriteFile(config, []byte("changed excluded bytes"), 0600) != nil {
		t.Fatal("fixture")
	}
	second, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if first.Cursor != second.Cursor {
		t.Fatal("excluded config influenced cursor")
	}
	if os.WriteFile(filepath.Join(dir, "SOUL.md"), []byte("included role changed"), 0600) != nil {
		t.Fatal("fixture")
	}
	third, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if third.Cursor == second.Cursor {
		t.Fatal("included content change not reflected in cursor")
	}
}

func TestConfigSymlinkCannotSupplyMetadata(t *testing.T) {
	dir, external := t.TempDir(), t.TempDir()
	outside := filepath.Join(external, "config.yaml")
	if os.WriteFile(outside, []byte("model:\n  default: outside-model\n"), 0600) != nil {
		t.Fatal("fixture")
	}
	if os.Symlink(outside, filepath.Join(dir, "config.yaml")) != nil {
		t.Fatal("symlink fixture")
	}
	if os.WriteFile(filepath.Join(dir, "SOUL.md"), []byte("synthetic role"), 0600) != nil {
		t.Fatal("fixture")
	}
	plan := protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{dir}, Include: []string{"config.yaml", "SOUL.md"}}, Limits: protocol.CollectLimits{MaxFiles: 200, MaxBytes: 1 << 20}}
	first, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Candidates) != 1 || first.Candidates[0].Attributes["model"] != "" {
		t.Fatal("escaped config influenced candidate")
	}
	if os.WriteFile(outside, []byte("outside changed"), 0600) != nil {
		t.Fatal("fixture")
	}
	second, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if first.Cursor != second.Cursor {
		t.Fatal("escaped config influenced cursor")
	}
}
