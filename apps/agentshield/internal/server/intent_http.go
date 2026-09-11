package server

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"siq-agent-security/apps/agentshield/internal/intent"
	"strings"
	"unicode/utf8"
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
	id := strings.TrimPrefix(r.URL.Path, "/v1/intents/")
	if strings.HasSuffix(id, "/revoke") {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		var body struct {
			ExpectedIntentDigest string `json:"expected_intent_digest"`
		}
		if !readAuthority(w, r, &body) {
			return
		}
		revoked, err := s.intents.RevokeIntent(strings.TrimSuffix(id, "/revoke"), body.ExpectedIntentDigest)
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 200, revoked)
		return
	}
	if strings.HasSuffix(id, "/revocation") {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		revoked, err := s.intents.GetIntentRevocation(strings.TrimSuffix(id, "/revocation"))
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 200, revoked)
		return
	}
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
			SchemaVersion         json.RawMessage `json:"schema_version"`
			GrantID               json.RawMessage `json:"grant_id"`
			ExpectedGrantRevision json.RawMessage `json:"expected_grant_revision"`
			Platform              string          `json:"platform"`
			SessionID             string          `json:"session_id"`
			AgentID               string          `json:"agent_id"`
			TaskID                string          `json:"task_id"`
			IntentID              string          `json:"intent_id"`
			ExpiresAt             string          `json:"expires_at"`
		}
		if !readAuthority(w, r, &body) {
			return
		}
		input := intent.Binding{Platform: body.Platform, SessionID: body.SessionID, AgentID: body.AgentID, TaskID: body.TaskID, IntentID: body.IntentID, ExpiresAt: body.ExpiresAt}
		var b intent.Binding
		var err error
		if len(body.SchemaVersion) > 0 || len(body.GrantID) > 0 || len(body.ExpectedGrantRevision) > 0 {
			var version, grantID string
			var revision *int
			if json.Unmarshal(body.SchemaVersion, &version) != nil || json.Unmarshal(body.GrantID, &grantID) != nil || json.Unmarshal(body.ExpectedGrantRevision, &revision) != nil || version != "intent-grant-bind/v1" || grantID == "" || revision == nil || *revision < 0 {
				intentError(w, &intent.Violation{Code: "intent_invalid_grant_selection"})
				return
			}
			for _, value := range []string{body.Platform, body.SessionID, body.AgentID, body.IntentID, grantID, body.TaskID, body.ExpiresAt} {
				if utf8.RuneCountInString(value) > 256 {
					intentError(w, &intent.Violation{Code: "intent_invalid_grant_selection"})
					return
				}
			}
			b, err = s.intents.BindWithGrant(input, grantID, *revision)
		} else {
			b, err = s.intents.Bind(input)
		}
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
	id := strings.TrimPrefix(r.URL.Path, "/v1/intent-bindings/")
	if strings.HasSuffix(id, "/revoke") {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		var body struct {
			ExpectedIntentDigest string `json:"expected_intent_digest"`
		}
		if !readAuthority(w, r, &body) {
			return
		}
		revoked, err := s.intents.RevokeBinding(strings.TrimSuffix(id, "/revoke"), body.ExpectedIntentDigest)
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 200, revoked)
		return
	}
	if strings.HasSuffix(id, "/revocation") {
		if r.Method != http.MethodGet {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		revoked, err := s.intents.GetBindingRevocation(strings.TrimSuffix(id, "/revocation"))
		if err != nil {
			intentError(w, err)
			return
		}
		writeJSON(w, 200, revoked)
		return
	}
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	b, err := s.intents.GetBinding(id)
	if err != nil {
		intentError(w, err)
		return
	}
	writeJSON(w, 200, b)
}
