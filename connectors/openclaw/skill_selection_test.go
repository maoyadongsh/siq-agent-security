package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestDeclaredSkillSelectionInheritanceAndUncertainty(t *testing.T) {
	cases := []struct {
		agent, defaults, source, status string
		names                           []string
	}{
		{"", "", "none", "unconfigured", []string{}},
		{"", `["weather","github"]`, "defaults", "declared_list", []string{"github", "weather"}},
		{`["docs"]`, `["weather"]`, "agent", "declared_list", []string{"docs"}},
		{`[]`, `["weather"]`, "agent", "declared_list", []string{}},
		{`null`, `["weather"]`, "agent", "unsupported", []string{}},
		{`"bad"`, "", "agent", "unsupported", []string{}},
		{`["docs","docs"]`, "", "agent", "unsupported", []string{}},
		{`["docs",42]`, "", "agent", "unsupported", []string{}},
		{`["sk-synthetic-secret-1234567890"]`, "", "agent", "unsupported", []string{}},
	}
	for _, c := range cases {
		var got skillSelection
		raw := declaredSkillSelection(json.RawMessage(c.agent), json.RawMessage(c.defaults))
		if err := json.Unmarshal([]byte(raw), &got); err != nil {
			t.Fatal(err)
		}
		if got.Schema != "enterprise-openclaw-skill-selection/v1" || got.Source != c.source || got.Status != c.status || !reflect.DeepEqual(got.Names, c.names) {
			t.Fatalf("unexpected selection: %+v", got)
		}
	}
}

func TestSkillSelectionLimitsDiscardPartialNames(t *testing.T) {
	for _, names := range [][]string{make([]string, 65), {"valid", strings.Repeat("a", 129)}} {
		data, _ := json.Marshal(names)
		var got skillSelection
		if err := json.Unmarshal([]byte(declaredSkillSelection(data, nil)), &got); err != nil {
			t.Fatal(err)
		}
		if got.Status != "unsupported" || len(got.Names) != 0 {
			t.Fatal("partial selection retained")
		}
	}
}

func TestOpenClawEntriesAndListKeepIdentityAndDeclaredRelations(t *testing.T) {
	root := t.TempDir()
	layouts := []string{
		`{"agents":{"defaults":{"skills":["shared"]},"list":[{"id":"docs","skills":[]},{"id":"writer"}]}}`,
		`{"agents":{"defaults":{"skills":["shared"]},"entries":{"writer":{},"docs":{"skills":[]}}}}`,
	}
	var previous []string
	for _, body := range layouts {
		if err := os.WriteFile(filepath.Join(root, "openclaw.json"), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		batch := identityCollect(t, root)
		if len(batch.Candidates) != 2 || len(batch.PermissionFacts) != 0 {
			t.Fatal("unexpected candidate or permission count")
		}
		var ids []string
		for i, candidate := range batch.Candidates {
			ids = append(ids, candidate.CandidateID)
			if len(candidate.EvidenceIDs) == 0 {
				t.Fatal("missing source evidence")
			}
			var selection skillSelection
			if err := json.Unmarshal([]byte(candidate.Attributes["skill_selection"]), &selection); err != nil {
				t.Fatal(err)
			}
			if selection.Status != "declared_list" {
				t.Fatal(selection)
			}
			if i == 0 && (selection.Source != "agent" || len(selection.Names) != 0) {
				t.Fatal(selection)
			}
			if i == 1 && (selection.Source != "defaults" || !reflect.DeepEqual(selection.Names, []string{"shared"})) {
				t.Fatal(selection)
			}
		}
		if previous != nil && !reflect.DeepEqual(previous, ids) {
			t.Fatal("layout changed identity")
		}
		previous = ids
	}
}

func TestOpenClawAmbiguousLayoutsAndEntriesRefused(t *testing.T) {
	for _, body := range []string{
		`{"agents":{"list":[],"entries":{"writer":{}}}}`,
		`{"agents":{"entries":{"writer":{"id":"other"}}}}`,
		`{"agents":{"entries":{"writer":null}}}`,
	} {
		root := t.TempDir()
		if err := os.WriteFile(filepath.Join(root, "openclaw.json"), []byte(body), 0600); err != nil {
			t.Fatal(err)
		}
		batch, err := collectOp(protocol.ScanPlan{Scope: &protocol.Scope{Roots: []string{root}}, Limits: defaultLimits()})
		if err == nil || len(batch.Candidates) != 0 || len(batch.Evidence) != 0 {
			t.Fatal("ambiguous layout accepted")
		}
	}
}
