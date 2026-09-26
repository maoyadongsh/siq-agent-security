package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestMultipleRootsSameProfileNameRemainDistinct(t *testing.T) {
	root := t.TempDir()
	var roots []string
	for _, instance := range []string{"one", "two"} {
		dir := filepath.Join(root, instance, "shared-role")
		if err := os.MkdirAll(dir, 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "config.yaml"), []byte("toolsets:\n  - browser\n"), 0600); err != nil {
			t.Fatal(err)
		}
		roots = append(roots, filepath.Join(root, instance, "*"))
	}
	plan := protocol.ScanPlan{Scope: &protocol.Scope{Roots: roots, Include: []string{"config.yaml"}}}
	first, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Candidates) != 2 || len(first.Evidence) != 2 || len(first.PermissionFacts) != 2 {
		t.Fatalf("incomplete multi-root discovery: %+v", first)
	}
	if first.Candidates[0].CandidateID == first.Candidates[1].CandidateID || first.Candidates[0].SourceLocator == first.Candidates[1].SourceLocator || first.Evidence[0].EvidenceID == first.Evidence[1].EvidenceID {
		t.Fatal("same-name profiles merged")
	}
	for i, candidate := range first.Candidates {
		if candidate.Name != "shared-role" || *first.Evidence[i].SubjectRef != candidate.CandidateID || first.PermissionFacts[i].Subject.ID != candidate.CandidateID || first.PermissionFacts[i].State != "declared" {
			t.Fatal("profile evidence or permission misbound")
		}
		if first.PermissionFacts[i].EvidenceIDs[0] != first.Evidence[i].EvidenceID {
			t.Fatal("permission evidence misbound")
		}
	}
	raw, _ := json.Marshal(first)
	if strings.Contains(string(raw), root) {
		t.Fatal("absolute path disclosed")
	}
	// Root order, overlapping literal scope and changed content must not change identity.
	plan.Scope.Roots = []string{roots[1], roots[0], filepath.Join(root, "one", "shared-role")}
	if err := os.WriteFile(filepath.Join(root, "one", "shared-role", "config.yaml"), []byte("toolsets:\n  - terminal\n"), 0600); err != nil {
		t.Fatal(err)
	}
	second, err := collectOp(plan)
	if err != nil {
		t.Fatal(err)
	}
	if len(second.Candidates) != 2 {
		t.Fatal("overlapping scope duplicated profiles")
	}
	for i := range first.Candidates {
		if first.Candidates[i].CandidateID != second.Candidates[i].CandidateID || first.Evidence[i].EvidenceID != second.Evidence[i].EvidenceID {
			t.Fatal("unstable origin")
		}
	}
	if first.Evidence[0].ContentHash == second.Evidence[0].ContentHash {
		t.Fatal("changed content not observed")
	}
}

func TestSecondRootSymlinkEscapeRejected(t *testing.T) {
	first, second, outside := t.TempDir(), t.TempDir(), t.TempDir()
	if err := os.WriteFile(filepath.Join(outside, "config.yaml"), []byte("provider: forbidden\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(outside, filepath.Join(second, "escaped")); err != nil {
		t.Fatal(err)
	}
	batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{first + "/*", second + "/*"}, Include: []string{"config.yaml"}}})
	if err != nil {
		t.Fatal(err)
	}
	if len(batch.Candidates) != 0 || len(batch.Evidence) != 0 || len(batch.PermissionFacts) != 0 {
		t.Fatal("escaped profile emitted")
	}
}
