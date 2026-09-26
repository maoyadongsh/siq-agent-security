package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func identityConfig(t *testing.T, root string, agents []map[string]string, auth bool) {
	t.Helper()
	body, err := json.Marshal(map[string]any{"agents": map[string]any{"list": agents}})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "openclaw.json"), body, 0600); err != nil {
		t.Fatal(err)
	}
	if auth {
		if err := os.MkdirAll(filepath.Join(root, "agents"), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(root, "agents", "auth-profiles.json"), []byte("private-fixture-content"), 0600); err != nil {
			t.Fatal(err)
		}
	}
}

func identityCollect(t *testing.T, roots ...string) protocol.EvidenceBatch {
	t.Helper()
	batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: roots}, Limits: defaultLimits()})
	if err != nil {
		t.Fatal(err)
	}
	return batch
}

func TestOpenClawIdentitySeparatesNamesPrefixesAndRoots(t *testing.T) {
	a, b := t.TempDir(), t.TempDir()
	agents := []map[string]string{
		{"id": "shared-prefix-a", "name": "same-name", "model": "fixture/model"},
		{"id": "shared-prefix-b", "name": "same-name", "model": "fixture/model"},
	}
	identityConfig(t, a, agents, true)
	identityConfig(t, b, agents, true)
	batch := identityCollect(t, a, b, a)
	if len(batch.Candidates) != 4 || len(batch.Evidence) != 6 {
		t.Fatal("roots or duplicate names collapsed", batch)
	}
	ids, evidence, refs := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, candidate := range batch.Candidates {
		if ids[candidate.CandidateID] || !strings.HasPrefix(candidate.CandidateID, "openclaw:v2:") {
			t.Fatal("role identity collision")
		}
		ids[candidate.CandidateID] = true
		if strings.Contains(candidate.SourceLocator, "same-name") || strings.Contains(candidate.SourceLocator, a) {
			t.Fatal("display name or raw path used as identity")
		}
		for _, id := range candidate.EvidenceIDs {
			refs[id] = true
		}
	}
	for _, item := range batch.Evidence {
		if evidence[item.EvidenceID] || !refs[item.EvidenceID] {
			t.Fatal("duplicate or unreferenced evidence", item.EvidenceID)
		}
		evidence[item.EvidenceID] = true
		if item.ContentHash == protocol.ContentHash([]byte("private-fixture-content")) {
			t.Fatal("secret content hashed")
		}
	}
	for _, fact := range batch.PermissionFacts {
		if fact.State != "declared" || !ids[fact.Subject.ID] {
			t.Fatal("permission reference or authority changed")
		}
		for _, id := range fact.EvidenceIDs {
			if !evidence[id] {
				t.Fatal("missing permission evidence")
			}
		}
	}
}

func TestOpenClawRenamePreservesRoleButChangesObservation(t *testing.T) {
	root := t.TempDir()
	agents := []map[string]string{{"id": "stable-id", "name": "before"}}
	identityConfig(t, root, agents, false)
	before := identityCollect(t, root)
	agents[0]["name"] = "after"
	identityConfig(t, root, agents, false)
	after := identityCollect(t, root)
	if before.Candidates[0].CandidateID != after.Candidates[0].CandidateID || before.Candidates[0].SourceLocator != after.Candidates[0].SourceLocator {
		t.Fatal("rename changes role identity")
	}
	if before.Evidence[0].EvidenceID == after.Evidence[0].EvidenceID {
		t.Fatal("new configuration reused old evidence")
	}
}

func TestOpenClawMissingOrAmbiguousIdentityFailsClosed(t *testing.T) {
	for _, agents := range [][]map[string]string{
		{{"name": "name-is-not-id"}},
		{{"id": "same"}, {"id": "same"}},
		{{"id": " spaced "}},
		{{"id": "control\n"}},
		{{"id": "embedded\u0085control"}},
		{{"id": strings.Repeat("a", 129)}},
	} {
		root := t.TempDir()
		identityConfig(t, root, agents, false)
		batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}}, Limits: defaultLimits()})
		if err == nil || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
			t.Fatal("ambiguous identity accepted")
		}
	}
}

func TestOpenClawNoOrphanMetadata(t *testing.T) {
	root := t.TempDir()
	identityConfig(t, root, []map[string]string{}, true)
	batch := identityCollect(t, root)
	if len(batch.Evidence) != 0 || len(batch.Candidates) != 0 {
		t.Fatal("unreferenced metadata emitted")
	}
}

func TestOpenClawInvalidUTF8CannotBecomeReplacementIdentity(t *testing.T) {
	root := t.TempDir()
	data := []byte("{\"agents\":{\"list\":[{\"id\":\"bad\xff\"}]}}")
	if err := os.WriteFile(filepath.Join(root, "openclaw.json"), data, 0600); err != nil {
		t.Fatal(err)
	}
	batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}}, Limits: defaultLimits()})
	if err == nil || len(batch.Candidates) != 0 {
		t.Fatal("invalid encoding produced identity")
	}
}
