package server

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillcontext"
	"siq-agent-security/apps/agentshield/internal/state"
)

var nativeContextID = regexp.MustCompile(`^sec-[0-9a-f]{32}$`)

func (s *Server) nativeContextStore() *skillcontext.InvocationStore {
	n := s.d.NativeRuntime
	if n == nil {
		return nil
	}
	n.mu.RLock()
	defer n.mu.RUnlock()
	if n.host == nil {
		return nil
	}
	// Revocation and signed history must work even when runtime verification is
	// unavailable. The immutable store binding is set only during daemon startup.
	return n.host.Contexts()
}

func nativeContextReadError(w http.ResponseWriter, err error) {
	var v *skillcontext.Violation
	if errors.As(err, &v) && v.Code == "skill_context_not_found" {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": v.Code})
		return
	}
	writeJSON(w, http.StatusServiceUnavailable, map[string]string{"error": "skill_context_unavailable"})
}

func (s *Server) nativeContextList(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	q, err := url.ParseQuery(r.URL.RawQuery)
	valid := err == nil && len(q["install_id"]) == 1 && len(q.Get("install_id")) >= 1 && len(q.Get("install_id")) <= 128
	for name, values := range q {
		if (name != "install_id" && name != "session_id" && name != "after" && name != "limit") || len(values) != 1 || values[0] == "" {
			valid = false
		}
	}
	limit := 32
	if q.Has("limit") {
		limit, err = strconv.Atoi(q.Get("limit"))
		valid = valid && err == nil && strconv.Itoa(limit) == q.Get("limit") && limit >= 1 && limit <= 64
	}
	valid = valid && skillcontext.ValidInvocationHistoryQuery(q.Get("install_id"), q.Get("session_id"), q.Get("after"), limit)
	if !valid {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": skillContextRequestError})
		return
	}
	if !skillContextResponseReady(w, r) {
		return
	}
	store := s.nativeContextStore()
	if store == nil {
		nativeContextReadError(w, nativeUnavailable())
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	page, err := store.ListHistory(ctx, q.Get("install_id"), q.Get("session_id"), q.Get("after"), limit)
	if err != nil {
		nativeContextReadError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, page)
}

func (s *Server) nativeContextOne(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v2/skill-contexts/"), "/")
	read := len(parts) == 1 && r.Method == http.MethodGet
	revoke := len(parts) == 2 && parts[1] == "revoke" && r.Method == http.MethodPost
	if !read && !revoke {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	if r.URL.RawQuery != "" || !nativeContextID.MatchString(parts[0]) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": skillContextRequestError})
		return
	}
	var req skillcontext.InvocationRevokeRequest
	if revoke {
		if !readStrictFlatRequest(w, r, &req, skillContextRequestError,
			"schema_version", "expected_context_signature", "actor_id", "confirm_revoke") {
			return
		}
		if !req.Valid() {
			writeJSON(w, http.StatusBadRequest, map[string]string{"error": skillContextRequestError})
			return
		}
	}
	if !skillContextResponseReady(w, r) {
		return
	}
	store := s.nativeContextStore()
	if store == nil {
		nativeContextReadError(w, nativeUnavailable())
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
	defer cancel()
	record, err := store.ReadHistory(ctx, parts[0])
	if err != nil {
		nativeContextReadError(w, err)
		return
	}
	if read {
		writeJSON(w, http.StatusOK, struct {
			SchemaVersion string `json:"schema_version"`
			*skillcontext.InvocationRecord
		}{"local-native-skill-context-record/v1", record})
		return
	}
	if !skillContextResponseReady(w, r.WithContext(ctx)) {
		return
	}
	if err := s.d.Store.AppendAudit(state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano),
		Event: "skill_context_v2_revoke_authorized", ActorID: req.ActorID, Target: parts[0]}); err != nil {
		writeJSON(w, http.StatusInternalServerError, map[string]string{"error": "skill_context_audit_failed"})
		return
	}
	revocation, err := store.Revoke(parts[0], req.ExpectedContextSignature)
	if err != nil {
		skillContextError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, revocation)
}
