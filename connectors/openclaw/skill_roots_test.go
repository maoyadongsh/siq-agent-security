package main

import (
	"encoding/json"
	"strings"
	"testing"

	"siq-agent-security/edge/agent/protocol"
)

func TestSkillRootsAreDeclaredPositionsNotNameMatches(t *testing.T) {
	body := `{"agents":{"entries":{"one":{"workspace":"/fixture/a/../shared","skills":["docs"]},"two":{"workspace":"/fixture/shared","skills":["other"]},"three":{"workspace":"/fixture/other","skills":["docs"]}}}}`
	batch, err := defaultRoleCollect(t, t.TempDir(), body)
	if err != nil || len(batch.Candidates) != 3 {
		t.Fatal(err)
	}
	byName := map[string]string{}
	for _, candidate := range batch.Candidates {
		raw := candidate.Attributes["skill_source_roots"]
		if strings.Contains(raw, "/fixture") {
			t.Fatal("raw workspace leaked")
		}
		byName[candidate.Name] = raw
	}
	if byName["one"] != byName["two"] || byName["one"] == byName["three"] {
		t.Fatal("sources conflated by skill name")
	}
	var value struct {
		Roots  []declaredSkillRoot `json:"roots"`
		Status string              `json:"status"`
		Basis  string              `json:"basis"`
	}
	if json.Unmarshal([]byte(byName["one"]), &value) != nil || value.Status != "declared" || value.Basis != "agent_workspace" || len(value.Roots) != 2 {
		t.Fatal("invalid roots")
	}
	for i, expected := range []string{"/fixture/shared/skills", "/fixture/shared/.agents/skills"} {
		if value.Roots[i].Locator != protocol.ContentHash([]byte(expected)) {
			t.Fatal("position hash mismatch")
		}
	}
}

func TestSkillRootsUnresolvedPathsNeverUseHostContext(t *testing.T) {
	for _, workspace := range []string{"", "relative", "~/work", "$HOME/work", "/work/${NAME}", "/work/*", "/work/\n", "/work/\\other", "/" + strings.Repeat("x", 4096)} {
		var value struct {
			Roots  []declaredSkillRoot `json:"roots"`
			Status string              `json:"status"`
		}
		if json.Unmarshal([]byte(declaredSkillRoots(openclawAgent{Workspace: workspace})), &value) != nil || value.Status != "unresolved" || len(value.Roots) != 0 {
			t.Fatal("unresolved path guessed")
		}
	}
}

func TestSkillRootsDefaultRoleBasis(t *testing.T) {
	batch, err := defaultRoleCollect(t, t.TempDir(), `{"agents":{"defaults":{"workspace":"/fixture/default"}}}`)
	if err != nil || len(batch.Candidates) != 1 {
		t.Fatal(err)
	}
	var value map[string]any
	if json.Unmarshal([]byte(batch.Candidates[0].Attributes["skill_source_roots"]), &value) != nil || value["basis"] != "default_workspace" || value["status"] != "declared" {
		t.Fatal("default basis lost")
	}
}
