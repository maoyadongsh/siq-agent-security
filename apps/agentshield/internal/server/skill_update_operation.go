package server

import (
	"context"
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

func (s *Server) skillUpdateCommit(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req skillinstall.UpdateCommitRequest
	if !readStrictFlatRequest(w, r, &req, "skill_install_invalid", "schema_version", "update_id", "plan_signature", "actor_id", "confirm_update") {
		return
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	result, err := s.skillInstallations.CommitUpdate(ctx, req)
	s.invalidateProjection("skill_update_commit")
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, result)
}
func (s *Server) skillUpdateOperation(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/skill-installations/updates/"), "/")
	recover := len(parts) == 2 && parts[1] == "recover"
	if parts[0] == "" || (len(parts) != 1 && !recover) {
		w.WriteHeader(404)
		return
	}
	if (!recover && r.Method != http.MethodGet) || (recover && r.Method != http.MethodPost) {
		w.WriteHeader(405)
		return
	}
	var req skillinstall.UpdateRecoverRequest
	if recover {
		if !readStrictFlatRequest(w, r, &req, "skill_install_invalid", "schema_version", "update_id", "claim_signature", "actor_id", "confirm_recovery") {
			return
		}
		if req.UpdateID != parts[0] {
			skillInstallError(w, skillinstall.ErrInvalid)
			return
		}
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	var result *skillinstall.UpdateView
	var err error
	if recover {
		result, err = s.skillInstallations.RecoverUpdate(ctx, req)
		s.invalidateProjection("skill_update_recover")
	} else {
		result, err = s.skillInstallations.ReadUpdate(ctx, parts[0])
	}
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, result)
}
