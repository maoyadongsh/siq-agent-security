package server

import (
	"encoding/json"
	"net/http"
	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/provenance"
	"time"
)

func (s *Server) provenanceReport(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		ReportID  string            `json:"report_id"`
		Platform  string            `json:"platform"`
		SessionID string            `json:"session_id"`
		AgentID   string            `json:"agent_id"`
		Source    provenance.Source `json:"source"`
		Content   json.RawMessage   `json:"content"`
	}
	if !readProvenance(w, r, &body) {
		return
	}
	if len(body.Content) == 0 {
		provenanceError(w, &provenance.Violation{Code: "provenance_invalid_request"})
		return
	}
	c, _, err := s.intents.ResolveBinding(body.Platform, body.SessionID, body.AgentID)
	now := time.Now().UTC()
	if err != nil || c == nil || c.Active(now) != nil {
		provenanceError(w, &provenance.Violation{Code: "provenance_authority_invalid"})
		return
	}
	content, err := canon.Decode(body.Content)
	if err != nil {
		provenanceError(w, &provenance.Violation{Code: "provenance_invalid_request"})
		return
	}
	expires, _ := time.Parse(time.RFC3339, c.ExpiresAt)
	out, err := s.provenance.Report(body.ReportID, body.Source, provenance.Scope{Platform: body.Platform, SessionID: body.SessionID, AgentID: body.AgentID, TaskID: c.TaskID}, content, expires, now)
	if err != nil {
		provenanceError(w, err)
		return
	}
	writeJSON(w, 201, out)
}

func (s *Server) provenanceSelect(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var body struct {
		ParentID  string          `json:"parent_id"`
		Pointer   string          `json:"pointer"`
		Platform  string          `json:"platform"`
		SessionID string          `json:"session_id"`
		AgentID   string          `json:"agent_id"`
		Content   json.RawMessage `json:"content"`
	}
	if !readProvenance(w, r, &body) {
		return
	}
	c, _, err := s.intents.ResolveBinding(body.Platform, body.SessionID, body.AgentID)
	now := time.Now().UTC()
	if err != nil || c == nil || c.Active(now) != nil {
		provenanceError(w, &provenance.Violation{Code: "provenance_authority_invalid"})
		return
	}
	content, err := canon.Decode(body.Content)
	if err != nil {
		provenanceError(w, &provenance.Violation{Code: "provenance_invalid_request"})
		return
	}
	out, err := s.provenance.Select(body.ParentID, body.Pointer, provenance.Scope{Platform: body.Platform, SessionID: body.SessionID, AgentID: body.AgentID, TaskID: c.TaskID}, content, now)
	if err != nil {
		provenanceError(w, err)
		return
	}
	writeJSON(w, 201, out)
}
