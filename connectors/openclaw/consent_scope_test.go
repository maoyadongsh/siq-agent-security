package main

import (
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestCollectionCannotBypassIncludeOrExcludeScope(t *testing.T) {
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "openclaw.json"), []byte(fixtureConfig), 0600); err != nil {
		t.Fatal(err)
	}
	for _, scope := range []*protocol.Scope{
		{Roots: []string{root}, Include: []string{"SOUL.md"}},
		{Roots: []string{root}, Include: []string{"openclaw.json"}, Exclude: []string{"openclaw.json"}},
	} {
		if len(validateScope(scope)) == 0 {
			t.Fatal("nonselected config allowed")
		}
		batch, err := collectOp(protocol.ScanPlan{Scope: scope})
		if err == nil || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
			t.Fatal("direct collection ignored scope")
		}
	}
	batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}, Include: []string{"openclaw.json"}}})
	if err != nil || len(batch.Candidates) == 0 {
		t.Fatal("explicit config scope stopped working")
	}
}
