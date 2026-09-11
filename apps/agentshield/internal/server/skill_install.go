package server

import (
	"context"
	"errors"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

type installPlanCreated struct {
	SchemaVersion string             `json:"schema_version"`
	Plan          *skillinstall.Plan `json:"plan"`
	Reused        bool               `json:"reused"`
}

func (s *Server) initSkillInstallations() error {
	var err error
	s.skillInstallations, err = skillinstall.Open(s.d.Store, s.d.Key, s.skillImports, func(ctx context.Context, id string) (skillinstall.Target, error) {
		if err := ctx.Err(); err != nil {
			return skillinstall.Target{}, err
		}
		options := s.hermesRoots()
		root, err := hermeshome.Resolve(options, id)
		if err != nil || !root.Detected {
			return skillinstall.Target{}, skillinstall.ErrChanged
		}
		shown := filepath.ToSlash(root.Path)
		home := strings.TrimSuffix(filepath.ToSlash(options.Home), "/")
		if home != "" && strings.HasPrefix(shown, home+"/") {
			shown = "~" + strings.TrimPrefix(shown, home)
		}
		return skillinstall.Target{InstanceID: root.ID, Platform: "hermes", Root: root.Path, Display: shown}, nil
	})

	if err == nil {
		s.d.Store.SetRuntimeGrantCheck(func(g *grant.Grant) error {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			return s.skillInstallations.ValidateRuntimeGrant(ctx, g)
		})
	}
	return err
}
func skillInstallError(w http.ResponseWriter, err error) {
	status, code := 503, "skill_install_unavailable"
	switch {
	case errors.Is(err, skillinstall.ErrRemovalPending):
		status, code = 409, "skill_install_removal_pending"
	case errors.Is(err, skillinstall.ErrRecoveryRequired):
		status, code = 409, "skill_install_recovery_required"
	case errors.Is(err, skillinstall.ErrReservedMetadata):
		status, code = 409, "skill_install_reserved_metadata"
	case errors.Is(err, skillinstall.ErrNoTools):
		status, code = 400, "skill_install_no_tools"
	case errors.Is(err, skillinstall.ErrInvalid):
		status, code = 400, "skill_install_invalid"
	case errors.Is(err, skillinstall.ErrChanged):
		status, code = 409, "skill_install_changed"
	case errors.Is(err, skillinstall.ErrConflict):
		status, code = 409, "skill_install_conflict"
	case errors.Is(err, skillinstall.ErrExpired):
		status, code = 409, "skill_install_expired"
	case errors.Is(err, skillinstall.ErrNotFound):
		status, code = 404, "skill_install_not_found"
	case errors.Is(err, skillinstall.ErrLimit):
		status, code = 413, "skill_install_limit"
	case errors.Is(err, context.Canceled), errors.Is(err, context.DeadlineExceeded):
		status, code = 408, "skill_install_interrupted"
	}
	writeJSON(w, status, map[string]string{"error": code})
}
func (s *Server) skillInstallSlot(w http.ResponseWriter) bool {
	if !s.skillImportMu.TryLock() {
		w.Header().Set("Retry-After", "1")
		writeJSON(w, 429, map[string]string{"error": "skill_install_busy"})
		return false
	}
	if err := http.NewResponseController(w).SetWriteDeadline(time.Now().Add(65 * time.Second)); err != nil && !errors.Is(err, http.ErrNotSupported) {
		s.skillImportMu.Unlock()
		skillInstallError(w, skillinstall.ErrUnavailable)
		return false
	}
	return true
}
func (s *Server) skillInstallPlanCreate(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req skillinstall.Request
	if !readStrictFlatRequest(w, r, &req, "skill_install_invalid", "schema_version", "request_id", "grant_id", "expected_revision", "instance_id", "directory_name", "actor_id") {
		return
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	plan, reused, err := s.skillInstallations.Stage(ctx, req)
	if err != nil {
		skillInstallError(w, err)
		return
	}
	status := 201
	if reused {
		status = 200
	}
	writeJSON(w, status, installPlanCreated{"local-skill-install-plan-created/v1", plan, reused})
}
func (s *Server) skillInstallPlanRead(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/skill-installations/plans/")
	if id == "" || strings.Contains(id, "/") {
		w.WriteHeader(404)
		return
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	plan, err := s.skillInstallations.Load(ctx, id)
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, plan)
}

type installRecoverRequest struct {
	SchemaVersion   string `json:"schema_version"`
	ActorID         string `json:"actor_id"`
	ConfirmRecovery bool   `json:"confirm_recovery"`
}

func (s *Server) skillInstallApply(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req skillinstall.ApplyRequest
	if !readStrictFlatRequest(w, r, &req, "skill_install_invalid", "schema_version", "plan_id", "plan_signature", "actor_id", "confirm_install") {
		return
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	result, err := s.skillInstallations.Apply(ctx, req)
	if result == nil {
		skillInstallError(w, err)
		return
	}
	// Even a failed publication can return durable rollback evidence. Do not
	// discard it or confuse a successful HTTP exchange with an installed Skill.
	view, err := s.skillInstallations.ReadView(ctx, result.InstallID)
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, view)
}

func (s *Server) skillInstallOperation(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/skill-installations/operations/"), "/")
	if len(parts) == 2 && parts[0] != "" && parts[1] == "update-plans" {
		if r.Method != http.MethodPost {
			w.WriteHeader(405)
			return
		}
		var req skillinstall.UpdateStageRequest
		if !readStrictFlatRequest(w, r, &req, "skill_install_invalid", "schema_version", "request_id", "operation_signature", "candidate_grant_id", "expected_candidate_revision", "expected_previous_revision", "expected_binding_signature", "actor_id") {
			return
		}
		if !s.skillInstallSlot(w) {
			return
		}
		defer s.skillImportMu.Unlock()
		ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
		defer cancel()
		plan, reused, err := s.skillInstallations.StageUpdate(ctx, parts[0], req)
		if err != nil {
			skillInstallError(w, err)
			return
		}
		status := 201
		if reused {
			status = 200
		}
		writeJSON(w, status, updatePlanCreated{"local-skill-update-plan-created/v1", plan, reused})
		return
	}
	if len(parts) == 2 && parts[0] != "" && parts[1] == "update-comparison" {
		if r.Method != http.MethodPost {
			w.WriteHeader(405)
			return
		}
		var req skillinstall.UpdateCompareRequest
		if !readStrictFlatRequest(w, r, &req, "skill_install_invalid", "schema_version", "operation_signature", "candidate_grant_id", "expected_candidate_revision") {
			return
		}
		if !s.skillInstallSlot(w) {
			return
		}
		defer s.skillImportMu.Unlock()
		ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
		defer cancel()
		result, err := s.skillInstallations.CompareUpdate(ctx, parts[0], req)
		if err != nil {
			skillInstallError(w, err)
			return
		}
		writeJSON(w, 200, result)
		return
	}
	recover := len(parts) == 2 && parts[1] == "recover"
	activate := len(parts) == 2 && parts[1] == "activate"
	readiness := len(parts) == 2 && parts[1] == "runtime"
	inspection := len(parts) == 2 && parts[1] == "inspection"
	removal := len(parts) == 2 && parts[1] == "removal"
	if parts[0] == "" || len(parts) > 2 || (len(parts) == 2 && !recover && !activate && !readiness && !inspection && !removal) {
		w.WriteHeader(404)
		return
	}
	if (removal && r.Method != http.MethodGet && r.Method != http.MethodPost) || (!removal && ((!recover && !activate && r.Method != http.MethodGet) || ((recover || activate) && r.Method != http.MethodPost))) {
		w.WriteHeader(405)
		return
	}
	var req installRecoverRequest
	var activation skillinstall.ActivateRequest
	var removalRequest skillinstall.RemoveRequest
	if removal && r.Method == http.MethodPost && !readStrictFlatRequest(w, r, &removalRequest, "skill_install_invalid", "schema_version", "operation_signature", "expected_grant_revision", "expected_binding_signature", "actor_id", "confirm_remove") {
		return
	}
	if activate && !readStrictFlatRequest(w, r, &activation, "skill_install_invalid", "schema_version", "operation_signature", "expected_revision", "actor_id", "confirm_instance_scope") {
		return
	}
	if recover {
		if !readStrictFlatRequest(w, r, &req, "skill_install_invalid", "schema_version", "actor_id", "confirm_recovery") {
			return
		}
		if req.SchemaVersion != "local-skill-install-recover/v1" || !req.ConfirmRecovery {
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

	if removal {
		var result *skillinstall.RemovalView
		var err error
		if r.Method == http.MethodPost {
			result, err = s.skillInstallations.Remove(ctx, parts[0], removalRequest)
			s.invalidateProjection("skill_install_remove")
		} else {
			result, err = s.skillInstallations.ReadRemoval(ctx, parts[0])
		}
		if result == nil {
			skillInstallError(w, err)
			return
		}
		// A pending view is durable progress, not a successful file removal.
		writeJSON(w, 200, result)
		return
	}
	if inspection {
		result, err := s.skillInstallations.Inspect(ctx, parts[0])
		if err != nil {
			skillInstallError(w, err)
			return
		}
		writeJSON(w, 200, result)
		return
	}
	if readiness {
		result, err := s.skillInstallations.ReadReadiness(ctx, parts[0])
		if err != nil {
			skillInstallError(w, err)
			return
		}
		writeJSON(w, 200, result)
		return
	}

	if activate {
		result, err := s.skillInstallations.Activate(ctx, parts[0], activation)
		if err != nil {
			skillInstallError(w, err)
			return
		}
		s.invalidateProjection("skill_install_instance_permission")
		writeJSON(w, 200, result)
		return
	}
	if recover {
		if _, err := s.skillInstallations.Recover(ctx, parts[0], req.ActorID); err != nil {
			skillInstallError(w, err)
			return
		}
	}
	view, err := s.skillInstallations.ReadView(ctx, parts[0])
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, view)
}

func (s *Server) skillInstallGrantRuntime(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/v1/skill-installations/grants/"), "/")
	if len(parts) != 2 || parts[0] == "" || parts[1] != "runtime" {
		w.WriteHeader(404)
		return
	}
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	result, err := s.skillInstallations.ReadGrantReadiness(ctx, parts[0])
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, result)
}

func (s *Server) skillInstallCatalog(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	result, err := s.skillInstallations.Catalog(ctx)
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, result)
}

type updatePlanCreated struct {
	SchemaVersion string                   `json:"schema_version"`
	Plan          *skillinstall.UpdatePlan `json:"plan"`
	Reused        bool                     `json:"reused"`
}

func (s *Server) skillUpdatePlanRead(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodGet {
		w.WriteHeader(405)
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/v1/skill-installations/update-plans/")
	if id == "" || strings.Contains(id, "/") {
		w.WriteHeader(404)
		return
	}
	if !s.skillInstallSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	plan, err := s.skillInstallations.LoadUpdatePlan(ctx, id)
	if err != nil {
		skillInstallError(w, err)
		return
	}
	writeJSON(w, 200, plan)
}
