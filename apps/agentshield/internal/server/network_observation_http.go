package server

import (
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/effectevidence"
	"siq-agent-security/apps/agentshield/internal/provenance"
)

func (s *Server) submitNetworkObservation(w http.ResponseWriter, r *http.Request) {
	if r.Method != "POST" {
		w.WriteHeader(405)
		return
	}
	var body struct {
		ID          string                            `json:"observation_id"`
		ActionID    string                            `json:"action_id"`
		ReceiptID   string                            `json:"decision_receipt_id"`
		Observation effectevidence.NetworkObservation `json:"observation"`
	}
	if !readEffect(w, r, &body) {
		return
	}
	s.observerMu.Lock()
	defer s.observerMu.Unlock()
	now := time.Now()
	o, ok := s.observer(strings.TrimPrefix(r.Header.Get("Authorization"), "Bearer "), now)
	if !ok || o.Source.Type != "test_oracle" || o.Source.Independence != "external_independent" {
		effectError(w, effectevidence.ErrObserver)
		return
	}
	a, err := s.d.Engine.EffectAction(body.ActionID, body.ReceiptID)
	if err != nil {
		effectError(w, err)
		return
	}
	if o.Scope != (provenance.Scope{Platform: a.Platform, SessionID: a.SessionID, AgentID: a.AgentID, TaskID: a.TaskID}) {
		effectError(w, effectevidence.ErrObserver)
		return
	}
	record, err := s.effects.SubmitNetwork(body.ID, body.Observation, a, o.Source, now)
	if err != nil {
		effectError(w, err)
		return
	}
	writeJSON(w, 201, record)
}
