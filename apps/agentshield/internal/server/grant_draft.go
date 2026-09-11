package server

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"os"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

type grantDraftRequest struct {
	SchemaVersion    string `json:"schema_version"`
	ExpectedRevision int    `json:"expected_revision"`
	ActorID          string `json:"actor_id"`
	RequestID        string `json:"request_id"`
}

var draftRequestPattern = regexp.MustCompile(`^gd-[a-f0-9]{32}$`)

func (s *Server) createGrantDraft(w http.ResponseWriter, r *http.Request, source grant.Grant, seq int) {
	w.Header().Set("Cache-Control", "no-store")
	var body grantDraftRequest
	if !readRuntimeIdentity(w, r, &body, "schema_version", "expected_revision", "actor_id", "request_id") {
		return
	}
	if body.SchemaVersion != "grant-draft-create/v1" || body.ExpectedRevision < 0 || strings.TrimSpace(body.ActorID) == "" || utf8.RuneCountInString(body.ActorID) > 128 || !draftRequestPattern.MatchString(body.RequestID) {
		writeJSON(w, 400, map[string]string{"error": "grant_draft_invalid_request"})
		return
	}
	if seq != body.ExpectedRevision || !grant.Verify(s.d.Key.Public(), source) {
		writeJSON(w, 409, map[string]string{"error": "grant_draft_source_changed"})
		return
	}
	actor := strings.TrimSpace(body.ActorID)
	digest := sha256.Sum256([]byte(fmt.Sprintf("%s\x00%d\x00%s\x00%s", source.GrantID, seq, actor, body.RequestID)))
	id := "grt-d-" + hex.EncodeToString(digest[:])
	response := func(g grant.Grant, revision int, reused bool) {
		writeJSON(w, 200, map[string]any{"schema_version": "grant-draft-created/v1", "source_grant_id": source.GrantID, "source_revision": seq, "grant": g, "state_revision": revision, "reused": reused})
	}
	if current, revision, err := s.d.Store.GetGrantWithSeq(id); err == nil {
		if !grant.Verify(s.d.Key.Public(), *current) {
			writeJSON(w, 409, map[string]string{"error": "grant_draft_unavailable"})
			return
		}
		response(*current, revision, true)
		return
	} else if !errors.Is(err, os.ErrNotExist) {
		writeJSON(w, 409, map[string]string{"error": "grant_draft_unavailable"})
		return
	}
	adm, err := s.d.Store.GetAdmission(source.AdmissionID)
	if err != nil || adm.Verdict == "quarantine" || !s.d.Store.VerifyAdmission(s.d.Key.Public(), *adm) {
		writeJSON(w, 409, map[string]string{"error": "grant_draft_admission_unavailable"})
		return
	}
	policy, err := s.d.Store.GrantPolicy(source)
	if err != nil {
		writeJSON(w, 409, map[string]string{"error": "grant_draft_source_policy_unavailable"})
		return
	}
	now := time.Now().UTC()
	drafted, err := grant.DraftFrom(source, policy, id, now, s.d.Key)
	if err != nil {
		writeJSON(w, 409, map[string]string{"error": "grant_draft_source_invalid"})
		return
	}
	revision, err := s.d.Store.CommitGrantFrom(state.GrantCommit{Grant: drafted.Grant, DesiredPolicy: drafted.DesiredPolicy, ExpectedRevision: -1, Audit: &state.AuditEvent{At: now.Format(time.RFC3339Nano), Event: "grant_draft", ActorID: actor, Target: id, Note: fmt.Sprintf("source=%s revision=%d request=%s", source.GrantID, seq, body.RequestID)}}, source.GrantID, seq, source.Signature)
	if err != nil {
		if errors.Is(err, state.ErrRevisionConflict) {
			if current, revision, readErr := s.d.Store.GetGrantWithSeq(id); readErr == nil && grant.Verify(s.d.Key.Public(), *current) {
				response(*current, revision, true)
				return
			}
		}
		writeCommitError(w, err)
		return
	}
	s.invalidateProjection("grant_draft")
	response(drafted.Grant, revision, false)
}
