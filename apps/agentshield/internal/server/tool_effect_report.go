package server

import (
	"net/http"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
)

// Tool claims can downgrade completion, but never attest an independent effect.
func (s *Server) toolEffectReport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var e effectevidence.Evidence
	if !readEffect(w, r, &e) {
		return
	}
	now := time.Now()
	if e.Source.Type != "tool_report" || e.Signature != "" || e.Validate(now) != nil {
		effectError(w, effectevidence.ErrInvalid)
		return
	}
	a, err := s.d.Engine.EffectAction(e.ActionID, e.DecisionReceiptID)
	if err != nil {
		effectError(w, effectevidence.ErrCorrelation)
		return
	}
	resourceMatches, effectMatches := false, false
	for _, resource := range a.Resources {
		ref, err := effectevidence.ResourceReference(resource)
		if err == nil && ref == e.ResourceRef {
			resourceMatches = true
		}
	}
	for _, effect := range a.Effects {
		if effect == e.EffectType {
			effectMatches = true
		}
	}
	if !resourceMatches || !effectMatches {
		effectError(w, effectevidence.ErrCorrelation)
		return
	}
	record, err := s.effects.Submit(e, a, e.Source, now)
	if err != nil {
		effectError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, record)
}
