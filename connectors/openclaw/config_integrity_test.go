package main

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestConfigBudgetNeverAttestsValidPrefix(t *testing.T) {
	for _, suffix := range []string{" ", "\n// unread configuration comment", `,"ignored":true}`} {
		t.Run(suffix, func(t *testing.T) {
			root := t.TempDir()
			prefix := `{"agents":{"list":[{"id":"reader","workspace":"/fixture","skills":["docs"]}]}}`
			path := filepath.Join(root, "openclaw.json")
			if err := os.WriteFile(path, []byte(prefix+suffix), 0600); err != nil {
				t.Fatal(err)
			}
			batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}},
				Limits: protocol.CollectLimits{MaxBytes: int64(len(prefix)), MaxFiles: 200}})
			if err != nil || !batch.Truncated || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 || len(batch.PermissionFacts) != 0 {
				t.Fatalf("partial configuration generated evidence: err=%v candidates=%d evidence=%d facts=%d truncated=%v",
					err, len(batch.Candidates), len(batch.Evidence), len(batch.PermissionFacts), batch.Truncated)
			}
			data, err := readFileLimited(path, int64(len(prefix)))
			if !errors.Is(err, errBudgetExhausted) || len(data) != 0 {
				t.Fatal("oversized configuration returned usable prefix")
			}
		})
	}
}

func TestConfigExactBudgetKeepsCompleteDigest(t *testing.T) {
	root := t.TempDir()
	body := []byte("{} // full comment\n")
	if err := os.WriteFile(filepath.Join(root, "openclaw.json"), body, 0600); err != nil {
		t.Fatal(err)
	}
	batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}},
		Limits: protocol.CollectLimits{MaxBytes: int64(len(body)), MaxFiles: 200}})
	if err != nil || batch.Truncated || len(batch.Candidates) != 1 || len(batch.Evidence) != 1 || len(batch.PermissionFacts) != 0 {
		t.Fatalf("complete configuration rejected: %v %+v", err, batch)
	}
	if batch.Evidence[0].ContentHash != protocol.ContentHash(body) {
		t.Fatal("evidence is not the full raw configuration digest")
	}
}

func TestConfigBudgetRetainsOnlyPreviouslyCompleteRoots(t *testing.T) {
	first, second := t.TempDir(), t.TempDir()
	for _, root := range []string{first, second} {
		if err := os.WriteFile(filepath.Join(root, "openclaw.json"), []byte("{} "), 0600); err != nil {
			t.Fatal(err)
		}
	}
	batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{first, second}},
		Limits: protocol.CollectLimits{MaxBytes: 5, MaxFiles: 200}})
	if err != nil || !batch.Truncated || len(batch.Candidates) != 1 || len(batch.Evidence) != 1 || len(batch.PermissionFacts) != 0 {
		t.Fatalf("incomplete root affected complete results: %v %+v", err, batch)
	}
	if batch.Evidence[0].SourceLocator != filepath.Join(first, "openclaw.json") || batch.Evidence[0].ContentHash != protocol.ContentHash([]byte("{} ")) {
		t.Fatal("retained evidence does not belong to complete first root")
	}
}
