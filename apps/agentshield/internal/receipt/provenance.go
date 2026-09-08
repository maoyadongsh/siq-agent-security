package receipt

import (
	"slices"
	"time"

	"siq-agent-security/apps/agentshield/internal/provenance"
	"siq-agent-security/apps/agentshield/internal/runtimeaction"
)

// messagePayloadPIIText is called only after current authority and every supplied
// provenance reference have passed validation. It narrows the PII scan of this
// request, never the secret/threat scan and never existing session state.
func messagePayloadPIIText(req Request, contract *IntentContract, descriptor runtimeaction.Descriptor, original string) string {
	if contract == nil || contract.Trusted == nil || contract.Trusted.SchemaVersion != "intent/v3" || contract.Trusted.ProvenanceConstraints == nil || descriptor.ResourceError != nil || !slices.Contains(descriptor.Effects, runtimeaction.EffectMessageSend) {
		return original
	}
	constraints := provenance.ConstraintsForAction(*contract.Trusted.ProvenanceConstraints, descriptor)
	params := map[string]any{}
	for key, value := range req.Params {
		params[key] = value
	}
	for _, c := range constraints {
		if !c.Required || (c.MinimumTrust != "trusted" && c.MinimumTrust != "authoritative") || (c.ParameterPath != "/recipient" && c.ParameterPath != "/to") {
			continue
		}
		key := c.ParameterPath[1:]
		if _, ok := params[key].(string); !ok {
			continue
		}
		// Keep the precondition explicit even though a valid required constraint
		// already guarantees a non-empty, fully checked binding.
		for _, binding := range req.ParameterProvenance {
			if binding.ParameterPath == c.ParameterPath && len(binding.ProvenanceRefs) > 0 {
				delete(params, key)
			}
		}
	}
	return flattenStrings(params)
}

func (e *Engine) checkProvenance(req Request, contract *IntentContract, now time.Time) error {
	v3 := contract != nil && contract.Trusted != nil && contract.Trusted.SchemaVersion == "intent/v3"
	if !v3 && len(req.ParameterProvenance) == 0 {
		return nil
	}
	if e.opts.ProvenanceCheck == nil || contract == nil || contract.Trusted == nil {
		return &provenance.Violation{Code: "provenance_authority_invalid"}
	}
	constraints := []provenance.Constraint{}
	if v3 {
		if contract.Trusted.ProvenanceConstraints == nil {
			return &provenance.Violation{Code: "provenance_authority_invalid"}
		}
		constraints = provenance.ConstraintsForAction(*contract.Trusted.ProvenanceConstraints, runtimeaction.Describe(req.Tool, req.Params))
	}
	return e.opts.ProvenanceCheck(req.Params, req.ParameterProvenance, constraints, provenance.Scope{Platform: req.Platform, SessionID: req.SessionID, AgentID: req.AgentID, TaskID: contract.TaskID}, now)
}
