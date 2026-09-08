package server

import (
	"net/http"
	"strings"
	"time"

	"siq-agent-security/apps/agentshield/internal/grant"
	"siq-agent-security/apps/agentshield/internal/state"
)

func (s *Server) requireToolApproval(w http.ResponseWriter, r *http.Request, g grant.Grant, seq int) {
	var body struct {
		SchemaVersion    string   `json:"schema_version"`
		ExpectedRevision *int     `json:"expected_revision"`
		ActorID          string   `json:"actor_id"`
		Tools            []string `json:"tools"`
	}
	if readJSONStrict(r, &body, 16<<10) != nil || body.SchemaVersion != "grant-tool-approval/v1" || body.ExpectedRevision == nil || strings.TrimSpace(body.ActorID) == "" || len(body.ActorID) > 256 {
		writeJSON(w, 400, map[string]any{"error": "invalid tool approval request"})
		return
	}
	if *body.ExpectedRevision != seq {
		writeJSON(w, 409, map[string]any{"error": "revision conflict"})
		return
	}
	out, err := grant.RequireToolApproval(g, body.Tools, s.d.Key)
	if err != nil {
		writeJSON(w, 400, map[string]any{"error": err.Error()})
		return
	}
	newSeq, err := s.d.Store.CommitGrant(state.GrantCommit{Grant: out, ExpectedRevision: seq,
		Audit: &state.AuditEvent{At: time.Now().UTC().Format(time.RFC3339), Event: "grant_require_approval", Target: g.GrantID, ActorID: body.ActorID}})
	if err != nil {
		writeCommitError(w, err)
		return
	}
	s.invalidateProjection("grant_require_approval")
	writeJSON(w, 200, map[string]any{"grant": out, "state_revision": newSeq})
}
