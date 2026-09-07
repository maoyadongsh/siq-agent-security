package server

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"siq-agent-security/apps/agentshield/internal/intent"
	"strings"
)

func intentError(w http.ResponseWriter, err error) {
	code := "intent_state_unavailable"
	status := http.StatusInternalServerError
	var v *intent.Violation
	if errors.As(err, &v) {
		code = v.Code
		status = http.StatusBadRequest
		if strings.Contains(code, "conflict") {
			status = http.StatusConflict
		}
	}
	if errors.Is(err, os.ErrNotExist) {
		status = http.StatusNotFound
		code = "intent_not_found"
	}
	writeJSON(w, status, map[string]any{"error": code, "reason_code": code})
}
func readAuthority(w http.ResponseWriter, r *http.Request, out any) bool {
	dec := json.NewDecoder(http.MaxBytesReader(w, r.Body, 1<<20))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(out); err != nil {
		writeJSON(w, 400, map[string]string{"error": "intent_invalid_request"})
		return false
	}
	var extra any
	if dec.Decode(&extra) != io.EOF {
		writeJSON(w, 400, map[string]string{"error": "intent_invalid_request"})
		return false
	}
	return true
}
func (s *Server) intentCollection(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		items, err := s.intents.List()
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 200, map[string]any{"items": items})
	case http.MethodPost:
		var c intent.Contract
		if !readAuthority(w, r, &c) {
			return
		}
		out, err := s.intents.Issue(c)
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 201, out)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}
func (s *Server) intentOne(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	c, err := s.intents.Get(strings.TrimPrefix(r.URL.Path, "/v1/intents/"))
	if err != nil {
		intentError(w, err)
		return
	}
	writeJSON(w, 200, c)
}
func (s *Server) bindingCollection(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		items, err := s.intents.ListBindings()
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 200, map[string]any{"items": items})
	case http.MethodPost:
		var body struct {
			Platform  string `json:"platform"`
			SessionID string `json:"session_id"`
			AgentID   string `json:"agent_id"`
			TaskID    string `json:"task_id"`
			IntentID  string `json:"intent_id"`
			ExpiresAt string `json:"expires_at"`
		}
		if !readAuthority(w, r, &body) {
			return
		}
		b, err := s.intents.Bind(intent.Binding{Platform: body.Platform, SessionID: body.SessionID, AgentID: body.AgentID, TaskID: body.TaskID, IntentID: body.IntentID, ExpiresAt: body.ExpiresAt})
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 201, b)
	default:
		w.WriteHeader(http.StatusMethodNotAllowed)
	}
}
func (s *Server) bindingOne(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	b, err := s.intents.GetBinding(strings.TrimPrefix(r.URL.Path, "/v1/intent-bindings/"))
	if err != nil {
		intentError(w, err)
		return
	}
	writeJSON(w, 200, b)
}
