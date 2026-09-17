package server

import (
	"errors"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"siq-agent-security/apps/agentshield/internal/state"
)

const skillContextRequestError = "skill_context_invalid_request"

func skillContextError(w http.ResponseWriter, err error) {
	status, code := http.StatusServiceUnavailable, "skill_context_unavailable"
	var violation *skillcontext.Violation
	if errors.As(err, &violation) {
		switch violation.Code {
		case "skill_context_not_found":
			status, code = http.StatusNotFound, violation.Code
		case "skill_context_conflict", "skill_context_changed", "skill_context_instance_invalid",
			"skill_context_install_changed", "skill_context_grant_changed", "skill_context_session_unbound":
			status, code = http.StatusConflict, violation.Code
		case "skill_context_invalid":
			status, code = http.StatusBadRequest, skillContextRequestError
		}
	}
	writeJSON(w, status, map[string]string{"error": code})
}

func (s *Server) skillContextCollection(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	if s.skillContexts == nil {
		skillContextError(w, errors.New("skill context store unavailable"))
		return
	}
	var req skillcontext.ManagementIssueRequest
	if !readStrictFlatRequest(w, r, &req, skillContextRequestError,
		"schema_version", "instance_id", "session_id", "task_id", "install_id", "ttl_seconds", "actor_id", "confirm_issue") {
		return
	}
	if !req.Valid() {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": skillContextRequestError})
		return
	}
	scope := skillcontext.EvidenceSession
	if req.TaskID != "" {
		scope = skillcontext.EvidenceTask
	}
	// The audit records an authorized attempt and contains no session/task or
	// parameter material. The signed SEC remains the sole proof that issuance
	// completed. Persisting this first makes audit failure close the write.
	if err := s.d.Store.AppendAudit(state.AuditEvent{
		At: time.Now().UTC().Format(time.RFC3339Nano), Event: "skill_context_issue_authorized",
		ActorID: req.ActorID, Target: req.InstallID, Note: "scope=" + scope,
	}); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "skill_context_audit_failed"})
		return
	}
	c, err := s.skillContexts.Issue(skillcontext.IssueRequest{
		InstanceID: req.InstanceID, SessionID: req.SessionID, TaskID: req.TaskID,
		InstallID: req.InstallID, TTL: time.Duration(req.TTLSeconds) * time.Second,
	})
	if err != nil {
		skillContextError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, c)
}

func (s *Server) skillContextOne(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if s.skillContexts == nil {
		skillContextError(w, errors.New("skill context store unavailable"))
		return
	}
	rest := strings.TrimPrefix(r.URL.Path, "/v1/skill-contexts/")
	parts := strings.Split(rest, "/")
	if len(parts) == 1 && parts[0] != "" && r.Method == http.MethodGet {
		c, err := s.skillContexts.Get(parts[0])
		if err != nil {
			skillContextError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, c)
		return
	}
	if len(parts) == 2 && parts[0] != "" && parts[1] == "revoke" {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		var req skillcontext.ManagementRevokeRequest
		if !readStrictFlatRequest(w, r, &req, skillContextRequestError,
			"schema_version", "expected_context_signature", "actor_id", "confirm_revoke") {
			return
		}
		if !req.Valid() {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": skillContextRequestError})
			return
		}
		if err := s.d.Store.AppendAudit(state.AuditEvent{
			At: time.Now().UTC().Format(time.RFC3339Nano), Event: "skill_context_revoke_authorized",
			ActorID: req.ActorID, Target: parts[0],
		}); err != nil {
			writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "skill_context_audit_failed"})
			return
		}
		revocation, err := s.skillContexts.RevokeExpected(parts[0], req.ExpectedContextSignature)
		if err != nil {
			skillContextError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, revocation)
		return
	}
	if len(parts) == 1 && parts[0] != "" {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	w.WriteHeader(http.StatusNotFound)
}
