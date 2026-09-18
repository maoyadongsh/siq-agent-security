package server

import (
	"context"
	"errors"
	"net/http"
	"net/url"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillcontext"
)

type skillContextSession struct {
	SessionID string `json:"session_id"`
	ExpiresAt string `json:"expires_at"`
}
type skillContextManagement struct {
	SchemaVersion string                          `json:"schema_version"`
	InstallID     string                          `json:"install_id"`
	InstanceID    string                          `json:"instance_id"`
	Sessions      []skillContextSession           `json:"sessions"`
	Contexts      []skillcontext.ManagementRecord `json:"contexts"`
}

func (s *Server) skillContextManagement(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
	defer cancel()
	r = r.WithContext(ctx)
	q, err := url.ParseQuery(r.URL.RawQuery)
	ids := q["install_id"]
	if err != nil || len(q) != 1 || len(ids) != 1 || len(ids[0]) == 0 || len(ids[0]) > 128 {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": skillContextRequestError})
		return
	}
	if s.skillContexts == nil || s.skillInstallations == nil || s.runtimeIdentities == nil || s.intents == nil {
		skillContextError(w, errors.New("unavailable"))
		return
	}
	record, err := s.skillInstallations.RecordByID(r.Context(), ids[0])
	if err != nil {
		skillInstallError(w, err)
		return
	}
	contexts, err := s.skillContexts.ManagementRecords(r.Context(), ids[0])
	if err != nil {
		skillContextError(w, err)
		return
	}
	out := skillContextManagement{"local-skill-context-management/v1", ids[0], record.Plan.InstanceID, []skillContextSession{}, contexts}
	identity, err := s.runtimeIdentities.InspectByInstance(record.Plan.InstanceID)
	if err != nil {
		skillContextError(w, err)
		return
	}
	if identity.Platform != record.Plan.Platform || identity.GrantRef.GrantID != record.Plan.GrantID {
		writeJSON(w, http.StatusOK, out)
		return
	}
	bindings, err := s.intents.ListBindingsContext(r.Context())
	if err != nil {
		skillContextError(w, err)
		return
	}
	for _, b := range bindings {
		if err := r.Context().Err(); err != nil {
			skillContextError(w, err)
			return
		}
		if b.Platform != identity.Platform || b.AgentID != identity.AgentID || b.GrantRef == nil || b.GrantRef.GrantID != record.Plan.GrantID {
			continue
		}
		_, live, err := s.intents.ResolveBinding(b.Platform, b.SessionID, b.AgentID)
		if err != nil || live == nil || live.GrantRef == nil || live.GrantRef.GrantID != record.Plan.GrantID {
			continue
		}
		expires, err := time.Parse(time.RFC3339, live.ExpiresAt)
		if err != nil || !time.Now().Before(expires) {
			continue
		}
		if len(out.Sessions) >= 64 {
			skillContextError(w, errors.New("capacity"))
			return
		}
		out.Sessions = append(out.Sessions, skillContextSession{live.SessionID, live.ExpiresAt})
	}
	writeJSON(w, http.StatusOK, out)
}
