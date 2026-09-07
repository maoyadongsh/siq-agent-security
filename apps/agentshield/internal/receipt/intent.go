package receipt

import (
	"fmt"
	"reflect"
	"time"

	"siq-agent-security/apps/agentshield/internal/intent"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

// IntentContract binds a tool call to the user's purpose and task.
type IntentContract struct {
	Trusted              *intent.Contract `json:"-"`
	IntentID             string           `json:"intent_id"`
	TaskID               string           `json:"task_id"`
	Principal            string           `json:"principal"`
	AgentID              string           `json:"agent_id"`
	Purpose              string           `json:"purpose"`
	Digest               string           `json:"digest,omitempty"`
	AllowedTools         []string         `json:"allowed_tools,omitempty"`
	AllowedEffects       []string         `json:"allowed_effects"`
	Resources            map[string]any   `json:"resources"`
	ParameterConstraints map[string]any   `json:"parameter_constraints"`
	ValidUntil           string           `json:"valid_until"`
	AuthorityRevision    string           `json:"authority_revision"`
	EvidenceIDs          []string         `json:"evidence_ids"`
}

func (i *IntentContract) validate(req Request, now time.Time) error {
	if i == nil {
		return nil
	}
	if i.Trusted != nil {
		return i.Trusted.Authorize(req.Platform, req.AgentID, req.Principal, req.Tool, req.Params, now)
	}
	if i.IntentID == "" || i.TaskID == "" || i.Principal == "" || i.AgentID == "" || i.Purpose == "" || i.AuthorityRevision == "" {
		return fmt.Errorf("intent contract missing required identity")
	}
	if i.AgentID != req.AgentID {
		return fmt.Errorf("intent agent mismatch")
	}
	if req.Principal != "" && i.Principal != req.Principal {
		return fmt.Errorf("intent principal mismatch")
	}
	if len(i.AllowedTools) > 0 {
		ok := false
		for _, tool := range i.AllowedTools {
			if tool == "*" || tool == req.Tool {
				ok = true
				break
			}
		}
		if !ok {
			return fmt.Errorf("tool %s is outside intent allowed_tools", req.Tool)
		}
	}
	until, err := time.Parse(time.RFC3339, i.ValidUntil)
	if err != nil || !now.Before(until) {
		return fmt.Errorf("intent expired or invalid valid_until")
	}
	_, normalizedEffects := runtimeaction.Normalize(req.Tool, req.Params)
	for _, effect := range normalizedEffects {
		allowed := false
		for _, wanted := range i.AllowedEffects {
			if wanted == "*" || wanted == effect || wanted == req.Tool { // req.Tool keeps intent/v1 compatibility
				allowed = true
				break
			}
		}
		if !allowed {
			return fmt.Errorf("effect %s is outside intent allowed_effects", effect)
		}
	}
	for key, constraint := range i.ParameterConstraints {
		value, ok := req.Params[key]
		if !ok || !reflect.DeepEqual(value, constraint) {
			if options, ok := constraint.([]any); ok {
				found := false
				for _, candidate := range options {
					if reflect.DeepEqual(value, candidate) {
						found = true
						break
					}
				}
				if found {
					continue
				}
			}
			return fmt.Errorf("parameter %s violates intent constraint", key)
		}
	}
	return nil
}

// ResolveStore adapts a verified V2 authority for the legacy receipt consumer.
func ResolveStore(store *intent.Store) IntentLookup {
	return func(platform, session, agent string) (*IntentContract, error) {
		c, _, err := store.ResolveBinding(platform, session, agent)
		if err != nil || c == nil {
			return nil, err
		}
		return &IntentContract{Trusted: c, IntentID: c.IntentID, TaskID: c.TaskID, Principal: c.Principal.ID, AgentID: c.Agent.ID, Purpose: c.Purpose, Digest: c.Digest, AuthorityRevision: c.Authority.Revision}, nil
	}
}
