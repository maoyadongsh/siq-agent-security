package server

import (
	"errors"
	"net/http"
	"siq-agent-security/apps/agentshield/internal/trustedcontext"
	"strings"
)

func contextError(w http.ResponseWriter, err error) {
	code, status := "trusted_context_invalid", 400
	var v *trustedcontext.Violation
	if errors.As(err, &v) {
		code = v.Code
	}
	if code == "trusted_context_conflict" {
		status = 409
	}
	writeJSON(w, status, map[string]string{"error": code, "reason_code": code})
}
func (s *Server) contextCollection(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var a trustedcontext.Assertion
	if !readAuthority(w, r, &a) {
		return
	}
	out, err := s.intents.IssueContext(a)
	if err != nil {
		contextError(w, err)
		return
	}
	writeJSON(w, 201, out)
}
func (s *Server) contextOne(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	a, err := s.intents.GetContext(strings.TrimPrefix(r.URL.Path, "/v1/context-assertions/"))
	if err != nil {
		contextError(w, err)
		return
	}
	writeJSON(w, 200, a)
}
