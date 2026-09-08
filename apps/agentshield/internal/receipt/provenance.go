package receipt

import (
	"siq-agent-security/apps/agentshield/internal/provenance"
	"time"
)

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
		constraints = *contract.Trusted.ProvenanceConstraints
	}
	return e.opts.ProvenanceCheck(req.Params, req.ParameterProvenance, constraints, provenance.Scope{Platform: req.Platform, SessionID: req.SessionID, AgentID: req.AgentID, TaskID: contract.TaskID}, now)
}
