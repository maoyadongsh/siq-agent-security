package main

import (
	"encoding/json"
	"path"
	"strings"
	"unicode"

	"siq-agent-security/edge/agent/protocol"
)

type declaredSkillRoot struct {
	Kind    string `json:"kind"`
	Locator string `json:"locator_sha256"`
}

func declaredSkillRoots(agent openclawAgent) string {
	value := struct {
		Schema string              `json:"schema_version"`
		Basis  string              `json:"basis"`
		Status string              `json:"status"`
		Roots  []declaredSkillRoot `json:"roots"`
	}{"enterprise-role-skill-roots/v1", "none", "unresolved", []declaredSkillRoot{}}
	workspace := agent.Workspace
	if workspace != "" {
		value.Basis = "agent_workspace"
		if agent.InferredDefault {
			value.Basis = "default_workspace"
		}
		if path.IsAbs(workspace) && len(workspace) <= 4096 &&
			!strings.ContainsAny(workspace, "$~\\*?[") && strings.IndexFunc(workspace, unicode.IsControl) < 0 {
			value.Status = "declared"
			for _, entry := range []struct{ kind, suffix string }{{"workspace_skills", "skills"}, {"project_agent_skills", ".agents/skills"}} {
				value.Roots = append(value.Roots, declaredSkillRoot{entry.kind, protocol.ContentHash([]byte(path.Join(workspace, entry.suffix)))})
			}
		}
	}
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
