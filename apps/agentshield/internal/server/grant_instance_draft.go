package server

import (
	"context"
	"errors"
	"net/http"
	"os"
	"regexp"
	"runtime"
	"time"

	"siq-agent-security/apps/agentshield/internal/adapterinstall"
	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/runtimeidentity"
	"siq-agent-security/apps/agentshield/internal/state"
)

type grantInstanceDraftRequest struct {
	SchemaVersion        string `json:"schema_version"`
	ActorID              string `json:"actor_id"`
	InstanceID           string `json:"instance_id"`
	AdmissionID          string `json:"admission_id"`
	RequestID            string `json:"request_id"`
	ConfirmInstanceScope bool   `json:"confirm_instance_scope"`
}

var ordinaryAdmissionID = regexp.MustCompile(`^adm-[a-f0-9]{12}$`)

func (s *Server) grantInstanceDraft(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	if r.Method != http.MethodPost {
		w.WriteHeader(http.StatusMethodNotAllowed)
		return
	}
	var body grantInstanceDraftRequest
	if !readStrictFlatRequest(w, r, &body, "grant_instance_draft_invalid", "schema_version", "actor_id", "instance_id", "admission_id", "request_id", "confirm_instance_scope") {
		return
	}
	id, err := grant.InstanceDraftID(body.ActorID, body.RequestID)
	agent, agentErr := runtimeidentity.AgentID(body.InstanceID)
	if err != nil || agentErr != nil || body.SchemaVersion != "grant-instance-draft-create/v1" || !body.ConfirmInstanceScope || !ordinaryAdmissionID.MatchString(body.AdmissionID) {
		writeJSON(w, 400, map[string]string{"error": "grant_instance_draft_invalid"})
		return
	}
	adm, err := s.d.Store.GetAdmission(body.AdmissionID)
	if errors.Is(err, os.ErrNotExist) {
		writeJSON(w, 404, map[string]string{"error": "grant_instance_draft_admission_not_found"})
		return
	}
	if err != nil || adm == nil || adm.Verdict == "quarantine" || !s.d.Store.VerifyAdmission(s.d.Key.Public(), *adm) {
		writeJSON(w, 409, map[string]string{"error": "grant_instance_draft_admission_unavailable"})
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
	defer cancel()
	target, err := s.resolveRuntimeIdentityTarget(ctx, body.InstanceID)
	if err != nil || !adapterinstall.NewIntegrationSupportedOnOS(target.Platform, runtime.GOOS) {
		writeJSON(w, 409, map[string]string{"error": "grant_instance_draft_target_unavailable"})
		return
	}
	subject := grant.Subject{Type: "agent_instance", ID: agent}
	reuse := func(existing *grant.Grant, revision int) {
		if existing == nil || !grant.Verify(s.d.Key.Public(), *existing) {
			writeJSON(w, 409, map[string]string{"error": "grant_instance_draft_unavailable"})
			return
		}
		if existing.GrantID != id || existing.AdmissionID != body.AdmissionID || existing.Subject != subject || existing.Platform != target.Platform || existing.Skill != nil {
			writeJSON(w, 409, map[string]string{"error": "grant_instance_draft_request_conflict"})
			return
		}
		if _, err := s.d.Store.GrantPolicy(*existing); err != nil {
			writeJSON(w, 409, map[string]string{"error": "grant_instance_draft_unavailable"})
			return
		}
		writeJSON(w, 200, map[string]any{"schema_version": "grant-instance-draft-created/v1", "instance_id": body.InstanceID, "grant": existing, "state_revision": revision, "reused": true})
	}
	if existing, revision, err := s.d.Store.GetGrantWithSeq(id); err == nil {
		reuse(existing, revision)
		return
	} else if !errors.Is(err, os.ErrNotExist) && !errors.Is(err, state.ErrIncompleteCommit) {
		writeJSON(w, 409, map[string]string{"error": "grant_instance_draft_unavailable"})
		return
	}
	built, err := grant.BuildInstanceDraft(*adm, grant.Options{Subject: subject, Platform: target.Platform, EnforcementMode: s.currentMode(), Key: s.d.Key, RedactSecrets: true}, body.ActorID, body.RequestID)
	if err != nil {
		writeJSON(w, 409, map[string]string{"error": "grant_instance_draft_admission_unavailable"})
		return
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	revision, err := s.d.Store.CommitGrant(state.GrantCommit{Grant: built.Grant, DesiredPolicy: built.DesiredPolicy, ExpectedRevision: -1,
		Audit: &state.AuditEvent{At: now, Event: "grant_instance_draft", Target: id, ActorID: body.ActorID, Note: "admission=" + body.AdmissionID + " instance=" + body.InstanceID + " request=" + body.RequestID}})
	if errors.Is(err, state.ErrRevisionConflict) {
		if existing, currentRevision, readErr := s.d.Store.GetGrantWithSeq(id); readErr == nil {
			reuse(existing, currentRevision)
			return
		}
	}
	if err != nil {
		writeCommitError(w, err)
		return
	}
	s.invalidateProjection("grant_instance_draft")
	writeJSON(w, 201, map[string]any{"schema_version": "grant-instance-draft-created/v1", "instance_id": body.InstanceID, "grant": built.Grant, "state_revision": revision, "reused": false})
}
