package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func defaultRoleCollect(t *testing.T, root, body string) (protocol.EvidenceBatch, error) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(root, "openclaw.json"), []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
	return collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}}, Limits: defaultLimits()})
}

func TestDefaultRoleIsConfigInferenceNotRuntimeOrPermission(t *testing.T) {
	for _, body := range []string{`{}`, `{"agents":{}}`, `{"agents":{"defaults":{}}}`} {
		batch, err := defaultRoleCollect(t, t.TempDir(), body)
		if err != nil || len(batch.Candidates) != 1 || len(batch.Evidence) != 1 || len(batch.PermissionFacts) != 0 {
			t.Fatalf("unexpected default discovery: %v %+v", err, batch)
		}
		candidate := batch.Candidates[0]
		if candidate.Name != "main" || candidate.Attributes["role_identity_basis"] != "config_default" {
			t.Fatal("default role lost inference basis")
		}
		if _, exists := candidate.Attributes["workspace"]; exists {
			t.Fatal("invented workspace")
		}
		var selection skillSelection
		if err := json.Unmarshal([]byte(candidate.Attributes["skill_selection"]), &selection); err != nil {
			t.Fatal(err)
		}
		if selection.Source != "none" || selection.Status != "unconfigured" {
			t.Fatal(selection)
		}
	}
}

func TestDefaultRoleInheritsOnlyDeclaredDefaultsAndKeepsIdentity(t *testing.T) {
	root := t.TempDir()
	before, err := defaultRoleCollect(t, root, `{"agents":{"defaults":{"workspace":"/fixture/work","model":"fixture/model","skills":["docs"]}}}`)
	if err != nil {
		t.Fatal(err)
	}
	if len(before.Candidates) != 1 || len(before.PermissionFacts) != 2 {
		t.Fatal(before)
	}
	for _, fact := range before.PermissionFacts {
		if fact.State != "declared" || fact.Subject.ID != before.Candidates[0].CandidateID {
			t.Fatal("invented authority")
		}
	}
	var selection skillSelection
	if err := json.Unmarshal([]byte(before.Candidates[0].Attributes["skill_selection"]), &selection); err != nil {
		t.Fatal(err)
	}
	if selection.Source != "defaults" || len(selection.Names) != 1 || selection.Names[0] != "docs" {
		t.Fatal(selection)
	}
	after, err := defaultRoleCollect(t, root, `{"agents":{"entries":{"main":{"name":"renamed"}}}}`)
	if err != nil {
		t.Fatal(err)
	}
	if before.Candidates[0].CandidateID != after.Candidates[0].CandidateID || before.Evidence[0].EvidenceID == after.Evidence[0].EvidenceID {
		t.Fatal("default-to-explicit identity or observation changed incorrectly")
	}
	if after.Candidates[0].Attributes["role_identity_basis"] != "explicit_config" {
		t.Fatal("explicit basis missing")
	}
	other, err := defaultRoleCollect(t, t.TempDir(), `{}`)
	if err != nil {
		t.Fatal(err)
	}
	if other.Candidates[0].CandidateID == before.Candidates[0].CandidateID {
		t.Fatal("roots collapsed")
	}
}

func TestAmbiguousConfigNeverInventsDefaultRole(t *testing.T) {
	for _, body := range []string{
		`null`, `[]`, `{"agents":null}`, `{"agents":{"defaults":null}}`,
		`{"agents":{"list":null}}`, `{"agents":{"entries":null}}`,
		`{"agents":{"entries":null,"list":[]}}`,
		`{"agents":{},"agents":{}}`, `{"agents":{"entries":{"a":{},"a":{}}}}`,
		`{"$include":"private-config.json"}`, `{"agents":{"defaults":{"$include":"private-config.json"}}}`,
		`{} {}`, `{"agents":{"defaults":{"workspace":42}}}`,
		strings.Repeat(`{"nested":`, 66) + `{}` + strings.Repeat(`}`, 66),
	} {
		batch, err := defaultRoleCollect(t, t.TempDir(), body)
		if err == nil || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 || len(batch.PermissionFacts) != 0 {
			t.Fatalf("ambiguous configuration invented role: %v %+v", err, batch)
		}
		if err.Error() != "openclaw_config_invalid" {
			t.Fatal("raw parser error leaked", err)
		}
	}
}

func TestExplicitEmptyRosterDoesNotCreateDefault(t *testing.T) {
	for _, body := range []string{`{"agents":{"list":[]}}`, `{"agents":{"entries":{}}}`} {
		batch, err := defaultRoleCollect(t, t.TempDir(), body)
		if err != nil || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
			t.Fatalf("%v %+v", err, batch)
		}
	}
}

func TestCaseAliasedFieldsNeverCreateRolesOrPermissions(t *testing.T) {
	for _, body := range []string{
		`{"Agents":{"list":[{"id":"real"}]}}`,
		`{"agents":{"List":[{"id":"real"}]}}`,
		`{"agents":{"Entries":{"real":{}}}}`,
		`{"agents":{"list":[],"LIST":[{"id":"extra"}]}}`,
		`{"agents":{"Defaults":{"workspace":"/fixture"}}}`,
		`{"agents":{"defaults":{"Workspace":"/fixture"}}}`,
		`{"agents":{"defaults":{"Skills":["docs"]}}}`,
		`{"agents":{"list":[{"ID":"real"}]}}`,
		`{"agents":{"list":[{"id":"real","AgentDir":"/fixture"}]}}`,
		`{"agents":{"entries":{"real":{"MODEL":"fixture"}}}}`,
		`{agents:{Li\u0073t:[{id:'real'}]}}`,
	} {
		batch, err := defaultRoleCollect(t, t.TempDir(), body)
		if err == nil || err.Error() != "openclaw_config_invalid" || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 || len(batch.PermissionFacts) != 0 {
			t.Fatalf("case alias accepted: %s: %v %+v", body, err, batch)
		}
	}
}

func TestDynamicRoleIDsAndUnknownFieldsRemainCaseSensitive(t *testing.T) {
	batch, err := defaultRoleCollect(t, t.TempDir(), `{"agents":{"entries":{"Reader":{"name":"Upper"},"reader":{"name":"Lower"}},"future":{"List":[]}},"future":{"Agents":{}}}`)
	if err != nil || len(batch.Candidates) != 2 || batch.Candidates[0].CandidateID == batch.Candidates[1].CandidateID {
		t.Fatalf("dynamic identities or unknown fields conflated: %v %+v", err, batch)
	}
	batch, err = defaultRoleCollect(t, t.TempDir(), `{"agents":{"list":[{"id":"real","agentDir":"/fixture","model":{"Primary":"opaque"}}]}}`)
	if err != nil || len(batch.Candidates) != 1 {
		t.Fatalf("canonical mixed-case field or opaque model rejected: %v", err)
	}
}
