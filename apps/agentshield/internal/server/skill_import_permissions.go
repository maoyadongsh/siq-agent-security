package server

import (
	"context"
	"errors"
	"net/http"
	"os"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/importsource"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"siq-agent-security/apps/agentshield/internal/state"
)

type importPermissionRequest struct {
	SchemaVersion  string `json:"schema_version"`
	RequestID      string `json:"request_id"`
	ArtifactDigest string `json:"artifact_digest"`
	AnalysisSHA256 string `json:"analysis_sha256"`
	InstanceID     string `json:"instance_id"`
	ActorID        string `json:"actor_id"`
}

func (s *Server) skillImportPermissions(w http.ResponseWriter, r *http.Request, id string) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(405)
		return
	}
	var req importPermissionRequest
	if !readStrictFlatRequest(w, r, &req, "skill_import_permission_invalid", "schema_version", "request_id", "artifact_digest", "analysis_sha256", "instance_id", "actor_id") {
		return
	}
	if req.SchemaVersion != "local-skill-import-permission-create/v1" {
		writeJSON(w, 400, map[string]string{"error": "skill_import_permission_invalid"})
		return
	}
	if !s.skillImportSlot(w) {
		return
	}
	defer s.skillImportMu.Unlock()
	ctx, cancel := context.WithTimeout(r.Context(), 60*time.Second)
	defer cancel()
	source, derived, err := s.skillImports.PermissionAdmission(ctx, id)
	if err != nil {
		skillImportError(w, err)
		return
	}
	if source.ArtifactDigest != req.ArtifactDigest || source.AnalysisSHA256 != req.AnalysisSHA256 {
		skillImportError(w, skillimport.ErrChanged)
		return
	}
	root, err := hermeshome.Resolve(s.hermesRoots(), req.InstanceID)
	if err != nil || !root.Detected {
		writeJSON(w, 409, map[string]string{"error": "skill_import_permission_target_unavailable"})
		return
	}
	opts := grant.Options{Subject: grant.Subject{Type: "agent_instance", ID: "hri-" + strings.TrimPrefix(root.ID, "hi-")}, Platform: "hermes", EnforcementMode: s.currentMode(), Key: s.d.Key, RedactSecrets: true}
	grantID, err := grant.ImportGrantID(derived.Admission, opts, req.ActorID, req.RequestID)
	if err != nil {
		writeJSON(w, 400, map[string]string{"error": "skill_import_permission_invalid"})
		return
	}
	response := func(g grant.Grant, revision int, reused bool) {
		status := 201
		if reused {
			status = 200
		}
		writeJSON(w, status, map[string]any{"schema_version": "local-skill-import-permission-created/v1", "import_id": id, "source": source, "grant": g, "state_revision": revision, "reused": reused, "installed": false})
	}
	if existing, revision, err := s.d.Store.GetGrantWithSeq(grantID); err == nil {
		if !grant.Verify(s.d.Key.Public(), *existing) || existing.AdmissionID != derived.Admission.AdmissionID || existing.Subject != opts.Subject || existing.Platform != opts.Platform {
			skillImportError(w, skillimport.ErrChanged)
			return
		}
		if err := s.validateImportedGrant(ctx, *existing); err != nil {
			skillImportError(w, err)
			return
		}
		if _, err := s.d.Store.GrantPolicy(*existing); err != nil {
			skillImportError(w, skillimport.ErrChanged)
			return
		}
		response(*existing, revision, true)
		return
	} else if !errors.Is(err, os.ErrNotExist) {
		skillImportError(w, skillimport.ErrUnavailable)
		return
	}
	drafted, err := grant.BuildImported(derived.Admission, opts, req.ActorID, req.RequestID)
	if err != nil {
		skillImportError(w, importsource.ErrInvalid)
		return
	}
	if err := s.d.Store.PutImportAdmission(derived); err != nil {
		skillImportError(w, skillimport.ErrChanged)
		return
	}
	if err := s.skillImports.ValidatePermissionAdmission(ctx, derived.Admission); err != nil {
		skillImportError(w, err)
		return
	}
	revision, err := s.d.Store.CommitGrant(state.GrantCommit{Grant: drafted.Grant, DesiredPolicy: drafted.DesiredPolicy, ExpectedRevision: -1, Audit: &state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339Nano), Event: "skill_import_permission_prepare", Target: grantID, ActorID: req.ActorID, Note: "import=" + id + " request=" + req.RequestID}})
	if err != nil {
		writeCommitError(w, err)
		return
	}
	s.invalidateProjection("skill_import_permission_prepare")
	response(drafted.Grant, revision, false)
}
func (s *Server) validateImportedGrant(ctx context.Context, g grant.Grant) error {
	if !grant.Verify(s.d.Key.Public(), g) {
		return skillimport.ErrChanged
	}
	adm, err := s.d.Store.GetAdmission(g.AdmissionID)
	if err != nil {
		return skillimport.ErrChanged
	}
	return s.skillImports.ValidatePermissionAdmission(ctx, *adm)
}
