package receipt

import (
	"fmt"
	"reflect"
	"time"
)

// IntentContract binds a tool call to the user's purpose and task.
type IntentContract struct {
	IntentID             string         `json:"intent_id"`
	TaskID               string         `json:"task_id"`
	Principal            string         `json:"principal"`
	AgentID              string         `json:"agent_id"`
	Purpose              string         `json:"purpose"`
	AllowedEffects       []string       `json:"allowed_effects"`
	Resources            map[string]any `json:"resources"`
	ParameterConstraints map[string]any `json:"parameter_constraints"`
	ValidUntil           string         `json:"valid_until"`
	AuthorityRevision    string         `json:"authority_revision"`
	EvidenceIDs          []string       `json:"evidence_ids"`
}

func (i *IntentContract) validate(req Request, now time.Time) error {
	if i == nil {
		return nil
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
	until, err := time.Parse(time.RFC3339, i.ValidUntil)
	if err != nil || !now.Before(until) {
		return fmt.Errorf("intent expired or invalid valid_until")
	}
	allowed := false
	for _, effect := range i.AllowedEffects {
		if effect == "*" || effect == req.Tool {
			allowed = true
			break
		}
	}
	if !allowed {
		return fmt.Errorf("tool %s is outside intent allowed_effects", req.Tool)
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
