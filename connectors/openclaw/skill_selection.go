package main

import (
	"encoding/json"
	"errors"
	"regexp"
	"sort"

	"siq-agent-security/edge/agent/protocol"
)

type openclawAgent struct {
	InferredDefault bool            `json:"-"`
	ID              string          `json:"id"`
	Name            string          `json:"name"`
	Workspace       string          `json:"workspace"`
	AgentDir        string          `json:"agentDir"`
	Model           any             `json:"model"`
	Skills          json.RawMessage `json:"skills"`
}

func configuredAgents(cfg openclawConfig) ([]openclawAgent, error) {
	if cfg.Agents.List != nil && cfg.Agents.Entries != nil {
		return nil, errors.New("openclaw agent layouts ambiguous")
	}
	if cfg.Agents.Entries == nil {
		return cfg.Agents.List, nil
	}
	keys := make([]string, 0, len(cfg.Agents.Entries))
	for key := range cfg.Agents.Entries {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	agents := make([]openclawAgent, 0, len(keys))
	for _, key := range keys {
		entry := cfg.Agents.Entries[key]
		if entry == nil {
			return nil, errors.New("openclaw entry invalid")
		}
		agent := *entry
		if agent.ID != "" && agent.ID != key {
			return nil, errors.New("openclaw entry identity mismatch")
		}
		agent.ID = key
		agents = append(agents, agent)
	}
	return agents, nil
}

var skillSelectionName = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$`)

type skillSelection struct {
	Schema string   `json:"schema_version"`
	Source string   `json:"source"`
	Status string   `json:"status"`
	Names  []string `json:"names"`
}

func declaredSkillSelection(agent, defaults json.RawMessage) string {
	value := skillSelection{Schema: "enterprise-openclaw-skill-selection/v1", Source: "none", Status: "unconfigured", Names: []string{}}
	raw := agent
	if len(raw) > 0 {
		value.Source = "agent"
	} else if len(defaults) > 0 {
		value.Source, raw = "defaults", defaults
	}
	if len(raw) > 0 {
		value.Status = "unsupported"
		var names []string
		if json.Unmarshal(raw, &names) == nil && names != nil && len(names) <= 64 {
			valid := true
			seen := map[string]bool{}
			redactor := protocol.NewRedactor()
			for _, name := range names {
				if !skillSelectionName.MatchString(name) || seen[name] || redactor.RedactString(name) != name {
					valid = false
					break
				}
				seen[name] = true
			}
			if valid {
				sort.Strings(names)
				value.Status, value.Names = "declared_list", names
			}
		}
	}
	encoded, _ := json.Marshal(value)
	return string(encoded)
}
